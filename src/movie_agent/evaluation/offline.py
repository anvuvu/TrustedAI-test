"""Offline ranking evaluation (design §9.2).

Question: does personalization beat non-personalized baselines, for which users, and at
what cost in popularity bias? Fit on train (val run) or train + val (final test run), rank
every movie the user has not rated in the fit data, and score against held-out ratings.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from movie_agent.config import Config
from movie_agent.data import Dataset, Split, temporal_split
from movie_agent.engines import Embedder
from movie_agent.evaluation.results import (
    bootstrap_ci,
    fmt_ci,
    new_results_dir,
    paired_bootstrap,
    save_run,
)
from movie_agent.ranking import Ranker, RecommendRequest, build_ranker
from movie_agent.trace import git_commit

Recommender = Callable[[int], list[int]]


def fit_and_holdout(split: Split, split_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(fit ratings, held-out ratings): (train, val) for tuning, (train + val, test) for final."""
    if split_name == "val":
        return split.train, split.val
    if split_name == "test":
        return split.train_val, split.test
    raise ValueError(f"unknown split {split_name!r}")


def top_k(
    scores: np.ndarray,
    movie_ids: np.ndarray,
    exclude: set[int],
    k: int,
    tiebreak: np.ndarray | None = None,
) -> list[int]:
    """Top-k movie ids by score, excluding `exclude`; NaN ranks last; ties by `tiebreak`, id."""
    s = np.where(np.isnan(scores), -np.inf, scores).astype(np.float64)
    s[np.isin(movie_ids, list(exclude))] = -np.inf
    secondary = np.zeros(len(s)) if tiebreak is None else -tiebreak
    order = np.lexsort((movie_ids, secondary, -s))
    return [int(movie_ids[i]) for i in order[:k] if np.isfinite(s[i])]


def recall_ndcg(ranked: list[int], relevant: set[int], k: int) -> tuple[float, float]:
    """Recall@k and binary NDCG@k (ideal DCG over min(|relevant|, k) positions)."""
    hits = [1.0 if m in relevant else 0.0 for m in ranked[:k]]
    recall = sum(hits) / len(relevant)
    dcg = sum(h / np.log2(i + 2) for i, h in enumerate(hits))
    idcg = sum(1 / np.log2(i + 2) for i in range(min(len(relevant), k)))
    return recall, dcg / idcg


def make_systems(ranker: Ranker, weights: dict[str, float] | None = None) -> dict[str, Recommender]:
    """The §9.2 systems as functions user_id -> top-k list."""
    k = ranker.cfg.evaluation.k
    ids = ranker.movie_ids
    pop = ranker.stats.movie["n"].to_numpy(dtype=np.float64)
    bayes = ranker.stats.movie["bayes"].to_numpy()
    knn_scores, _ = ranker.user_knn.score_all()
    knn_row = {int(u): i for i, u in enumerate(ranker.user_knn.user_ids)}

    def seen(u: int) -> set[int]:
        return set(ranker.history(u))

    def content(u: int) -> list[int]:
        profile = ranker.content.profile(ranker.history(u), ranker.cfg.data.liked_abs)
        if profile is None:
            return top_k(pop, ids, seen(u), k)
        return top_k(ranker.content.movie_vecs @ profile, ids, seen(u), k, tiebreak=pop)

    def blend(u: int) -> list[int]:
        return ranker.rank(RecommendRequest(user_id=u, k=k), weights=weights).top(k)

    return {
        "MostPopular": lambda u: top_k(pop, ids, seen(u), k),
        "TopBayesian": lambda u: top_k(bayes, ids, seen(u), k, tiebreak=pop),
        "UserKNN": lambda u: top_k(knn_scores[knn_row[u]], ids, seen(u), k, tiebreak=pop),
        "EASE": lambda u: top_k(
            ranker.ease.scores(list(ranker.history(u))), ids, seen(u), k, tiebreak=pop
        ),
        "ContentProfile": content,
        "Blend": blend,
    }


def per_user_rows(ranker: Ranker, holdout: pd.DataFrame, systems: dict[str, Recommender]):
    """One row per (system, user) with accuracy and beyond-accuracy values."""
    cfg = ranker.cfg
    k = cfg.evaluation.k
    n_fit = ranker.stats.movie["n"]
    head = set(
        n_fit.sort_values(ascending=False, kind="stable").index[
            : int(cfg.evaluation.head_frac * len(n_fit))
        ]
    )
    rows = []
    for user_id, held in holdout.groupby("userId"):
        user_id = int(user_id)
        history = ranker.history(user_id)
        if not history:
            continue
        mu = float(np.mean(list(history.values())))
        rel_abs = set(held.loc[held["rating"] >= cfg.data.liked_abs, "movieId"].astype(int))
        rel_rel = set(held.loc[held["rating"] - mu >= cfg.data.liked_rel, "movieId"].astype(int))
        if not rel_abs:
            continue
        hist_pop = float(n_fit.loc[list(history)].mean())
        tail = rel_abs - head
        for name, recommend in systems.items():
            ranked = recommend(user_id)
            recall, ndcg = recall_ndcg(ranked, rel_abs, k)
            row = {
                "system": name,
                "user_id": user_id,
                "n_train": len(history),
                "recall": recall,
                "ndcg": ndcg,
                "recall_rel": recall_ndcg(ranked, rel_rel, k)[0] if rel_rel else np.nan,
                "ndcg_rel": recall_ndcg(ranked, rel_rel, k)[1] if rel_rel else np.nan,
                "tail_recall": recall_ndcg(ranked, tail, k)[0] if tail else np.nan,
                "head_recall": recall_ndcg(ranked, rel_abs & head, k)[0]
                if rel_abs & head
                else np.nan,
                "rec_pop": float(n_fit.loc[ranked].mean()) if ranked else np.nan,
                "hist_pop": hist_pop,
                "sparse_share": float(
                    (n_fit.loc[ranked] < cfg.evaluation.sparse_movie_below).mean()
                )
                if ranked
                else np.nan,
                "recommended": ranked,
            }
            rows.append(row)
    return pd.DataFrame(rows)


