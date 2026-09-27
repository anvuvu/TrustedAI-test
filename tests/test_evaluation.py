"""I1 (no leakage) and end-to-end runs of every evaluation script on the tiny fixture."""

import json

import numpy as np
import pandas as pd
import pytest
import yaml

from movie_agent.data import temporal_split
from movie_agent.evaluation.honesty import perturb, run_honesty
from movie_agent.evaluation.offline import fit_and_holdout, recall_ndcg, run_offline
from movie_agent.evaluation.report_tables import latest_run, run_report_tables
from movie_agent.evaluation.results import bootstrap_ci, new_results_dir
from movie_agent.evaluation.scenarios import run_scenarios
from movie_agent.evaluation.search import run_search
from movie_agent.ranking import build_ranker
from tests.test_agent import ScriptedLLM


def pairs(frame):
    return set(zip(frame.userId, frame.movieId, strict=True))


def test_i1_evaluation_fits_never_see_heldout_ratings(cfg, ds, embedder):
    split = temporal_split(ds.ratings, cfg)
    for name, heldout_parts in (("val", [split.val, split.test]), ("test", [split.test])):
        fit, holdout = fit_and_holdout(split, name)
        ranker = build_ranker(cfg, ds, fit, embedder=embedder)
        seen = {(u, m) for u, h in ranker.histories.items() for m in h}
        for part in heldout_parts:
            assert not seen & pairs(part)
        assert ranker.stats.movie["n"].sum() == len(fit)
        assert int(ranker.user_knn.mask.sum()) == len(fit)
        counts = fit.groupby("movieId").size().reindex(ds.movies.index).fillna(0)
        assert np.array_equal(ranker.ease.has_signal, counts.to_numpy() > 0)


def test_recall_ndcg_by_hand():
    recall, ndcg = recall_ndcg([1, 2, 3], {2, 9}, k=3)
    assert recall == 0.5
    assert abs(ndcg - (1 / np.log2(3)) / (1 + 1 / np.log2(3))) < 1e-12


def test_bootstrap_ci_brackets_the_mean(cfg):
    ci = bootstrap_ci(np.array([0.0, 1.0] * 50), cfg, np.random.default_rng(0))
    assert ci["lo"] <= ci["mean"] == 0.5 <= ci["hi"]


def test_results_dirs_are_never_overwritten(cfg):
    assert new_results_dir(cfg, "x") != new_results_dir(cfg, "x")


def test_offline_val_runs_and_test_requires_final(cfg, ds, embedder):
    out = run_offline(cfg, ds, "val", embedder=embedder)
    metrics = json.loads((out / "metrics.json").read_text())
    assert set(metrics["systems"]) == {
        "MostPopular",
        "TopBayesian",
        "UserKNN",
        "EASE",
        "ContentProfile",
        "Blend",
    }
    assert set(metrics["sweeps"]["ease_lambda"]) == {str(x) for x in cfg.ease.lambda_grid}
    assert (out / "summary.md").exists() and (out / "config.yaml").exists()
    with pytest.raises(ValueError):
        run_offline(cfg, ds, "test", final=False, embedder=embedder)


def test_search_writes_sheet_then_scores_grades(cfg, ds, embedder, tmp_path):
    queries = tmp_path / "q.yaml"
    queries.write_text(yaml.safe_dump({"queries": [{"id": "q1", "text": "alien creature"}]}))
    sheet = tmp_path / "judgments.csv"
    run_search(cfg, ds, embedder, queries, sheet)
    grades = pd.read_csv(sheet)
    assert grades["grade"].isna().all() and len(grades) >= 3
    grades["grade"] = 2
    grades.to_csv(sheet, index=False)
    out = run_search(cfg, ds, embedder, queries, sheet)
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["variants"]["plain"]["p_at_k"]["mean"] == 1.0


def test_scenarios_run_with_a_scripted_llm(cfg, ds, embedder, tmp_path):
    path = tmp_path / "scenarios.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenarios": [
                    {
                        "id": "s1",
                        "user_id": 1,
                        "turns": [
                            {
                                "user": "Profile?",
                                "expect": {"tools": ["get_user_profile"], "recommends": False},
                            }
                        ],
                    }
                ]
            }
        )
    )

    def factory():
        return ScriptedLLM(
            [
                [("get_user_profile", {"user_id": 1})],
                [("final_answer", {"answer": "You have rated movies."})],
            ]
        )

    out = run_scenarios(cfg, ds, factory, embedder, path)
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["scenario_success"] == 1.0
    assert (out / "transcripts" / "s1.md").exists() and (out / "rubric_sheet.csv").exists()


def test_honesty_engine_part_and_perturbation(cfg, ds, embedder):
    flipped = perturb(ds.ratings, 2, [1, 2])
    heat = flipped[flipped.movieId == 2].set_index("userId")["rating"]
    assert heat[1] == 0.5 and heat[2] == 1.5 and heat[5] == 3.0
    out = run_honesty(cfg, ds, None, embedder)
    fidelity = json.loads((out / "metrics.json").read_text())["fidelity"]
    assert fidelity["n_pairs"] == 6


def test_report_tables_from_saved_results(cfg, ds, embedder, tmp_path):
    run_offline(cfg, ds, "val", embedder=embedder)
    run_honesty(cfg, ds, None, embedder)
    assert latest_run(cfg.paths.results_dir, "offline_val") is not None
    # a temporary report: the real REPORT.md must never receive fixture tables
    report = tmp_path / "REPORT.md"
    report.write_text("<!-- table:offline -->\nold\n<!-- /table:offline -->\n")
    out = run_report_tables(cfg, reports=(report,))
    text = out.read_text()
    assert "## Offline ranking" in text and "## Honesty tests" in text
    assert (cfg.paths.results_dir / "figures" / "accuracy_by_system.png").exists()
    assert "old" not in report.read_text() and "| EASE |" in report.read_text()


