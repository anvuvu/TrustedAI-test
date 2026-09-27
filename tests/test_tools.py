import json

import pytest


def test_every_tool_schema_is_openai_compatible(toolbox):
    schemas = toolbox.openai_schemas()
    assert [s["function"]["name"] for s in schemas] == [
        "get_user_profile",
        "find_movie",
        "recommend",
        "peer_opinion",
        "explain",
    ]
    for s in schemas:
        assert s["function"]["description"] and s["function"]["parameters"]["type"] == "object"
        json.dumps(s)


def test_error_codes(toolbox):
    assert toolbox.call("get_user_profile", {"user_id": 99}).error_code == "USER_NOT_FOUND"
    assert toolbox.call("find_movie", {"title": "The Matrix"}).error_code == "MOVIE_NOT_FOUND"
    ambiguous = toolbox.call("find_movie", {"title": "Sabrina"})
    assert ambiguous.error_code == "AMBIGUOUS_MOVIE"
    assert {c["movie_id"] for c in ambiguous.data["candidates"][:2]} == {8, 9}
    assert (
        toolbox.call("recommend", {"user_id": 1, "exclude_genres": ["Cartoons"]}).error_code
        == "INVALID_ARGS"
    )
    assert toolbox.call("peer_opinion", {"user_id": 1}).error_code == "INVALID_ARGS"
    assert (
        toolbox.call("peer_opinion", {"user_id": 1, "movie_id": 999}).error_code
        == "MOVIE_NOT_FOUND"
    )
    assert toolbox.call("nope", {}).error_code == "INVALID_ARGS"


def test_find_movie_found_has_stats_tags_and_excerpt(toolbox):
    result = toolbox.call("find_movie", {"title": "usual suspects"})
    assert result.ok and result.data["movie_id"] == 10
    assert result.data["n_ratings"] == 3 and result.confidence == "low"  # < 5 ratings
    assert result.data["top_tags"] == [{"tag": "twist ending", "count": 2}]
    netflix = toolbox.call("find_movie", {"title": "Heat"}).data["top_tags"]
    assert netflix == []  # "in netflix queue" is stoplisted


def test_recommend_canonicalizes_genres_and_reports_filters(toolbox):
    result = toolbox.call("recommend", {"user_id": 1, "exclude_genres": ["animation"], "k": 3})
    assert result.ok
    items = result.data["items"]
    assert len(items) == 3 and all("Animation" not in i["genres"] for i in items)
    assert result.data["filter_counts"]["exclude_genres"] >= 1
    assert result.confidence == "low" and "sparse_user" in result.warnings


def test_peer_opinion_counts_neighbours_who_rated(toolbox):
    result = toolbox.call("peer_opinion", {"user_id": 1, "movie_id": 12})
    assert result.ok
    d = result.data
    raters = [e for e in d["examples"]]
    assert d["similar_users_who_rated"] == len(raters)
    assert result.confidence == "low"  # fewer than 3 neighbours rated it
    assert d["all_users"]["n_ratings"] == 2 and d["your_rating"] is None


def test_peer_opinion_without_neighbours_falls_back_to_global(toolbox):
    result = toolbox.call("peer_opinion", {"user_id": 4, "movie_id": 2})
    assert result.ok and "no_similar_user_rated" in result.warnings
    assert result.data["similar_users_mean_rating"] is None
    assert result.data["all_users"]["n_ratings"] == 3


def test_user_profile_genres_and_blind_spots(toolbox):
    result = toolbox.call("get_user_profile", {"user_id": 3})
    d = result.data
    assert d["n_ratings"] == 6 and result.confidence == "low"
    assert d["top_liked"][0]["rating"] == 5.0
    unexplored = {g["genre"] for g in d["unexplored_genres"]}
    assert {"Crime", "Thriller"} <= unexplored  # never rated
    assert "suggestions" not in json.dumps(d)  # the profile never suggests movies
    assert all(g["genre"] not in {"IMAX", "(no genres listed)"} for g in d["genres"])


def test_avoided_genre_needs_ratings_and_negative_affinity(toolbox, ranker):
    ranker.histories[3] = {1: 5.0, 11: 5.0, 5: 1.0, 6: 1.0, 7: 1.0, 3: 5.0}
    avoided = {
        g["genre"] for g in toolbox.call("get_user_profile", {"user_id": 3}).data["avoided_genres"]
    }
    assert "Horror" in avoided and "Sci-Fi" in avoided


def test_explain_returns_drivers_with_history_movies(toolbox):
    result = toolbox.call("explain", {"user_id": 2, "movie_id": 4})
    d = result.data
    assert d["drivers"] and d["drivers"] == sorted(d["drivers"], key=lambda x: -x["contribution"])
    assert {x["signal"] for x in d["drivers"]} <= {"cf", "content", "quality"}
    assert len(d["similar_plots_you_rated"]) == 3
    assert d["personal_rank"] is not None
    cf = next(x for x in d["drivers"] if x["signal"] == "cf")
    if d["because_you_rated"]:
        assert cf["via_history_movie"]["movie_id"] == d["because_you_rated"][0]["movie_id"]


@pytest.mark.parametrize("tool", ["peer_opinion", "explain"])
def test_tools_reject_unknown_user(toolbox, tool):
    assert toolbox.call(tool, {"user_id": 42, "movie_id": 1}).error_code == "USER_NOT_FOUND"
