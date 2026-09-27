"""Step 2 diagnosis (val only): why does the personal-mode Blend lose to EASE alone?

Hypotheses tested:
  H1 the sparse-user adjustment moves cf weight away for a third of the users;
  H2 the quality / content weights reorder EASE's head;
  H3 percentile normalization flattens EASE's large score gaps at the top.
Also: UserKNN-as-recommender with the unnormalized top-N sum instead of the mean deviation.
Writes eval/results/<date>_blend_diagnosis/ (metrics.json, summary.md, this script).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from scipy import sparse

import movie_agent.ranking as ranking_mod
from movie_agent.config import load_config
from movie_agent.data import load_dataset, temporal_split
from movie_agent.evaluation.offline import fit_and_holdout, per_user_rows, top_k
from movie_agent.evaluation.results import (
    bootstrap_ci,
    fmt_ci,
    new_results_dir,
    paired_bootstrap,
    save_run,
)
from movie_agent.ranking import RecommendRequest, build_ranker

PERCENTILE = ranking_mod.percentile


def zscore(values: np.ndarray) -> np.ndarray:
    std = values.std()
    return (values - values.mean()) / std if std > 0 else np.zeros_like(values, dtype=float)


def top_n_percentile(n: int):
    def norm(values: np.ndarray) -> np.ndarray:
        out = np.zeros(len(values))
        order = np.argsort(-values, kind="stable")[:n]
        out[order] = 1 - np.arange(len(order)) / n
        return out

    return norm


def main() -> None:
    cfg = load_config()
    ds = load_dataset(cfg.paths.data_dir)
    split = temporal_split(ds.ratings, cfg)
    fit, holdout = fit_and_holdout(split, "val")
    ranker = build_ranker(cfg, ds, fit)
    base_cfg = ranker.cfg
    no_sparse = cfg.with_overrides(ranking={"sparse_user_threshold": 0})
    k = cfg.evaluation.k
    ids = ranker.movie_ids
    pop = ranker.stats.movie["n"].to_numpy(dtype=np.float64)
    personal = dict(cfg.ranking.weights["personal"])

    def blend(weights, norm=PERCENTILE, sparse_on=True):
        def recommend(u: int) -> list[int]:
            ranking_mod.percentile = norm
            ranker.cfg = base_cfg if sparse_on else no_sparse
            try:
                return ranker.rank(RecommendRequest(user_id=u, k=k), weights=weights).top(k)
            finally:
                ranking_mod.percentile = PERCENTILE
                ranker.cfg = base_cfg

        return recommend

    # UserKNN with the unnormalized top-N sum: sum_v s_uv * centred_vi over neighbours who rated i.
    knn = ranker.user_knn
    weights = np.zeros_like(knn.similarity)
    for row, user_id in enumerate(knn.user_ids):
        for nb in knn.neighbours(int(user_id)):
            weights[row, knn.row_of(nb.user_id)] = nb.similarity
    w = sparse.csr_matrix(weights)
    knn_sum = (w @ knn.centred).toarray()
    support = ((w > 0).astype(float) @ knn.mask).toarray()
    knn_sum[support < cfg.user_knn.min_support] = np.nan
    knn_row = {int(u): i for i, u in enumerate(knn.user_ids)}

    systems = {
        "EASE": lambda u: top_k(ranker.ease.scores(list(ranker.history(u))), ids,
                                set(ranker.history(u)), k, tiebreak=pop),
        "Blend default (as deployed)": blend(None),
        "Blend default, no sparse adj.": blend(None, sparse_on=False),
        "Blend cf 1.0 (sanity)": blend({"cf": 1.0}, sparse_on=False),
        "Blend cf .9 quality .1": blend({"cf": 0.9, "quality": 0.1}, sparse_on=False),
        "Blend cf .8 content .2": blend({"cf": 0.8, "content": 0.2}, sparse_on=False),
        "Blend default, z-score": blend(None, norm=zscore),
        "Blend default, z-score, no sparse adj.": blend(None, norm=zscore, sparse_on=False),
        "Blend default, top-200 percentile": blend(None, norm=top_n_percentile(200)),
        "Blend default, top-200 pct, no sparse adj.": blend(None, norm=top_n_percentile(200),
                                                             sparse_on=False),
        "UserKNN sum form": lambda u: top_k(knn_sum[knn_row[u]], ids, set(ranker.history(u)), k,
                                            tiebreak=pop),
    }
    rows = per_user_rows(ranker, holdout, systems)
    rng = np.random.default_rng(cfg.seed)
    ease = rows[rows.system == "EASE"].sort_values("user_id")
    sparse_users = set(ease.loc[ease.n_train < cfg.ranking.sparse_user_threshold, "user_id"])
    out = {"n_users": int(ease.user_id.nunique()), "n_sparse_users": len(sparse_users),
           "systems": {}}
    for name, g in rows.groupby("system", sort=False):
        g = g.sort_values("user_id")
        small = g[g.user_id.isin(sparse_users)]
        out["systems"][name] = {
            "ndcg": bootstrap_ci(g.ndcg, cfg, rng),
            "recall": bootstrap_ci(g.recall, cfg, rng),
            "ndcg_sparse_users": bootstrap_ci(small.ndcg, cfg, rng),
            "tail_recall": bootstrap_ci(g.tail_recall.dropna(), cfg, rng),
            "pop_ratio": float((g.rec_pop / g.hist_pop).mean()),
            "vs_ease_ndcg": paired_bootstrap(g.ndcg.to_numpy(), ease.ndcg.to_numpy(), cfg, rng),
        }

    # H3 evidence: raw EASE scores vs their percentiles at a few ranks, for three users.
    flat = {}
    for u in cfg.evaluation.qualitative_users:
        hist = ranker.history(u)
        scores = ranker.ease.scores(list(hist))
        unseen = ~np.isin(ids, list(hist))
        s = np.sort(scores[unseen])[::-1]
        pct = np.sort(PERCENTILE(scores[unseen]))[::-1]
        flat[str(u)] = {f"rank {r}": {"ease": round(float(s[r - 1]), 4),
                                      "percentile": round(float(pct[r - 1]), 4)}
                        for r in (1, 5, 10, 50, 200)}
    out["ease_top_flattening"] = flat

    path = new_results_dir(cfg, "blend_diagnosis")
    rows.drop(columns="recommended").to_csv(path / "per_user.csv", index=False)
    shutil.copy(__file__, path / "blend_diagnosis.py")
    lines = [f"# Blend diagnosis (val, K = {k}, {out['n_users']} users, "
             f"{out['n_sparse_users']} with < {cfg.ranking.sparse_user_threshold} train ratings)",
             "", "| System | NDCG@10 | vs EASE (paired) | NDCG@10 sparse users | Recall@10 | "
             "Tail recall | Pop. ratio |", "|---|---|---|---|---|---|---|"]
    for name, s in out["systems"].items():
        lines.append(f"| {name} | {fmt_ci(s['ndcg'])} | {fmt_ci(s['vs_ease_ndcg'])} | "
                     f"{fmt_ci(s['ndcg_sparse_users'])} | {fmt_ci(s['recall'])} | "
                     f"{fmt_ci(s['tail_recall'])} | {s['pop_ratio']:.2f} |")
    lines += ["", "EASE raw score vs percentile among unseen movies (H3):", ""]
    for u, ranks in flat.items():
        lines.append(f"- user {u}: " + "; ".join(
            f"{r}: {v['ease']} -> {v['percentile']}" for r, v in ranks.items()))
    save_run(path, cfg, out, "\n".join(lines))
    print("\n".join(lines))
    print(f"\nwritten to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
