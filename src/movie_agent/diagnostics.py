"""`why-not`: explain why a movie was not recommended (design §8.2).

It reruns the ranking with the same arguments and returns the first matching code:
NOT_IN_CATALOG, ALREADY_SEEN, FILTERED:<filter>, RANKED_BELOW or IN_TOP_K.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from movie_agent.ranking import Ranker, RecommendRequest


class WhyNot(BaseModel):
    code: str
    movie_id: int | None
    title: str | None
    detail: dict[str, Any]

    def to_text(self) -> str:
        lines = [f"{self.code}: {self.title or '(no movie)'}"]
        lines += [f"  {k}: {v}" for k, v in self.detail.items()]
        return "\n".join(lines)


def resolve_movie_arg(ranker: Ranker, movie: str) -> int | None:
    """A movieId given as digits, else a title resolved through the catalog (found only)."""
    if movie.strip().isdigit():
        movie_id = int(movie)
        return movie_id if movie_id in ranker.catalog else None
    return ranker.catalog.resolve(movie).movie_id


def why_not(ranker: Ranker, req: RecommendRequest, movie: str) -> WhyNot:
    """Diagnose `movie` (title or id) for this request against the fitted ranker."""
    movie_id = resolve_movie_arg(ranker, movie)
    if movie_id is None:
        res = ranker.catalog.resolve(movie)
        closest = [ranker.catalog.display_title(c.movie_id) for c in res.candidates[:3]]
        return WhyNot(
            code="NOT_IN_CATALOG",
            movie_id=None,
            title=None,
            detail={"query": movie, "status": res.status, "closest": closest},
        )

    ranking = ranker.rank(req)
    catalog = ranker.catalog
    pos = int(np.searchsorted(ranking.movie_ids, movie_id))
    stats = ranker.stats.movie.loc[movie_id]
    base = {"mode": ranking.mode, "n_ratings": int(stats["n"]), "genres": catalog.genres(movie_id)}
    title = catalog.display_title(movie_id)
    history = ranking.history
    if movie_id in history:
        return WhyNot(
            code="ALREADY_SEEN",
            movie_id=movie_id,
            title=title,
            detail={**base, "your_rating": history[movie_id]},
        )
    removed = ranking.removed_by[pos]
    if removed:
        return WhyNot(
            code=f"FILTERED:{removed}",
            movie_id=movie_id,
            title=title,
            detail={**base, **_filter_detail(ranker, req, removed, movie_id)},
        )

    rank = ranking.rank_of(movie_id)
    assert rank is not None
    if rank <= req.k:
        return WhyNot(
            code="IN_TOP_K",
            movie_id=movie_id,
            title=title,
            detail={
                **base,
                "rank": rank,
                "note": "the engine recommended it; if the "
                "answer did not mention it, the LLM dropped it",
            },
        )
    kth = int(ranking.order[req.k - 1])
    own = {f: round(float(v[pos]), 3) for f, v in ranking.contributions.items()}
    other = {f: round(float(v[kth]), 3) for f, v in ranking.contributions.items()}
    gaps = {f: round(other[f] - own[f], 3) for f in own}
    return WhyNot(
        code="RANKED_BELOW",
        movie_id=movie_id,
        title=title,
        detail={
            **base,
            "rank": rank,
            "k": req.k,
            "score": round(float(ranking.score[pos]), 3),
            "contributions": own,
            "rank_k_movie": catalog.display_title(int(ranking.movie_ids[kth])),
            "rank_k_score": round(float(ranking.score[kth]), 3),
            "rank_k_contributions": other,
            "largest_gap_feature": max(gaps, key=gaps.get),
            "no_cf_signal": bool(ranking.no_cf_signal[pos]),
        },
    )


def _filter_detail(ranker: Ranker, req: RecommendRequest, name: str, movie_id: int) -> dict:
    catalog = ranker.catalog
    if name == "exclude_genres":
        return {"excluded": sorted(set(catalog.genres(movie_id)) & set(req.exclude_genres))}
    if name == "include_genres":
        return {"required_any_of": req.include_genres}
    if name == "year_range":
        return {"year": catalog.year(movie_id), "year_min": req.year_min, "year_max": req.year_max}
    if name == "min_ratings":
        return {"min_ratings": ranker.effective_min_ratings(req)}
    return {}
