"""Title normalization, display titles and title resolution (design §4.3).

This module is the only place that turns text into a movieId or a movieId into a title.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from movie_agent.config import ResolveConfig

ARTICLES = ("the", "a", "an", "l'", "le", "la", "les", "il", "el", "der", "die", "das")
_PAREN = re.compile(r"\(([^()]*)\)")
_AKA = re.compile(r"^\s*a\.?\s?k\.?\s?a\.?\s*", re.IGNORECASE)
_TRAILING_ARTICLE = re.compile(
    r"^(?P<rest>.*),\s*(?P<art>" + "|".join(re.escape(a) for a in ARTICLES) + r")\s*$",
    re.IGNORECASE,
)
_TRAILING_YEAR = re.compile(r"\s*\(?\b(?P<year>(?:18|19|20)\d{2})\)?\s*$")
_NORMALIZED_ARTICLES = {normal.rstrip("'") for normal in ARTICLES}


def normalize(text: str) -> str:
    """Accent-free, lowercase, punctuation-free form of `text` with single spaces.

    NFKD also maps superscripts to digits ("Alien³" -> "alien3").
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"['’]", "", text)  # "ocean's" -> "oceans", not "ocean s"
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(text.split())


def split_title(raw: str) -> tuple[str, list[str]]:
    """Split "Seven (a.k.a. Se7en)" into ("Seven", ["Se7en"])."""
    aliases = [_AKA.sub("", part).strip() for part in _PAREN.findall(raw)]
    main = " ".join(_PAREN.sub(" ", raw).split())
    return main, [a for a in aliases if a]


def move_article(title: str) -> str:
    """Move a trailing article to the front: "Postman, The" -> "The Postman"."""
    match = _TRAILING_ARTICLE.match(title.strip())
    if not match:
        return title.strip()
    art, rest = match.group("art"), match.group("rest").strip()
    return f"{art}{rest}" if art.endswith("'") else f"{art} {rest}"


def strip_leading_article(normalized: str) -> str:
    """Drop a leading article from a normalized title ("the postman" -> "postman")."""
    tokens = normalized.split()
    if len(tokens) > 1 and tokens[0] in _NORMALIZED_ARTICLES:
        return " ".join(tokens[1:])
    return normalized


def title_forms(raw: str) -> list[str]:
    """All normalized forms a title can be found by: main title, aliases, article-less variants."""
    main, aliases = split_title(raw)
    forms: list[str] = []
    for part in [main, *aliases]:
        normalized = normalize(move_article(part))
        for form in (normalized, strip_leading_article(normalized)):
            if form and form not in forms:
                forms.append(form)
    return forms


@dataclass(frozen=True)
class Candidate:
    movie_id: int
    score: float


@dataclass(frozen=True)
class Resolution:
    status: Literal["found", "ambiguous", "not_found"]
    query: str
    year: int | None
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def movie_id(self) -> int | None:
        return self.candidates[0].movie_id if self.status == "found" else None


