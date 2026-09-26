"""Loading, validation, statistics and splits (design §4).

Everything here is a pure function of dataframes, except `load_dataset` (reads CSVs)
and `write_data_report` (writes JSON).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from movie_agent.config import Config

RATING_VALUES = {x / 2 for x in range(1, 11)}  # 0.5, 1.0, ..., 5.0


@dataclass(frozen=True)
class Dataset:
    """The raw tables. `movies` is indexed by movieId; `genres` holds a list per movie."""

    movies: pd.DataFrame  # index movieId; columns title, year, genres (list[str]), plot
    ratings: pd.DataFrame  # userId, movieId, rating, timestamp
    tags: pd.DataFrame  # userId, movieId, tag, timestamp


def load_dataset(data_dir: Path) -> Dataset:
    """Read `movies_with_plots.csv`, `ratings.csv` and `tags.csv` from `data_dir`."""
    movies = pd.read_csv(data_dir / "movies_with_plots.csv")
    movies["genres"] = movies["genres"].fillna("").map(lambda s: [g for g in s.split("|") if g])
    movies["plot"] = movies["plot"].fillna("")
    movies = movies.set_index("movieId").sort_index()
    ratings = pd.read_csv(data_dir / "ratings.csv")
    tags = pd.read_csv(data_dir / "tags.csv")
    return Dataset(movies=movies, ratings=ratings, tags=tags)


# ---------------------------------------------------------------------------
# Statistics (§4.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    """Rating statistics of one ratings frame (train, train + val, or all data)."""

    global_mean: float
    user: pd.DataFrame  # index userId: n, mean, std
    movie: pd.DataFrame  # index movieId (whole catalog): n, mean, bayes
    genre_share: pd.Series  # genre -> share of all ratings that fall in the genre


def compute_stats(ratings: pd.DataFrame, movies: pd.DataFrame, cfg: Config) -> Stats:
    """User and movie statistics, Bayesian averages and global genre shares.

    Movies without ratings get n = 0, mean NaN and bayes = global mean.
    """
    m = float(ratings["rating"].mean())
    user = ratings.groupby("userId")["rating"].agg(n="size", mean="mean", std="std")
    user["std"] = user["std"].fillna(0.0)
    movie = ratings.groupby("movieId")["rating"].agg(n="size", mean="mean", total="sum")
    movie = movie.reindex(movies.index)
    movie["n"] = movie["n"].fillna(0).astype(int)
    movie["total"] = movie["total"].fillna(0.0)
    c = cfg.stats.bayes_C
    movie["bayes"] = (c * m + movie["total"]) / (c + movie["n"])
    movie = movie.drop(columns="total")
    return Stats(
        global_mean=m,
        user=user,
        movie=movie,
        genre_share=genre_shares(ratings["movieId"], movies, cfg),
    )


def content_genres(movies: pd.DataFrame, cfg: Config) -> list[str]:
    """Genre labels used for affinity and blind spots: all labels minus `genre_exclude`."""
    labels = {g for gs in movies["genres"] for g in gs}
    return sorted(labels - set(cfg.data.genre_exclude))


def genre_shares(movie_ids: pd.Series, movies: pd.DataFrame, cfg: Config) -> pd.Series:
    """Fraction of the given ratings (one movieId per rating) that fall in each content genre.

    A multi-genre movie counts toward each of its genres, so shares can sum above 1.
    """
    genres = content_genres(movies, cfg)
    exploded = movies.loc[movie_ids.to_numpy(), "genres"].explode()
    counts = exploded.value_counts()
    return (counts.reindex(genres).fillna(0) / max(len(movie_ids), 1)).astype(float)


def genre_table(history: pd.DataFrame, movies: pd.DataFrame, stats: Stats, cfg: Config):
    """Per content genre: the user's count, share, global share and shrunk affinity.

    Input: `history` with columns movieId, rating (one user's ratings).
    Affinity = sum of mean-centred ratings in the genre / (count + alpha), in rating units.
    Output: DataFrame indexed by genre.
    """
    genres = content_genres(movies, cfg)
    mu = float(history["rating"].mean()) if len(history) else 0.0
    rows = history.assign(centred=history["rating"] - mu)
    rows = rows.assign(genre=movies.loc[rows["movieId"].to_numpy(), "genres"].to_numpy())
    rows = rows.explode("genre")
    grouped = rows.groupby("genre")["centred"].agg(["size", "sum"]).reindex(genres).fillna(0)
    n_hist = max(len(history), 1)
    return pd.DataFrame(
        {
            "count": grouped["size"].astype(int),
            "share": grouped["size"] / n_hist,
            "global_share": stats.genre_share.reindex(genres).fillna(0.0),
            "affinity": grouped["sum"] / (grouped["size"] + cfg.stats.genre_alpha),
        }
    )


def history_of(ratings: pd.DataFrame, user_id: int) -> pd.DataFrame:
    """One user's ratings (movieId, rating, timestamp), in timestamp order."""
    rows = ratings[ratings["userId"] == user_id]
    return rows[["movieId", "rating", "timestamp"]].sort_values(["timestamp", "movieId"])


# ---------------------------------------------------------------------------
# Splits (§4.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame

    @property
    def train_val(self) -> pd.DataFrame:
        """Train plus val: the fit set of the final (Step 3) run."""
        return pd.concat([self.train, self.val], ignore_index=True)


def _holdout_size(n: int, frac: float, minimum: int) -> int:
    return max(minimum, math.ceil(frac * n))


def temporal_split(ratings: pd.DataFrame, cfg: Config) -> Split:
    """Per-user temporal split: last 20% test, last 10% of the rest val, the rest train.

    Ratings are ordered by (timestamp, movieId); ties are therefore broken by movieId.
    """
    parts: dict[str, list[pd.DataFrame]] = {"train": [], "val": [], "test": []}
    ordered = ratings.sort_values(["userId", "timestamp", "movieId"])
    for _, rows in ordered.groupby("userId", sort=True):
        n = len(rows)
        n_test = _holdout_size(n, cfg.data.test_frac, cfg.data.min_test)
        n_val = _holdout_size(n - n_test, cfg.data.val_frac, cfg.data.min_val)
        n_train = n - n_test - n_val
        parts["train"].append(rows.iloc[:n_train])
        parts["val"].append(rows.iloc[n_train : n_train + n_val])
        parts["test"].append(rows.iloc[n_train + n_val :])
    frames = {k: pd.concat(v, ignore_index=True) for k, v in parts.items()}
    return Split(**frames)


def tie_boundary_users(ratings: pd.DataFrame, cfg: Config) -> int:
    """Number of users whose train/test boundary falls inside a block of equal timestamps."""
    count = 0
    ordered = ratings.sort_values(["userId", "timestamp", "movieId"])
    for _, rows in ordered.groupby("userId"):
        ts = rows["timestamp"].to_numpy()
        cut = len(ts) - _holdout_size(len(ts), cfg.data.test_frac, cfg.data.min_test)
        if 0 < cut < len(ts) and ts[cut - 1] == ts[cut]:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Validation (§4.1, §4.2)
# ---------------------------------------------------------------------------


def validate(ds: Dataset, cfg: Config) -> dict:
    """Run the §4.2 checks and recompute the §4.1 facts.

    Output: a JSON-serializable report with `checks` (issue counts, 0 = clean) and `facts`.
    """
    movies, ratings, tags = ds.movies, ds.ratings, ds.tags
    known = set(movies.index)
    per_movie = ratings.groupby("movieId").size().reindex(movies.index).fillna(0)
    per_user = ratings.groupby("userId").size()
    label_counts = movies["genres"].explode().value_counts()
    tag_movies = tags.assign(tag=tags["tag"].str.strip().str.lower()).groupby("tag")["movieId"]
    top_tags = tag_movies.nunique().sort_values(ascending=False).head(10)
    tagger_counts = tags.groupby("userId").size().sort_values(ascending=False)
    user_std = ratings.groupby("userId")["rating"].std().fillna(0.0)

    checks = {
        "ratings_unknown_movie": int((~ratings["movieId"].isin(known)).sum()),
        "duplicate_user_movie_pairs": int(ratings.duplicated(["userId", "movieId"]).sum()),
        "invalid_rating_values": int((~ratings["rating"].isin(RATING_VALUES)).sum()),
        "short_or_empty_plots": int((movies["plot"].str.len() < cfg.data.short_plot_chars).sum()),
        "missing_years": int(movies["year"].isna().sum()),
        "tags_unknown_movie": int((~tags["movieId"].isin(known)).sum()),
    }
    facts = {
        "n_movies": len(movies),
        "n_ratings": len(ratings),
        "n_users": int(ratings["userId"].nunique()),
        "n_tags": len(tags),
        "year_range": [int(movies["year"].min()), int(movies["year"].max())],
        "titles_with_year_in_title": int(movies["title"].str.contains(r"\(\d{4}\)\s*$").sum()),
        "titles_with_parenthetical_alias": int(movies["title"].str.contains(r"\(").sum()),
        "genre_labels": {str(k): int(v) for k, v in label_counts.items()},
        "n_genre_labels": len(label_counts),
        "n_content_genres": len(content_genres(movies, cfg)),
        "movies_with_0_ratings": int((per_movie == 0).sum()),
        "movies_under_3_ratings": int((per_movie < 3).sum()),
        "movies_under_3_ratings_share": round(float((per_movie < 3).mean()), 4),
        "movies_under_5_ratings_share": round(float((per_movie < 5).mean()), 4),
        "ratings_per_user": _describe(per_user),
        "ratings_per_movie": _describe(per_movie),
        "users_under_10_ratings": int((per_user < 10).sum()),
        "zero_variance_users": [int(u) for u in user_std[user_std == 0].index],
        "tie_boundary_users": tie_boundary_users(ratings, cfg),
        "n_taggers": int(tags["userId"].nunique()),
        "top_tagger": {
            "user_id": int(tagger_counts.index[0]),
            "n_tags": int(tagger_counts.iloc[0]),
            "share": round(float(tagger_counts.iloc[0] / len(tags)), 4),
        },
        "movies_with_tags": int(tags["movieId"].nunique()),
        "top_tags_by_movies": {str(k): int(v) for k, v in top_tags.items()},
        "global_mean_rating": round(float(ratings["rating"].mean()), 4),
    }
    return {"checks": checks, "facts": facts}


def _describe(series: pd.Series) -> dict[str, float]:
    return {
        "min": float(series.min()),
        "median": float(series.median()),
        "mean": round(float(series.mean()), 2),
        "max": float(series.max()),
    }


def write_data_report(report: dict, cfg: Config) -> Path:
    """Write the validation report to `<results_dir>/data_report.json` and return the path."""
    path = cfg.paths.results_dir / "data_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=_json_default) + "\n")
    return path


def _json_default(value: object) -> object:
    if isinstance(value, np.integer | np.floating):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)}")
