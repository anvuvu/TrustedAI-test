# Design: Conversational Movie Discovery Agent (lean v2)

**Status:** v2, replaces the v1 draft. Living document: update it in the same change as the code it describes.
**Brief:** `Exam/README.md`. **Report template:** `Exam/REPORT_TEMPLATE.md`.

**Guiding idea.** The brief weights the report equally with the code and says a mediocre system with excellent analysis beats a good system with a shallow report. So this design spends its complexity budget on **evaluation and analysis**, not on components. The system is small, correct and fully traceable. The depth goes into measuring where it works, where it fails, and why.

## Contents

1. Purpose and scope
2. Principles
3. Architecture
4. Data
5. Ranking
6. Tools
7. Agent
8. Traces and diagnostics
9. Evaluation
10. Report plan
11. Configuration
12. Repository layout and commands
13. Build plan and Definitions of Done
14. Decision log
15. Limitations and open questions

---

## 1. Purpose and scope

### 1.1 Goal

An assistant that helps a known user (by `userId`) discover movies by investigating the dataset on their behalf. It decides what to look up, combines rating patterns, plots and genres, and explains its reasoning with evidence from the data, never from the LLM's own movie knowledge.

### 1.2 Requirement mapping

| Brief requirement | Where it is satisfied |
|---|---|
| R1. Personalize from the user's rating history | User profile (§6.2), EASE + content profile (§5) |
| R2. Multi-step questions | Agent loop chaining tools (§7.1), e.g. `find_movie` → `peer_opinion` |
| R3. Explain with historical data, not LLM knowledge | Tool outputs carry the facts; movie placeholders and verifier (§7.3, §7.4); perturbation test (§9.5) |
| R4. Evaluate with evidence, including failures | §9, feeding the report plan in §10 |

| Sample query | Expected tool chain |
|---|---|
| "What should I watch tonight?" | `recommend(user)` (optionally `get_user_profile` first) |
| "I want a dark psychological thriller with a twist" | `recommend(user, query=…)` |
| "What do people with similar taste to mine think about Pulp Fiction?" | `find_movie` → `peer_opinion` |
| "Why do you think I'd like that?" | state `focus_movie_id` → `explain` |
| "I liked Toy Story but I'm tired of animated movies — what else?" | `find_movie` → `recommend(seed_movie_ids=[…], exclude_genres=["Animation"])` |
| "What's my blind spot? What genres am I missing?" | `get_user_profile` → `recommend(include_genres=[g])` for a blind-spot genre |

### 1.3 Deliberate scope cuts

Each cut is also report material: it is an alternative that was considered and rejected, and several are natural "with more time" items for the Reflection section.

| Cut from v1 | Why | What replaces it |
|---|---|---|
| ItemKNN, BM25, HyDE query rewriting, negative profiles, MMR, learning-to-rank | Each adds tuning and failure surface; the dataset is small and the brief does not reward state-of-the-art | EASE + UserKNN + one embedding model, one weighted blend |
| Candidate generation with top-N pools | Scoring all ~5k movies per request is instant, so there is no recall stage to debug | Score the whole catalog |
| 9 tools | Fewer, broader tools mean fewer tool-choice errors and simpler scenarios | 5 tools (§6) |
| Evidence IDs `[E#]` on every claim; 8 verifier rules | High implementation cost for a take-home | Movie placeholders plus a 3-rule verifier (§7.4) |
| Trace CLI with replay, diff, export | Infrastructure, not insight | JSONL traces plus one `why-not` diagnostic (§8) |
| Tag-based weak labels for search | The data makes them unreliable (§4.1) | A small author-judged query set (§9.3) |
| 47 scenarios, 3 perturbation datasets, agent-vs-engine study, Gradio UI | Days of work | ~24 scenarios, 2 cheap honesty tests, CLI only |

---

## 2. Principles

1. **Deterministic core; the LLM orchestrates and narrates.** Python computes every number, ranking and list. The LLM picks tools and phrases the results. When something goes wrong, we can tell whether the engine or the LLM caused it.
2. **Grounded by construction.** The LLM refers to movies only through `[[m:<movieId>]]` placeholders, and the verifier checks movies, constraints and numbers against tool outputs.
3. **Traceable.** Every turn is logged with its tool calls and outputs. Every recommended movie carries its score contributions. `why-not` explains any movie that was not recommended.
4. **No evaluation leakage.** Evaluation fits on train only, tunes on val, and uses test exactly once at the end (§13.3).
5. **Always against baselines, with uncertainty.** Every result is compared with non-personalized baselines and reported with bootstrap confidence intervals.
6. **Small and readable.** Every module should be explainable in the interview in two minutes.

---

## 3. Architecture

```
User ──► Agent loop (OpenAI function calling, ConversationState)
            │ tool calls                         ▲ verifier → renderer
            ▼                                    │
         5 tools: get_user_profile · find_movie · recommend · peer_opinion · explain
            ▼
         Ranking: filters → features (cf, content, quality) → weighted blend → contributions
            ▼
         Engines: EASE · UserKNN · plot embeddings (chunked, cached)
            ▼
         Data: validation · catalog + title resolution · stats · splits

         Cross-cutting: JSONL trace per turn · why-not diagnostic · evaluation scripts
```

Everything except the embeddings is fitted in memory at startup in a few seconds. Plot embeddings do not depend on ratings, so they are computed once and cached in `cache/`.

