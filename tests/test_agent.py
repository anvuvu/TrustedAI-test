"""Agent loop with a scripted LLM: tool use, verification, retry, fallback, state, traces."""

import json

from movie_agent.agent import Agent
from movie_agent.llm import LLMResponse, ToolCall
from movie_agent.trace import TraceWriter, read_trace


class ScriptedLLM:
    """Returns pre-written tool calls, one list per LLM call."""

    model = "scripted"

    def __init__(self, steps):
        self.steps = list(steps)
        self.seen_messages = []

    def complete(self, messages, tools):
        self.seen_messages.append(list(messages))
        calls = [
            ToolCall(
                id=f"c{len(self.seen_messages)}_{i}",
                name=name,
                arguments=args,
                raw_arguments=json.dumps(args),
            )
            for i, (name, args) in enumerate(self.steps.pop(0))
        ]
        return LLMResponse(content=None, tool_calls=calls)


def make_agent(toolbox, cfg, steps, tmp_path=None, user_id=1):
    tracer = TraceWriter(tmp_path, "test") if tmp_path else None
    return Agent(user_id, toolbox, ScriptedLLM(steps), cfg, tracer=tracer)


def top_ids(toolbox, **args):
    result = toolbox.call("recommend", {"user_id": 1, **args})
    return [i["movie_id"] for i in result.data["items"]]


def test_grounded_turn_passes_and_is_traced(toolbox, cfg, tmp_path):
    ids = top_ids(toolbox, k=3)
    answer = "Try " + ", ".join(f"[[m:{m}]]" for m in ids) + "."
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("recommend", {"user_id": 1, "k": 3})],
            [("final_answer", {"answer": answer, "recommended_movie_ids": ids})],
        ],
        tmp_path,
    )
    turn = agent.run_turn("What should I watch tonight?")
    assert not turn.fallback and turn.verifier.passed
    assert "[[m:" not in turn.rendered and "**" in turn.rendered
    assert agent.state.last_recommended == ids
    record = read_trace(tmp_path / "test.jsonl")[0]
    assert record["tool_calls"][0]["name"] == "recommend"
    assert record["verifier_first_pass"] is True
    assert record["state_after"]["last_recommended"] == ids


def test_verifier_rejection_gets_one_retry(toolbox, cfg):
    ids = top_ids(toolbox, k=2)
    bad = "Try The Usual Suspects."  # typed title, not a placeholder
    good = f"Try [[m:{ids[0]}]]."
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("recommend", {"user_id": 1, "k": 2})],
            [("final_answer", {"answer": bad, "recommended_movie_ids": []})],
            [("final_answer", {"answer": good, "recommended_movie_ids": ids[:1]})],
        ],
    )
    turn = agent.run_turn("Something to watch?")
    assert not turn.fallback and turn.record["verifier_first_pass"] is False
    feedback = agent.llm.seen_messages[-1][-1]
    assert feedback["role"] == "tool" and "V1" in feedback["content"]


def test_repeated_failure_falls_back_to_template(toolbox, cfg):
    ids = top_ids(toolbox, k=2)
    bad = {"answer": "Everyone loves [[m:9999]].", "recommended_movie_ids": []}
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("recommend", {"user_id": 1, "k": 2})],
            [("final_answer", bad)],
            [("final_answer", bad)],
        ],
    )
    turn = agent.run_turn("Something to watch?")
    assert turn.fallback and turn.record["verifier_fallback"]
    assert turn.final.recommended_movie_ids == ids
    assert "[[m:" not in turn.rendered


