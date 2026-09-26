"""Agent loop, conversation state, `final_answer` and rendering (design §7).

One turn: build messages -> LLM picks tools -> tools run -> `final_answer` -> verifier ->
(one retry, else template fallback) -> render -> update state -> write trace.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from movie_agent.catalog import Catalog
from movie_agent.config import Config
from movie_agent.llm import LLMClient, ToolCall
from movie_agent.ranking import canonical_genres
from movie_agent.tools import Toolbox, ToolResult, openai_schema
from movie_agent.trace import TraceWriter
from movie_agent.verifier import (
    PLACEHOLDER,
    Verifier,
    VerifierResult,
    VerifyContext,
    collect_movie_ids,
    collect_numbers,
)


class ConversationState(BaseModel):
    """What persists between turns, outside the chat history (design §7.1)."""

    user_id: int
    focus_movie_id: int | None = None
    last_recommended: list[int] = Field(default_factory=list)  # in the order shown
    exclude_genres: list[str] = Field(default_factory=list)  # persists until relaxed
    seen_in_session: list[int] = Field(default_factory=list)  # movies in any tool result


class FinalAnswer(BaseModel):
    """Finish the turn. `answer` is markdown that refers to movies only as [[m:ID]].
    `recommended_movie_ids` lists the movies recommended in this answer (from `recommend`),
    in the order shown. Set `focus_movie_id` to the movie the conversation is now about.
    Use add/remove_exclude_genres when the user adds or relaxes a persistent genre constraint."""

    answer: str
    recommended_movie_ids: list[int] = Field(default_factory=list)
    focus_movie_id: int | None = None
    add_exclude_genres: list[str] = Field(default_factory=list)
    remove_exclude_genres: list[str] = Field(default_factory=list)


class UnknownPlaceholderError(ValueError):
    pass


def render(answer: str, catalog: Catalog) -> str:
    """Replace every [[m:ID]] with "Title (Year)". Unknown IDs raise UnknownPlaceholderError."""

    def title(match: Any) -> str:
        movie_id = int(match.group(1))
        if movie_id not in catalog:
            raise UnknownPlaceholderError(f"unknown movie placeholder [[m:{movie_id}]]")
        return f"**{catalog.display_title(movie_id)}**"

    return PLACEHOLDER.sub(title, answer)


def load_prompt(version: str) -> str:
    return resources.files("movie_agent.prompts").joinpath(f"{version}.md").read_text()


@dataclass
class TurnResult:
    rendered: str
    final: FinalAnswer | None
    verifier: VerifierResult | None
    fallback: bool
    tool_calls: list[dict[str, Any]]
    record: dict[str, Any] = field(default_factory=dict)


class Agent:
    """A conversation with one user. Keeps state, dialogue and recent tool outputs."""

    def __init__(
        self,
        user_id: int,
        toolbox: Toolbox,
        llm: LLMClient,
        cfg: Config,
        tracer: TraceWriter | None = None,
        versions: dict[str, str] | None = None,
    ) -> None:
        self.toolbox = toolbox
        self.catalog = toolbox.r.catalog
        self.llm = llm
        self.cfg = cfg
        self.tracer = tracer
        self.versions = versions or {}
        self.verifier = Verifier(self.catalog, cfg.verifier)
        self.system_prompt = load_prompt(cfg.agent.prompt_version)
        self.state = ConversationState(user_id=user_id)
        self.dialogue: list[tuple[str, str]] = []  # (user message, raw answer with placeholders)
        self.turn_tools: list[list[dict[str, Any]]] = []  # tool calls of each past turn
        self.tools = [*toolbox.openai_schemas(), openai_schema("final_answer", FinalAnswer)]

    # -- turn ---------------------------------------------------------------

    def run_turn(self, message: str) -> TurnResult:
        """Answer one user message. Always returns a rendered, verified (or fallback) answer."""
        started = time.perf_counter()
        state_before = self.state.model_copy(deep=True)
        messages = self._messages(message)
        tool_log: list[dict[str, Any]] = []
        llm_log: list[dict[str, Any]] = []
        final: FinalAnswer | None = None
        verdicts: list[VerifierResult] = []
        n_tools = 0
        max_llm_calls = self.cfg.agent.max_tool_calls + self.cfg.agent.max_retries + 2

        for _ in range(max_llm_calls):
            response = self.llm.complete(messages, self.tools)
            llm_log.append(
                {
                    "content": response.content,
                    "usage": response.usage,
                    "latency_ms": response.latency_ms,
                    "tool_calls": [c.name for c in response.tool_calls],
                }
            )
            messages.append(response.as_message())
            if not response.tool_calls:
                messages.append({"role": "system", "content": "Call `final_answer` to reply."})
                continue
            final_call: ToolCall | None = None
            for call in response.tool_calls:
                if call.name == "final_answer":
                    final_call = call
                    continue
                result = self._run_tool(call, n_tools)
                n_tools += 1
                tool_log.append(
                    {"name": call.name, "arguments": call.arguments, "result": result.model_dump()}
                )
                messages.append(_tool_message(call.id, result.model_dump()))
            if final_call is None:
                continue
            candidate, feedback = self._check_final(final_call, tool_log, verdicts)
            if candidate is not None:
                final = candidate
                break
            if len(verdicts) > self.cfg.agent.max_retries:
                break
            messages.append(_tool_message(final_call.id, {"accepted": False, "problems": feedback}))

        fallback = final is None
        if fallback:
            final = self._fallback_answer(tool_log)
        assert final is not None
        rendered = render(final.answer, self.catalog)
        self._update_state(final, tool_log)
        self.dialogue.append((message, final.answer))
        self.turn_tools.append(tool_log)
        record = {
            "session_id": self.tracer.session_id if self.tracer else None,
            "turn_index": len(self.dialogue) - 1,
            "user_message": message,
            "llm_calls": llm_log,
            "tool_calls": tool_log,
            "final_answer": final.model_dump(),
            "verifier": [v.model_dump() for v in verdicts],
            "verifier_first_pass": bool(verdicts) and verdicts[0].passed,
            "verifier_fallback": fallback,
            "rendered_answer": rendered,
            "state_before": state_before.model_dump(),
            "state_after": self.state.model_dump(),
            "versions": self.versions,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if self.tracer:
            self.tracer.write(record)
        return TurnResult(
            rendered, final, verdicts[-1] if verdicts else None, fallback, tool_log, record
        )

    # -- steps --------------------------------------------------------------

    def _messages(self, message: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": self.state_summary()},
        ]
        for user_text, answer in self.dialogue[-self.cfg.agent.history_turns :]:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": message})
        return messages

    def state_summary(self) -> str:
        """The state as shown to the LLM, with list positions for "the second one"."""
        s = self.state
        lines = [f"Session state. The user is user_id {s.user_id}."]
        excluded = ", ".join(s.exclude_genres) or "none"
        lines.append(f"Active excluded genres (pass them to `recommend`): {excluded}.")
        if s.focus_movie_id is not None:
            lines.append(
                f"Focus movie: [[m:{s.focus_movie_id}]] "
                f"({self.catalog.display_title(s.focus_movie_id)})."
            )
        if s.last_recommended:
            lines.append("Last recommended, in the order shown:")
            lines += [
                f"  {i}. [[m:{m}]] ({self.catalog.display_title(m)})"
                for i, m in enumerate(s.last_recommended, start=1)
            ]
        return "\n".join(lines)

    def _run_tool(self, call: ToolCall, n_done: int) -> ToolResult:
        if call.parse_error:
            return ToolResult(
                tool=call.name,
                ok=False,
                error_code="INVALID_ARGS",
                data={"message": f"arguments are not valid JSON: {call.parse_error}"},
            )
        if n_done >= self.cfg.agent.max_tool_calls:
            return ToolResult(
                tool=call.name,
                ok=False,
                error_code="INVALID_ARGS",
                data={"message": "tool budget used up; call final_answer now"},
            )
        arguments = dict(call.arguments)
        overridden = False
        spec = self.toolbox.specs.get(call.name)
        if spec and "user_id" in spec[0].model_fields:
            overridden = arguments.get("user_id") not in (None, self.state.user_id)
            arguments["user_id"] = self.state.user_id  # tools always act for the session user
        result = self.toolbox.call(call.name, arguments)
        if overridden:
            result.warnings.append("user_id_overridden_to_session_user")
        return result

    def _check_final(
        self, call: ToolCall, tool_log: list[dict[str, Any]], verdicts: list[VerifierResult]
    ) -> tuple[FinalAnswer | None, str]:
        """Parse and verify a `final_answer` call. Returns (accepted answer, feedback)."""
        try:
            final = FinalAnswer.model_validate(call.arguments)
        except ValidationError as exc:
            verdict = VerifierResult(passed=False, violations=[])
            verdicts.append(verdict)
            return None, f"final_answer arguments are invalid: {exc.errors()}"
        verdict = self.verifier.verify(
            final.answer, final.recommended_movie_ids, self._verify_context(final, tool_log)
        )
        verdicts.append(verdict)
        return (final, "") if verdict.passed else (None, verdict.report())

    def _verify_context(self, final: FinalAnswer, tool_log: list[dict[str, Any]]) -> VerifyContext:
        previous = self.turn_tools[-1] if self.turn_tools else []
        recent = previous + tool_log
        session_ids = set(self.state.seen_in_session)
        for call in tool_log:
            session_ids |= collect_movie_ids(call["result"])
        recommended = set()
        numbers: list[float] = []
        for call in recent:
            if call["name"] == "recommend" and call["result"]["ok"]:
                recommended |= {i["movie_id"] for i in call["result"]["data"]["items"]}
            numbers += collect_numbers(call["result"]["data"]) + collect_numbers(call["arguments"])
        numbers.append(float(len(final.recommended_movie_ids)))
        return VerifyContext(
            session_movie_ids=session_ids,
            recent_recommended_ids=recommended,
            seen_ids=set(self.toolbox.r.history(self.state.user_id)),
            exclude_genres=set(self._next_exclude_genres(final)),
            recent_numbers=numbers,
        )

    def _next_exclude_genres(self, final: FinalAnswer) -> list[str]:
        genres = list(self.state.exclude_genres)
        for g in _valid_genres(final.add_exclude_genres, self.toolbox):
            if g not in genres:
                genres.append(g)
        removed = set(_valid_genres(final.remove_exclude_genres, self.toolbox))
        return [g for g in genres if g not in removed]

    def _update_state(self, final: FinalAnswer, tool_log: list[dict[str, Any]]) -> None:
        s = self.state
        s.exclude_genres = self._next_exclude_genres(final)
        if final.focus_movie_id is not None and final.focus_movie_id in self.catalog:
            s.focus_movie_id = final.focus_movie_id
        if final.recommended_movie_ids:
            s.last_recommended = list(final.recommended_movie_ids)
        seen = set(s.seen_in_session)
        for call in tool_log:
            seen |= collect_movie_ids(call["result"])
        s.seen_in_session = sorted(seen)

    def _fallback_answer(self, tool_log: list[dict[str, Any]]) -> FinalAnswer:
        """Template answer built only from this turn's tool outputs (design §7.4)."""
        recs = [c for c in tool_log if c["name"] == "recommend" and c["result"]["ok"]]
        items = recs[-1]["result"]["data"]["items"] if recs else []
        if not items:
            return FinalAnswer(
                answer="I could not produce an answer that passes my grounding "
                "checks. Could you rephrase, or ask about a specific movie?"
            )
        lines = [
            "I could not write a verified explanation, so here are the recommender's "
            "results directly:"
        ]
        for item in items:
            top_signal = max(item["contributions"], key=item["contributions"].get)
            lines.append(
                f"{item['rank']}. [[m:{item['movie_id']}]] (main signal: {top_signal}; "
                f"{item['n_ratings']} ratings)"
            )
        return FinalAnswer(
            answer="\n".join(lines), recommended_movie_ids=[i["movie_id"] for i in items]
        )


def _valid_genres(names: list[str], toolbox: Toolbox) -> list[str]:
    valid = []
    for name in names:
        try:
            valid += canonical_genres([name], toolbox.r.movies)
        except ValueError:
            continue
    return valid


def _tool_message(call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }
