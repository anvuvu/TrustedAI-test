"""JSONL trace writer: one line per turn (design §8.1)."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from movie_agent.config import PROJECT_ROOT, Config


def git_commit() -> str:
    """Current commit hash, with a `-dirty` suffix if the tree has changes; "unknown" if no git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{commit}-dirty" if dirty else commit
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def versions(cfg: Config, embedding_model: str) -> dict[str, str]:
    """Everything needed to reproduce a turn, recorded in every trace line and result."""
    return {
        "git_commit": git_commit(),
        "config_hash": cfg.config_hash(),
        "prompt_version": cfg.agent.prompt_version,
        "llm_model": cfg.agent.model,
        "embedding_model": embedding_model,
    }


def new_session_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


class TraceWriter:
    """Appends one JSON object per turn to `<traces_dir>/<session_id>.jsonl`."""

    def __init__(self, traces_dir: Path, session_id: str) -> None:
        self.session_id = session_id
        self.path = traces_dir / f"{session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, default=_json_default, ensure_ascii=False) + "\n")


def read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _json_default(value: object) -> object:
    if isinstance(value, np.integer | np.floating | np.bool_):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)
