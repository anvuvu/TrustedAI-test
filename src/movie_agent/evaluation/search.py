"""Content search evaluation (design §9.3).

Question: does description search return relevant movies, and where does plot text fail?
Flow: rank each query under every variant, add unseen (query, movie) pairs to the grading
sheet `eval/search_judgments.csv` in shuffled order without variant labels, and score the
variants once every pair has a grade (0 irrelevant, 1 partly, 2 relevant).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from movie_agent.config import PROJECT_ROOT, Config
from movie_agent.data import Dataset
from movie_agent.engines import Embedder
from movie_agent.evaluation.results import bootstrap_ci, fmt_ci, new_results_dir, save_run
from movie_agent.ranking import Ranker, RecommendRequest, build_ranker

QUERIES = PROJECT_ROOT / "eval" / "search_queries.yaml"
JUDGMENTS = PROJECT_ROOT / "eval" / "search_judgments.csv"
PERSONAL_USER = 15


def variants(ranker: Ranker) -> dict[str, dict]:
    """Search variants: plain (query + quality), plain without min_ratings, personalized."""
    base = ranker.cfg.ranking.weights["query"]
    plain = {k: v for k, v in base.items() if k != "cf"}
    return {
        "plain": {"history": {}, "weights": plain, "min_ratings": None},
        "plain_min0": {"history": {}, "weights": plain, "min_ratings": 0},
        f"personal_u{PERSONAL_USER}": {"history": None, "weights": None, "min_ratings": None},
    }


def run_variants(ranker: Ranker, queries: list[dict]) -> pd.DataFrame:
    """Top-k per (variant, query) with rank, excerpt and movie stats."""
    k = ranker.cfg.evaluation.search_top_k
    rows = []
    for name, v in variants(ranker).items():
        for q in queries:
            req = RecommendRequest(
                user_id=PERSONAL_USER, query=q["text"], k=k, min_ratings=v["min_ratings"]
            )
            result = ranker.recommend(req, history=v["history"], weights=v["weights"])
            for item in result.items:
                rows.append(
                    {
                        "variant": name,
                        "query_id": q["id"],
                        "rank": item.rank,
                        "movie_id": item.movie_id,
                        "title": item.title,
                        "n_ratings": item.n_ratings,
                        "bayes_avg": item.bayes_avg,
                        "excerpt": item.plot_excerpt,
                    }
                )
    return pd.DataFrame(rows)


def update_judgments(
    results: pd.DataFrame, queries: list[dict], path: Path, rng: np.random.Generator
) -> pd.DataFrame:
    """Append ungraded (query, movie) pairs in shuffled order; existing grades are kept."""
    text = {q["id"]: q["text"] for q in queries}
    existing = (
        pd.read_csv(path)
        if path.exists()
        else pd.DataFrame(columns=["query_id", "query", "movie_id", "title", "excerpt", "grade"])
    )
    known = set(zip(existing["query_id"], existing["movie_id"], strict=True))
    new = results.drop_duplicates(["query_id", "movie_id"]).loc[
        lambda d: [(q, m) not in known for q, m in zip(d.query_id, d.movie_id, strict=True)]
    ]
    if len(new):
        new = new.iloc[rng.permutation(len(new))]
        new = new.assign(query=new["query_id"].map(text), grade="")
        existing = pd.concat([existing, new[existing.columns]], ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing.to_csv(path, index=False)
    return existing


def score(results: pd.DataFrame, judgments: pd.DataFrame, cfg: Config) -> dict:
    """P@k (grade >= 1) and mean grade per variant, with bootstrap CIs over queries."""
    rng = np.random.default_rng(cfg.seed)
    grades = judgments.dropna(subset=["grade"])
    grades = grades[grades["grade"].astype(str).str.strip() != ""]
    graded = results.merge(
        grades.assign(grade=grades["grade"].astype(float))[["query_id", "movie_id", "grade"]],
        on=["query_id", "movie_id"],
        how="left",
    )
    out = {}
    for name, g in graded.groupby("variant", sort=False):
        per_query = g.groupby("query_id").agg(
            p_at_k=("grade", _precision), mean_grade=("grade", "mean")
        )
        out[name] = {
            "p_at_k": bootstrap_ci(per_query["p_at_k"].dropna(), cfg, rng),
            "mean_grade": bootstrap_ci(per_query["mean_grade"].dropna(), cfg, rng),
            "mean_bayes_avg": float(g["bayes_avg"].mean()),
            "share_under_5_ratings": float((g["n_ratings"] < 5).mean()),
            "ungraded": int(g["grade"].isna().sum()),
        }
    return out


def _precision(grades: pd.Series) -> float:
    """Share of graded results with grade >= 1; NaN when nothing is graded yet."""
    graded = grades.dropna()
    return float((graded >= 1).mean()) if len(graded) else float("nan")


def run_search(
    cfg: Config,
    ds: Dataset,
    embedder: Embedder | None = None,
    queries_path: Path = QUERIES,
    judgments_path: Path = JUDGMENTS,
) -> Path:
    """Run §9.3 on all ratings (search quality does not depend on the split)."""
    queries = yaml.safe_load(queries_path.read_text())["queries"]
    ranker = build_ranker(cfg, ds, embedder=embedder)
    results = run_variants(ranker, queries)
    rng = np.random.default_rng(cfg.seed)
    judgments = update_judgments(results, queries, judgments_path, rng)
    metrics = {"variants": score(results, judgments, cfg), "n_queries": len(queries)}
    out = new_results_dir(cfg, "search")
    results.to_csv(out / "results.csv", index=False)
    save_run(out, cfg, metrics, _summary(metrics, results, queries))
    return out


def _summary(metrics: dict, results: pd.DataFrame, queries: list[dict]) -> str:
    lines = [
        f"# Content search, {metrics['n_queries']} queries",
        "",
        "| Variant | P@5 | Mean grade | Mean Bayesian avg | Share < 5 ratings | Ungraded |",
        "|---|---|---|---|---|---|",
    ]
    for name, v in metrics["variants"].items():
        lines.append(
            f"| {name} | {fmt_ci(v['p_at_k'], 2)} | {fmt_ci(v['mean_grade'], 2)} | "
            f"{v['mean_bayes_avg']:.2f} | {v['share_under_5_ratings']:.2f} | "
            f"{v['ungraded']} |"
        )
    for q in queries:
        lines += ["", f"## {q['id']}: {q['text']}", ""]
        for name, g in results[results.query_id == q["id"]].groupby("variant", sort=False):
            titles = "; ".join(f"{r.title} ({r.n_ratings})" for r in g.itertuples())
            lines.append(f"- **{name}**: {titles}")
    return "\n".join(lines)
