"""Deterministic answer verifier (design §7.4).

V1 Movies: every [[m:ID]] appeared in a tool result this session, and no catalog title of
   two or more words (after dropping a leading article) appears outside a placeholder.
V2 Constraints: recommended movies are unseen, avoid the active excluded genres, and came
   from a `recommend` result in this or the previous turn.
V3 Numbers: every number (except list ordinals and years) appears in this or the previous
   turn's tool outputs, within tolerance. A minus sign or a direction word right after the
   number ("2.3 below their average") makes it negative, so "0.6 below" is checked against
   -0.6 and a flipped sign is caught.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from movie_agent.catalog import Catalog, normalize
from movie_agent.config import VerifierConfig

PLACEHOLDER = re.compile(r"\[\[m:(\d+)\]\]")
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?%)?")
_ORDINAL = re.compile(r"^\s*(?:[-*]\s*)?\d+[.)]\s", re.MULTILINE)
_ANSWER_NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-\u2212])?(?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?(?P<pct>\s?%)?"
)
_BELOW = re.compile(
    r"\s*(?:points?\s+|stars?\s+)?(?:below|lower|less|under|worse)\b", re.IGNORECASE
)


class Violation(BaseModel):
    rule: str
    message: str


class VerifierResult(BaseModel):
    passed: bool
    violations: list[Violation]

    def report(self) -> str:
        return "\n".join(f"{v.rule}: {v.message}" for v in self.violations)


@dataclass
class VerifyContext:
    """What the answer is checked against."""

    session_movie_ids: set[int]  # every movie id seen in a tool result this session
    recent_recommended_ids: set[int]  # recommend results in this or the previous turn
    seen_ids: set[int]  # the user's rated movies
    exclude_genres: set[str]  # active after applying this answer's state updates
    recent_numbers: list[float] = field(default_factory=list)  # tool outputs and arguments


class Verifier:
    def __init__(self, catalog: Catalog, cfg: VerifierConfig) -> None:
        self.catalog = catalog
        self.cfg = cfg
        self.title_forms = catalog.multiword_forms()
        self.max_title_words = max((len(f.split()) for f in self.title_forms), default=0)

    def verify(self, answer: str, recommended_ids: list[int], ctx: VerifyContext) -> VerifierResult:
        violations = [
            *self._check_movies(answer, ctx),
            *self._check_constraints(recommended_ids, ctx),
            *self._check_numbers(answer, ctx),
        ]
        return VerifierResult(passed=not violations, violations=violations)

    # V1 ---------------------------------------------------------------------

    def _check_movies(self, answer: str, ctx: VerifyContext) -> Iterable[Violation]:
        for mid in {int(m) for m in PLACEHOLDER.findall(answer)}:
            if mid not in self.catalog:
                yield Violation(rule="V1", message=f"[[m:{mid}]] is not a movie in the catalog")
            elif mid not in ctx.session_movie_ids:
                yield Violation(rule="V1", message=f"[[m:{mid}]] did not appear in any tool result")
        for title in self.titles_outside_placeholders(answer):
            yield Violation(
                rule="V1",
                message=f"title typed outside a placeholder: {title!r}; use [[m:ID]] instead",
            )

    def titles_outside_placeholders(self, answer: str) -> list[str]:
        """Normalized catalog titles found in the text between placeholders."""
        found: list[str] = []
        for segment in PLACEHOLDER.split(answer)[::2]:  # odd items are the captured ids
            tokens = normalize(segment).split()
            for n in range(2, self.max_title_words + 1):
                for i in range(len(tokens) - n + 1):
                    gram = " ".join(tokens[i : i + n])
                    if gram in self.title_forms and gram not in found:
                        found.append(gram)
        return found

    # V2 ---------------------------------------------------------------------

    def _check_constraints(self, recommended: list[int], ctx: VerifyContext) -> Iterable[Violation]:
        for mid in recommended:
            if mid not in ctx.recent_recommended_ids:
                yield Violation(
                    rule="V2",
                    message=f"movie {mid} was not returned by `recommend` "
                    "in this or the previous turn",
                )
            if mid in ctx.seen_ids:
                yield Violation(rule="V2", message=f"movie {mid} is already rated by the user")
            if mid in self.catalog:
                clash = set(self.catalog.genres(mid)) & ctx.exclude_genres
                if clash:
                    yield Violation(
                        rule="V2", message=f"movie {mid} has excluded genre(s) {sorted(clash)}"
                    )

    # V3 ---------------------------------------------------------------------

    def _check_numbers(self, answer: str, ctx: VerifyContext) -> Iterable[Violation]:
        for text, value, kind in self.numbers_in(answer):
            if not self._supported(value, kind, ctx.recent_numbers):
                yield Violation(
                    rule="V3",
                    message=f"number {text!r} does not appear in the "
                    "tool outputs of this or the previous turn",
                )

    def numbers_in(self, answer: str) -> list[tuple[str, float, str]]:
        """(text, value, kind) for each checkable number; kind is pct, decimal or int."""
        text = PLACEHOLDER.sub(" ", answer)
        text = _ORDINAL.sub(" ", text)
        out = []
        for match in _ANSWER_NUMBER.finditer(text):
            whole, frac, pct = match.group("whole"), match.group("frac"), match.group("pct")
            value = float(whole.replace(",", "") + (frac or ""))
            kind = "pct" if pct else "decimal" if frac else "int"
            if (
                kind == "int"
                and not match.group("sign")
                and (self.cfg.year_min <= value <= self.cfg.year_max)
            ):
                continue  # years
            below = bool(_BELOW.match(text, match.end()))
            if match.group("sign") or below:
                value = -value
            label = match.group(0).strip() + (" below" if below else "")
            out.append((label, value, kind))
        return out

    def _supported(self, value: float, kind: str, numbers: list[float]) -> bool:
        if kind == "pct":
            return any(
                abs(value - v) <= self.cfg.pct_tol
                or (0 <= v <= 1 and abs(value - 100 * v) <= self.cfg.pct_tol)
                for v in numbers
            )
        if kind == "decimal":
            return any(abs(value - v) <= self.cfg.rating_tol for v in numbers)
        return any(value == v for v in numbers)


def collect_numbers(obj: Any) -> list[float]:
    """Every number in a nested tool output, including numbers written inside strings."""
    out: list[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(
            float(m.group(1).replace(",", "") + (m.group(2) or "")) for m in _NUMBER.finditer(obj)
        )
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(collect_numbers(value))
    elif isinstance(obj, list | tuple):
        for value in obj:
            out.extend(collect_numbers(value))
    return out


def collect_movie_ids(obj: Any) -> set[int]:
    """Values of every `movie_id` key in a nested tool output."""
    out: set[int] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "movie_id" and isinstance(value, int):
                out.add(value)
            else:
                out |= collect_movie_ids(value)
    elif isinstance(obj, list | tuple):
        for value in obj:
            out |= collect_movie_ids(value)
    return out
