"""Step 2: paired comparison of personal-mode cf weights on val (quality fixed at 0.1)."""
import json, shutil, sys
from pathlib import Path
import numpy as np
from movie_agent.config import load_config
from movie_agent.data import load_dataset, temporal_split
from movie_agent.evaluation.offline import fit_and_holdout, make_systems, per_user_rows
from movie_agent.evaluation.results import fmt_ci, paired_bootstrap
from movie_agent.ranking import build_ranker

cfg = load_config()
ds = load_dataset(cfg.paths.data_dir)
fit, holdout = fit_and_holdout(temporal_split(ds.ratings, cfg), "val")
ranker = build_ranker(cfg, ds, fit)
rows = {}
for cf in (0.7, 0.8, 0.9):
    w = {"cf": cf, "content": round(0.9 - cf, 2), "quality": 0.1}
    r = per_user_rows(ranker, holdout, {"Blend": make_systems(ranker, w)["Blend"]})
    rows[cf] = r.sort_values("user_id")
rng = np.random.default_rng(cfg.seed)
out, lines = {}, ["| Comparison | all users | users < 30 train ratings |", "|---|---|---|"]
for a, b in ((0.9, 0.7), (0.8, 0.7)):
    ra, rb = rows[a], rows[b]
    sp = ra.n_train < cfg.ranking.sparse_user_threshold
    d_all = paired_bootstrap(ra.ndcg.to_numpy(), rb.ndcg.to_numpy(), cfg, rng)
    d_sp = paired_bootstrap(ra.ndcg[sp].to_numpy(), rb.ndcg[sp].to_numpy(), cfg, rng)
    out[f"cf {a} - cf {b}"] = {"all": d_all, "sparse": d_sp}
    lines.append(f"| NDCG@10 cf {a} - cf {b} | {fmt_ci(d_all)} (sig. {d_all['significant']}) | "
                 f"{fmt_ci(d_sp)} (sig. {d_sp['significant']}) |")
dest = Path(sys.argv[1])
(dest / "cf_weight_paired.json").write_text(json.dumps(out, indent=2))
(dest / "cf_weight_paired.md").write_text("# Personal-mode cf weight, paired (val)\n\n" + "\n".join(lines) + "\n")
shutil.copy(__file__, dest / "cf_weight_paired.py")
print("\n".join(lines))
