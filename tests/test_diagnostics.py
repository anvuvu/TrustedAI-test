"""why-not returns the right code for crafted cases covering every code in §8.2."""

from movie_agent.diagnostics import why_not
from movie_agent.ranking import RecommendRequest


def test_not_in_catalog(ranker):
    assert why_not(ranker, RecommendRequest(user_id=1), "The Matrix").code == "NOT_IN_CATALOG"


def test_already_seen(ranker):
    result = why_not(ranker, RecommendRequest(user_id=1), "Heat")
    assert result.code == "ALREADY_SEEN" and result.detail["your_rating"] == 5.0


def test_filtered_by_genre_and_min_ratings(ranker):
    req = RecommendRequest(user_id=1, exclude_genres=["Animation"])
    result = why_not(ranker, req, "Shrek")
    assert result.code == "FILTERED:exclude_genres" and result.detail["excluded"] == ["Animation"]
    query = RecommendRequest(user_id=1, query="lighthouse keeper")
    assert why_not(ranker, query, "14").code == "FILTERED:min_ratings"


def test_ranked_below_names_the_largest_gap(ranker):
    req = RecommendRequest(user_id=1, k=1)
    ranking = ranker.rank(req)
    second = ranking.top(2)[1]
    result = why_not(ranker, req, str(second))
    assert result.code == "RANKED_BELOW"
    assert result.detail["rank"] == 2
    assert result.detail["largest_gap_feature"] in result.detail["contributions"]


def test_in_top_k(ranker):
    req = RecommendRequest(user_id=1, k=3)
    top = ranker.rank(req).top(1)[0]
    assert why_not(ranker, req, str(top)).code == "IN_TOP_K"
