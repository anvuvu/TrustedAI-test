"""Results directories and bootstrap helpers shared by the evaluation scripts (design §9.7)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from movie_agent.config import Config
from movie_agent.trace import git_commit


def new_results_dir(cfg: Config, name: str) -> Path:
    """`<results_dir>/<YYYY-MM-DD>_<name>/`, with a numeric suffix so nothing is overwritten."""
    base = cfg.paths.results_dir / f"{date.today():%Y-%m-%d}_{name}"
    path, n = base, 2
    while path.exists():
        path = base.with_name(f"{base.name}_{n}")
        n += 1
    path.mkdir(parents=True)
    return path


def save_run(path: Path, cfg: Config, metrics: dict[str, Any], summary_md: str) -> None:
    """Write metrics.json, summary.md, the config snapshot and the git commit."""
    meta = {"git_commit": git_commit(), "config_hash": cfg.config_hash()}
    (path / "metrics.json").write_text(
        json.dumps({"meta": meta, **metrics}, indent=2, default=_json_default) + "\n"
    )
    (path / "summary.md").write_text(summary_md.rstrip() + "\n")
    (path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False))
    (path / "git_commit.txt").write_text(meta["git_commit"] + "\n")


def bootstrap_ci(values: np.ndarray, cfg: Config, rng: np.random.Generator) -> dict[str, float]:
    """Mean with a percentile bootstrap CI over users (resampling rows of `values`)."""
    values = np.asarray(values, dtype=np.float64)
    if len(values) == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    idx = rng.integers(0, len(values), size=(cfg.evaluation.bootstrap_resamples, len(values)))
    means = values[idx].mean(axis=1)
    alpha = (1 - cfg.evaluation.ci) / 2
    return {
        "mean": float(values.mean()),
        "lo": float(np.quantile(means, alpha)),
        "hi": float(np.quantile(means, 1 - alpha)),
        "n": int(len(values)),
    }


def paired_bootstrap(a: np.ndarray, b: np.ndarray, cfg: Config, rng: np.random.Generator) -> dict:
    """CI of mean(a - b) over the same users; `significant` is False if the CI contains 0."""
    ci = bootstrap_ci(np.asarray(a) - np.asarray(b), cfg, rng)
    return {**ci, "significant": not (ci["lo"] <= 0 <= ci["hi"])}


def fmt_ci(ci: dict[str, float], digits: int = 3) -> str:
    return f"{ci['mean']:.{digits}f} [{ci['lo']:.{digits}f}, {ci['hi']:.{digits}f}]"


def _json_default(value: object) -> object:
    if isinstance(value, np.integer | np.floating | np.bool_):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)}")
