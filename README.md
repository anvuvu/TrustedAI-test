# Movie discovery agent

A conversational assistant that helps a MovieLens user discover movies by investigating the dataset on their behalf: their ratings, similar users' ratings, plots and genres. It decides what to look up, calls deterministic tools, and explains every recommendation with evidence from the data, never from the LLM's own movie knowledge.

- **Report:** [`REPORT.md`](REPORT.md) (problem analysis, approach, evaluation, failure analysis, reflection)
- **Design:** [`docs/design.md`](docs/design.md) · **Lab notebook:** [`docs/notes.md`](docs/notes.md)
- **Brief and data:** [`Exam/`](Exam/) (the unmodified handout, read-only)

## How it works

```
User ──► Agent loop (OpenAI function calling + conversation state)
            │ tool calls                        ▲ verifier → renderer
            ▼                                   │
         5 tools: get_user_profile · find_movie · recommend · peer_opinion · explain
            ▼
         Ranking: filters → features (cf, content, query, seed, quality) → weighted blend
            ▼
         Engines: EASE · UserKNN · plot embeddings (bge-small, chunked, cached)
            ▼
         Data: validation · catalog + title resolution · statistics · temporal splits
```

- Python computes every number, ranking and list. The LLM (gpt-4.1-mini) only chooses tools and phrases their results.
- The LLM refers to movies only as `[[m:<movieId>]]` placeholders. The renderer turns them into "Title (Year)" from the catalog, so the LLM cannot invent a title.
- A deterministic verifier checks each answer before it is shown: movies must come from tool results, recommendations must respect the constraints, and numbers must match tool outputs. A failing answer gets one retry, then a template answer built from the tool outputs.
- Every turn is written to a JSONL trace. `why-not` explains why any movie was not recommended.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # then set OPENAI_API_KEY (only needed for the agent, see below)
```

The first command that ranks movies downloads the local embedding model `BAAI/bge-small-en-v1.5` (about 130 MB, from Hugging Face). It then embeds the 16,204 plot chunks, which takes about 1–2 minutes on a laptop CPU. The vectors are cached in `cache/` and later runs start in a few seconds.

## Commands

| Command | What it does | Needs an API key |
|---|---|---|
| `movie-agent validate` | Checks the data and writes `eval/results/data_report.json` | no |
| `movie-agent chat --user 15` | Interactive session (empty line to quit); writes `traces/<session>.jsonl` | yes |
| `movie-agent why-not --user 15 --movie "Heat" --exclude-genres Animation` | Why a movie is not recommended for these arguments | no |
| `movie-agent eval offline --split val` | Ranking metrics with baselines and bootstrap CIs, plus the val tuning sweeps | no |
| `movie-agent eval search` | Top 5 per judged query; scores the graded sheet `eval/search_judgments.csv` | no |
| `movie-agent eval agent` | The 24 scenarios in `eval/scenarios.yaml`; saves transcripts and a rubric sheet | yes |
| `movie-agent eval honesty` | Explanation fidelity (no key) plus the perturbation and attribution tests (key) | yes |
| `movie-agent report-tables` | Regenerates `eval/results/report_tables.md`, the figures and the tables inside `REPORT.md` | no |
| `movie-agent eval offline --split test --final` | The single final test run; already done and logged in `eval/results/test_runs.log` | no |

Checks: `pytest -q` (tiny synthetic fixture, LLM mocked, no network) and `ruff check . && ruff format --check .`.

## External API

Only the agent uses an external API: OpenAI chat completions with `gpt-4.1-mini` (configurable in `configs/default.yaml`), for `chat`, `eval agent` and part of `eval honesty`. It sends the conversation and the tool outputs, which contain dataset values only. A turn uses about 7k tokens; a full scenario run (29 turns) is about 200k tokens. Everything else, including the embeddings, runs locally.

Responses vary slightly between runs even at temperature 0, so re-running `eval agent` gives numbers close to, but not identical with, the saved ones (`REPORT.md` compares several runs).

## Example outputs (no API key needed)

- `transcripts/chat_user_{1,15,30}.md`: one `chat` session per test user with all six sample queries from the brief. The matching full traces (every tool call with its output, verifier result, state) are in `traces/examples/`.
- `eval/results/<date>_agent_*/transcripts/`: every scenario of each agent evaluation run.
- `eval/results/`: every evaluation run (metrics, summary, config snapshot, git commit); `eval/results/report_tables.md` and `eval/results/figures/` are generated from them.
- `eval/grading/`: the grading packets and the graded sheets with a rationale for every grade.

## Reproducing the results

```bash
movie-agent validate
movie-agent eval offline --split val    # ranking, tuning sweeps
movie-agent eval search                 # uses the graded eval/search_judgments.csv
movie-agent eval agent                  # needs OPENAI_API_KEY
movie-agent eval honesty                # needs OPENAI_API_KEY for the LLM parts
movie-agent report-tables
```

Each run writes a new `eval/results/<date>_<name>/` directory, and nothing is overwritten. The test split was evaluated once, from the commit tagged `final-eval`. Running it again appends to `eval/results/test_runs.log`, and the report would have to list that run.

## Repository layout

```
Exam/                     brief, report template and data (read-only)
configs/default.yaml      every tunable (the only config file)
src/movie_agent/          data.py, catalog.py, engines.py, ranking.py, tools.py, llm.py,
                          agent.py, verifier.py, trace.py, diagnostics.py, cli.py,
                          prompts/system_v{1,2}.md, evaluation/
eval/                     search queries and judgments, scenarios, rubric, grading/, results/
tests/                    pytest suite and the tiny fixture
transcripts/  traces/examples/   curated sample conversations and their traces
docs/                     design.md, notes.md
```
