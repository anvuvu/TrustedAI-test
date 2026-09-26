import pandas as pd

from movie_agent.data import (
    compute_stats,
    genre_table,
    temporal_split,
    tie_boundary_users,
    validate,
)


def test_validate_reports_clean_fixture_and_facts(ds, cfg):
    report = validate(ds, cfg)
    assert all(v == 0 for v in report["checks"].values()), report["checks"]
    facts = report["facts"]
    assert facts["n_movies"] == 15 and facts["n_ratings"] == 36 and facts["n_users"] == 6
    assert facts["n_genre_labels"] == 15
    assert facts["n_content_genres"] == 13  # IMAX and (no genres listed) excluded
    assert facts["movies_with_0_ratings"] == 1  # movie 14
    assert facts["zero_variance_users"] == [4]
    assert facts["top_tagger"] == {"user_id": 2, "n_tags": 4, "share": 0.8}
    assert facts["top_tags_by_movies"]["twist ending"] == 2  # case-folded


def test_validate_counts_bad_rows(ds, cfg):
    bad = ds.ratings.copy()
    bad.loc[len(bad)] = [1, 999, 4.2, 1]  # unknown movie and invalid value
    bad.loc[len(bad)] = [1, 2, 3.0, 2]  # duplicate pair
    report = validate(type(ds)(movies=ds.movies, ratings=bad, tags=ds.tags), cfg)
    assert report["checks"]["ratings_unknown_movie"] == 1
    assert report["checks"]["invalid_rating_values"] == 1
    assert report["checks"]["duplicate_user_movie_pairs"] == 1


def test_split_sizes_and_temporal_order(ds, cfg):
    split = temporal_split(ds.ratings, cfg)
    assert len(split.train) + len(split.val) + len(split.test) == len(ds.ratings)
    user1 = {
        name: part[part.userId == 1]
        for name, part in [("train", split.train), ("val", split.val), ("test", split.test)]
    }
    assert [len(user1[k]) for k in ("train", "val", "test")] == [4, 1, 2]  # n = 7
    assert user1["train"]["timestamp"].max() < user1["val"]["timestamp"].min()
    assert user1["val"]["timestamp"].max() < user1["test"]["timestamp"].min()


def test_tie_boundary_counts_users_split_inside_equal_timestamps(ds, cfg):
    # user 4 (4 ratings, 2 test) has three at t=4000; user 5 (6 ratings, 2 test) three at 5003.
    assert tie_boundary_users(ds.ratings, cfg) == 2


def test_stats_bayes_and_unrated_movies(ds, cfg):
    stats = compute_stats(ds.ratings, ds.movies, cfg)
    m = ds.ratings["rating"].mean()
    assert stats.movie.at[14, "n"] == 0
    assert stats.movie.at[14, "bayes"] == m
    heat = ds.ratings[ds.ratings.movieId == 2]["rating"]
    expected = (cfg.stats.bayes_C * m + heat.sum()) / (cfg.stats.bayes_C + len(heat))
    assert abs(stats.movie.at[2, "bayes"] - expected) < 1e-12


def test_genre_table_affinity_is_shrunk_centred_mean(ds, cfg):
    stats = compute_stats(ds.ratings, ds.movies, cfg)
    hist = pd.DataFrame({"movieId": [1, 2, 5], "rating": [2.0, 5.0, 5.0]})  # mean 4
    table = genre_table(hist, ds.movies, stats, cfg)
    # Sci-Fi: only movie 5 (+1.0) -> 1.0 / (1 + 3)
    assert abs(table.at["Sci-Fi", "affinity"] - 0.25) < 1e-12
    assert table.at["Sci-Fi", "count"] == 1
    assert "IMAX" not in table.index