def test_search_score_is_nan_not_zero_when_ungraded(cfg):
    from movie_agent.evaluation.search import score

    results = pd.DataFrame(
        {
            "variant": ["v"] * 2,
            "query_id": ["q"] * 2,
            "movie_id": [1, 2],
            "bayes_avg": [3.0, 3.0],
            "n_ratings": [5, 5],
        }
    )
    judgments = pd.DataFrame({"query_id": ["q", "q"], "movie_id": [1, 2], "grade": [None, None]})
    out = score(results, judgments, cfg)["v"]
    assert np.isnan(out["p_at_k"]["mean"]) and out["ungraded"] == 2


def test_title_echo_detects_repeated_title_or_year(ds, cfg):
    from movie_agent.catalog import Catalog
    from movie_agent.evaluation.scenarios import title_echoes

    catalog = Catalog(ds.movies, cfg.resolve)
    answer = "Try [[m:5]] (Alien), [[m:2]] (1995) and [[m:10]] (a crime classic)."
    assert title_echoes(answer, catalog) == ["[[m:5]] (Alien)", "[[m:2]] (1995)"]


def test_refresh_report_replaces_only_marked_blocks():
    from movie_agent.evaluation.report_tables import refresh_report

    text = (
        "Intro\n<!-- table:x -->\nold\n<!-- /table:x -->\nkeep <!-- table:y -->old<!-- /table:y -->"
    )
    out = refresh_report(text, {"x": ["## Title `run`", "", "| a |", "|---|"]})
    assert "old\n<!-- /table:x" not in out and "*Source: Title `run`*" in out and "| a |" in out
    assert "<!-- table:y -->old<!-- /table:y -->" in out and out.startswith("Intro")


def test_agent_runs_table_names_the_model_of_each_run(tmp_path):
    from movie_agent.evaluation.report_tables import _agent_runs_table

    for name, model in (("2026-01-01_agent", "model-a"), ("2026-01-02_agent", "model-b")):
        _fake_agent_run(tmp_path, name, model, verifier_first_pass_rate=0.5)
    rows = [line for line in _agent_runs_table(tmp_path) if line.startswith("| `")]
    assert [line.split(" | ")[1] for line in rows] == ["model-a", "model-b"]


def _fake_agent_run(results, name, model, **metrics):
    import yaml

    run = results / name
    run.mkdir(parents=True)
    (run / "metrics.json").write_text(json.dumps({"meta": {"git_commit": "abc"}, **metrics}))
    agent = {"model": model, "prompt_version": "system_v2"}
    (run / "config.yaml").write_text(yaml.safe_dump({"agent": agent}))
    return run


def test_latest_llm_run_is_chosen_for_the_configured_model(tmp_path):
    base = _fake_agent_run(tmp_path, "2026-01-01_agent", "model-a")
    _fake_agent_run(tmp_path, "2026-01-02_agent", "model-b")
    assert latest_run(tmp_path, "agent", "model-a") == base
    assert latest_run(tmp_path, "agent").name == "2026-01-02_agent"


def test_model_swap_table_pairs_turns_and_signs_the_difference(cfg, tmp_path):
    from movie_agent.evaluation.report_tables import _model_swap_table

    keys = dict.fromkeys(
        [
            "scenario_success",
            "verifier_first_pass_rate",
            "fallback_rate",
            "tool_chain_accuracy",
            "mean_tool_calls",
            "p50_latency_ms",
            "p95_latency_ms",
        ],
        0.5,
    )
    results, grading = tmp_path / "results", tmp_path / "grading"
    _fake_agent_run(results, "2026-01-01_agent", cfg.agent.model, **keys)
    _fake_agent_run(results, "2026-01-02_agent", "other-model", **keys)
    grading.mkdir()
    rows = []
    for turn, (mine, theirs) in enumerate([(2, 1), (2, 2), (1, 0)], start=1):
        for run, model, g in (
            ("2026-01-01_agent", cfg.agent.model, mine),
            ("2026-01-02_agent", "other-model", theirs),
        ):
            rows.append(
                {"run": run, "model": model, "scenario": "s", "turn": turn, "grounded": g}
                | {"relevant": 2, "specific": 2, "honest": 2}
            )
    pd.DataFrame(rows).to_csv(grading / "rubric_grades_blind_with_rationale.csv", index=False)
    table = "\n".join(_model_swap_table(cfg, grading, results))
    assert "other-model vs " + cfg.agent.model in table
    grounded = next(line for line in table.splitlines() if "rubric grounded" in line)
    assert "| 1.00 | 1.67 | -0.67" in grounded and "0 / 1 / 2" in grounded
    assert _model_swap_table(cfg, grading, tmp_path / "empty") == []


def test_vietnamese_translations_stay_in_sync_with_the_english_documents():
    """REPORT.vi.md carries the same generated tables as REPORT.md; each pair links to the other."""
    from movie_agent.config import PROJECT_ROOT
    from movie_agent.evaluation.report_tables import _MARKER

    def blocks(text):
        return {m.group(2): m.group(3).strip() for m in _MARKER.finditer(text)}

    for en, vi in (("REPORT.md", "REPORT.vi.md"), ("README.md", "README.vi.md")):
        en_text, vi_text = (PROJECT_ROOT / en).read_text(), (PROJECT_ROOT / vi).read_text()
        assert blocks(vi_text) == blocks(en_text)
        assert f"]({vi})" in en_text and f"]({en})" in vi_text
