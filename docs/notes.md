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

### Step 1 checks on the real data

- `validate` reproduces every §4.1 fact (0 issues in all six checks; 20 labels, 18 content genres;
  1,884 movies = 36.7% under 3 ratings; 120 tie-boundary users; 45 taggers, user 474 = 43.3%).
  It also finds exactly one zero-variance user (53).
- Plot embeddings (`bge-small-en-v1.5`): 16,204 chunks for 5,135 movies, built once in about 1.5
  minutes after the model download, cached in `cache/`. The author considered switching to OpenAI
  embeddings while the download was slow and decided to keep the local model (D4 unchanged).
- **Title resolution deviates from §4.3 (proposal to update the design).** WRatio misfires on this
  catalog: "The Matrix" scored 85.5 against every title containing "the" (partial token-set match
  on the article), and "Matrix" resolved as `found` to "M (1931)" (score 90: a one-letter title
  inside the query). Implemented instead: exact match on any form = 100; otherwise
  `max(ratio, 0.9 * token_set_ratio)` on article-free forms, where the subset credit applies only
  to forms at least as long as the query ("shawshank" still finds The Shawshank Redemption, but
  "Empire" no longer matches "star wars empire strikes back"). Apostrophes are deleted
  ("ocean's" -> "oceans"). Checked on ~35 real queries; known misses: "Ocean's 11" (digits vs
  words) is not found, "inceptoin" is ambiguous with Inception on top.
- `why-not --user 15 --movie "Heat" --exclude-genres Animation` -> RANKED_BELOW at rank 13; the
  largest gap to the rank-5 movie is `content`.
- `eval offline --split test` without `--final` is refused; `test_runs.log` does not exist.

### First offline val run, defaults, not tuned (`eval/results/2026-09-26_offline_val`)

- EASE NDCG@10 0.102 [0.088, 0.118] beats MostPopular 0.064 (paired +0.038 [0.024, 0.054]), as
  expected. λ = 500 is best on the grid (100: 0.092, 300: 0.098, 1000: 0.101).
- **Blend (personal mode as deployed) is worse than EASE alone**: 0.050, paired −0.052
  [−0.069, −0.036], and below MostPopular. This is the pre-registered D3 trigger. The cf-weight
  sweep rises monotonically to 0.082 at cf 0.9 / content 0, still below EASE, so the loss is not
  only the content weight. Hypothesis (code R): percentile normalization flattens EASE's large
  score gaps at the top (the best ~50 EASE movies all get cf ≈ 0.99), so small quality and content
  differences reorder the head. The sparse-user adjustment also moves cf weight away for about a
  third of the users. Step 2: compare other normalizations (rank within the top N, z-score) or
  EASE order with content only for sparse users or ties.
- **UserKNN as a recommender is near zero** (NDCG 0.004): the normalized mean-deviation formula
  rewards movies rated by just two neighbours (popularity ratio 0.33, 7% sparse movies). The usual
  top-N form is the unnormalized sum of `s * centred rating`. Proposed for Step 2; it does not
  affect `peer_opinion`, which only uses the neighbours.
- ContentProfile: lowest accuracy (0.006) but the only non-zero tail recall besides UserKNN
  (0.011) and the lowest popularity ratio (0.17). Tail recall is 0 for MostPopular, TopBayesian,
  EASE and Blend.

### Search, ungraded (`eval/results/2026-09-26_search`)

- The quality percentile dominates: the plain variants return mostly well-rated classics, and
  "time travel that changes the past" returns Once Upon a Time in America and Memento. Setting
  `min_ratings = 0` barely changes the lists (share under 5 ratings is 0 either way) because the
  quality percentile already pushes sparse movies down. 84 (query, movie) pairs await grading in
  `eval/search_judgments.csv` (Step 2).
- Harness bug found and fixed: P@5 showed 0.00 instead of NaN for ungraded variants (regression
  test added). The buggy first search run had nothing graded; it was deleted and re-run, and the
  re-run is identical apart from that field (all ranking is deterministic). Deviation from
  "never overwrite" recorded here.

### Failures found (root-cause codes, §8.3)

1. **G, not caught by the verifier.** Query "Why do you think I would like the first one?" (user 15,
   `traces/20260926-233833-e4b156.jsonl`, turn 1). The answer wrote "**Alien (1979)** (Alien)" and
   "(Prometheus)": the LLM repeats single-word titles after placeholders, which V1 does not check
   (two-word minimum). Fix: V1 also flags a placeholder followed by its own title; prompt v2 rule.