def summarize(rows: pd.DataFrame, cfg: Config, n_movies: int) -> dict:
    rng = np.random.default_rng(cfg.seed)
    users = sorted(rows["user_id"].unique())
    terciles = np.unique(np.quantile(rows.drop_duplicates("user_id")["n_train"], [1 / 3, 2 / 3]))
    labels = ["small", "medium", "large"][: len(terciles) + 1]  # fewer if cut points coincide
    rows = rows.assign(segment=pd.cut(rows["n_train"], [-np.inf, *terciles, np.inf], labels=labels))
    out: dict = {
        "n_users": len(users),
        "k": cfg.evaluation.k,
        "history_terciles": [float(t) for t in terciles],
        "systems": {},
    }
    for name, g in rows.groupby("system", sort=False):
        g = g.sort_values("user_id")
        coverage = len({m for rec in g["recommended"] for m in rec}) / n_movies
        out["systems"][name] = {
            "recall": bootstrap_ci(g["recall"], cfg, rng),
            "ndcg": bootstrap_ci(g["ndcg"], cfg, rng),
            "recall_rel": bootstrap_ci(g["recall_rel"].dropna(), cfg, rng),
            "ndcg_rel": bootstrap_ci(g["ndcg_rel"].dropna(), cfg, rng),
            "tail_recall": bootstrap_ci(g["tail_recall"].dropna(), cfg, rng),
            "head_recall": bootstrap_ci(g["head_recall"].dropna(), cfg, rng),
            "coverage": coverage,
            "rec_pop": float(g["rec_pop"].mean()),
            "hist_pop": float(g["hist_pop"].mean()),
            "pop_ratio": float((g["rec_pop"] / g["hist_pop"]).mean()),
            "sparse_share": float(g["sparse_share"].mean()),
            "segments": {
                str(seg): {
                    "recall": bootstrap_ci(s["recall"], cfg, rng),
                    "ndcg": bootstrap_ci(s["ndcg"], cfg, rng),
                }
                for seg, s in g.groupby("segment", observed=True)
            },
        }
    out["paired"] = {}
    for a, b in [("Blend", "EASE"), ("EASE", "MostPopular")]:
        ga = rows[rows.system == a].sort_values("user_id")
        gb = rows[rows.system == b].sort_values("user_id")
        out["paired"][f"{a} - {b}"] = {
            m: paired_bootstrap(ga[m].to_numpy(), gb[m].to_numpy(), cfg, rng)
            for m in ("recall", "ndcg")
        }
    return out


def sweeps(
    cfg: Config, ds: Dataset, fit: pd.DataFrame, holdout: pd.DataFrame, base: Ranker
) -> dict:
    """Val-only tuning: EASE lambda grid and the personal-mode cf/content split (quality fixed)."""
    rng = np.random.default_rng(cfg.seed)
    result: dict = {"ease_lambda": {}, "cf_weight": {}}
    for lam in cfg.ease.lambda_grid:
        ranker = build_ranker(cfg, ds, fit, base.embedder, base.content, ease_lambda=lam)
        systems = {"EASE": make_systems(ranker)["EASE"]}
        rows = per_user_rows(ranker, holdout, systems)
        result["ease_lambda"][str(lam)] = bootstrap_ci(rows["ndcg"], cfg, rng)
    personal = cfg.ranking.weights["personal"]
    free = personal["cf"] + personal["content"]
    for cf in cfg.evaluation.cf_weight_grid:
        w = {"cf": cf, "content": max(free - cf, 0.0), "quality": personal["quality"]}
        rows = per_user_rows(base, holdout, {"Blend": make_systems(base, w)["Blend"]})
        small = rows[rows["n_train"] < cfg.ranking.sparse_user_threshold]
        result["cf_weight"][str(cf)] = {
            "weights": w,
            "ndcg": bootstrap_ci(rows["ndcg"], cfg, rng),
            "ndcg_sparse_users": bootstrap_ci(small["ndcg"], cfg, rng),
        }
    return result


