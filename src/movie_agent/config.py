"""Typed access to `configs/default.yaml` (design §11).

Every tunable lives in the YAML file; code reads it only through `Config`.
Relative paths are resolved against the project root (the parent of `configs/`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsConfig(_Section):
    data_dir: Path
    cache_dir: Path
    traces_dir: Path
    results_dir: Path


class DataConfig(_Section):
    test_frac: float
    val_frac: float
    min_test: int
    min_val: int
    liked_abs: float
    liked_rel: float
    short_plot_chars: int
    genre_exclude: list[str]
    tag_stoplist: list[str]


class StatsConfig(_Section):
    bayes_C: float
    genre_alpha: float


class ResolveConfig(_Section):
    found_min: float
    ambiguous_min: float
    min_gap: float
    subset_weight: float
    year_window: int
    max_candidates: int


class UserKNNConfig(_Section):
    k: int
    min_common: int
    gamma: int
    min_support: int


class EASEConfig(_Section):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    lambda_: float = Field(alias="lambda")
    lambda_grid: list[float]


class ContentConfig(_Section):
    model: str
    query_prefix: str
    chunk_tokens: int
    chunk_overlap: int
    batch_size: int
    excerpt_chars: int


class RankingConfig(_Section):
    top_n: int
    sparse_user_threshold: int
    query_min_ratings: int
    seed_weight_with_query: float
    weights: dict[str, dict[str, float]]


class ToolsConfig(_Section):
    default_k: int
    max_k: int
    plot_excerpt_chars: int
    top_tags: int
    profile_top_liked: int
    profile_bottom: int
    unexplored_share_ratio: float
    avoided_min_ratings: int
    avoided_max_affinity: float
    peer_examples: int
    explain_top_n: int
    ease_reasons_per_item: int


class ConfidenceConfig(_Section):
    peer_low_below: int
    peer_high_min: int
    user_low_below: int
    movie_low_below: int


class AgentConfig(_Section):
    provider: str
    model: str
    temperature: float
    max_tool_calls: int
    max_retries: int
    history_turns: int
    prompt_version: str
    request_timeout_s: float


class VerifierConfig(_Section):
    rating_tol: float
    pct_tol: float
    year_min: int
    year_max: int


class EvaluationConfig(_Section):
    k: int
    bootstrap_resamples: int
    ci: float
    head_frac: float
    sparse_movie_below: int
    qualitative_users: list[int]
    cf_weight_grid: list[float]
    search_top_k: int
    fidelity_pairs: int
    fidelity_min_drop: int
    fidelity_top: int
    perturbation_pairs: int
    perturbation_min_neighbours: int


class Config(_Section):
    seed: int
    paths: PathsConfig
    data: DataConfig
    stats: StatsConfig
    resolve: ResolveConfig
    user_knn: UserKNNConfig
    ease: EASEConfig
    content: ContentConfig
    ranking: RankingConfig
    tools: ToolsConfig
    confidence: ConfidenceConfig
    agent: AgentConfig
    verifier: VerifierConfig
    evaluation: EvaluationConfig

    def config_hash(self) -> str:
        """Short SHA-256 of the config values, recorded in traces and results."""
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]

    def with_overrides(self, **sections: dict[str, object]) -> Config:
        """Return a copy with some section fields replaced, e.g. `ease={"lambda_": 100}`."""
        data = self.model_dump()
        for name, fields in sections.items():
            data[name] = {**data[name], **fields}
        return Config.model_validate(data)


def load_config(path: Path | None = None) -> Config:
    """Load a config file and resolve its relative paths against the project root.

    Input: path to a YAML file (default `configs/default.yaml`).
    Output: a frozen `Config`.
    """
    path = path or DEFAULT_CONFIG
    raw = yaml.safe_load(path.read_text())
    root = path.resolve().parent.parent
    raw["paths"] = {k: _resolve(root, v) for k, v in raw["paths"].items()}
    return Config.model_validate(raw)


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p
