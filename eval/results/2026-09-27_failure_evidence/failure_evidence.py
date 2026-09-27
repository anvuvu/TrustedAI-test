"""Step 3: engine-only evidence for the report's failure cases (no LLM), saved as a results run."""
import json, shutil
from movie_agent.config import load_config
from movie_agent.data import load_dataset
from movie_agent.diagnostics import why_not
from movie_agent.evaluation.results import new_results_dir, save_run
from movie_agent.ranking import RecommendRequest, build_ranker

cfg = load_config(); ds = load_dataset(cfg.paths.data_dir)
r = build_ranker(cfg, ds)
out, lines = {}, ["# Failure evidence (engine only, all ratings, frozen config)", ""]
lines += ["## Case 1: \"I liked Toy Story but I'm tired of animated movies\" (seed 1, exclude Animation)", ""]
for u in (1, 15):
    req = RecommendRequest(user_id=u, seed_movie_ids=[1], exclude_genres=["Animation"], k=5)
    res = r.recommend(req)
    out[f"toy_story_top5_user_{u}"] = [i.model_dump(include={"rank", "movie_id", "title", "genres", "contributions", "n_ratings", "mean_rating"}) for i in res.items]
    lines += [f"User {u}, weights {res.weights}:", ""]
    lines += [f"{i.rank}. {i.title} — {', '.join(i.genres)}; contributions {i.contributions}; {i.n_ratings} ratings, mean {i.mean_rating}" for i in res.items]
    lines.append("")
lines += ["`why-not` for user 15 (same request):", ""]
for title in ["The Princess Bride", "Big", "Home Alone", "Jumanji"]:
    w = why_not(r, RecommendRequest(user_id=15, seed_movie_ids=[1], exclude_genres=["Animation"], k=5), title)
    out[f"why_not_{title}"] = w.model_dump()
    lines += ["```", w.to_text(), "```", ""]
lines += ["## Case 2: \"I want a dark psychological thriller with a twist\" (user 15)", ""]
res = r.recommend(RecommendRequest(user_id=15, query="dark psychological thriller with a twist", k=5))
out["dark_thriller_top5_user_15"] = [i.model_dump(include={"rank", "movie_id", "title", "n_ratings", "confidence", "flags", "contributions", "plot_excerpt"}) for i in res.items]
for i in res.items:
    lines.append(f"{i.rank}. {i.title} — {i.n_ratings} ratings, confidence {i.confidence} {i.flags}; contributions {i.contributions}; matched passage: \"{(i.plot_excerpt or '')[:160]}…\"")
lines += ["", "## Case 3: \"because you rated\" includes low ratings (user 15, personal mode)", ""]
res = r.recommend(RecommendRequest(user_id=15, k=5))
for i in res.items:
    reasons = "; ".join(f"{b.title} (rated {b.user_rating}, EASE contribution {b.ease_contribution})" for b in i.because_you_rated)
    lines.append(f"{i.rank}. {i.title} — because you rated: {reasons}")
    out.setdefault("personal_top5_user_15", []).append({"title": i.title, "because_you_rated": [b.model_dump() for b in i.because_you_rated]})
path = new_results_dir(cfg, "failure_evidence")
save_run(path, cfg, out, "\n".join(lines))
shutil.copy(__file__, path / "failure_evidence.py")
print(path)