---

## 4. Data

### 4.1 Location and facts

The dataset is at `Exam/data/ml-latest-small-filtered/` and is read-only. The facts below come from the author's profiling of the five CSV files. `movie-agent validate` recomputes all of them into `eval/results/data_report.json`, and the report quotes the script's output.

| Fact | Value | Consequence |
|---|---|---|
| Size | 5,135 movies, 74,064 ratings, 610 users, 2,440 tags | Small enough to score the whole catalog per request |
| `title` column | Contains no year; year is a separate column | Normalization does not strip years |
| Alternate titles in parentheses | e.g. "Postman, The (Postino, Il)", "Seven (a.k.a. Se7en)", "Alien³ (a.k.a. Alien 3)" | Parenthetical parts become aliases (§4.3) |
| Genre labels | 20, including `IMAX` (84 movies, a format) and `(no genres listed)` (3 movies) | Both excluded from affinity and blind spots (§4.4) |
| Sparse movies | 1,884 movies (37%) have fewer than 3 ratings | CF barely sees a third of the catalog; `min_ratings` is a real trade-off (§15) |
| Users | All 610 have at least 10 ratings | Every user is eligible for evaluation |
| Timestamp ties | For 120 of 610 users the test boundary falls inside a block of identical timestamps | Order inside those blocks is arbitrary; reported as a limitation |
| Taggers | Only 45 users tag; user 474 wrote 1,056 of 2,440 tags (43%) | Tags mostly reflect one person's vocabulary; not used as evaluation labels |
| Most common tag | "in netflix queue" (71 movies), a list label with no content meaning | Tag stoplist for display (§11) |
| Validation checks | No ratings outside the catalog, no duplicates, no plots under 100 characters, no missing years | Checks stay in the code; the report states they found 0 issues |

### 4.2 Validation

`data.validate()` checks: ratings referencing unknown movies, duplicate `(userId, movieId)` pairs, rating values outside {0.5, …, 5.0}, empty or very short plots, missing years, tags referencing unknown movies. It also records the distribution facts of §4.1 (ratings per movie and user, genre label counts, tagger concentration, tie blocks at the split boundary).

### 4.3 Titles and resolution

**Normalization** (`catalog.py`), applied to the main title and to every alias:

1. Unicode NFKD, strip accents, lowercase. NFKD also maps "³" to "3".
2. Split off each parenthesized part as an alias, dropping a leading "a.k.a.": "Seven (a.k.a. Se7en)" → main "Seven", alias "Se7en".
3. Move a trailing article to the front, for the main title and for aliases: "Postman, The" → "the postman"; "Postino, Il" → "il postino". Articles: The, A, An, L', Le, La, Les, Il, El, Der, Die, Das.
4. Replace "&" with "and", delete apostrophes ("Ocean's" → "oceans"), replace other punctuation with spaces, collapse whitespace.
5. Also index each form without its leading article.

**Resolution** (`find_movie`):

1. If the user gives a year, restrict to that year ±1. A trailing number in the text ("Heat 1995") is read as a year only if that gives a `found` match; otherwise the text is resolved as typed, so "Death Race 2000" still works.
2. Exact match on any normalized form scores 100.
3. Otherwise compare the query without its leading article with the article-free forms, using rapidfuzz:
   - `ratio` for every form (catches typos: "pulp fictoin");
   - for forms at least as long as the query, also `0.9 × token_set_ratio` (catches partial titles: "shawshank" → The Shawshank Redemption). The weight is config `resolve.subset_weight`.

   A movie's score is the best over its forms; keep the top 5.
4. `found` if the top score is ≥ 90 and at least 5 ahead of the second; `ambiguous` if ≥ 75 with a smaller gap, or several exact matches (remakes, disambiguated by year); otherwise `not_found`.

Why not rapidfuzz `WRatio` (the v2 draft): on this catalog it scores "The Matrix" 85.5 against every title containing "the" (a partial token match on the article), and it resolves "Matrix" as `found` to "M (1931)" because a one-letter title matches inside the query. Dropping articles and giving subset credit only to forms at least as long as the query removes both failures: a short title ("M", "Empire") can no longer match inside a longer query. Known misses, kept as report material: "Ocean's 11" (digits vs words) is `not_found`, and "inceptoin" is `ambiguous` with Inception on top.

Unit tests cover at least: "Se7en", "Il Postino", "Alien 3", "Alien" vs "Aliens", a remake pair, and "The Matrix" (absent from this dataset).

### 4.4 Genres

Genres are pipe-separated. For affinity and blind spots, `IMAX` and `(no genres listed)` are excluded (config `genre_exclude`); they are still shown in movie info. The report therefore works with 18 content genres.

### 4.5 Statistics and "liked"

- User: number of ratings, mean μ_u, standard deviation.
- Movie: number of ratings n_i, mean, Bayesian average `(C·m + Σr) / (C + n_i)` with m the global mean and C = 10.
- Mean-centered rating `r̃ = r − μ_u`.
- Genre affinity for user u and genre g: `Σ r̃ over u's movies in g / (count + α)`, α = 3, so rarely rated genres shrink toward 0. Genre share: fraction of u's ratings in g, compared with the global fraction.
- `liked`: r ≥ 4.0 (primary evaluation relevance). Secondary, reported alongside: r̃ ≥ 0.5, because lenient users such as user 30 (mean 4.61) rate almost everything ≥ 4.

