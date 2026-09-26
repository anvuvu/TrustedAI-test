"""The five agent tools, their result envelope and confidence rules (design §6).

Tools return only data computed in Python. The numbers in `ToolResult.data` are the only
numbers the agent may state (verifier V3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from movie_agent.config import Config
from movie_agent.data import genre_table
from movie_agent.ranking import Ranker, RecommendRequest, canonical_genres

Confidence = Literal["high", "medium", "low"]


class ToolResult(BaseModel):
    """Envelope returned by every tool (design §6.1)."""

    tool: str
    ok: bool
    error_code: str | None = None  # USER_NOT_FOUND, MOVIE_NOT_FOUND, AMBIGUOUS_MOVIE, INVALID_ARGS
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: Confidence = "high"
    confidence_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class ToolError(Exception):
    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = {"message": message, **(data or {})}


# ---------------------------------------------------------------------------
# Argument models (their docstrings and field descriptions are shown to the LLM)
# ---------------------------------------------------------------------------


class UserProfileArgs(BaseModel):
    """The user's rating history summarized: counts, mean, most liked and disliked movies,
    a genre table (share of their ratings vs all users, and affinity = how much above their
    own average they rate the genre), `unexplored` genres (rarely or never rated: blind
    spots) and `avoided` genres (rated and disliked: not blind spots). Returns no movie
    suggestions; for movies in a blind-spot genre call `recommend` with include_genres."""

    user_id: int


class FindMovieArgs(BaseModel):
    """Resolve a movie title to a movieId and return its data: year, genres, rating
    statistics, top tags and a plot excerpt. Status `ambiguous` means you must ask the user
    which candidate they mean; `not_found` means the movie is not in this dataset."""

    title: str = Field(description="Title as the user wrote it; may include a year.")
    year: int | None = Field(None, description="Release year, if the user gave one.")


class RecommendArgs(BaseModel):
    """Rank every movie the user has not rated and return the top k with the reasons behind
    each score. Modes: personal (no query, no seeds), query (a description of what they want
    to watch), seed (movies they say they liked), or query+seed. Put negative constraints
    ("not animated", "no horror") in exclude_genres, never in query."""

    user_id: int
    query: str | None = Field(
        None, description="Positive description of the wanted movie, e.g. 'dark thriller'."
    )
    seed_movie_ids: list[int] = Field(
        default_factory=list, description="movieIds the user liked (from find_movie)."
    )
    exclude_genres: list[str] = Field(default_factory=list, description="Genres to avoid.")
    include_genres: list[str] = Field(
        default_factory=list, description="Keep only movies with at least one of these genres."
    )
    year_min: int | None = None
    year_max: int | None = None
    min_ratings: int | None = Field(
        None, description="Minimum number of ratings (default 3 in query mode, else 0)."
    )
    k: int = Field(5, ge=1, description="Number of movies to return.")


class PeerOpinionArgs(BaseModel):
    """What the user's most similar users (by rating history) think of one movie: how many
    of them rated it, their mean rating, how far above or below their own averages they
    rated it, and how that compares with all users."""

    user_id: int
    movie_id: int


class ExplainArgs(BaseModel):
    """Evidence for why this user might like a movie: the history movies that drive its
    collaborative score, the history movies with the most similar plots, the user's genre
    affinity, similar users' opinion, and `drivers` (the signals ordered by strength)."""

    user_id: int
    movie_id: int


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------