def test_excluded_genre_persists_and_is_enforced_next_turn(toolbox, cfg):
    ids = top_ids(toolbox, k=3, exclude_genres=["Animation"])
    first = {
        "answer": " ".join(f"[[m:{m}]]" for m in ids),
        "recommended_movie_ids": ids,
        "add_exclude_genres": ["animation"],
    }
    shrek_rec = toolbox.call("recommend", {"user_id": 1, "k": 10})
    all_ids = [i["movie_id"] for i in shrek_rec.data["items"]]
    assert 11 in all_ids  # Shrek is recommendable without the constraint
    violating = {"answer": "Try [[m:11]].", "recommended_movie_ids": [11]}
    fixed = {"answer": f"Try [[m:{ids[0]}]].", "recommended_movie_ids": ids[:1]}
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("recommend", {"user_id": 1, "k": 3, "exclude_genres": ["Animation"]})],
            [("final_answer", first)],
            [("recommend", {"user_id": 1, "k": 10})],  # the LLM forgets the constraint
            [("final_answer", violating)],
            [("final_answer", fixed)],
        ],
    )
    agent.run_turn("No animated movies please.")
    assert agent.state.exclude_genres == ["Animation"]
    turn = agent.run_turn("More?")
    assert "Active excluded genres (pass them to `recommend`): Animation." in agent.state_summary()
    assert turn.record["verifier"][0]["violations"][0]["rule"] == "V2"
    assert not turn.fallback


def test_tools_always_act_for_the_session_user(toolbox, cfg):
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("get_user_profile", {"user_id": 2})],
            [("final_answer", {"answer": "Done."})],
        ],
    )
    turn = agent.run_turn("Profile?")
    call = turn.tool_calls[0]
    assert call["result"]["data"]["user_id"] == 1
    assert "user_id_overridden_to_session_user" in call["result"]["warnings"]


def test_focus_movie_is_kept_for_follow_ups(toolbox, cfg):
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("find_movie", {"title": "Pulp Fiction"})],
            [("final_answer", {"answer": "About [[m:15]].", "focus_movie_id": 15})],
        ],
    )
    agent.run_turn("What about Pulp Fiction?")
    assert agent.state.focus_movie_id == 15
    assert "Focus movie: [[m:15]]" in agent.state_summary()


def test_genres_excluded_in_recommend_persist_without_add_exclude(toolbox, cfg):
    # Failure 14 in docs/notes.md: the LLM excluded Animation in `recommend` but never set
    # add_exclude_genres, so the next turn's recommendations were unconstrained.
    ids = top_ids(toolbox, k=3, exclude_genres=["Animation"])
    first = {"answer": " ".join(f"[[m:{m}]]" for m in ids), "recommended_movie_ids": ids}
    violating = {"answer": "Try [[m:11]].", "recommended_movie_ids": [11]}  # Shrek: Animation
    fixed = {"answer": f"Try [[m:{ids[0]}]].", "recommended_movie_ids": ids[:1]}
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("recommend", {"user_id": 1, "k": 3, "exclude_genres": ["animation"]})],
            [("final_answer", first)],
            [("recommend", {"user_id": 1, "k": 10})],
            [("final_answer", violating)],
            [("final_answer", fixed)],
        ],
    )
    agent.run_turn("I'm tired of animated movies.")
    assert agent.state.exclude_genres == ["Animation"]
    turn = agent.run_turn("More?")
    assert turn.record["verifier"][0]["violations"][0]["rule"] == "V2"
    assert not turn.fallback


def test_removing_a_genre_in_the_answer_wins_over_persistence(toolbox, cfg):
    ids = top_ids(toolbox, k=2, exclude_genres=["Animation"])
    answer = {
        "answer": " ".join(f"[[m:{m}]]" for m in ids),
        "recommended_movie_ids": ids,
        "remove_exclude_genres": ["Animation"],
    }
    agent = make_agent(
        toolbox,
        cfg,
        [
            [("recommend", {"user_id": 1, "k": 2, "exclude_genres": ["Animation"]})],
            [("final_answer", answer)],
        ],
    )
    agent.run_turn("Just this once, no animation.")
    assert agent.state.exclude_genres == []


def test_openai_client_sends_reasoning_effort_only_when_configured(cfg, monkeypatch):
    from types import SimpleNamespace

    from movie_agent.llm import OpenAIClient

    sent = []
    message = SimpleNamespace(content=None, tool_calls=[])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: sent.append(kw) or response)
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for effort in ("none", None):
        client = OpenAIClient(cfg.agent.model_copy(update={"reasoning_effort": effort}))
        client._client = fake
        client.complete([{"role": "user", "content": "hi"}], [])
    assert sent[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in sent[1]
    assert sent[0]["temperature"] == sent[1]["temperature"] == cfg.agent.temperature
