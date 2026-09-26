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


def test_report_tables_from_saved_results(cfg, ds, embedder):
    run_offline(cfg, ds, "val", embedder=embedder)
    run_honesty(cfg, ds, None, embedder)
    assert latest_run(cfg.paths.results_dir, "offline_val") is not None
    out = run_report_tables(cfg)
    text = out.read_text()
    assert "## Offline ranking" in text and "## Honesty tests" in text
    assert (cfg.paths.results_dir / "figures" / "accuracy_by_system.png").exists()