2. **G, caught.** Same session, turns 0 and 2: the first `final_answer` typed "saving private ryan"
   and "pulp fiction" outside placeholders; V1 rejected them and the retry passed. Verifier first
   pass 1 of 3 in this session. Fix: stronger prompt wording plus an example answer (Step 2).
3. **R.** Blend below EASE (see above).
4. **G, caught (systematic).** `eval/results/2026-09-26_agent`: all 45 verifier violations in the
   suite are V1 (typed titles), e.g. "fight club", "reservoir dogs" in `dark_thriller_u1`, and
   "psycho ii", "american psycho" in `ambiguous_psycho_u15`. V2 and V3 never fired. Verifier first
   pass 0.52; one fallback (`no_animation_persists_u15`, turn 1, two typed "toy story" attempts).
   Fix: prompt v2 with an explicit wrong/right example; re-run and compare the first-pass rate.
5. **C (state).** Every "tired of animated movies" turn passes `exclude_genres=["Animation"]` to
   `recommend` (constraint satisfaction 1.0, including all three turns of the persistence
   scenario), but the LLM never sets `add_exclude_genres`, so `state.exclude_genres` stays empty
   (state persistence 0.0). The constraint survives only because the dialogue history repeats it,
   which breaks after `history_turns` turns. Fix options for Step 2: prompt v2, or let the
   orchestrator persist genres excluded in `recommend` unless the answer removes them.
6. **R / D (expected, §9.6).** "I liked Toy Story but I'm tired of animated movies" (user 15, seed
   mode) returns Snatch, Willy Wonka & the Chocolate Factory, E.T., Dr. Horrible's Sing-Along Blog
   and Big: removing Animation leaves the family films that share Toy Story's plot space.
7. **G (cosmetic).** The LLM appends years after placeholders ("**Psycho (1960)** (1960)") and
   titles in parentheses (failure 1); the renderer already adds the year.
8. **Unknown user** (`unknown_user`): the answer says the user "has no ratings yet" and asks for
   preferences instead of saying the ID is unknown and asking again (§7.5). `chat` itself asks for
   a valid ID before starting, so this only affects the agent-level scenario.

### Honesty tests (`eval/results/2026-09-26_honesty`)

- **Perturbation: the stance follows the data in 3 of 3 pairs.** E.g. user 1 and The Empire Strikes
  Back: original "rated very highly, 4.59, +1.11 above their averages"; perturbed "quite low, 2.08,
  only 27.9% liked it". The answers state the flipped numbers even for famous films the LLM surely
  "knows". Verifier first pass 1.0 on the original and 0.0 on the perturbed runs (typed titles).
  Caveats for Step 2: the pair picker (movie most rated by the neighbours) chose Star Wars films
  all three times, and the users had rated them 5.0 themselves; pick diverse, unseen movies. After
  the flip, refitting UserKNN changes the neighbourhood slightly (46 -> 43 raters).
- **Explanation fidelity is weak: 0.07 [0.00, 0.17]** of 30 top-1 recommendations drop at least 5
  places (or out of the top 10) when the top driver is removed; mean new rank 2.7. Control (remove
  a random history movie): 0.00. So the named driver does move the item more than a random movie,
  but "because you liked X" is not decisive: EASE sums over the whole history and the percentile
  blend keeps the item near the top. Report material for R3; Step 2 can also report the score drop,
  not only the rank drop.
- LLM attribution: 7 of 10 answers name the engine's top driver movie (match judged by hand later).

### Step 1 Definition of Done (§13.1), checked 2026-09-26

- Tests: 93 pass, including I1–I6 (`pytest -q`); `ruff check` and `ruff format --check` clean.
- `validate` reproduces the §4.1 facts with no differences.
- README sample queries: `chat --user 15` run live (3 turns, trace
  `traces/20260926-233833-e4b156.jsonl`); `eval agent` runs all 6 sample queries for users 1, 15 and
  30 through the same `Agent` class: correct tool chain in 18 of 18 scenarios, every answer verified
  (some after one retry), no fallback in the sample set.
- Every §12 command runs: `validate`, `chat`, `why-not`, `eval offline --split val` (test refused
  without `--final`, not run), `eval search`, `eval agent`, `eval honesty`, `report-tables`.
- Assumptions: listed above.
