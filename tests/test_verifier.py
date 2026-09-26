"""I5: the renderer rejects unknown placeholders; the verifier catches crafted bad answers."""

from pathlib import Path

import pytest
import yaml

from movie_agent.agent import UnknownPlaceholderError, render
from movie_agent.catalog import Catalog
from movie_agent.verifier import Verifier, VerifyContext, collect_movie_ids, collect_numbers

CASES = yaml.safe_load((Path(__file__).parent / "verifier_cases" / "cases.yaml").read_text())


@pytest.fixture
def verifier(ds, cfg):
    return Verifier(Catalog(ds.movies, cfg.resolve), cfg.verifier)


def context(exclude=("Horror",)):
    return VerifyContext(
        session_movie_ids={2, 4, 5, 10, 15},
        recent_recommended_ids={4, 10},
        seen_ids={2, 5, 15},
        exclude_genres=set(exclude),
        recent_numbers=[4.25, 12, 0.46, 3.9, 7],
    )


@pytest.mark.parametrize("case", CASES["bad"], ids=lambda c: c["id"])
def test_bad_answers_are_caught_by_the_expected_rule(verifier, case):
    ctx = context(case.get("exclude_genres", ["Horror"]))
    result = verifier.verify(case["answer"], case["recommended"], ctx)
    assert not result.passed
    assert case["rule"] in {v.rule for v in result.violations}, result.report()


@pytest.mark.parametrize("case", CASES["good"], ids=lambda c: c["id"])
def test_good_answers_pass(verifier, case):
    result = verifier.verify(case["answer"], case["recommended"], context())
    assert result.passed, result.report()


def test_renderer_substitutes_titles_and_rejects_unknown_ids(ds, cfg):
    catalog = Catalog(ds.movies, cfg.resolve)
    assert render("Try [[m:10]].", catalog) == "Try **The Usual Suspects (1995)**."
    with pytest.raises(UnknownPlaceholderError):
        render("Try [[m:424242]].", catalog)


def test_collectors_walk_nested_outputs():
    data = {"items": [{"movie_id": 3, "score": 0.5, "note": "rated 4.5 by 12 users"}], "n": 2}
    assert collect_movie_ids(data) == {3}
    assert sorted(collect_numbers(data)) == [0.5, 2.0, 3.0, 4.5, 12.0]
