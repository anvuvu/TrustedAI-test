# Lab notebook

Dated entries: decisions, assumptions, surprising results, failures. Feeds `REPORT.md`.

## 2026-09-26 — Step 1 (build)

### Design check before building

- Re-read `CLAUDE.md` and `docs/design.md` v2 against `Exam/README.md` and the data. No conflicts.
  Every number the brief states matches the data (5,135 movies, 74,064 ratings, 610 users, 51% of
  movies under 5 ratings, ~121 ratings per user, years 1903–2014, users 1/15/30 counts and means).
- The brief says "19 genres"; the data has 20 labels, including `IMAX` and `(no genres listed)`.
  §4.4 already handles this: 18 content genres are used for affinity and blind spots.

### Assumptions made while building (small ambiguities, simplest option per §2)

- **Zero-variance user.** User 53 rated all 18 movies 5.0, so every centred rating is 0. The content
  profile falls back to equal weights on liked movies (r ≥ 4.0). UserKNN gives them no neighbours
  (the correlation is undefined), so `peer_opinion` falls back to global stats with low confidence.
- **Seed movies are filtered out** of `recommend` results (filter `seed`, logged with the others).
  §5.3 does not list it, but recommending the movie the user just named is useless.
- **Sparse-user adjustment**: the removed cf weight is split equally between `content` and
  `quality`. In query and seed modes, where `content` has no base weight, it is added.
- **Percentile** is the mid-rank percentile in (0, 1): share of eligible movies with a lower
  value, counting ties as half. Movies without CF signal get cf = 0.5 and are excluded from the cf
  percentile computation of the others.
- **Session user enforced.** The agent overwrites `user_id` in every tool call with the session
  user and adds a warning to the tool result when the LLM passed another one.
- **`explain` drivers** are computed in personal mode, with the explained movie itself removed from
  the history, so that a movie the user already rated can also be explained.
- **Persistent constraints are not auto-merged** into `recommend` calls. The state summary tells the
  LLM the active excluded genres and V2 rejects answers that break them. Auto-merging would make
  "relax the constraint" impossible within the same turn, and it would hide LLM state errors (code C)
  that the scenarios should measure.
- **V1 title check** only looks for titles with at least two words after dropping a leading article,
  so prose such as "the others" or "the game" is not flagged. Single-word titles (Heat, Up) are not
  checked at all; placeholders are still required by the prompt.
- **V3 numbers**: integers in 1900–2030 are treated as years; a percentage matches a tool fraction
  (0.46 ↔ 46%) or percent value; numbers in tool arguments and the count of recommended movies are
  also allowed ("here are 5 picks").
- **Design inconsistency, resolved in the scenario file**: §9.4 lists `"Alien" ambiguous` as an edge
  case, but by the §4.3 rules "Alien" is an exact match (score 100) and resolves as `found`. The
  ambiguous-title scenario uses "Psycho" (1960 and the 1998 remake, both rated) instead; "Alien" vs
  "Aliens" stays a title-resolution unit test (I6).
- **Evaluation regimes**: `eval search` and `eval agent` use all ratings (search quality does not
  depend on the split; scenarios test the agent as deployed in `chat`). The fidelity test uses the
  train split. Only `eval offline` touches val/test.
- **Fidelity control**: besides removing the top driver, the fidelity test also removes a random
  other history movie, so the report can compare the drop with what removing any movie does.
- **Extra helper module** `evaluation/results.py` (results directories, bootstrap CIs) shared by the
  five evaluation scripts; not listed in §12 but not a new component.
- **`.gitignore`**: the Python template ignores `*.log`; `eval/results/test_runs.log` is re-included
  because it is a deliverable (§9.7).

### Dependencies (why each one)

- numpy, pandas, scipy: core computation (EASE inverse, sparse matrices, ranks).
- pydantic: tool results, state, `final_answer`, config.
- typer: the CLI. pyyaml: config, scenarios, queries.
- rapidfuzz: fuzzy title matching (§4.3, WRatio).
- sentence-transformers: the local `BAAI/bge-small-en-v1.5` embedding model (§5.1). It pulls in
  torch, which is the heaviest dependency; accepted because embeddings run once and are cached.
- openai: the LLM client (§7.1). python-dotenv: reads `OPENAI_API_KEY` from `.env`.
- matplotlib: the three report figures (§10).
- dev: pytest, ruff.