### 4.6 Splits

1. For each user, sort ratings by `(timestamp, movieId)`.
2. **Test:** the last 20% (at least 2). **Val:** the last 10% of the remainder (at least 1). **Train:** the rest.
3. Val is used only to choose EASE λ and the personal-mode CF weight. Final numbers: fit on train + val, evaluate on test once.
4. The report states the 120/610 tie-block count and what it means: for those users the train/test order inside the block is arbitrary.

The demo (`chat`) fits on all ratings; evaluation fits on train (or train + val for the final run). The same fitting code is used for both.

---

## 5. Ranking

### 5.1 Engines

**EASE** (main recommender). Binary interaction matrix X (1 if rated). `P = (XᵀX + λI)⁻¹`, `B_ij = −P_ij / P_jj`, `B_jj = 0`, scores `x_u · B`. λ chosen on val from {100, 300, 500, 1000}. The contribution of history movie j to candidate i is `x_uj · B_ji`, which gives "because you rated X". Movies with no train ratings get no CF signal.

**UserKNN** (for "people like you"). Pearson-style correlation on mean-centered ratings over co-rated movies, requiring at least 5 in common, with significance weighting `s · min(n_common, 50) / 50`. Top 50 neighbours with positive similarity. It powers `peer_opinion` and is also evaluated as a recommender for comparison.

**Plot embeddings.** Plots are split into ~300-token chunks with 50-token overlap, each prefixed with "Title. Genres.". Model: `BAAI/bge-small-en-v1.5` (local, sentence-transformers), cached in `cache/`. Query–movie similarity is the maximum over chunks, and the best chunk becomes the evidence excerpt. A movie vector is the normalized mean of its chunks. The user content profile is the average of liked movie vectors weighted by positive r̃.

### 5.2 Modes and scoring

Every unseen movie that passes the filters is scored; there is no candidate stage.

| Feature | Meaning |
|---|---|
| `cf` | EASE score from the user's history (plus seeds in seed mode). Movies with no train ratings are never in the cf top N, so their cf score is 0; they carry the flag `no_cf_signal` |
| `content` | Cosine to the user content profile |
| `query` | Max-chunk similarity to the query (query mode) |
| `seed` | Max cosine to the seed movies (seed mode) |
| `quality` | Bayesian average |

Each feature is converted to a **top-N rank score** among the eligible movies: 1 for the best movie on that feature, falling linearly to 1/N at rank N, and 0 below (N = 200, config `ranking.top_n`; ties by movieId). The score is `Σ w_f · f / Σ w_f`, and each feature's contribution is `w_f · f / Σ w_f`, so contributions sum exactly to the score and stay in [0, 1].

| Mode | Triggered by | Weights (config) |
|---|---|---|
| personal | no query, no seeds | cf 0.7, content 0.2, quality 0.1 |
| query | a query | query 0.6, cf 0.2, quality 0.2; default `min_ratings = 3` |
| seed | seed movies | seed 0.5, cf 0.3, quality 0.2 |

Query plus seeds uses the query weights with `seed` added at 0.3 (renormalized). The personal-mode cf/content split is tuned on val; the other weights are hand-set and justified in §14. Users with fewer than 30 ratings are flagged `sparse_user` (low confidence, §6.1); their weights are not changed.

**Why top-N rank scores and no sparse-user shift** (revised in Step 2, decision D3; evidence in `eval/results/2026-09-26_blend_diagnosis`). The v2 draft used percentile ranks over the whole catalog and moved cf weight to content and quality for sparse users. On val that blend lost to EASE alone (NDCG@10 0.050 vs 0.102, paired difference −0.052 [−0.068, −0.036]). Two causes:

- Percentiles flatten the head: for user 1, EASE scores fall fourfold from rank 1 to rank 200 (0.52 → 0.12), but their percentiles only from 0.9999 to 0.960, so small content differences reorder the best CF candidates.
- The sparse-user shift hurt the users it was meant to help (NDCG@10 on users with < 30 train ratings: 0.059 with it, 0.076 without).

With top-200 rank scores and no shift, the blend is at 0.099, with no significant difference from EASE (−0.003 [−0.016, 0.008]). In query mode it keeps 88% of the top 5 among the 50 best plot matches, against 46% for percentiles. z-score normalization matched EASE in personal mode (0.102), but EASE's heavy-tailed scores then dominated query mode (42%).

The query-mode `min_ratings = 3` default is the brief's "quality filter", but it removes 37% of the catalog. That trade-off is measured in §9.3 and discussed in §15.

### 5.3 Filters

Applied before scoring, each logged with the number of movies removed: already seen, `exclude_genres`, `include_genres` (any), `year_min` / `year_max`, `min_ratings`. If fewer than k movies remain, the result carries the warning `few_candidates` and the per-filter counts, so the agent can suggest which constraint to relax.

### 5.4 Output

