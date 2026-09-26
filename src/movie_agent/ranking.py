"""Filters, features, weighted blend and contributions (design §5.2–§5.4).

`Ranker` bundles every model fitted on one ratings frame. It scores the whole catalog
per request: there is no candidate stage, so nothing can be lost before ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from movie_agent.catalog import Catalog
from movie_agent.config import Config
from movie_agent.data import Dataset, Stats, compute_stats
from movie_agent.engines import (
    EASE,
    ContentIndex,
    Embedder,
    SentenceTransformerEmbedder,
    UserKNN,
    build_content_index,
)

Mode = Literal["personal", "query", "seed", "query+seed"]
FILTER_ORDER = ("seen", "seed", "exclude_genres", "include_genres", "year_range", "min_ratings")


class RecommendRequest(BaseModel):
    """Arguments of `recommend` (design §6.2). Genres must be catalog labels."""

    user_id: int
    query: str | None = None
    seed_movie_ids: list[int] = Field(default_factory=list)
    exclude_genres: list[str] = Field(default_factory=list)
    include_genres: list[str] = Field(default_factory=list)
    year_min: int | None = None
    year_max: int | None = None
    min_ratings: int | None = None
    k: int = 5

    @property
    def mode(self) -> Mode:
        if self.query and self.seed_movie_ids:
            return "query+seed"
        if self.query:
            return "query"
        return "seed" if self.seed_movie_ids else "personal"


class Reason(BaseModel):
    """A history movie that pushed a recommendation up through EASE."""

    movie_id: int
    title: str
    user_rating: float
    ease_contribution: float


class RankedItem(BaseModel):
    """One recommended movie with its provenance (design §5.4)."""

    movie_id: int
    title: str
    year: int
    genres: list[str]
    rank: int
    score: float  # weighted blend of feature scores, in [0, 1]
    contributions: dict[str, float]  # feature -> weight * feature score / total weight
    features: dict[str, float]  # feature -> top-N rank score among eligible movies, in [0, 1]
    flags: list[str]
    confidence: Literal["high", "low"]
    because_you_rated: list[Reason]
    plot_excerpt: str | None = None
    n_ratings: int
    mean_rating: float | None
    bayes_avg: float


class RecommendResult(BaseModel):
    mode: Mode
    items: list[RankedItem]
    n_eligible: int
    filter_counts: dict[str, int]  # filter -> movies it removed (applied in FILTER_ORDER)
    weights: dict[str, float]
    sparse_user: bool
    warnings: list[str]


@dataclass
class Ranking:
    """Full ranking of the catalog for one request; the basis of `why-not`."""

    request: RecommendRequest
    mode: Mode
    movie_ids: np.ndarray
    removed_by: np.ndarray  # filter name per movie, "" if eligible
    filter_counts: dict[str, int]
    order: np.ndarray  # positions of eligible movies, best first
    features: dict[str, np.ndarray]  # top-N rank scores, NaN for ineligible movies
    contributions: dict[str, np.ndarray]
    score: np.ndarray  # NaN for ineligible movies
    weights: dict[str, float]
    sparse_user: bool
    history: dict[int, float]
    best_chunk: np.ndarray | None = None
    no_cf_signal: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))

    def rank_of(self, movie_id: int) -> int | None:
        """1-based rank among eligible movies, or None if filtered out."""
        pos = int(np.searchsorted(self.movie_ids, movie_id))
        hits = np.flatnonzero(self.order == pos)
        return int(hits[0]) + 1 if len(hits) else None

    def top(self, k: int) -> list[int]:
        return [int(self.movie_ids[p]) for p in self.order[:k]]


def top_n_score(values: np.ndarray, n: int) -> np.ndarray:
    """Rank score in [0, 1]: 1 for the best value, falling linearly to 1/n at rank n, 0 below.

    Unlike a percentile over the whole catalog, this keeps the head of a feature spread out
    (design §5.2). Ties are broken by position (catalog order), so results are deterministic.
    """
    out = np.zeros(len(values), dtype=np.float64)
    top = np.argsort(-values, kind="stable")[:n]
    out[top] = 1.0 - np.arange(len(top)) / n
    return out


def canonical_genres(names: list[str], movies: pd.DataFrame) -> list[str]:
    """Map genre names case-insensitively to catalog labels. Raises ValueError if unknown."""
    labels = {g.lower(): g for gs in movies["genres"] for g in gs}
    unknown = [n for n in names if n.lower() not in labels]
    if unknown:
        raise ValueError(f"unknown genres {unknown}; valid: {sorted(labels.values())}")
    return [labels[n.lower()] for n in names]


class Ranker:
    """Engines, statistics and histories fitted on one ratings frame."""

    def __init__(
        self,
        cfg: Config,
        ratings: pd.DataFrame,
        movies: pd.DataFrame,
        catalog: Catalog,
        content: ContentIndex,
        embedder: Embedder,
        ease_lambda: float | None = None,
    ) -> None:
        self.cfg = cfg
        self.ratings = ratings
        self.movies = movies
        self.catalog = catalog
        self.content = content
        self.embedder = embedder
        self.movie_ids = movies.index.to_numpy(dtype=np.int64)
        self.stats: Stats = compute_stats(ratings, movies, cfg)
        lam = cfg.ease.lambda_ if ease_lambda is None else ease_lambda
        self.ease = EASE(self.movie_ids, lam).fit(ratings)
        self.user_knn = UserKNN(self.movie_ids, cfg.user_knn).fit(ratings)
        self.histories: dict[int, dict[int, float]] = {
            int(u): dict(zip(g["movieId"].astype(int), g["rating"].astype(float), strict=True))
            for u, g in ratings.groupby("userId")
        }
        self._genre_sets = [set(g) for g in movies["genres"]]
        self._query_cache: dict[str, np.ndarray] = {}

    def history(self, user_id: int) -> dict[int, float]:
        """The user's ratings in the fitted data (movieId -> rating); empty if unknown."""
        return self.histories.get(user_id, {})

    # -- ranking -----------------------------------------------------------

    def rank(
        self,
        req: RecommendRequest,
        history: dict[int, float] | None = None,
        weights: dict[str, float] | None = None,
    ) -> Ranking:
        """Filter, featurize and score the whole catalog for one request.

        `history` overrides the fitted history (fidelity test, perturbations); `weights`
        overrides the mode's base weights (evaluation variants). Deterministic: ties are
        broken by movieId.
        """
        history = self.history(req.user_id) if history is None else history
        mode = req.mode
        removed = np.full(len(self.movie_ids), "", dtype=object)
        counts: dict[str, int] = {}
        for name, mask in self._filter_masks(req, history):
            newly = mask & (removed == "")
            removed[newly] = name
            counts[name] = int(newly.sum())
        eligible = removed == ""

        raw, best_chunk, has_profile = self._raw_features(req, history)
        w = self._weights(mode, weights, has_profile)
        sparse_user = len(history) < self.cfg.ranking.sparse_user_threshold
        no_cf = ~self.ease.has_signal
        feats: dict[str, np.ndarray] = {}
        for name in w:
            feat = np.full(len(self.movie_ids), np.nan)
            feat[eligible] = 0.0  # movies without CF signal never enter the cf top N
            scored = eligible & ~no_cf if name == "cf" else eligible
            feat[scored] = top_n_score(raw[name][scored], self.cfg.ranking.top_n)
            feats[name] = feat
        total = sum(w.values())
        contributions = {name: w[name] * feats[name] / total for name in w}
        score = np.sum(list(contributions.values()), axis=0)
        idx = np.flatnonzero(eligible)
        order = idx[np.lexsort((self.movie_ids[idx], -score[idx]))]
        return Ranking(
            request=req,
            mode=mode,
            movie_ids=self.movie_ids,
            removed_by=removed,
            filter_counts=counts,
            order=order,
            features=feats,
            contributions=contributions,
            score=score,
            weights=w,
            sparse_user=sparse_user,
            history=history,
            best_chunk=best_chunk,
            no_cf_signal=no_cf,
        )

    def _filter_masks(self, req: RecommendRequest, history: dict[int, float]):
        """Yield (filter name, mask of movies it removes) in FILTER_ORDER."""
        ids = self.movie_ids
        years = self.movies["year"].to_numpy()
        yield "seen", np.isin(ids, list(history))
        yield "seed", np.isin(ids, req.seed_movie_ids)
        exclude = set(req.exclude_genres)
        yield "exclude_genres", np.array([bool(gs & exclude) for gs in self._genre_sets])
        include = set(req.include_genres)
        yield (
            "include_genres",
            np.array([bool(include) and not (gs & include) for gs in self._genre_sets]),
        )
        too_old = years < req.year_min if req.year_min is not None else np.zeros(len(ids), bool)
        too_new = years > req.year_max if req.year_max is not None else np.zeros(len(ids), bool)
        yield "year_range", too_old | too_new
        yield "min_ratings", self.stats.movie["n"].to_numpy() < self.effective_min_ratings(req)

    def effective_min_ratings(self, req: RecommendRequest) -> int:
        """Explicit `min_ratings`, else the query-mode default, else 0."""
        if req.min_ratings is not None:
            return req.min_ratings
        return self.cfg.ranking.query_min_ratings if req.query else 0

    def _raw_features(self, req: RecommendRequest, history: dict[int, float]):
        """Raw (un-normalized) feature values over the whole catalog."""
        cf_history = list(history) + list(req.seed_movie_ids)
        raw = {
            "cf": self.ease.scores(cf_history),
            "quality": self.stats.movie["bayes"].to_numpy(),
        }
        profile = self.content.profile(history, self.cfg.data.liked_abs)
        raw["content"] = (
            self.content.movie_vecs @ profile
            if profile is not None
            else np.zeros(len(self.movie_ids))
        )
        best_chunk = None
        if req.query:
            raw["query"], best_chunk = self.content.query_similarity(self._embed(req.query))
        raw["seed"] = self.content.movie_similarity(req.seed_movie_ids)
        return raw, best_chunk, profile is not None

    def _weights(
        self, mode: Mode, override: dict[str, float] | None, has_profile: bool
    ) -> dict[str, float]:
        """Mode weights (or `override`); `content` is dropped without a profile, zeros dropped.

        Sparse users keep the same weights: shifting cf weight to content and quality hurt
        them on val (design §5.2, decision D3).
        """
        cfg = self.cfg.ranking
        if override is not None:
            w = dict(override)
        elif mode == "query+seed":
            w = {**cfg.weights["query"], "seed": cfg.seed_weight_with_query}
        else:
            w = dict(cfg.weights[mode])
        if not has_profile:
            w.pop("content", None)
        return {k: v for k, v in w.items() if v > 0}

    def _embed(self, query: str) -> np.ndarray:
        if query not in self._query_cache:
            self._query_cache[query] = self.embedder.encode([query], query=True)[0]
        return self._query_cache[query]

    # -- output -------------------------------------------------------------

    def recommend(
        self,
        req: RecommendRequest,
        history: dict[int, float] | None = None,
        weights: dict[str, float] | None = None,
    ) -> RecommendResult:
        """Top-k items with provenance, per-filter counts and warnings."""
        ranking = self.rank(req, history, weights)
        items = [self._item(ranking, pos, i + 1) for i, pos in enumerate(ranking.order[: req.k])]
        warnings = ["few_candidates"] if len(ranking.order) < req.k else []
        if ranking.sparse_user:
            warnings.append("sparse_user")
        return RecommendResult(
            mode=ranking.mode,
            items=items,
            n_eligible=len(ranking.order),
            filter_counts=ranking.filter_counts,
            weights={k: round(v, 3) for k, v in ranking.weights.items()},
            sparse_user=ranking.sparse_user,
            warnings=warnings,
        )

    def _item(self, ranking: Ranking, pos: int, rank: int) -> RankedItem:
        movie_id = int(self.movie_ids[pos])
        stats = self.stats.movie.loc[movie_id]
        flags = []
        if ranking.no_cf_signal[pos]:
            flags.append("no_cf_signal")
        if ranking.sparse_user:
            flags.append("sparse_user")
        excerpt = None
        if ranking.best_chunk is not None:
            text = self.content.chunk_texts[int(ranking.best_chunk[pos])]
            excerpt = text[: self.cfg.content.excerpt_chars]
        return RankedItem(
            movie_id=movie_id,
            title=self.catalog.display_title(movie_id),
            year=self.catalog.year(movie_id),
            genres=self.catalog.genres(movie_id),
            rank=rank,
            score=round(float(ranking.score[pos]), 3),
            contributions={k: round(float(v[pos]), 3) for k, v in ranking.contributions.items()},
            features={k: round(float(v[pos]), 3) for k, v in ranking.features.items()},
            flags=flags,
            confidence="low" if flags else "high",
            because_you_rated=self.ease_reasons(ranking.history, movie_id),
            plot_excerpt=excerpt,
            n_ratings=int(stats["n"]),
            mean_rating=None if stats["n"] == 0 else round(float(stats["mean"]), 2),
            bayes_avg=round(float(stats["bayes"]), 2),
        )

    def ease_reasons(self, history: dict[int, float], movie_id: int, n: int | None = None):
        """History movies with the largest positive EASE contribution to `movie_id`."""
        n = n or self.cfg.tools.ease_reasons_per_item
        if not history:
            return []
        ids = np.fromiter(history.keys(), dtype=np.int64)
        contrib = self.ease.contributions(ids, movie_id)
        order = np.lexsort((ids, -contrib))
        return [
            Reason(
                movie_id=int(ids[j]),
                title=self.catalog.display_title(int(ids[j])),
                user_rating=history[int(ids[j])],
                ease_contribution=round(float(contrib[j]), 4),
            )
            for j in order[:n]
            if contrib[j] > 0
        ]


def build_ranker(
    cfg: Config,
    ds: Dataset,
    ratings: pd.DataFrame | None = None,
    embedder: Embedder | None = None,
    content: ContentIndex | None = None,
    ease_lambda: float | None = None,
) -> Ranker:
    """Fit a `Ranker` on `ratings` (default: all ratings), building or loading the plot index.

    Plot embeddings do not depend on ratings, so evaluation and chat share one cached index.
    """
    embedder = embedder or SentenceTransformerEmbedder(cfg.content)
    if content is None:
        content = build_content_index(
            ds.movies, embedder, cfg.content, cfg.paths.cache_dir, cfg.data.genre_exclude
        )
    catalog = Catalog(ds.movies, cfg.resolve)
    fit = ds.ratings if ratings is None else ratings
    return Ranker(cfg, fit, ds.movies, catalog, content, embedder, ease_lambda)
