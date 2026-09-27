"""I6: title resolution passes the design §4.3 cases (on the tiny fixture)."""

import pytest

from movie_agent.catalog import Catalog, move_article, normalize, split_title, title_forms


@pytest.fixture
def catalog(ds, cfg):
    return Catalog(ds.movies, cfg.resolve)


def test_normalization_steps():
    assert normalize("Alien³") == "alien3"
    assert normalize("Amélie & Co.") == "amelie and co"
    assert split_title("Seven (a.k.a. Se7en)") == ("Seven", ["Se7en"])
    assert split_title("Postman, The (Postino, Il)") == ("Postman, The", ["Postino, Il"])
    assert move_article("Postman, The") == "The Postman"
    assert move_article("Avventura, L'") == "L'Avventura"
    assert title_forms("Postman, The (Postino, Il)") == [
        "the postman",
        "postman",
        "il postino",
        "postino",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Se7en", 4),
        ("Seven", 4),
        ("Il Postino", 3),
        ("The Postman", 3),
        ("Alien 3", 7),
        ("Alien", 5),
        ("Aliens", 6),
        ("the usual suspects", 10),
        ("Usual Suspects, The", 10),
        ("Sabrina 1995", 9),
        ("Sabrina (1954)", 8),
        ("Heat", 2),
        ("pulp fictoin", 15),
    ],
)
def test_found(catalog, text, expected):
    res = catalog.resolve(text)
    assert res.status == "found", res
    assert res.movie_id == expected


def test_remake_pair_is_ambiguous_without_year(catalog):
    res = catalog.resolve("Sabrina")
    assert res.status == "ambiguous"
    assert {c.movie_id for c in res.candidates[:2]} == {8, 9}


def test_year_argument_disambiguates(catalog):
    assert catalog.resolve("Sabrina", year=1954).movie_id == 8


def test_absent_movie_is_not_found(catalog):
    assert catalog.resolve("The Matrix").status == "not_found"
    assert catalog.resolve("").status == "not_found"


def test_display_title_moves_article(catalog):
    assert catalog.display_title(10) == "The Usual Suspects (1995)"
    assert catalog.display_title(3) == "The Postman (Postino, Il) (1994)"


def test_multiword_forms_ignore_single_word_titles(catalog):
    forms = catalog.multiword_forms()
    assert "pulp fiction" in forms and "usual suspects" in forms
    assert "heat" not in forms and "the postman" not in forms  # one word after the article


def test_short_title_does_not_match_inside_a_longer_query(catalog):
    # WRatio would score "heat" inside "heatwave" at 90 (found); plain ratio gives 67.
    assert catalog.resolve("Heatwave").status == "not_found"


def test_apostrophes_are_deleted_not_spaced():
    assert normalize("Ocean's Eleven") == "oceans eleven"
    assert normalize("Schindler’s List") == "schindlers list"


def test_trailing_number_is_a_year_only_if_that_resolves(cfg):
    import pandas as pd

    movies = pd.DataFrame(
        {
            "title": ["Death Race 2000", "Heat"],
            "year": [1975, 1995],
            "genres": [[], []],
            "plot": ["", ""],
        },
        index=pd.Index([1, 2], name="movieId"),
    )
    catalog = Catalog(movies, cfg.resolve)
    assert catalog.resolve("Death Race 2000").movie_id == 1
    assert catalog.resolve("Heat 1995").movie_id == 2
