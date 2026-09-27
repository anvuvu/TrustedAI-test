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
- **Title resolution deviated from the §4.3 draft; the author agreed and §4.3, §11 and decision D8 are
  updated.** WRatio misfires on this
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

## 2026-09-26 — Step 2 (evaluate on val)

### Ranking: why Blend lost to EASE (`eval/results/2026-09-26_blend_diagnosis`)

- Diagnosis on val (scripts saved in the results directory). Personal-mode NDCG@10:
  EASE 0.102; Blend as deployed 0.050; without the sparse-user shift 0.057; cf 1.0 alone 0.102
  (sanity: equals EASE); cf .9 + quality .1: 0.100 (n.s.); cf .8 + content .2: 0.061.
- Confirmed: percentiles flatten EASE's head (user 1: raw 0.52 at rank 1 -> 0.12 at rank 200;
  percentile 0.9999 -> 0.960), so the content feature reorders the best CF candidates. The
  sparse-user shift hurt sparse users (0.059 vs 0.076 without it), refuting the pre-registered
  expectation that content helps them.
- Normalizations without the shift: z-score 0.102, top-200 rank 0.099, min-max 0.098; query
  adherence@5 (top 5 within the 50 best plot matches, user 15, 10 judged queries): percentile 0.46,
  z-score 0.42 (EASE's heavy tail lets cf override the query), min-max 0.68, top-200 0.88.
- **Decision (author, 2026-09-26): top-200 rank scores, no sparse-user weight shift** (design §5.2,
  D3 revised). The `sparse_user` flag stays for confidence. `no_cf_signal` movies now get cf = 0.
- UserKNN as a recommender switched to the unnormalized sum (implementation choice left open by
  §5.1): 0.004 -> 0.081 in the diagnosis. `peer_opinion` is unaffected.
- Deviation: the diagnosis tried 11 variants on val; val is the tuning split, the test split is
  untouched. The chosen variant is not the val maximum (z-score) but the one that also behaves in
  query mode, so the val number is not cherry-picked upward.

### Offline val on the revised ranking (`eval/results/2026-09-26_offline_val_2`)

- Blend 0.099 [0.084, 0.114] vs EASE 0.102: paired −0.003 [−0.016, 0.009], no significant
  difference (was −0.052). UserKNN (sum form) 0.081, now above MostPopular 0.064. Tail recall is
  still 0 for every CF system; ContentProfile stays the only one with tail hits.
- **Chosen values (Step 2):** EASE λ = 500 (best on the grid; 1000 within 0.001). Personal weights
  stay cf 0.7 / content 0.2 / quality 0.1: the sweep peaks at cf 0.9 (0.103) but the paired
  differences to 0.7 are not significant (cf 0.9 − 0.7: +0.004 [−0.006, 0.012]; on users with
  < 30 train ratings −0.007 [−0.027, 0.013]), and 0.7 keeps the plot-similarity signal in personal
  explanations. Rule used: keep the default unless another value is significantly better.
  Evidence: `cf_weight_paired.md` in the same results directory.

### Search re-run on the revised ranking (`eval/results/2026-09-27_search`)

- The ungraded Step 1 sheet (0 of 84 graded) was reset so the author only grades the pools the
  current system shows: 79 pairs in `eval/search_judgments.csv`.
- Query mode now follows the query: 26% of the plain top 5 are movies with < 5 ratings (0%
  before), 42% without `min_ratings`.
- **New failure pattern (S, to be quantified by the grades):** title words leak into matching
  through the "Title. Genres." chunk prefix (§5.1): "Darkness Falls" and "Twisted" for "dark ...
  with a twist", "Lonely Are the Brave" and "In a Lonely Place" for "loneliness", "Road Trip" for
  "road trip". Possible fix: embed plot text without the title in the prefix, keep genres.

### Agent: prompt v2 (`prompts/system_v2.md`, now the default)

- v2 adds: an explicit wrong/right example for placeholders (no typed titles, nothing after a
  placeholder), `add_exclude_genres` for lasting genre constraints, `USER_NOT_FOUND` handling, a
  reread-before-final_answer step. A new automatic scenario check `no_title_echo` measures
  failure 1 (placeholder followed by its own title or year).
- Same ranking, same scenarios, v1 (`2026-09-27_agent`) vs v2 (`2026-09-27_agent_2`): verifier
  first pass 0.48 -> 0.79, fallback 0.10 -> 0.00, state persistence 0.00 -> 0.67, no title echo
  0.86 -> 0.97, scenario success 0.50 -> 0.67, tokens per turn 9,462 -> 6,518.
- **Run-to-run variance (important for the report).** A second v2 run (`2026-09-27_agent_3`, only
  the V3 fix changed, which does not affect these turns) gave state persistence 0.17 (1 of 6) and
  first pass 0.86. gpt-4.1-mini is not deterministic at temperature 0, and with 6 state turns one
  run cannot tell 0.17 from 0.67. Report both runs; do not claim the prompt fixed state
  persistence. A deterministic fix (the orchestrator persists genres excluded in `recommend`
  unless the answer removes them) is proposed below.
- Remaining v2 failures are all V1 typed titles, recovered on retry except one fallback
  (`why_that_u30` turn 1 typed "star wars episode v the empire strikes back" and "batman begins"
  twice).

### Failures found in Step 2 (continuing the numbering)

9. **Verifier false positive, V3 (G in the verifier).** Perturbation test, user 30 / Forrest Gump
   perturbed (`traces/eval-2026-09-27_honesty-pert-30-perturbed.jsonl`): the tool said
   `similar_users_mean_vs_own_average = -2.3`, the answer said "2.3 below their own average rating",
   and V3 rejected it twice (signed comparison), so the user got the unhelpful template fallback.
   "2.01 below" in the T2 answer had passed only by coincidence (2.0 is a neighbour's rating).
   Fix: V3 reads a minus sign or a following "below / lower / less / under" as negative; verifier
   cases added first (a correct "2.3 below" passes, "0.62 below" against +0.62 and "2.3 above"
   against −2.3 fail). Re-run: that answer passes on the first try. Design §7.4 V3 row clarified.
10. **Fallback for non-recommend turns is uninformative (design limitation).** When a peer or explain
    answer fails twice, the template says only "I could not produce an answer that passes my
    grounding checks". Proposed: a template per tool (e.g. peer_opinion: "N similar users rated it,
    mean X, Y above/below their averages").
11. **S / R (seed mode).** Toy Story minus Animation for user 1 (v2 run): Gremlins, Babe, Snatch,
    The Santa Clause, Santa Claus: The Movie. Seed plot similarity keeps family and Christmas
    films after the Animation filter; confirms the §9.6 candidate.

### Honesty tests, final Step 2 run (`eval/results/2026-09-27_honesty_2`)

- Pair picker now chooses unseen, distinct movies: Terminator 2 (user 1), Jurassic Park (user 15),
  Forrest Gump (user 30). The stance follows the flipped data in all 3 pairs (e.g. Forrest Gump
  4.18, +0.52 above averages, 74.4% liked -> 1.32, 2.3 below, none liked). Stance and extra-facts
  labels still need the author's hand grading in `perturbation_sheet.csv`.
- Explanation fidelity with top-N rank scores: 0.27 [0.10, 0.43] of top-1 recommendations drop
  >= 5 places when the top driver is removed (was 0.07 with percentiles); mean score drop 0.091
  [0.043, 0.151] vs 0.007 for a random history movie. All 30 top drivers are cf. The named driver
  is real (13x the control's score effect) but usually not decisive on its own.
- LLM attribution: 9 of 10 answers name the engine's top driver movie (10 of 10 in the previous
  run); match to be judged by the author in `attribution_sheet.csv`.
- Reproducibility note: `2026-09-27_agent_2`, `_agent_3`, `_honesty_2`, `_search` and the second
  offline run record a `-dirty` commit (`c315916-dirty`) because they ran on uncommitted working-
  tree changes (prompt v2, the V3 sign fix, the pair picker); those changes are in the commit that
  follows c315916 ("Step 2: prompt v2, sign-aware V3, ...").

### Step 2 status (2026-09-27)

- Done: offline ranking and tuned values (λ 500, personal cf .7 / content .2 / quality .1, top-200
  rank scores); agent suite run, fixed (prompt v2) and re-run twice; honesty tests run; 11
  failures logged with root-cause codes; decision log D1, D2, D5, D6, D7 accepted, D3 and D8
  revised, D4 pending the search grades.
- Waiting for the author (hand grading, by design): 79 pairs in `eval/search_judgments.csv`;
  `rubric_sheet.csv` in `eval/results/2026-09-27_agent_3`; `perturbation_sheet.csv` and
  `attribution_sheet.csv` in `eval/results/2026-09-27_honesty_2`.
- Open proposals: (a) orchestrator persists genres excluded in `recommend` (state failures are
  unreliable to fix by prompt: 4/6 vs 1/6 in identical runs); (b) per-tool fallback templates;
  (c) embed plots without the title in the chunk prefix (title-word leakage in search), to decide
  after grading.

### Grading by an LLM grader (protocol deviation, 2026-09-27)

- The author asked Claude to do the hand grading. Design §9.3/§9.4 pre-registered author grades,
  so this is a deviation, recorded in design §9.3, §9.4 and §15 and to be stated in the report.
- Process, to limit builder bias: two fresh Claude subagents that did not build the system, one
  for search (79 shuffled pairs, variant hidden, judged only from the dataset's title, year,
  genres and full plot, not from memory of the films) and one for the rubric (29 turns, graded
  against the full tool outputs from the traces) plus the perturbation and attribution sheets.
  Every grade has a written rationale; search grades below 2 carry a failure type. Grading
  packets and raw grader outputs are saved under `eval/grading/`.
- Recommended before Step 3: the author regrades a random subset (e.g. 20 search pairs and 6
  rubric turns) so the report can quote agreement with the LLM grader.

### Graded results (LLM grader, see the deviation above)

- **Search** (`eval/results/2026-09-27_search_2`, 10 queries, 79 graded pairs): P@5 plain 0.84
  [0.72, 0.94], without `min_ratings` 0.88 [0.78, 0.96], personalized for user 15 0.74
  [0.58, 0.88]; mean grade 1.32 / 1.38 / 1.14. The CIs overlap: no variant is significantly better.
  Failure types of the 47 grades below 2: partial_element 25, genre_only 8, other 7, title_word 4,
  wrong_tone 3. Concrete plot queries do best (war romance 1.57, heist 1.50); space survival (0.70:
  space operas with battle damage instead of an accident) and the mood query "bleak loneliness"
  (0.75) do worst. Personalization lowers relevance a little (n.s.): cf pulls in the user's
  favourites that fit the query less.
- **Open question answered:** query-mode `min_ratings` stays 3. Dropping it is not significantly
  better (0.88 vs 0.84) and raises the share of results with < 5 ratings from 26% to 42%.
- **D4 accepted:** the search failures are mostly about what plots contain (events, not tone;
  partial elements) and about bad plot data, not the embedding model; title-word leakage explains
  only 4 of 47. Proposal (c), dropping the title from the chunk prefix, is not worth a re-embed.
- **Rubric** (`eval/results/2026-09-27_agent_3`, 29 turns): grounded 1.45, relevant 1.86, specific
  1.66, honest 1.45; 10 turns have a 0 (3 grounded only, 5 honest only, 2 both). Rationales in
  `eval/grading/rubric_grades_with_rationale.csv`.
- **Perturbation (graded):** stance follows the data 6 of 6; 0 answers add facts beyond the tools.
- **Attribution (graded):** the stated reason matches the engine's top driver: yes 5, partly 4, no 1
  (the "no" is a fallback answer that gives no reason). The "partly" answers lead with the peer
  average and mention the driver movie second.

### Failures found by the grading (continuing the numbering)

12. **D (data): about 6% of plots belong to another film.** Seeded audit of 100 plots (the 50 most
    rated + 50 random; `eval/grading/plot_audit.csv`): 6 mismatches, 95% Wilson CI [2.8%, 12.5%],
    a lower bound. Seven (1995) carries The Land Before Time III, Independence Day carries Day Watch,
    Twelve Monkeys carries Mighty Aphrodite, Men in Black carries Against Her Will: An Incident in
    Baltimore, Wild Reeds carries La Cité de la peur, Evil Dead II carries Red's Dream; the search
    grading found Psycho (1960) too. The names quoted by the auditor were checked in the plot text.
    Consequence: the system is **grounded but wrong** for these movies (`find_movie` excerpts,
    `explain` plot passages and content similarity all describe another film). `Exam/` is
    read-only, so this is a reported limitation; a mitigation would flag plots whose vectors are
    far from those of the movie's CF neighbours. This is the one place where outside knowledge was
    used, and only to audit the data.
13. **Confidence gap (design §6.1).** Item confidence is low only for `no_cf_signal` or
    `sparse_user`, so a query-mode pick with 4 ratings, mean 2.12 and nothing but the query signal
    (Darkness Falls) is labelled `high`, and the answer presents it without a hedge. Most rubric
    "honest = 0" scores trace to this rule, not to the LLM hiding a flag. Fix: item confidence also
    low when `n_ratings < movie_low_below`.
14. **C (state), confirmed in the trace.** `no_animation_persists_u15` turns 2 and 3 called
    `recommend` with `exclude_genres=[]`; turn 2's result contained Toy Story 3 (Animation) and the
    LLM happened not to pick it. Constraint satisfaction 1.0 is luck, not enforcement. Fix: the
    orchestrator persists excluded genres (proposal a).
15. **G / R: "because you rated X" is read as "liked".** EASE is fitted on binary interactions, so a
    movie the user rated 1.0 or 2.0 can be the top driver, and answers call it a movie they liked.
    Fix options: only list history movies rated at or above the user's mean as reasons, or fit EASE
    on liked-only interactions (a val ablation).
16. **G: outside knowledge in adjectives** ("a classic thriller with a strong plot", "classic
    madcap"). V1–V3 cannot catch it (no number, no title); only the rubric measures it.

### Fixes after grading (author chose a and b; commit 03ffabb)

- **D9, state in code:** the orchestrator adds genres excluded in successful `recommend` calls to
  `state.exclude_genres` (removal in the answer wins). Tests reproduce failure 14 first.
- **D10, confidence counts ratings:** items with fewer than `movie_low_below` (5) ratings get the
  flag `few_ratings` and confidence `low`; the `recommend` confidence reason lists the counts.
  Tests reproduce failure 13 first.
- Not done (author's choice): filtering `because_you_rated` to liked movies (failure 15) and
  per-tool fallback templates (failure 10). Both stay as report items ("with more time").
- **Two identical re-runs** (`2026-09-27_agent_4`, `_agent_5`, clean commit 03ffabb): state
  persistence 1.00 and 1.00 (was 0.67 and 0.17), fallback 0.00 and 0.00, verifier first pass
  0.79 and 0.76, scenario success 0.79 and 0.75 (agent_4, agent_5). In the persistence scenario the state summary now
  shows Animation from turn 2 and the LLM passes it to `recommend` itself, so V2 never had to
  step in. All remaining violations are V1 typed titles (12 and 17 per run), recovered on retry.
  6 recommended items per run carry `few_ratings`.
- **Rubric regraded on `2026-09-27_agent_4`** (fresh grader, identical instructions): grounded
  1.45 (=), relevant 1.97 (1.86 before), specific 1.72 (1.66), honest 1.90 (1.45). The grader
  reports that `few_ratings` is now nearly always disclosed, which is what D10 targeted. Caveat:
  a different run and a different grader instance, so the comparison is indicative only.
- Grounded stays at 1.45; of its six 0s, three are failure 15 ("liked" for movies rated 1.0–2.5,
  e.g. Django Unchained rated 1.0) and three are outside knowledge in adjectives or premises
  (failure 16: "a classic thriller", "each film has a twist", Superbad's "before college"). New
  pattern: CF scores paraphrased as peer opinion ("loved by similar users") without a peer tool
  call (failure 17, G).

## 2026-09-27 — Step 3 (analyze and write)

- Frozen at commit de4c522, tagged `final-eval`. `eval offline --split test --final` ran once
  (`eval/results/2026-09-27_offline_test`, logged in `eval/results/test_runs.log`): EASE and Blend
  NDCG@10 0.113, UserKNN 0.107, MostPopular 0.084, TopBayesian 0.065, ContentProfile 0.009;
  EASE − MostPopular +0.029 [0.016, 0.041]; Blend − EASE 0.000 [−0.008, 0.009].
- Curated `chat` sessions for users 1, 15 and 30 with the six sample queries
  (`transcripts/chat_user_*.md`, traces in `traces/examples/`). New failures seen only in these
  long sessions: the previous query carried into the Toy Story request (user 30, turn 5, code C/U);
  Toy Story never resolved, so no seed (user 15, turn 5, code U); an invented placeholder
  `[[m:1107]]` (Loser) blocked by V1 (user 30, turn 1, code G, caught). Not fixed: code frozen.
- Engine-only evidence for the report's failure cases: `eval/results/2026-09-27_failure_evidence`
  (Toy Story seed top 5 and `why-not` for The Princess Bride and others; the dark-thriller top 5
  with the wrong Psycho plot; `because_you_rated` with ratings 1.0 and 2.5).
- `report-tables` now also refreshes the tables in `REPORT.md` between `<!-- table:NAME -->`
  markers, so the report's tables are generated, never typed. Changing the reporting code after
  the test run does not touch any metric.
- Fresh-clone check (2026-09-27, clone of 779ab91): `pip install -e ".[dev]"`, 106 tests pass,
  `validate` reproduces §4.1, embeddings rebuilt from scratch (why-not in 1 min 22 s),
  `eval offline --split val` gives NDCG identical to `2026-09-26_offline_val_2` for every system,
  and `report-tables` reproduces the tables in REPORT.md with no diff. Not checked in the clone:
  the LLM commands (no `.env` there); they were run in the main checkout.
