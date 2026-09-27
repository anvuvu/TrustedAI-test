"""Shared fixtures: the tiny dataset, a test config and a hashing embedder (no network)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest

from movie_agent.config import Config, load_config

TINY_DIR = Path(__file__).parent / "fixtures" / "tiny"


class HashingEmbedder:
    """Deterministic bag-of-words embedder for tests: hashed word counts, L2-normalized."""

    name = "hashing-test"

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def count_tokens(self, texts: list[str]) -> list[int]:
        return [len(t.split()) for t in texts]

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[a-z]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                out[row, h % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1.0, norms)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    """Default config pointed at the tiny fixture, with thresholds sized for it."""
    base = load_config()
    return base.with_overrides(
        paths={
            "data_dir": TINY_DIR,
            "cache_dir": tmp_path / "cache",
            "traces_dir": tmp_path / "traces",
            "results_dir": tmp_path / "results",
        },
        user_knn={"min_common": 3, "k": 5},
        content={"chunk_tokens": 20, "chunk_overlap": 5},
    )


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture
def ds(cfg: Config):
    from movie_agent.data import load_dataset

    return load_dataset(cfg.paths.data_dir)


@pytest.fixture
def ranker(cfg: Config, ds, embedder: HashingEmbedder):
    from movie_agent.ranking import build_ranker

    return build_ranker(cfg, ds, embedder=embedder, ease_lambda=1.0)


@pytest.fixture
def toolbox(cfg: Config, ds, ranker):
    from movie_agent.tools import Toolbox

    return Toolbox(ranker, ds.tags, cfg)
