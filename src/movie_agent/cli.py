"""`movie-agent` command-line interface (design §12).

Commands import their modules lazily so that `--help` stays fast.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from dotenv import load_dotenv

from movie_agent.config import PROJECT_ROOT, Config, load_config

if TYPE_CHECKING:
    from movie_agent.data import Dataset
    from movie_agent.llm import LLMClient

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
eval_app = typer.Typer(no_args_is_help=True, help="Evaluation suites (design §9).")
app.add_typer(eval_app, name="eval")

ConfigOpt = typer.Option(None, "--config", help="Config file (default configs/default.yaml).")


def _setup(config: Path | None) -> tuple[Config, Dataset]:
    from movie_agent.data import load_dataset

    load_dotenv(PROJECT_ROOT / ".env")
    cfg = load_config(config)
    return cfg, load_dataset(cfg.paths.data_dir)


def _llm_factory(cfg: Config) -> Callable[[], LLMClient]:
    from movie_agent.llm import OpenAIClient

    return lambda: OpenAIClient(cfg.agent)


@app.command()
def validate(config: Path | None = ConfigOpt) -> None:
    """Validate the dataset and write eval/results/data_report.json (design §4.1)."""
    from movie_agent.data import validate as run_validate
    from movie_agent.data import write_data_report

    cfg, ds = _setup(config)
    report = run_validate(ds, cfg)
    path = write_data_report(report, cfg)
    typer.echo("Checks (0 = no issue):")
    for name, count in report["checks"].items():
        typer.echo(f"  {name:<30} {count}")
    facts = report["facts"]
    keys = [
        "n_movies",
        "n_ratings",
        "n_users",
        "n_tags",
        "year_range",
        "n_genre_labels",
        "n_content_genres",
        "movies_under_3_ratings",
        "movies_under_3_ratings_share",
        "movies_under_5_ratings_share",
        "users_under_10_ratings",
        "tie_boundary_users",
        "zero_variance_users",
        "n_taggers",
        "top_tagger",
    ]
    typer.echo("Facts:")
    for key in keys:
        typer.echo(f"  {key:<30} {json.dumps(facts[key])}")
    typer.echo(f"Report written to {path}")


@app.command()
def chat(
    user: int = typer.Option(..., "--user", help="userId of the person chatting."),
    config: Path | None = ConfigOpt,
) -> None:
    """Interactive session; every turn is written to traces/ (design §7, §8.1)."""
    from movie_agent.agent import Agent
    from movie_agent.ranking import build_ranker
    from movie_agent.tools import Toolbox
    from movie_agent.trace import TraceWriter, new_session_id, versions

    cfg, ds = _setup(config)
    typer.echo("Loading models...")
    ranker = build_ranker(cfg, ds)
    while not ranker.history(user):
        typer.echo(f"User {user} has no ratings in this dataset.")
        user = typer.prompt("Enter a valid userId", type=int)
    tracer = TraceWriter(cfg.paths.traces_dir, new_session_id())
    agent = Agent(
        user,
        Toolbox(ranker, ds.tags, cfg),
        _llm_factory(cfg)(),
        cfg,
        tracer,
        versions(cfg, ranker.embedder.name),
    )
    typer.echo(
        f"Chatting as user {user} ({len(ranker.history(user))} ratings). "
        f"Trace: {tracer.path}. Empty line or 'exit' to quit."
    )
    while True:
        try:
            message = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"", "exit", "quit"}:
            break
        turn = agent.run_turn(message)
        typer.echo(f"\nassistant> {turn.rendered}")
        tools = ", ".join(c["name"] for c in turn.tool_calls) or "none"
        status = (
            "fallback"
            if turn.fallback
            else ("passed" if turn.record["verifier_first_pass"] else "passed after retry")
        )
        typer.echo(f"\n[tools: {tools} | verifier: {status}]")


@app.command("why-not")
def why_not(
    user: int = typer.Option(..., "--user"),
    movie: str = typer.Option(..., "--movie", help="Title or movieId."),
    query: str | None = typer.Option(None, "--query"),
    seed: list[int] = typer.Option([], "--seed", help="Seed movieId (repeatable)."),
    exclude_genres: list[str] = typer.Option([], "--exclude-genres"),
    include_genres: list[str] = typer.Option([], "--include-genres"),
    year_min: int | None = typer.Option(None, "--year-min"),
    year_max: int | None = typer.Option(None, "--year-max"),
    min_ratings: int | None = typer.Option(None, "--min-ratings"),
    k: int | None = typer.Option(None, "--k"),
    config: Path | None = ConfigOpt,
) -> None:
    """Explain why a movie was not recommended for these arguments (design §8.2)."""
    from movie_agent.diagnostics import why_not as diagnose
    from movie_agent.ranking import RecommendRequest, build_ranker, canonical_genres

    cfg, ds = _setup(config)
    ranker = build_ranker(cfg, ds)
    req = RecommendRequest(
        user_id=user,
        query=query,
        seed_movie_ids=seed,
        exclude_genres=canonical_genres(exclude_genres, ds.movies),
        include_genres=canonical_genres(include_genres, ds.movies),
        year_min=year_min,
        year_max=year_max,
        min_ratings=min_ratings,
        k=k or cfg.tools.default_k,
    )
    typer.echo(diagnose(ranker, req, movie).to_text())


@eval_app.command("offline")
def eval_offline(
    split: str = typer.Option("val", "--split", help="val, or test (Step 3 only)."),
    final: bool = typer.Option(False, "--final", help="Required for --split test."),
    config: Path | None = ConfigOpt,
) -> None:
    """Offline ranking evaluation with baselines and bootstrap CIs (design §9.2)."""
    from movie_agent.evaluation.offline import run_offline

    if split == "test" and not final:
        typer.echo("The test split is used exactly once, in Step 3: add --final.", err=True)
        raise typer.Exit(code=2)
    cfg, ds = _setup(config)
    out = run_offline(cfg, ds, split, final)
    typer.echo((out / "summary.md").read_text())
    typer.echo(f"Results written to {out}")


@eval_app.command("search")
def eval_search(config: Path | None = ConfigOpt) -> None:
    """Content search: print top 5 per query for grading, then score judgments (§9.3)."""
    from movie_agent.evaluation.search import JUDGMENTS, run_search

    cfg, ds = _setup(config)
    out = run_search(cfg, ds)
    typer.echo((out / "summary.md").read_text())
    typer.echo(f"Results written to {out}. Grade ungraded pairs in {JUDGMENTS}, then re-run.")


@eval_app.command("agent")
def eval_agent(config: Path | None = ConfigOpt) -> None:
    """Run the agent scenarios in eval/scenarios.yaml (design §9.4)."""
    from movie_agent.evaluation.scenarios import run_scenarios

    cfg, ds = _setup(config)
    out = run_scenarios(cfg, ds, _llm_factory(cfg))
    typer.echo((out / "summary.md").read_text())
    typer.echo(f"Results and transcripts written to {out}")


@eval_app.command("honesty")
def eval_honesty(config: Path | None = ConfigOpt) -> None:
    """Perturbation and explanation-fidelity tests (design §9.5)."""
    from movie_agent.evaluation.honesty import run_honesty

    cfg, ds = _setup(config)
    out = run_honesty(cfg, ds, _llm_factory(cfg))
    typer.echo((out / "summary.md").read_text())
    typer.echo(f"Results written to {out}")


@app.command("report-tables")
def report_tables(config: Path | None = ConfigOpt) -> None:
    """Build report tables and figures from saved results; refresh REPORT.md and REPORT.vi.md."""
    from movie_agent.evaluation.report_tables import run_report_tables

    load_dotenv(PROJECT_ROOT / ".env")
    out = run_report_tables(load_config(config))
    typer.echo(f"Tables written to {out}")


if __name__ == "__main__":
    app()
