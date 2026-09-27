"""Step 2 diagnosis, part 2: how each feature normalization behaves in query mode.

Descriptive only (search is not graded yet): for the 10 judged queries and user 15, the share of
the top 5 that are also in the top 50 by pure query similarity ("query adherence"), the mean
Bayesian average and the mean rating count of the top 5, plus personal-mode NDCG@10 on val for
min-max (percentile, z-score and top-200 are in the first diagnosis run).
Appends to the blend_diagnosis results directory given as argv[1].
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import yaml

import movie_agent.ranking as ranking_mod
from movie_agent.config import load_config
from movie_agent.data import load_dataset, temporal_split
from movie_agent.evaluation.offline import fit_and_holdout, per_user_rows
from movie_agent.evaluation.results import bootstrap_ci, fmt_ci, paired_bootstrap
from movie_agent.ranking import RecommendRequest, build_ranker

PERCENTILE = ranking_mod.percentile


def zscore(v):
    s = v.std()
    return (v - v.mean()) / s if s > 0 else np.zeros_like(v, dtype=float)


def minmax(v):
    lo, hi = v.min(), v.max()
    return (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v, dtype=float)


def top200(v):
    out = np.zeros(len(v))
    order = np.argsort(-v, kind="stable")[:200]
    out[order] = 1 - np.arange(len(order)) / 200
    return out


NORMS = {"percentile": PERCENTILE, "z-score": zscore, "min-max": minmax, "top-200": top200}


def main(out_dir: Path) -> None:
    cfg = load_config()
    no_sparse = cfg.with_overrides(ranking={"sparse_user_threshold": 0})
    ds = load_dataset(cfg.paths.data_dir)
    full = build_ranker(cfg, ds)
    full.cfg = no_sparse
    queries = yaml.safe_load(Path("eval/search_queries.yaml").read_text())["queries"]
    report: dict = {"query_mode": {}, "personal_minmax": {}}
    lines = ["", "## Query mode by normalization (user 15, all ratings, no sparse adj.)", "",
             "| Normalization | Query adherence@5 | Mean Bayesian avg | Mean n_ratings | "
             "Example: q01 top 3 |", "|---|---|---|---|---|"]
    for name, norm in NORMS.items():
        ranking_mod.percentile = norm
        adherence, bayes, counts, example = [], [], [], ""
        for q in queries:
            req = RecommendRequest(user_id=15, query=q["text"], k=5)
            r = full.rank(req)
            sims, _ = full.content.query_similarity(full._embed(q["text"]))
            eligible = r.removed_by == ""
            idx = np.flatnonzero(eligible)
            top50 = set(idx[np.argsort(-sims[idx], kind="stable")[:50]])
            top5 = list(r.order[:5])
            adherence.append(np.mean([p in top50 for p in top5]))
            bayes.append(full.stats.movie["bayes"].to_numpy()[top5].mean())
            counts.append(full.stats.movie["n"].to_numpy()[top5].mean())
            if q["id"] == "q01_dark_twist":
                example = "; ".join(full.catalog.display_title(int(full.movie_ids[p]))
                                    for p in top5[:3])
        ranking_mod.percentile = PERCENTILE
        report["query_mode"][name] = {"adherence": float(np.mean(adherence)),
                                      "bayes": float(np.mean(bayes)),
                                      "n_ratings": float(np.mean(counts)), "q01_top3": example}
        lines.append(f"| {name} | {np.mean(adherence):.2f} | {np.mean(bayes):.2f} | "
                     f"{np.mean(counts):.0f} | {example} |")

    split = temporal_split(ds.ratings, cfg)
    fit, holdout = fit_and_holdout(split, "val")
    ranker = build_ranker(cfg, ds, fit, full.embedder, full.content)
    rng = np.random.default_rng(cfg.seed)

    def blend(norm, sparse_on):
        def rec(u):
            ranking_mod.percentile = norm
            ranker.cfg = cfg if sparse_on else no_sparse
            try:
                return ranker.rank(RecommendRequest(user_id=u, k=10)).top(10)
            finally:
                ranking_mod.percentile = PERCENTILE
                ranker.cfg = cfg
        return rec

    from movie_agent.evaluation.offline import make_systems

    systems = {"EASE": make_systems(ranker)["EASE"],
               "min-max": blend(minmax, True), "min-max, no sparse adj.": blend(minmax, False)}
    rows = per_user_rows(ranker, holdout, systems)
    ease = rows[rows.system == "EASE"].sort_values("user_id")
    lines += ["", "## Personal mode, min-max (val)", "",
              "| System | NDCG@10 | vs EASE |", "|---|---|---|"]
    for name, g in rows.groupby("system", sort=False):
        g = g.sort_values("user_id")
        nd = bootstrap_ci(g.ndcg, cfg, rng)
        diff = paired_bootstrap(g.ndcg.to_numpy(), ease.ndcg.to_numpy(), cfg, rng)
        report["personal_minmax"][name] = {"ndcg": nd, "vs_ease": diff}
        lines.append(f"| {name} | {fmt_ci(nd)} | {fmt_ci(diff)} |")

    (out_dir / "norm_query_check.json").write_text(json.dumps(report, indent=2))
    with (out_dir / "summary.md").open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.copy(__file__, out_dir / "norm_query_check.py")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