class Toolbox:
    """The five tools over one fitted `Ranker` (all ratings for chat, train for evaluation)."""

    def __init__(self, ranker: Ranker, tags: pd.DataFrame, cfg: Config) -> None:
        self.r = ranker
        self.cfg = cfg
        self.tags = tags.assign(tag=tags["tag"].str.strip().str.lower())
        self.tags = self.tags[~self.tags["tag"].isin([t.lower() for t in cfg.data.tag_stoplist])]
        self.specs: dict[str, tuple[type[BaseModel], Callable[[Any], ToolResult]]] = {
            "get_user_profile": (UserProfileArgs, self.get_user_profile),
            "find_movie": (FindMovieArgs, self.find_movie),
            "recommend": (RecommendArgs, self.recommend),
            "peer_opinion": (PeerOpinionArgs, self.peer_opinion),
            "explain": (ExplainArgs, self.explain),
        }

    # -- dispatch -----------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate arguments and run a tool. Errors come back as codes, never exceptions."""
        if name not in self.specs:
            return _error(name, "INVALID_ARGS", f"unknown tool {name!r}")
        model, fn = self.specs[name]
        try:
            args = model.model_validate(arguments)
        except ValidationError as exc:
            return _error(name, "INVALID_ARGS", _short_validation_error(exc))
        try:
            return fn(args)
        except ToolError as exc:
            return ToolResult(
                tool=name,
                ok=False,
                error_code=exc.code,
                data=exc.data,
                confidence="low",
                confidence_reason=str(exc),
            )

    def openai_schemas(self) -> list[dict[str, Any]]:
        """Tool definitions in the OpenAI function-calling format."""
        return [openai_schema(name, model) for name, (model, _) in self.specs.items()]

    # -- helpers ------------------------------------------------------------

    def _require_user(self, user_id: int) -> dict[int, float]:
        history = self.r.history(user_id)
        if not history:
            raise ToolError("USER_NOT_FOUND", f"user {user_id} has no ratings in this dataset")
        return history

    def _require_movie(self, movie_id: int) -> None:
        if movie_id not in self.r.catalog:
            raise ToolError("MOVIE_NOT_FOUND", f"movieId {movie_id} is not in this dataset")

    def _movie_stats(self, movie_id: int) -> dict[str, Any]:
        s = self.r.stats.movie.loc[movie_id]
        n = int(s["n"])
        return {
            "n_ratings": n,
            "mean_rating": None if n == 0 else round(float(s["mean"]), 2),
            "bayes_avg": round(float(s["bayes"]), 2),
        }

    def _history_frame(self, user_id: int) -> pd.DataFrame:
        history = self.r.history(user_id)
        return pd.DataFrame({"movieId": list(history), "rating": list(history.values())})

    def _movie_ref(self, movie_id: int, **extra: Any) -> dict[str, Any]:
        return {"movie_id": movie_id, "title": self.r.catalog.display_title(movie_id), **extra}

    # -- tools --------------------------------------------------------------

    def get_user_profile(self, args: UserProfileArgs) -> ToolResult:
        self._require_user(args.user_id)
        cfg, tcfg = self.cfg, self.cfg.tools
        hist = self._history_frame(args.user_id)
        n, mu = len(hist), float(hist["rating"].mean())
        user_means = self.r.stats.user["mean"]
        table = genre_table(hist, self.r.movies, self.r.stats, cfg)
        ordered = hist.sort_values(["rating", "movieId"], ascending=[False, True])
        bottom = hist.sort_values(["rating", "movieId"], ascending=[True, True])

        neighbour_tables = [
            genre_table(self._history_frame(nb.user_id), self.r.movies, self.r.stats, cfg)
            for nb in self.r.user_knn.neighbours(args.user_id)
        ]
        unexplored, avoided = [], []
        for genre, row in table.iterrows():
            if row["share"] < tcfg.unexplored_share_ratio * row["global_share"]:
                peer = [t.at[genre, "affinity"] for t in neighbour_tables]
                unexplored.append(
                    {
                        "genre": genre,
                        "your_ratings": int(row["count"]),
                        "your_share_pct": _pct(row["share"]),
                        "global_share_pct": _pct(row["global_share"]),
                        "similar_users_affinity": round(float(np.mean(peer)), 2) if peer else None,
                    }
                )
            elif row["count"] >= tcfg.avoided_min_ratings and (
                row["affinity"] <= tcfg.avoided_max_affinity
            ):
                avoided.append(
                    {
                        "genre": genre,
                        "your_ratings": int(row["count"]),
                        "affinity": round(float(row["affinity"]), 2),
                    }
                )

        genres = [
            {
                "genre": g,
                "your_ratings": int(r["count"]),
                "your_share_pct": _pct(r["share"]),
                "global_share_pct": _pct(r["global_share"]),
                "affinity": round(float(r["affinity"]), 2),
            }
            for g, r in table.sort_values(["count", "affinity"], ascending=False).iterrows()
        ]
        low = n < cfg.confidence.user_low_below
        return ToolResult(
            tool="get_user_profile",
            ok=True,
            data={
                "user_id": args.user_id,
                "n_ratings": n,
                "mean_rating": round(mu, 2),
                "std_rating": round(float(hist["rating"].std(ddof=0)), 2),
                "users_with_lower_mean_pct": _pct(float((user_means < mu).mean())),
                "top_liked": [
                    self._movie_ref(int(m), rating=float(r))
                    for m, r in ordered.head(tcfg.profile_top_liked).to_numpy()
                ],
                "most_disliked": [
                    self._movie_ref(int(m), rating=float(r))
                    for m, r in bottom.head(tcfg.profile_bottom).to_numpy()
                ],
                "genres": genres,
                "unexplored_genres": unexplored,
                "avoided_genres": avoided,
                "n_similar_users": len(neighbour_tables),
            },
            confidence="low" if low else "high",
            confidence_reason=f"only {n} ratings" if low else f"{n} ratings",
            warnings=["sparse_user"] if low else [],
        )

    def find_movie(self, args: FindMovieArgs) -> ToolResult:
        res = self.r.catalog.resolve(args.title, args.year)
        candidates = [
            self._movie_ref(
                c.movie_id,
                year=self.r.catalog.year(c.movie_id),
                match_score=c.score,
                n_ratings=self._movie_stats(c.movie_id)["n_ratings"],
            )
            for c in res.candidates
        ]
        if res.status == "not_found":
            raise ToolError(
                "MOVIE_NOT_FOUND",
                f"no movie matching {args.title!r} is in this dataset",
                {"status": "not_found", "closest": candidates[:3]},
            )
        if res.status == "ambiguous":
            raise ToolError(
                "AMBIGUOUS_MOVIE",
                f"{args.title!r} matches several movies; ask the user which one they mean",
                {"status": "ambiguous", "candidates": candidates},
            )
        movie_id = res.candidates[0].movie_id
        stats = self._movie_stats(movie_id)
        tags = self.tags[self.tags["movieId"] == movie_id]["tag"].value_counts()
        low = stats["n_ratings"] < self.cfg.confidence.movie_low_below
        return ToolResult(
            tool="find_movie",
            ok=True,
            data={
                "status": "found",
                **self._movie_ref(movie_id),
                "year": self.r.catalog.year(movie_id),
                "genres": self.r.catalog.genres(movie_id),
                **stats,
                "top_tags": [
                    {"tag": t, "count": int(c)}
                    for t, c in tags.head(self.cfg.tools.top_tags).items()
                ],
                "plot_excerpt": str(self.r.movies.at[movie_id, "plot"])[
                    : self.cfg.tools.plot_excerpt_chars
                ],
                "other_candidates": candidates[1:],
            },
            confidence="low" if low else "high",
            confidence_reason=f"{stats['n_ratings']} ratings",
            warnings=["few_ratings"] if low else [],
        )

    def recommend(self, args: RecommendArgs) -> ToolResult:
        self._require_user(args.user_id)
        for mid in args.seed_movie_ids:
            self._require_movie(mid)
        try:
            exclude = canonical_genres(args.exclude_genres, self.r.movies)
            include = canonical_genres(args.include_genres, self.r.movies)
        except ValueError as exc:
            raise ToolError("INVALID_ARGS", str(exc)) from exc
        req = RecommendRequest(
            **{
                **args.model_dump(),
                "exclude_genres": exclude,
                "include_genres": include,
                "k": min(args.k, self.cfg.tools.max_k),
            }
        )
        result = self.r.recommend(req)
        low = [i.movie_id for i in result.items if i.confidence == "low"]
        warnings = list(result.warnings) + ([] if result.items else ["no_candidates"])
        reason = _recommend_confidence_reason(
            result.items, result.sparse_user, self.cfg.confidence.movie_low_below
        )
        return ToolResult(
            tool="recommend",
            ok=True,
            data=result.model_dump(),
            confidence="low" if low or not result.items else "high",
            confidence_reason=reason,
            warnings=warnings,
        )

    def peer_opinion(self, args: PeerOpinionArgs) -> ToolResult:
        history = self._require_user(args.user_id)
        self._require_movie(args.movie_id)
        data, confidence, reason = self._peer_summary(args.user_id, args.movie_id)
        data["your_rating"] = history.get(args.movie_id)
        warnings = [] if data["similar_users_who_rated"] else ["no_similar_user_rated"]
        return ToolResult(
            tool="peer_opinion",
            ok=True,
            data=data,
            confidence=confidence,
            confidence_reason=reason,
            warnings=warnings,
        )

    def _peer_summary(self, user_id: int, movie_id: int) -> tuple[dict[str, Any], Confidence, str]:
        knn, ccfg = self.r.user_knn, self.cfg.confidence
        neighbours = knn.neighbours(user_id)
        raters = [(nb, knn.rating(nb.user_id, movie_id)) for nb in neighbours]
        raters = [(nb, r) for nb, r in raters if r is not None]
        ratings = np.array([r for _, r in raters])
        deviations = np.array([r - (knn.user_mean(nb.user_id) or 0.0) for nb, r in raters])
        n = len(raters)
        data: dict[str, Any] = {
            **self._movie_ref(movie_id),
            "n_similar_users": len(neighbours),
            "similar_users_who_rated": n,
            "similar_users_mean_rating": round(float(ratings.mean()), 2) if n else None,
            "similar_users_mean_vs_own_average": round(float(deviations.mean()), 2) if n else None,
            "similar_users_liked_pct": _pct(float((ratings >= self.cfg.data.liked_abs).mean()))
            if n
            else None,
            "all_users": self._movie_stats(movie_id),
            "examples": [
                {
                    "user_id": nb.user_id,
                    "similarity": round(nb.similarity, 2),
                    "shared_movies": nb.n_common,
                    "rating": r,
                }
                for nb, r in raters[: self.cfg.tools.peer_examples]
            ],
        }
        if n < ccfg.peer_low_below:
            return data, "low", f"only {n} similar user(s) rated it"
        if n >= ccfg.peer_high_min:
            return data, "high", f"{n} similar users rated it"
        return data, "medium", f"{n} similar users rated it"

    def explain(self, args: ExplainArgs) -> ToolResult:
        history = self._require_user(args.user_id)
        self._require_movie(args.movie_id)
        r, tcfg = self.r, self.cfg.tools
        movie_id = args.movie_id
        warnings: list[str] = []

        ease = r.ease_reasons(history, movie_id, tcfg.explain_top_n)
        plot_similar = self._plot_similar(history, movie_id, tcfg.explain_top_n)
        movie_genres = [
            g for g in r.catalog.genres(movie_id) if g not in self.cfg.data.genre_exclude
        ]
        table = genre_table(self._history_frame(args.user_id), r.movies, r.stats, self.cfg)
        affinity = [
            {
                "genre": g,
                "your_ratings": int(table.at[g, "count"]),
                "affinity": round(float(table.at[g, "affinity"]), 2),
            }
            for g in movie_genres
        ]
        peer, peer_conf, peer_reason = self._peer_summary(args.user_id, movie_id)

        drivers, rank = self._drivers(args.user_id, history, movie_id, ease, plot_similar)
        stats = self._movie_stats(movie_id)
        if movie_id in history:
            warnings.append("already_rated")
        if stats["n_ratings"] < self.cfg.confidence.movie_low_below:
            warnings.append("few_ratings")
        if len(history) < self.cfg.ranking.sparse_user_threshold:
            warnings.append("sparse_user")
        if not r.ease.has_signal[r.ease.positions([movie_id])[0]]:
            warnings.append("no_cf_signal")
        return ToolResult(
            tool="explain",
            ok=True,
            data={
                **self._movie_ref(movie_id),
                **stats,
                "your_rating": history.get(movie_id),
                "personal_rank": rank,
                "drivers": drivers,
                "because_you_rated": [x.model_dump() for x in ease],
                "similar_plots_you_rated": plot_similar,
                "genre_affinity": affinity,
                "similar_users": {
                    k: peer[k]
                    for k in (
                        "similar_users_who_rated",
                        "similar_users_mean_rating",
                        "similar_users_mean_vs_own_average",
                    )
                }
                | {"confidence": peer_conf},
            },
            confidence="low" if warnings else "high",
            confidence_reason=", ".join(warnings) or peer_reason,
            warnings=warnings,
        )

    def _plot_similar(self, history: dict[int, float], movie_id: int, n: int) -> list[dict]:
        """History movies whose plots are most similar to `movie_id`, with the matched passage."""
        content = self.r.content
        target = content.movie_vecs[content.position(movie_id)]
        ids = [m for m in history if m != movie_id]
        if not ids:
            return []
        sims = content.movie_vecs[np.searchsorted(content.movie_ids, ids)] @ target
        order = np.lexsort((np.array(ids), -sims))[:n]
        out = []
        for j in order:
            chunk = content.best_chunk_against(ids[j], target)
            out.append(
                self._movie_ref(
                    ids[j],
                    your_rating=history[ids[j]],
                    plot_similarity=round(float(sims[j]), 2),
                    matched_passage=content.chunk_texts[chunk][: self.cfg.content.excerpt_chars],
                )
            )
        return out

    def _drivers(
        self,
        user_id: int,
        history: dict[int, float],
        movie_id: int,
        ease: list,
        plot_similar: list[dict],
    ) -> tuple[list[dict], int | None]:
        """Personal-mode contributions for the movie, strongest first.

        cf and content drivers name the history movie behind them, which the fidelity test
        (§9.5) removes to check that the driver is real. The movie's own rating is excluded
        from the history so that already-rated movies can be explained too.
        """
        hist = {m: v for m, v in history.items() if m != movie_id}
        ranking = self.r.rank(RecommendRequest(user_id=user_id), history=hist)
        pos = int(self.r.content.position(movie_id))
        rank = ranking.rank_of(movie_id)
        drivers = []
        for signal, values in ranking.contributions.items():
            value = values[pos]
            if np.isnan(value):
                continue
            via = None
            if signal == "cf" and ease:
                via = {"movie_id": ease[0].movie_id, "title": ease[0].title}
            elif signal == "content" and plot_similar:
                via = {k: plot_similar[0][k] for k in ("movie_id", "title")}
            drivers.append(
                {
                    "signal": signal,
                    "contribution": round(float(value), 3),
                    "feature_score": round(float(ranking.features[signal][pos]), 2),
                    "via_history_movie": via,
                }
            )
        drivers.sort(key=lambda d: -d["contribution"])
        return drivers, rank


def openai_schema(name: str, model: type[BaseModel]) -> dict[str, Any]:
    """OpenAI function-calling definition from a pydantic model (docstring = description)."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    doc = " ".join((model.__doc__ or "").split())
    return {
        "type": "function",
        "function": {"name": name, "description": doc, "parameters": schema},
    }


def _recommend_confidence_reason(items: list, sparse_user: bool, min_ratings: int) -> str:
    """Why `recommend` is low confidence: sparse user, and per-item flags with counts."""
    parts = ["sparse user history"] if sparse_user else []
    few = sum("few_ratings" in i.flags for i in items)
    no_cf = sum("no_cf_signal" in i.flags for i in items)
    if few:
        parts.append(f"{few} item(s) with fewer than {min_ratings} ratings")
    if no_cf:
        parts.append(f"{no_cf} item(s) without collaborative signal")
    return "; ".join(parts)


def _pct(fraction: float) -> float:
    return round(100.0 * float(fraction), 1)


def _error(tool: str, code: str, message: str) -> ToolResult:
    return ToolResult(
        tool=tool,
        ok=False,
        error_code=code,
        data={"message": message},
        confidence="low",
        confidence_reason=message,
    )


def _short_validation_error(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
