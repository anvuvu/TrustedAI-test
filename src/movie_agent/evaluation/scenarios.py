"""Agent scenario suite (design §9.4).

Question: does the assistant pick the right tools, stay grounded, respect constraints and
admit uncertainty? Automatic checks per turn; a rubric sheet for manual grading; every run
saved as transcripts. Runs on all ratings, as deployed in `chat`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from movie_agent.agent import Agent
from movie_agent.config import PROJECT_ROOT, Config
from movie_agent.data import Dataset
from movie_agent.engines import Embedder
from movie_agent.evaluation.results import new_results_dir, save_run
from movie_agent.llm import LLMClient
from movie_agent.ranking import build_ranker
from movie_agent.tools import Toolbox
from movie_agent.trace import TraceWriter, versions

SCENARIOS = PROJECT_ROOT / "eval" / "scenarios.yaml"
RUBRIC_CRITERIA = ("grounded", "relevant", "specific", "honest")


def check_turn(expect: dict[str, Any], record: dict[str, Any], toolbox: Toolbox) -> dict[str, bool]:
    """Automatic checks for one turn against its `expect` block."""
    called = [c["name"] for c in record["tool_calls"]]
    recommended = record["final_answer"]["recommended_movie_ids"]
    user_id = record["state_after"]["user_id"]
    checks = {
        "tools": all(t in called for t in expect.get("tools", []))
        and not any(t in called for t in expect.get("forbid_tools", [])),
        "verifier_first_pass": bool(record["verifier_first_pass"]),
        "no_fallback": not record["verifier_fallback"],
    }
    if "recommends" in expect:
        checks["recommends"] = bool(recommended) == expect["recommends"]
    excluded = set(expect.get("exclude_genres", [])) | set(record["state_after"]["exclude_genres"])
    if recommended:
        seen = set(toolbox.r.history(user_id))
        checks["constraints"] = all(
            m not in seen and not set(toolbox.r.catalog.genres(m)) & excluded
            for m in recommended
            if m in toolbox.r.catalog
        )
    if expect.get("exclude_genres"):
        checks["state"] = set(expect["exclude_genres"]) <= set(
            record["state_after"]["exclude_genres"]
        )
    return checks


def transcript(scenario: dict, records: list[dict]) -> str:
    lines = [f"# {scenario['id']} (user {scenario['user_id']})", ""]
    for i, r in enumerate(records):
        lines += [f"## Turn {i + 1}", "", f"**User:** {r['user_message']}", ""]
        for c in r["tool_calls"]:
            ok = "ok" if c["result"]["ok"] else c["result"]["error_code"]
            lines.append(
                f"- tool `{c['name']}` {c['arguments']} -> {ok}, "
                f"confidence {c['result']['confidence']}"
            )
        verdict = (
            "passed"
            if r["verifier_first_pass"]
            else ("fallback" if r["verifier_fallback"] else "passed after retry")
        )
        lines += ["", f"**Assistant** (verifier: {verdict}):", "", r["rendered_answer"], ""]
    return "\n".join(lines)


def run_scenarios(
    cfg: Config,
    ds: Dataset,
    llm_factory: Callable[[], LLMClient],
    embedder: Embedder | None = None,
    path: Path = SCENARIOS,
) -> Path:
    scenarios = yaml.safe_load(path.read_text())["scenarios"]
    ranker = build_ranker(cfg, ds, embedder=embedder)
    toolbox = Toolbox(ranker, ds.tags, cfg)
    vers = versions(cfg, ranker.embedder.name)
    out = new_results_dir(cfg, "agent")
    (out / "transcripts").mkdir()
    turn_rows, rubric_rows = [], []
    for sc in scenarios:
        tracer = TraceWriter(cfg.paths.traces_dir, f"eval-{out.name}-{sc['id']}")
        agent = Agent(sc["user_id"], toolbox, llm_factory(), cfg, tracer, vers)
        records = []
        for i, turn in enumerate(sc["turns"]):
            record = agent.run_turn(turn["user"]).record
            records.append(record)
            checks = check_turn(turn.get("expect", {}), record, toolbox)
            usage = [c["usage"].get("total_tokens", 0) for c in record["llm_calls"]]
            turn_rows.append(
                {
                    "scenario": sc["id"],
                    "turn": i + 1,
                    "tags": ",".join(sc.get("tags", [])),
                    **{f"check_{k}": v for k, v in checks.items()},
                    "passed": all(checks.values()),
                    "tool_calls": len(record["tool_calls"]),
                    "llm_calls": len(record["llm_calls"]),
                    "tokens": sum(usage),
                    "latency_ms": record["latency_ms"],
                }
            )
            rubric_rows.append(
                {
                    "scenario": sc["id"],
                    "turn": i + 1,
                    "user": turn["user"],
                    "answer": record["rendered_answer"],
                    **dict.fromkeys(RUBRIC_CRITERIA, ""),
                }
            )
        (out / "transcripts" / f"{sc['id']}.md").write_text(transcript(sc, records))

    turns = pd.DataFrame(turn_rows)
    turns.to_csv(out / "turns.csv", index=False)
    pd.DataFrame(rubric_rows).to_csv(out / "rubric_sheet.csv", index=False)
    metrics = summarize(turns)
    save_run(out, cfg, metrics, _summary(metrics, turns))
    return out


def summarize(turns: pd.DataFrame) -> dict:
    def rate(col: str) -> float | None:
        return float(turns[col].dropna().astype(bool).mean()) if col in turns else None

    by_scenario = turns.groupby("scenario")["passed"].all()
    return {
        "n_scenarios": int(len(by_scenario)),
        "n_turns": int(len(turns)),
        "scenario_success": float(by_scenario.mean()),
        "turn_success": float(turns["passed"].mean()),
        "tool_chain_accuracy": rate("check_tools"),
        "verifier_first_pass_rate": rate("check_verifier_first_pass"),
        "fallback_rate": 1 - (rate("check_no_fallback") or 0.0),
        "constraint_satisfaction": rate("check_constraints"),
        "state_persistence": rate("check_state"),
        "mean_tool_calls": float(turns["tool_calls"].mean()),
        "mean_tokens": float(turns["tokens"].mean()),
        "p50_latency_ms": float(np.percentile(turns["latency_ms"], 50)),
        "p95_latency_ms": float(np.percentile(turns["latency_ms"], 95)),
        "failed_turns": turns.loc[~turns["passed"], ["scenario", "turn"]].to_dict("records"),
    }


def _summary(m: dict, turns: pd.DataFrame) -> str:
    keys = [
        "scenario_success",
        "turn_success",
        "tool_chain_accuracy",
        "verifier_first_pass_rate",
        "fallback_rate",
        "constraint_satisfaction",
        "state_persistence",
        "mean_tool_calls",
        "mean_tokens",
        "p50_latency_ms",
        "p95_latency_ms",
    ]
    lines = [
        f"# Agent scenarios: {m['n_scenarios']} scenarios, {m['n_turns']} turns",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    lines += [
        f"| {k} | {m[k]:.3f} |" if isinstance(m[k], float) else f"| {k} | {m[k]} |" for k in keys
    ]
    check_cols = [c for c in turns.columns if c.startswith("check_")]
    lines += [
        "",
        "| Scenario | Turn | " + " | ".join(c[6:] for c in check_cols) + " |",
        "|---|---|" + "---|" * len(check_cols),
    ]
    for r in turns.itertuples():
        values = [getattr(r, c) for c in check_cols]
        cells = ["" if pd.isna(v) else ("ok" if v else "FAIL") for v in values]
        lines.append(f"| {r.scenario} | {r.turn} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Manual rubric: fill `rubric_sheet.csv` (0–2 per criterion), then run "
        "`movie-agent report-tables`.",
    ]
    return "\n".join(lines)
