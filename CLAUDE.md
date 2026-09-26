# CLAUDE.md

Working instructions for Claude Code in this repository. The design is in `docs/design.md` (sections referenced as §N). The design says **what** to build; this file says **how** to work.

## What this project is

TrustedAI AI Engineer take-home. A conversational assistant that helps a user discover movies by investigating a MovieLens subset on their behalf, and explains every recommendation with evidence from the data, never from the LLM's own movie knowledge.

**The report (`REPORT.md`) is weighted equally with the code, and it is where most of the value is.** Keep the system small, correct and traceable; put the depth into evaluation and analysis. Do not add components beyond `docs/design.md` without a proposal (see below).

## Paths

- Brief: `Exam/README.md`. Report template: `Exam/REPORT_TEMPLATE.md`.
- Dataset: `Exam/data/ml-latest-small-filtered/`. **Everything under `Exam/` is read-only.**
- The root `README.md` is ours: project overview and setup instructions, written in Step 3.
- `REPORT.md` lives at the root.

## Before you write code

- Read the matching section of `docs/design.md` before implementing or changing a module.
- If the design is wrong, ambiguous or missing something, propose the change first. Once agreed, update `docs/design.md` in the same change as the code and add a line to its Decision Log (§14). For small ambiguities during Step 1, pick the simplest option consistent with §2, note the assumption in `docs/notes.md`, and continue.

## Principles

1. **Deterministic core; the LLM orchestrates and narrates.** Python computes every number, ranking and list. The LLM never computes, estimates or recalls a number.
2. **Grounded by construction.** The agent refers to movies only through `[[m:<movieId>]]` placeholders (§7.3). The verifier checks movies, constraints and numbers against tool outputs (§7.4). A movie title typed free-hand by the LLM is a bug.
3. **Traceable.** Every turn writes a JSONL trace (§8.1). Every recommended movie carries its score contributions (§5.4). `why-not` explains any movie that was not recommended (§8.2).
4. **No leakage.** Evaluation fits on train only and tunes on val. The test split is used exactly once, in Step 3 (§13.3), through `--final`.
5. **Baselines and uncertainty.** Every result is compared with MostPopular and TopBayesian and reported with bootstrap CIs (§9.2).
6. **Report honestly.** If something does not beat a baseline, say so. Never change a metric or split after seeing test results.
7. **Small and readable.** Flat modules, numpy/pandas/scipy, a hand-written agent loop. No agent frameworks, vector databases or UI frameworks.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                     # Python 3.11
cp .env.example .env                        # OPENAI_API_KEY

movie-agent validate                        # data report → eval/results/data_report.json
movie-agent chat --user 15                  # interactive session, writes traces/
movie-agent why-not --user 15 --movie "Heat" --exclude-genres Animation
movie-agent eval offline --split val
movie-agent eval search
movie-agent eval agent
movie-agent eval honesty
movie-agent report-tables

movie-agent eval offline --split test --final   # Step 3 only, once

pytest -q                                   # must pass before every commit
ruff check . && ruff format --check .
```

Implement commands exactly as specified in §12. Update this list if they change.

## Conventions

- Python 3.11, type hints, pydantic v2 for tool results, state and `final_answer`.
- Layout as in §12: flat modules under `src/movie_agent/`, evaluation scripts in `src/movie_agent/evaluation/`, evaluation data in `eval/`.
- Every tunable lives in `configs/default.yaml` (the only config file). No magic numbers, no hard-coded model names.
- Seed from config for anything random.
- `movieId` and `userId` are the canonical keys. Titles are resolved only through `catalog.py`.
- Keep functions short and documented; reviewers will read this code in the interview.

## Tests

- Tests run on `tests/fixtures/tiny/` with the LLM mocked; no network.
- Invariants I1–I6 (§9.1) are required and must stay green.
- Never weaken a verifier rule to make a scenario pass. Fix the cause.
- When a failure is found, add a test or scenario that reproduces it before fixing.

## LLM

- OpenAI via `llm.py`; key `OPENAI_API_KEY` from `.env`; model from `configs/default.yaml`. If the model is still `"<set-me>"`, ask the author instead of choosing one.
- The prompt starts at `prompts/system_v1.md`. A change means a new version file; traces record the version.
- Evaluation runs use temperature 0.

## Working log (feeds the report)

- Append dated entries to `docs/notes.md`: decisions, assumptions, surprising results, failures (query, trace file, root-cause code from §8.3, proposed fix).
- Every evaluation run goes to `eval/results/<YYYY-MM-DD>_<name>/`; never overwrite. Report tables come from these files via `report-tables`, never typed by hand.

## Don'ts

- Don't modify anything under `Exam/`.
- Don't touch the test split before Step 3.
- Don't use sampled negatives; always rank all unseen movies.
- Don't let the agent recommend a movie that did not come from a `recommend` result.
- Don't commit `.env`, `cache/`, or `traces/` other than `traces/examples/`.

## Build plan and progress

Three steps (§13). Effort split roughly 40% build, 30% evaluate, 30% analyze and write. Spare time goes to Steps 2–3, not to more components. Tick items with the date.

**Step 1: build** (DoD §13.1). After each module: tests, ruff, commit, note in `docs/notes.md`.

- [x] 1. Scaffolding: pyproject, `.gitignore`, config, CLI skeleton, tiny fixture (2026-09-26)
- [x] 2. `data.py`, `catalog.py`, `validate` (2026-09-26)
- [x] 3. `engines.py`, `ranking.py` (2026-09-26)
- [x] 4. `tools.py` (2026-09-26)
- [x] 5. `llm.py`, `agent.py`, `verifier.py`, `trace.py`, `prompts/system_v1.md` (2026-09-26)
- [x] 6. `diagnostics.py` (`why-not`) (2026-09-26)
- [x] 7. `evaluation/` scripts; `eval/` queries, scenarios, rubric (2026-09-26)
- [x] Step 1 DoD verified (2026-09-26)

**Step 2: evaluate on val** (DoD §13.2)

- [ ] Offline ranking; EASE λ and personal-mode weights chosen
- [ ] Search judged set graded; variants compared
- [ ] Agent scenarios run, graded, fixed, re-run
- [ ] Honesty tests
- [ ] At least 5 failures logged with root-cause codes

**Step 3: analyze and write** (DoD §13.3)

- [ ] Freeze; single test run
- [ ] Tables and figures; 3 failure cases; 3 decisions
- [ ] `REPORT.md`, root `README.md`, curated transcripts and traces