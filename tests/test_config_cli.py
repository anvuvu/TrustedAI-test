from typer.testing import CliRunner

from movie_agent.cli import _read_message, app
from movie_agent.config import DEFAULT_CONFIG, load_config


def test_default_config_loads_and_resolves_paths():
    cfg = load_config()
    assert cfg.paths.data_dir.is_absolute()
    assert cfg.paths.data_dir.parts[-3:] == ("Exam", "data", "ml-latest-small-filtered")
    assert cfg.ease.lambda_ == 500
    assert cfg.agent.model != "<set-me>"
    assert DEFAULT_CONFIG.exists()


def test_config_hash_is_stable_and_sensitive():
    cfg = load_config()
    assert cfg.config_hash() == load_config().config_hash()
    assert cfg.with_overrides(ease={"lambda_": 100}).config_hash() != cfg.config_hash()


def test_cli_help_lists_every_design_command():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["validate", "chat", "why-not", "eval", "report-tables"]:
        assert name in result.output
    result = CliRunner().invoke(app, ["eval", "--help"])
    for name in ["offline", "search", "agent", "honesty"]:
        assert name in result.output


def test_chat_input_drops_bytes_left_by_a_partial_backspace(monkeypatch):
    # "về" typed as "vê", then a backspace that removed one byte of "ê" (C3 AA) before "ề".
    # stdin decodes the stray C3 byte to "\udcc3", which the OpenAI client cannot encode.
    raw = b"tim phim v\xc3\xe1\xbb\x81 giang sinh ".decode("utf-8", "surrogateescape")
    monkeypatch.setattr("builtins.input", lambda prompt: raw)
    message = _read_message("you> ")
    assert message == "tim phim về giang sinh"
    message.encode("utf-8")