Each recommended item has: `movie_id`, `rank`, `score`, `contributions` (feature → value), flags, the top 2 history movies by EASE contribution (with the user's ratings), the matched plot excerpt in query mode, and movie stats. This record is the provenance: it goes into the tool output and the trace.

---

## 6. Tools

### 6.1 Result envelope and confidence

Every tool returns `{ok, error_code, data, confidence, confidence_reason, warnings}`. Errors are codes (`USER_NOT_FOUND`, `MOVIE_NOT_FOUND`, `AMBIGUOUS_MOVIE`, `INVALID_ARGS`), never stack traces. Numbers in `data` are the only numbers the agent may state (§7.4).

| Object | Low confidence when |
|---|---|
| Peer opinion | Fewer than 3 neighbours rated the movie (high: 8 or more) |
| User profile | Fewer than 20 ratings |
| Movie stats | Fewer than 5 ratings |
| Recommendation item | Flagged `no_cf_signal`, `few_ratings` (the movie has fewer than 5 ratings), or the user is `sparse_user` |

### 6.2 Tool specifications

**1. `get_user_profile(user_id)`**
Number of ratings, mean, strictness percentile; top 10 liked and bottom 5 movies; genre table (share, global share, affinity) over the 18 content genres; `unexplored` genres (share below a quarter of the global share, or zero) with the neighbours' affinity for each; `avoided` genres (at least 3 ratings and affinity ≤ −0.3). It returns **no movie suggestions**: for movies in a blind-spot genre the agent calls `recommend(include_genres=[g])`, so every suggested movie goes through the ranking core, has provenance, and passes the verifier.

**2. `find_movie(title, year=None)`**
Resolution status and up to 5 candidates (§4.3). When found: year, genres, number of ratings, mean, Bayesian average, top tags (stoplisted), and a plot excerpt (first 400 characters) for the agent to summarize. When not found, it says so explicitly.

**3. `recommend(user_id, query=None, seed_movie_ids=[], exclude_genres=[], include_genres=[], year_min=None, year_max=None, min_ratings=None, k=5)`**
Runs §5 and returns the items of §5.4, the mode used, per-filter counts and warnings. The tool description tells the LLM to put negative constraints ("not animated") in `exclude_genres`, never in `query`.

**4. `peer_opinion(user_id, movie_id)`**
Among the user's 50 nearest neighbours: how many rated the movie, their mean rating, their mean deviation from their own averages, the share who liked it, the comparison with all users (mean and count), the user's own rating if seen, and up to 5 example neighbours (similarity, shared movies, rating). With no neighbour ratings, it still returns global stats with confidence low and warning `no_similar_user_rated`.

**5. `explain(user_id, movie_id)`**
The top 3 history movies by EASE contribution (with the user's ratings), the top 3 by plot similarity (with excerpts), the user's affinity for the movie's genres, a `peer_opinion` summary, warnings, and `drivers`: the signals ordered by strength. The fidelity test (§9.5) checks whether these drivers really drive the ranking.

---

## 7. Agent

### 7.1 Loop and state

The agent uses OpenAI chat completions with function calling, through a thin client in `llm.py` (key `OPENAI_API_KEY` from `.env`, model from config). One turn:

1. Build messages: system prompt, a short state summary, the last 6 dialogue turns, the new message.
2. Call the LLM with the 5 tools plus `final_answer`. Execute tool calls and loop, at most 6 tool calls per turn.
3. Verify the final answer (§7.4), render it (§7.3), update state, write the trace (§8.1).

```python
class ConversationState(BaseModel):
    user_id: int
    focus_movie_id: int | None = None
    last_recommended: list[int] = []        # in the order shown
    exclude_genres: list[str] = []          # persists until the user relaxes it
    seen_in_session: list[int] = []
```

"That", "it" or "the second one" resolve through `focus_movie_id` and `last_recommended`, which the LLM sees with their positions.

Excluded genres are kept by the orchestrator, not only by the LLM: after each turn, `exclude_genres` gains every genre excluded in a successful `recommend` call and every `add_exclude_genres`, and loses every `remove_exclude_genres` (removal wins). V2 checks recommendations against this state, so a later call that forgets the constraint is caught (decision D9).

### 7.2 Prompt rules

`prompts/system_v1.md`; any change creates a new version, and traces record it.

1. State only facts that appear in tool results. Never use outside knowledge about movies, actors, directors or awards, even when confident.
2. Refer to movies only as `[[m:ID]]`.
3. Call `recommend` before recommending and `peer_opinion` before describing what similar users think.
4. Put constraints in structured arguments; negative constraints never go in the query.
5. When a tool reports low confidence, say so and give the reason.
6. When `find_movie` is ambiguous, ask which movie is meant. When a movie is absent, say the dataset does not contain it.
7. Be concise: 3–5 recommendations, each with a one-line reason from the data, then offer to explain.

### 7.3 `final_answer` and rendering

```python
class FinalAnswer(BaseModel):
    answer: str                         # markdown with [[m:ID]] placeholders
    recommended_movie_ids: list[int] = []
    focus_movie_id: int | None = None
    add_exclude_genres: list[str] = []
    remove_exclude_genres: list[str] = []
```

The renderer replaces each placeholder with "Title (Year)" from the catalog.

### 7.4 Verifier

| Rule | Check |
|---|---|
| V1 Movies | Every `[[m:ID]]` appeared in a tool result this session, and no catalog title of two or more words appears outside a placeholder |
| V2 Constraints | `recommended_movie_ids` are unseen, satisfy the active constraints, and came from a `recommend` result in this or the previous turn |
| V3 Numbers | Every number in the answer, except list ordinals and years, appears in this or the previous turn's tool outputs (ratings ±0.05, percentages ±1 point, counts exact). A minus sign or a following "below / lower / less / under" makes the number negative, so "2.3 below their average" matches −2.3 and a flipped sign is caught |

On failure the LLM gets one retry with the verifier message. If that also fails, the agent returns a template answer built directly from the tool outputs and the trace marks `verifier_fallback`. The verifier is tested on about 10 crafted bad answers (§9.1), and its first-pass and fallback rates are reported (§9.4).

### 7.5 Edge cases

| Situation | Behaviour |
|---|---|
| Unknown user ID | Say so and ask again |
| Movie not in the dataset (The Matrix) | Say so; offer to search by a description instead |
| Ambiguous title | Ask, listing candidates |
| Sparse user (user 30) | Answer with an explicit low-confidence note |
| Out of scope, or "just use what you know" | Explain that answers come only from the dataset |
| No movies left after filtering | Say so and suggest which constraint to relax, using the filter counts |

---

## 8. Traces and diagnostics

### 8.1 Trace

`traces/<session_id>.jsonl`, one line per turn: user message; every LLM request and response; every tool call with arguments and full output; verifier result; rendered answer; state before and after; versions (git commit, config hash, prompt version, LLM model, embedding model). Curated traces are committed in `traces/examples/`, and matching readable conversations in `transcripts/`, so reviewers can evaluate without an API key.

### 8.2 `why-not`

`movie-agent why-not --user <id> --movie <title|id> [recommend arguments]` reruns the ranking with the same arguments and returns the first matching code:

| Code | Meaning |
|---|---|
| `NOT_IN_CATALOG` | The movie is not in the dataset |
| `ALREADY_SEEN` | It is in the user's history |
| `FILTERED:<filter>` | Removed by that filter |
| `RANKED_BELOW` | Its rank, its contributions next to those of the movie at rank k, and the feature with the largest gap |
| `IN_TOP_K` | The engine did recommend it; if the answer did not mention it, the LLM dropped it |

It also prints the movie's rating count and genres. This is the main tool for the failure analysis.

### 8.3 Root-cause codes

| Code | Failure type | Where it shows up |
|---|---|---|
| U | Request misunderstood (wrong arguments, missed constraint) | Tool arguments in the trace vs the user message |
| T | Wrong or missing tool | Tool calls in the trace |
| E | Wrong movie resolved | `find_movie` output |
| R | Ranking: a signal or weight produces a poor result | `why-not`, contributions |
| D | Data limitation (absent movie, too few ratings, sparse user) | Movie and user stats |
| G | Generation: misstated or unsupported claim | Verifier result, manual audit |
| C | Constraint or state error (constraint lost, "that" resolved wrongly) | State before/after, V2 |

---

## 9. Evaluation

Each evaluation answers one question, and every result goes to `eval/results/<date>_<name>/` (§9.7).

### 9.1 Invariants and tests

pytest, on a tiny synthetic fixture in `tests/fixtures/tiny/`, with the LLM mocked:

| ID | Invariant |
|---|---|
| I1 | No leakage: evaluation fits never see val/test ratings |
| I2 | `recommend` never returns seen movies or movies violating its filters |
| I3 | Contributions sum to the score |
| I4 | The same request twice gives identical results |
| I5 | The renderer rejects unknown placeholders; the verifier catches the ~10 crafted bad answers in `tests/verifier_cases/` |
| I6 | Title resolution passes the cases in §4.3 |

### 9.2 Offline ranking

**Question:** does personalization beat non-personalized baselines, for which users, and at what cost in popularity bias?

- **Protocol:** per-user temporal split (§4.6). Rank all movies the user has not rated in train. No sampled negatives. Relevant: test ratings ≥ 4.0; the relative definition (r̃ ≥ 0.5) is reported as a sensitivity check.
- **Systems:** MostPopular, TopBayesian (baselines); UserKNN, EASE, ContentProfile; Blend (personal mode as deployed).
- **Metrics:** Recall@10 and NDCG@10. Beyond accuracy: catalog coverage@10; mean popularity of recommended movies compared with the user's own history; share of recommendations from sparse movies (fewer than 5 train ratings).
- **Segments:** users by train history size (terciles), and relevant test movies split into head vs tail.
- **Uncertainty:** 95% bootstrap CIs over users (1,000 resamples); paired bootstrap for Blend vs EASE and EASE vs MostPopular. If the CI of a difference contains 0, the report says there is no significant difference.
- **Expectations, written down in advance:** MostPopular is strong on MovieLens; EASE is probably the most accurate; the content feature probably matters more for tail movies and sparse users than for overall accuracy. Whatever the results, they are reported as they are.
- **Qualitative check:** the top 5 for users 1, 15 and 30 next to each user's top-rated movies.

### 9.3 Content search

**Question:** does description search return relevant movies, and where does plot text fail?

- 10 queries in `eval/search_queries.yaml`: the brief's dark-thriller query, plus tone, plot-element and setting queries.
- Top 5 per query, graded 0/1/2 by the author in shuffled order, in `eval/search_judgments.csv`. Metrics: P@5 (grade ≥ 1) and mean grade.
- **Deviation (Step 2, 2026-09-27):** at the author's request the grades were produced by an independent LLM grader (a fresh Claude subagent given only the guidelines, the shuffled pairs and the dataset's title, genres and plot; blind to the variant), with a rationale and failure type per pair. The report says so; an author spot-check of a random subset measures agreement (docs/notes.md).
- Variants: with and without `min_ratings = 3`; with and without the personalization weight (for user 15).
- Failure types are labeled for the report: keyword match with the wrong tone, sparse movies with poor plots, and so on.
- Tags are not used as labels because of the concentration in §4.1; that analysis goes in the report.

### 9.4 Agent scenarios

**Question:** does the assistant pick the right tools, stay grounded, respect constraints and admit uncertainty?

- `eval/scenarios.yaml`, about 24 scenarios: the 6 README sample queries for users 1, 15 and 30 (18), plus 6 edge cases (The Matrix absent, "Alien" ambiguous, user 30 asking about peers on a niche movie, "use your own knowledge", a 3-turn conversation where "no animation" must persist, an unknown user ID).
- **Automatic checks per scenario:** expected tools called; verifier passed on the first try; constraints satisfied.
- **Manual rubric** (`eval/rubric.md`), all scenarios, 0–2 each: grounded, relevant, explanation specific, honest about uncertainty. Step 2 deviation: graded by an independent LLM grader against the full tool outputs, at the author's request (same process as §9.3).
- **Reported:** tool-chain accuracy, verifier first-pass and fallback rates, constraint satisfaction, rubric means, tokens and latency per turn. Every run is saved as a transcript.

### 9.5 Honesty tests

Two cheap tests that measure requirement R3 directly.

**(a) Perturbation.** For 3 (user, movie) pairs where at least 8 neighbours rated the movie (for example user 15 and Pulp Fiction), build an in-memory copy of the ratings in which those neighbours' ratings of the movie become 5.5 − r. Ask the peer question against the original and the perturbed data. The agent passes if its stance flips with the data and it adds no facts beyond the tool outputs (checked by hand).

**(b) Explanation fidelity.** For 30 (user, recommended movie) pairs, take the top driver X from `explain`, remove X from the user's history, and rerun the ranking. The explanation is faithful if the movie drops at least 5 places or leaves the top 10. For 10 agent answers, also check whether the reason the LLM gave matches the top driver.

### 9.6 Failure analysis

Every failure found in §9.2–§9.5 is logged in `docs/notes.md` with the query, trace, `why-not` output where relevant, and a root-cause code (§8.3). The report presents 3 diverse cases. Expected candidates, to confirm or refute with data:

- popularity bias in personal mode;
- user 30's sparse history;
- tone queries where plot text misleads;
- Toy Story minus animation collapsing into children's films;
- the 37% of sparse movies CF can never recommend;
- ambiguous titles.

### 9.7 Results format

Each run writes `metrics.json`, a `summary.md` table, the config snapshot and the git commit. Nothing is overwritten. Report tables and figures are generated from these files with `movie-agent report-tables`, never typed by hand. `eval offline --split test` requires `--final` and logs every run to `eval/results/test_runs.log`.

---

## 10. Report plan

The report is where the effort goes. This maps each template section to its evidence.

| Template section | Content | Source |
|---|---|---|
| Problem Analysis | Who the users are, what a good conversational recommendation is, key challenges: sparse movies (37% under 3 ratings), sparse users, grounding an LLM | §4.1 facts, §1 |
| Approach | Problem breakdown, tool design, alternatives rejected | §1.3, §5, §6 |
| Decision Log | 3 entries chosen from §14 | §14 |
| Evaluation | Offline table with CIs and segments, popularity analysis, search results, scenario metrics, honesty tests | §9 results |
| Failure Analysis | 3 cases, each with query, output, `why-not`/trace evidence, root cause, fix | §9.6 |
| Reflection | What works, what does not and why, what the §1.3 cuts would add with more time | §1.3, §9 |
| Open Section | Data findings (tag concentration, tie blocks, IMAX label, zero validation issues), verifier statistics, perturbation results | §4.1, §9.5 |

**Figures** (at most 3, matplotlib, saved with results): Recall@10 and NDCG@10 by system with CIs; the same by user-history tercile; mean popularity of recommendations vs user history per system.

---

## 11. Configuration

`configs/default.yaml` is the only config file.

```yaml
seed: 42
paths:
  data_dir: Exam/data/ml-latest-small-filtered
  cache_dir: cache
  traces_dir: traces
  results_dir: eval/results
data:
  test_frac: 0.2
  val_frac: 0.1
  liked_abs: 4.0
  liked_rel: 0.5
  genre_exclude: ["IMAX", "(no genres listed)"]
  tag_stoplist: ["in netflix queue"]
stats: {bayes_C: 10, genre_alpha: 3}
resolve: {found_min: 90, ambiguous_min: 75, min_gap: 5, subset_weight: 0.9}
user_knn: {k: 50, min_common: 5, gamma: 50}
ease: {lambda: 500, lambda_grid: [100, 300, 500, 1000]}
content: {model: BAAI/bge-small-en-v1.5, chunk_tokens: 300, chunk_overlap: 50}
ranking:
  top_n: 200
  sparse_user_threshold: 30
  query_min_ratings: 3
  weights:
    personal: {cf: 0.7, content: 0.2, quality: 0.1}
    query:    {query: 0.6, cf: 0.2, quality: 0.2}
    seed:     {seed: 0.5, cf: 0.3, quality: 0.2}
confidence: {peer_low_below: 3, peer_high_min: 8, user_low_below: 20, movie_low_below: 5}
agent:
  provider: openai
  model: "<set-me>"          # the author sets this
  temperature: 0.0
  max_tool_calls: 6
  history_turns: 6
  prompt_version: system_v1
```

The tag stoplist is extended if more list-style tags turn up during validation.

---

## 12. Repository layout and commands

```
Exam/                     brief (README.md), REPORT_TEMPLATE.md, data/ — READ-ONLY
README.md                 project overview + setup (written in Step 3)
REPORT.md
CLAUDE.md
pyproject.toml  .env.example  .gitignore
configs/default.yaml
src/movie_agent/
  config.py  cli.py
  data.py          loading, validation, stats, splits
  catalog.py       title normalization and resolution
  engines.py       EASE, UserKNN, plot embeddings
  ranking.py       filters, features, blend, contributions
  tools.py         the 5 tools, envelope, confidence
  llm.py           thin OpenAI client
  agent.py         loop, state, final_answer, renderer
  verifier.py
  trace.py         JSONL writer
  diagnostics.py   why-not
  prompts/system_v1.md
  evaluation/      offline.py, search.py, scenarios.py, honesty.py, report_tables.py
eval/              search_queries.yaml, search_judgments.csv, scenarios.yaml, rubric.md, results/
tests/             fixtures/tiny/, verifier_cases/, test_*.py
traces/examples/   curated traces (the rest of traces/ is git-ignored)
transcripts/       curated conversations
docs/              design.md, notes.md
cache/             embeddings (git-ignored)
```

| Command | Purpose |
|---|---|
| `movie-agent validate` | Data report (§4.1) |
| `movie-agent chat --user <id>` | Interactive session; writes traces |
| `movie-agent why-not --user <id> --movie <title\|id> [recommend args]` | §8.2 |
| `movie-agent eval offline --split val` | §9.2 on val; `--split test --final` in Step 3 only |
| `movie-agent eval search` | §9.3 (prints top 5 per query for grading, then scores judgments) |
| `movie-agent eval agent` | §9.4 |
| `movie-agent eval honesty` | §9.5 |
| `movie-agent report-tables` | Report tables and figures from saved results |

---

## 13. Build plan and Definitions of Done

The brief suggests 3–4 hours with about half on building. The effort split here is roughly **40% build, 30% evaluate, 30% analyze and write**; if more time is available, it goes into Steps 2 and 3, not into more components.

### 13.1 Step 1: build

Order, with tests and a commit after each module:

1. Scaffolding: `pyproject.toml`, `.gitignore` (cache/, traces/ except examples, .env), config loader, CLI skeleton, tiny fixture.
2. `data.py` and `catalog.py`, with `validate`.
3. `engines.py` and `ranking.py`.
4. `tools.py`.
5. `llm.py`, `agent.py`, `verifier.py`, `trace.py`, `prompts/system_v1.md`.
6. `diagnostics.py` (`why-not`).
7. `evaluation/` scripts and `eval/` files (queries, scenarios, rubric).

**Done when:** tests I1–I6 pass; `validate` reproduces the §4.1 facts (differences noted in `docs/notes.md`); every README sample query works in `chat` for users 1, 15 and 30; every command in §12 runs; every assumption made while building is in `docs/notes.md`.

### 13.2 Step 2: evaluate (on val)

1. Offline ranking; choose EASE λ and the personal-mode cf/content split.
2. Search: grade the judged set; compare the variants.
3. Agent scenarios: run, grade with the rubric, fix what fails (new prompt version if needed), re-run.
4. Honesty tests.
5. Log every failure with a root-cause code.

**Done when:** all §9 results are saved; tuned values are in the config; decision-log entries are marked accepted or revised; at least 5 failures are logged.

### 13.3 Step 3: analyze and write

1. Freeze code and config. Fit on train + val, run `eval offline --split test --final` once.
2. Generate tables and figures; pick 3 failure cases and 3 decisions.
3. Write `REPORT.md` following `Exam/REPORT_TEMPLATE.md`; write the root `README.md` (setup, how to run, API usage, where example outputs are).
4. Curate `transcripts/` and `traces/examples/`.

If a bug is found after the test run, fix it, re-run, and report both runs with the reason.

**Done when:** every template section is filled from saved results; the test run is logged; a fresh clone can follow the README.

---

## 14. Decision log

Candidates for the report's three decisions. Status is proposed until Step 2 provides the evidence.

| ID | Decision | Alternative | Why | Would change if |
|---|---|---|---|---|
| D1 | Deterministic tools; the LLM only orchestrates and narrates; placeholders + verifier. **Accepted in Step 2**: every first-pass rejection in the final agent run was a real violation (typed titles); one false-positive class (V3 signs) was found and fixed; fallback 0–3% of turns | Free-form LLM answers over retrieved data | Makes R3 enforceable and failures attributable | Verifier rejects too many good answers |
| D2 | EASE as main recommender; UserKNN kept for peer questions. **Accepted in Step 2**: EASE is the best single model on val (NDCG@10 0.102 vs UserKNN 0.081, MostPopular 0.064) | Matrix factorization; ItemKNN; UserKNN only | Closed form, deterministic, strong on MovieLens, explainable contributions; peer questions need real neighbours | UserKNN or another model beats EASE on val beyond the CI |
| D3 | Score the whole catalog with a weighted blend of top-N rank scores (N = 200), with no sparse-user weight shift. Revised in Step 2, 2026-09-26 | Candidate generation plus learning-to-rank; the v2 draft's percentile blend; z-score or min-max blend | 5k movies is small; contributions are directly readable. The draft percentile blend lost to EASE on val (0.050 vs 0.102) because percentiles flatten EASE's head; top-200 rank scores match EASE (0.099, n.s.) and follow the query best in query mode (§5.2) | Blend does worse than EASE alone on val (the trigger fired for the draft; revised) |
| D4 | Chunked plots, max-chunk similarity, local embedding model. **Accepted in Step 2**: P@5 0.84 [0.72, 0.94] (LLM-graded); failures are mostly partial plot matches and bad plot data (about 6% of plots belong to another film), not the model | Whole-plot embedding; BM25 hybrid; API embeddings | Long plots are not diluted; the matched excerpt is evidence; reproducible and free | Search grades are poor mainly because of the model |
| D5 | Per-user temporal split, full ranking, bootstrap CIs. **Accepted** | Random split; sampled negatives | Random splits leak the future; sampled metrics can misorder models | — |
| D6 | Lean scope (5 tools, 3 verifier rules, JSONL traces). **Accepted**: the Step 2 findings came from traces, `why-not` and the scenario checks | The v1 design (9 tools, 8 rules, trace CLI) | Brief's time budget; effort moved to analysis | — |
| D7 | Tags not used as evaluation labels. **Accepted** | Tag weak labels for search | 45 taggers, 43% of tags from one user, list-style tags | — |
| D8 | Title matching: exact forms, then `max(ratio, 0.9 × token_set_ratio)` on article-free forms, subset credit only for forms at least as long as the query (§4.3). Revised in Step 1, 2026-09-26 | rapidfuzz `WRatio` over all forms (v2 draft) | `WRatio` returned "The Matrix" as ambiguous (85.5 against any title containing "the") and "Matrix" as found ("M (1931)"); the replacement passes every §4.3 case and ~35 real queries | Resolution errors (code E) show up in Step 2 scenarios |
| D9 | Excluded genres persist in code: the orchestrator adds genres excluded in `recommend` to the state (§7.1). Added in Step 2, 2026-09-27 | State updated only through `final_answer.add_exclude_genres` (the v2 draft) | With prompt rules alone, persistence was 4/6 in one run and 1/6 in an identical one; a follow-up call with `exclude_genres=[]` returned Toy Story 3 and the constraint held only because the LLM skipped it | A one-off exclusion ("no horror tonight") now persists until the user relaxes it; revise if scenarios show that confuses users |
| D10 | A recommendation with fewer than 5 ratings is low confidence (`few_ratings`, §6.1). Added in Step 2, 2026-09-27 | Only `no_cf_signal` and `sparse_user` lower item confidence (the v2 draft) | A query-mode pick with 4 ratings, mean 2.12 and only the query signal was labelled high, so the answer did not hedge; most rubric honest = 0 scores traced to this | — |
| D11 | LLM stays gpt-4.1-mini. gpt-5.1 was tried as a drop-in replacement (`reasoning_effort: none`, temperature 0, same prompt and code) and **rejected**, 2026-09-27: blind paired grading on val shows it less grounded (1.14 vs 1.48, −0.34 [−0.62, −0.07]), equal on relevance, 1.6× slower (notes, gpt-5.1 trial). `agent.reasoning_effort` stays in the config (null = not sent) | gpt-5.1 as the deployed model | Grounding (R3) is the property the design exists for; the stronger model attributes all-user statistics to similar users and adds outside-knowledge descriptions, which the verifier cannot see | A prompt or verifier change (failures 18–19) closes the grounded gap for a stronger model |

---

## 15. Limitations and open questions

**Known limitations**

- Offline metrics treat unrated as irrelevant and favour popular movies (data is missing not at random).
- Plot text describes events, not tone; mood queries are weak.
- 37% of movies have fewer than 3 ratings; CF cannot recommend them.
- Sparse users make similarities unreliable.
- Rules and the verifier reduce but cannot remove the LLM's prior knowledge; §9.5 measures how much remains.
- The verifier's title and number checks are heuristics with some false positives and negatives.
- One annotator for search grades and the rubric, and in Step 2 that annotator is an LLM grader, not the author: grades can share the grader model's blind spots, and the builder chose the guidelines.
- Movies end in 2014, so "tonight" suggestions are dated.

**Open questions (answered in Step 2)**

| Question | Evidence |
|---|---|
| EASE λ | Val NDCG@10 |
| Personal-mode cf vs content weight | Val NDCG@10, overall and on the sparse-user tercile |
| Query-mode `min_ratings`: 0, 3 or 5? It trades 37% of the catalog against reliability | §9.3 variants |
| 3 or 5 recommendations per answer | Rubric scores |

Answers from Step 2 (evidence in `docs/notes.md`): λ = 500; personal weights stay cf 0.7 / content 0.2 / quality 0.1 (no significant difference to the val maximum); query-mode `min_ratings` stays 3 (dropping it is not significantly better and doubles sparse results); 3–5 recommendations stays (the rubric does not separate the two).