class Catalog:
    """Movie metadata lookups and title resolution over the whole catalog."""

    def __init__(self, movies: pd.DataFrame, cfg: ResolveConfig) -> None:
        self.movies = movies
        self.cfg = cfg
        self.forms: dict[int, list[str]] = {
            int(mid): title_forms(title) for mid, title in movies["title"].items()
        }
        self._exact: dict[str, list[int]] = {}
        self._choices: list[str] = []
        self._choice_movie: list[int] = []
        for mid, forms in self.forms.items():
            for form in forms:
                self._exact.setdefault(form, []).append(mid)
                self._choices.append(strip_leading_article(form))
                self._choice_movie.append(mid)
        self._choice_len = np.array([len(c) for c in self._choices])
        self._choice_movie_arr = np.array(self._choice_movie)

    def __contains__(self, movie_id: object) -> bool:
        return movie_id in self.forms

    def title(self, movie_id: int) -> str:
        return str(self.movies.at[movie_id, "title"])

    def year(self, movie_id: int) -> int:
        return int(self.movies.at[movie_id, "year"])

    def genres(self, movie_id: int) -> list[str]:
        return list(self.movies.at[movie_id, "genres"])

    def display_title(self, movie_id: int) -> str:
        """Human-readable "Title (Year)", e.g. "The Postman (Postino, Il) (1994)"."""
        raw = self.title(movie_id)
        main, _ = split_title(raw)
        parens = "".join(f" ({p})" for p in _PAREN.findall(raw))
        return f"{move_article(main)}{parens} ({self.year(movie_id)})"

    def multiword_forms(self) -> set[str]:
        """Normalized title forms with at least two words after dropping a leading article.

        Used by the verifier (V1) to spot titles typed outside placeholders.
        """
        return {
            f
            for forms in self.forms.values()
            for f in forms
            if len(strip_leading_article(f).split()) >= 2
        }

    def resolve(self, text: str, year: int | None = None) -> Resolution:
        """Resolve free text to a movie (design §4.3).

        A trailing year in `text` ("Heat 1995", "Heat (1995)") is used when `year` is None.
        Output status: `found` (top score >= found_min and >= min_gap ahead of the second),
        `ambiguous` (top >= ambiguous_min otherwise, or several exact matches), `not_found`.
        An exact match on any form scores 100. Otherwise the article-free query is compared
        with article-free forms by rapidfuzz `ratio` (typos: "pulp fictoin"), and, for forms
        at least as long as the query, by `subset_weight * token_set_ratio` (partial titles:
        "shawshank" -> "The Shawshank Redemption"). Shorter forms get no subset credit, so a
        short title ("M", "Empire") cannot match inside a longer query. Scores are in [0, 100].
        """
        if year is not None:
            return self._resolve(text, text, year)
        query, parsed_year = _split_year(text)
        if parsed_year is None:
            return self._resolve(text, query, None)
        with_year = self._resolve(text, query, parsed_year)
        if with_year.status == "found":
            return with_year
        # A trailing number can be part of the title ("Death Race 2000"): retry as plain text.
        plain = self._resolve(text, text, None)
        return plain if plain.status == "found" else with_year

    def _resolve(self, text: str, query: str, year: int | None) -> Resolution:
        normalized = normalize(move_article(query))
        allowed = self._year_filter(year)
        if not normalized:
            return Resolution("not_found", text, year)

        best: dict[int, float] = {mid: 100.0 for mid in self._exact.get(normalized, [])}
        core = strip_leading_article(normalized)
        plain = process.cdist([core], self._choices, scorer=fuzz.ratio)[0]
        subset = (
            self.cfg.subset_weight
            * process.cdist([core], self._choices, scorer=fuzz.token_set_ratio)[0]
        )
        scores = np.where(self._choice_len >= len(core), np.maximum(plain, subset), plain)
        for index in np.flatnonzero(scores >= self.cfg.ambiguous_min / 2):
            mid = int(self._choice_movie_arr[index])
            best[mid] = max(best.get(mid, 0.0), float(scores[index]))
        best = {mid: s for mid, s in best.items() if allowed is None or mid in allowed}
        ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
        candidates = [Candidate(mid, round(s, 1)) for mid, s in ranked[: self.cfg.max_candidates]]
        return Resolution(self._status(candidates), text, year, candidates)

    def _status(self, candidates: list[Candidate]) -> Literal["found", "ambiguous", "not_found"]:
        if not candidates or candidates[0].score < self.cfg.ambiguous_min:
            return "not_found"
        top = candidates[0].score
        second = candidates[1].score if len(candidates) > 1 else 0.0
        if top >= self.cfg.found_min and top - second >= self.cfg.min_gap:
            return "found"
        return "ambiguous"

    def _year_filter(self, year: int | None) -> set[int] | None:
        if year is None:
            return None
        years = self.movies["year"]
        window = self.cfg.year_window
        return {int(m) for m in years[(years - year).abs() <= window].index}


def _split_year(text: str) -> tuple[str, int | None]:
    """Split a trailing year off a title query: "Heat (1995)" -> ("Heat", 1995)."""
    match = _TRAILING_YEAR.search(text)
    if not match or match.start() == 0:
        return text.strip(), None
    return text[: match.start()].strip(), int(match.group("year"))
