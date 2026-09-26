"""I2 (filters), I3 (contributions sum to score), I4 (determinism)."""

import numpy as np
import pytest

from movie_agent.ranking import RecommendRequest, build_ranker, top_n_score


def test_top_n_score_decays_linearly_inside_the_top_n():
    values = np.array([0.1, 0.9, 0.5, 0.5, 0.3])
    # ranks: 0.9 -> 1, first 0.5 -> 2, second 0.5 -> 3 (ties by position), rest outside top 3
    assert np.allclose(top_n_score(values, 3), [0.0, 1.0, 2 / 3, 1 / 3, 0.0])
    assert np.allclose(top_n_score(values, 10), [0.6, 1.0, 0.9, 0.8, 0.7])


def test_i2_recommend_never_violates_filters(ranker):
    rng = np.random.default_rng(0)
    genres = sorted({g for gs in ranker.movies["genres"] for g in gs})
    for _ in range(200):
        req = RecommendRequest(
            user_id=int(rng.integers(1, 7)),
            query=str(rng.choice(["alien space", "love story", "heist"]))
            if rng.random() < 0.5
            else None,
            seed_movie_ids=[int(rng.choice(ranker.movie_ids))] if rng.random() < 0.3 else [],
            exclude_genres=list(rng.choice(genres, size=rng.integers(0, 3), replace=False)),
            include_genres=list(rng.choice(genres, size=rng.integers(0, 2), replace=False)),
            year_min=int(rng.integers(1950, 2000)) if rng.random() < 0.3 else None,
            year_max=int(rng.integers(1990, 2015)) if rng.random() < 0.3 else None,
            min_ratings=int(rng.integers(0, 4)) if rng.random() < 0.3 else None,
            k=int(rng.integers(1, 8)),
        )
        result = ranker.recommend(req)
        seen = set(ranker.history(req.user_id)) | set(req.seed_movie_ids)
        for item in result.items:
            g = set(item.genres)
            assert item.movie_id not in seen
            assert not g & set(req.exclude_genres)
            assert not req.include_genres or g & set(req.include_genres)
            assert req.year_min is None or item.year >= req.year_min
            assert req.year_max is None or item.year <= req.year_max
            assert item.n_ratings >= ranker.effective_min_ratings(req)


@pytest.mark.parametrize("query", [None, "alien creature"])
def test_i3_contributions_sum_to_score(ranker, query):
    ranking = ranker.rank(RecommendRequest(user_id=1, query=query, seed_movie_ids=[11]))
    total = np.sum([v[ranking.order] for v in ranking.contributions.values()], axis=0)
    assert np.allclose(total, ranking.score[ranking.order], atol=1e-6)


def test_i4_determinism(cfg, ds, embedder, ranker):
    req = RecommendRequest(user_id=2, query="heist in the city", k=10)
    assert ranker.recommend(req) == ranker.recommend(req)
    other = build_ranker(cfg, ds, embedder=embedder, ease_lambda=1.0)
    assert np.array_equal(other.ease.B, ranker.ease.B)
    assert other.recommend(req) == ranker.recommend(req)


def test_modes_and_weights(ranker):
    assert RecommendRequest(user_id=1).mode == "personal"
    assert RecommendRequest(user_id=1, query="x").mode == "query"
    assert RecommendRequest(user_id=1, seed_movie_ids=[1]).mode == "seed"
    both = ranker.rank(RecommendRequest(user_id=1, query="x", seed_movie_ids=[11]))
    assert both.mode == "query+seed" and "seed" in both.weights and "query" in both.weights


def test_sparse_user_is_flagged_but_keeps_the_mode_weights(ranker):
    ranking = ranker.rank(RecommendRequest(user_id=1))  # 7 ratings < threshold 30
    assert ranking.sparse_user
    assert ranking.weights == ranker.cfg.ranking.weights["personal"]


def test_no_cf_signal_movie_gets_no_cf_score(ranker):
    ranking = ranker.rank(RecommendRequest(user_id=1))
    pos = int(np.searchsorted(ranking.movie_ids, 14))
    assert ranking.no_cf_signal[pos] and ranking.features["cf"][pos] == 0.0


def test_seeds_are_not_recommended_and_few_candidates_warns(ranker):
    result = ranker.recommend(RecommendRequest(user_id=3, seed_movie_ids=[12], k=20))
    assert 12 not in [i.movie_id for i in result.items]
    assert "few_candidates" in result.warnings
    assert result.filter_counts["seen"] == 6 and result.filter_counts["seed"] == 1


def test_query_mode_defaults_to_min_ratings(ranker):
    ranking = ranker.rank(RecommendRequest(user_id=1, query="lighthouse keeper alone"))
    assert ranker.effective_min_ratings(ranking.request) == 3
    pos = int(np.searchsorted(ranking.movie_ids, 14))
    assert ranking.removed_by[pos] == "min_ratings"


def test_items_carry_provenance(ranker):
    item = ranker.recommend(RecommendRequest(user_id=1, query="alien creature", k=1)).items[0]
    assert item.plot_excerpt and set(item.contributions) == set(item.features)
    assert abs(sum(item.contributions.values()) - item.score) < 2e-3  # rounded to 3 dp


def test_items_with_few_ratings_are_low_confidence(cfg, ds, embedder):
    # Failure 13 in docs/notes.md: a query-mode pick with 4 ratings was labelled "high".
    lenient = cfg.with_overrides(ranking={"sparse_user_threshold": 0})
    ranker = build_ranker(lenient, ds, embedder=embedder, ease_lambda=1.0)
    items = ranker.recommend(RecommendRequest(user_id=1, k=3)).items
    assert all(i.n_ratings < cfg.confidence.movie_low_below for i in items)  # tiny fixture
    assert all("few_ratings" in i.flags and i.confidence == "low" for i in items)
    none_few = build_ranker(
        lenient.with_overrides(confidence={"movie_low_below": 0}),
        ds,
        embedder=embedder,
        ease_lambda=1.0,
    )
    assert all(
        i.confidence == "high"
        for i in none_few.recommend(RecommendRequest(user_id=1, k=3)).items
        if "no_cf_signal" not in i.flags
    )