def qualitative(ranker: Ranker, cfg: Config) -> dict:
    """Top 5 for the qualitative users next to their top-rated fitted movies."""
    out = {}
    for user_id in cfg.evaluation.qualitative_users:
        history = ranker.history(user_id)
        if not history:
            continue
        liked = sorted(history.items(), key=lambda x: (-x[1], x[0]))[:5]
        top = ranker.recommend(RecommendRequest(user_id=user_id, k=5)).items
        out[str(user_id)] = {
            "n_ratings": len(history),
            "top_rated": [f"{ranker.catalog.display_title(m)}: {r}" for m, r in liked],
            "blend_top5": [f"{i.title} (score {i.score}, {i.n_ratings} ratings)" for i in top],
        }
    return out


def run_offline(
    cfg: Config, ds: Dataset, split_name: str, final: bool = False, embedder: Embedder | None = None
) -> Path:
    """Run §9.2 and write results. `--split test` needs `final=True` and is logged."""
    if split_name == "test" and not final:
        raise ValueError("the test split is used once, in Step 3: pass --final")
    split = temporal_split(ds.ratings, cfg)
    fit, holdout = fit_and_holdout(split, split_name)
    ranker = build_ranker(cfg, ds, fit, embedder)
    rows = per_user_rows(ranker, holdout, make_systems(ranker))
    metrics = summarize(rows, cfg, len(ds.movies))
    metrics["split"] = split_name
    metrics["fit_ratings"], metrics["holdout_ratings"] = len(fit), len(holdout)
    if split_name == "val":
        metrics["sweeps"] = sweeps(cfg, ds, fit, holdout, ranker)
    metrics["qualitative"] = qualitative(ranker, cfg)

    out = new_results_dir(cfg, f"offline_{split_name}")
    rows.drop(columns="recommended").to_csv(out / "per_user.csv", index=False)
    save_run(out, cfg, metrics, summary_markdown(metrics))
    if split_name == "test":
        log = cfg.paths.results_dir / "test_runs.log"
        with log.open("a") as fh:
            fh.write(
                f"{datetime.now().isoformat(timespec='seconds')}\t{git_commit()}\t"
                f"{cfg.config_hash()}\t{out.name}\n"
            )
    return out


def summary_markdown(m: dict) -> str:
    lines = [
        f"# Offline ranking ({m['split']}), K = {m['k']}, {m['n_users']} users",
        "",
        "Relevant: held-out rating >= 4.0. 95% bootstrap CIs over users.",
        "",
        "| System | Recall@K | NDCG@K | Tail recall | Coverage | Pop. ratio | Sparse share |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in m["systems"].items():
        lines.append(
            f"| {name} | {fmt_ci(s['recall'])} | {fmt_ci(s['ndcg'])} | "
            f"{fmt_ci(s['tail_recall'])} | {s['coverage']:.3f} | {s['pop_ratio']:.2f} | "
            f"{s['sparse_share']:.3f} |"
        )
    lines += [
        "",
        "Secondary relevance (rating - user mean >= 0.5):",
        "",
        "| System | Recall@K | NDCG@K |",
        "|---|---|---|",
    ]
    lines += [
        f"| {n} | {fmt_ci(s['recall_rel'])} | {fmt_ci(s['ndcg_rel'])} |"
        for n, s in m["systems"].items()
    ]
    lines += [
        "",
        f"NDCG@K by train-history tercile (cut points {m['history_terciles']}):",
        "",
        "| System | small | medium | large |",
        "|---|---|---|---|",
    ]
    for n, s in m["systems"].items():
        seg = s["segments"]
        lines.append(
            f"| {n} | "
            + " | ".join(
                fmt_ci(seg[t]["ndcg"]) if t in seg else "-" for t in ("small", "medium", "large")
            )
            + " |"
        )
    lines += [
        "",
        "Paired differences:",
        "",
        "| Comparison | Metric | Mean diff [CI] | Significant |",
        "|---|---|---|---|",
    ]
    for comp, metrics in m["paired"].items():
        for metric, ci in metrics.items():
            lines.append(f"| {comp} | {metric} | {fmt_ci(ci)} | {ci['significant']} |")
    if "sweeps" in m:
        lines += ["", "EASE lambda (NDCG@K):", ""]
        lines += [f"- {lam}: {fmt_ci(ci)}" for lam, ci in m["sweeps"]["ease_lambda"].items()]
        lines += [
            "",
            "Personal-mode cf weight (NDCG@K overall / users under the sparse threshold):",
            "",
        ]
        lines += [
            f"- cf {cf} {v['weights']}: {fmt_ci(v['ndcg'])} / {fmt_ci(v['ndcg_sparse_users'])}"
            for cf, v in m["sweeps"]["cf_weight"].items()
        ]
    lines += ["", "Qualitative:", ""]
    for user_id, q in m["qualitative"].items():
        lines += [
            f"**User {user_id}** ({q['n_ratings']} ratings). Top rated: "
            + "; ".join(q["top_rated"]),
            "",
            "Blend top 5: " + "; ".join(q["blend_top5"]),
            "",
        ]
    return "\n".join(lines)
