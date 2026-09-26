"""Signal engines: EASE, UserKNN and chunked plot embeddings (design §5.1).

Engines are fitted on an explicit ratings frame (train, train + val or all data), so the
same code serves evaluation and the demo without leakage.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
import pandas as pd
from scipy import sparse

from movie_agent.catalog import move_article, split_title
from movie_agent.config import ContentConfig, UserKNNConfig

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


def interaction_matrix(
    ratings: pd.DataFrame, user_ids: np.ndarray, movie_ids: np.ndarray, values: np.ndarray
) -> sparse.csr_matrix:
    """Sparse users x movies matrix with `values` at each rated (user, movie) cell."""
    rows = np.searchsorted(user_ids, ratings["userId"].to_numpy())
    cols = np.searchsorted(movie_ids, ratings["movieId"].to_numpy())
    shape = (len(user_ids), len(movie_ids))
    return sparse.csr_matrix((values, (rows, cols)), shape=shape)


# ---------------------------------------------------------------------------
# EASE (Steck, 2019)
# ---------------------------------------------------------------------------


class EASE:
    """Linear item-item model with a closed-form fit.

    `B[j, i]` is the weight with which having rated movie j pushes up movie i.
    Scores for a history H are `sum_{j in H} B[j, :]` (unitless, comparable within a user).
    """

    def __init__(self, movie_ids: np.ndarray, lam: float) -> None:
        self.movie_ids = movie_ids
        self.lam = lam
        self.B = np.zeros((0, 0), dtype=np.float32)
        self.has_signal = np.zeros(len(movie_ids), dtype=bool)

    def fit(self, ratings: pd.DataFrame) -> EASE:
        """Fit on binary interactions (1 if rated). Movies without ratings get zero columns."""
        users = np.unique(ratings["userId"].to_numpy())
        x = interaction_matrix(ratings, users, self.movie_ids, np.ones(len(ratings)))
        gram = (x.T @ x).toarray().astype(np.float64)
        gram[np.diag_indices_from(gram)] += self.lam
        p = np.linalg.inv(gram)
        b = -p / np.diag(p)[None, :]
        np.fill_diagonal(b, 0.0)
        self.B = b.astype(np.float32)
        self.has_signal = np.asarray(x.sum(axis=0)).ravel() > 0
        return self

    def positions(self, movie_ids: list[int] | np.ndarray) -> np.ndarray:
        return np.searchsorted(self.movie_ids, np.asarray(movie_ids, dtype=np.int64))

    def scores(self, history_ids: list[int] | np.ndarray) -> np.ndarray:
        """EASE score of every catalog movie for a set of rated movies."""
        pos = self.positions(history_ids)
        if len(pos) == 0:
            return np.zeros(len(self.movie_ids), dtype=np.float32)
        return self.B[pos].sum(axis=0)

    def contributions(self, history_ids: list[int] | np.ndarray, movie_id: int) -> np.ndarray:
        """Contribution of each history movie to `movie_id`'s score (same order as input)."""
        target = self.positions([movie_id])[0]
        return self.B[self.positions(history_ids), target]


# ---------------------------------------------------------------------------
# UserKNN
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Neighbour:
    user_id: int
    similarity: float  # significance-weighted Pearson-style correlation, in [-1, 1]
    n_common: int  # movies rated by both users


class UserKNN:
    """User-user similarity on mean-centred ratings over co-rated movies (design §5.1)."""

    def __init__(self, movie_ids: np.ndarray, cfg: UserKNNConfig) -> None:
        self.movie_ids = movie_ids
        self.cfg = cfg

    def fit(self, ratings: pd.DataFrame) -> UserKNN:
        self.user_ids = np.unique(ratings["userId"].to_numpy())
        means = ratings.groupby("userId")["rating"].mean()
        self.user_means = means.reindex(self.user_ids).to_numpy()
        row = np.searchsorted(self.user_ids, ratings["userId"].to_numpy())
        centred = ratings["rating"].to_numpy() - self.user_means[row]
        ones = np.ones(len(ratings))
        self.centred = interaction_matrix(ratings, self.user_ids, self.movie_ids, centred)
        self.mask = interaction_matrix(ratings, self.user_ids, self.movie_ids, ones)
        r, m = self.centred.toarray(), self.mask.toarray()
        self.raw = interaction_matrix(
            ratings, self.user_ids, self.movie_ids, ratings["rating"].to_numpy()
        )

        numerator = r @ r.T
        sq = r**2
        denominator = np.sqrt((sq @ m.T) * (m @ sq.T))
        n_common = m @ m.T
        ok = (denominator > 0) & (n_common >= self.cfg.min_common)
        sim = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=ok)
        sim *= np.minimum(n_common, self.cfg.gamma) / self.cfg.gamma
        np.fill_diagonal(sim, 0.0)
        self.similarity = sim
        self.n_common = n_common.astype(int)
        return self

    def row_of(self, user_id: int) -> int | None:
        idx = int(np.searchsorted(self.user_ids, user_id))
        return idx if idx < len(self.user_ids) and self.user_ids[idx] == user_id else None

    def neighbours(self, user_id: int, k: int | None = None) -> list[Neighbour]:
        """Top-k users with positive similarity, most similar first (ties by userId)."""
        row = self.row_of(user_id)
        if row is None:
            return []
        sims = self.similarity[row]
        candidates = np.flatnonzero(sims > 0)
        order = candidates[np.lexsort((self.user_ids[candidates], -sims[candidates]))]
        top = order[: k or self.cfg.k]
        return [
            Neighbour(int(self.user_ids[j]), float(sims[j]), int(self.n_common[row, j]))
            for j in top
        ]

    def rating(self, user_id: int, movie_id: int) -> float | None:
        """The user's rating of the movie in the fitted data, or None."""
        row = self.row_of(user_id)
        col = int(np.searchsorted(self.movie_ids, movie_id))
        if row is None or col >= len(self.movie_ids) or self.movie_ids[col] != movie_id:
            return None
        return float(self.raw[row, col]) if self.mask[row, col] else None

    def user_mean(self, user_id: int) -> float | None:
        row = self.row_of(user_id)
        return None if row is None else float(self.user_means[row])

    def score_all(self) -> tuple[np.ndarray, np.ndarray]:
        """UserKNN-as-recommender scores for every fitted user (used by offline evaluation).

        score(u, i) = sum_v s_uv * centred_vi / sum_v |s_uv| over neighbours v who rated i.
        Output: (scores users x movies, NaN where support < min_support; support counts).
        """
        weights = np.zeros_like(self.similarity)
        for row, user_id in enumerate(self.user_ids):
            for n in self.neighbours(int(user_id)):
                weights[row, self.row_of(n.user_id)] = n.similarity
        w = sparse.csr_matrix(weights)
        numerator = (w @ self.centred).toarray()
        denominator = (abs(w) @ self.mask).toarray()
        support = ((w > 0).astype(float) @ self.mask).toarray()
        scores = np.divide(
            numerator, denominator, out=np.full_like(numerator, np.nan), where=denominator > 0
        )
        scores[support < self.cfg.min_support] = np.nan
        return scores, support


# ---------------------------------------------------------------------------
# Plot embeddings
# ---------------------------------------------------------------------------


class Embedder(Protocol):
    """Text embedder. Vectors are L2-normalized rows."""

    name: str

    def count_tokens(self, texts: list[str]) -> list[int]: ...

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Local sentence-transformers model (default BAAI/bge-small-en-v1.5), loaded lazily."""

    def __init__(self, cfg: ContentConfig) -> None:
        self.cfg = cfg
        self.name = cfg.model
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.cfg.model)
        return self._model

    def count_tokens(self, texts: list[str]) -> list[int]:
        ids = self.model.tokenizer(texts, add_special_tokens=False)["input_ids"]
        return [len(x) for x in ids]

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if query:
            texts = [self.cfg.query_prefix + t for t in texts]
        vectors = self.model.encode(
            texts, batch_size=self.cfg.batch_size, normalize_embeddings=True
        )
        return np.asarray(vectors, dtype=np.float32)


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def pack_chunks(sentences: list[str], lengths: list[int], size: int, overlap: int) -> list[str]:
    """Pack whole sentences into chunks of at most `size` tokens.

    Consecutive chunks share trailing sentences worth at most `overlap` tokens. A sentence
    longer than `size` forms its own chunk (the model truncates it).
    """
    chunks: list[str] = []
    start = 0
    while start < len(sentences):
        end, total = start, 0
        while end < len(sentences) and (end == start or total + lengths[end] <= size):
            total += lengths[end]
            end += 1
        chunks.append(" ".join(sentences[start:end]))
        if end >= len(sentences):
            break
        back, carried = end, 0
        while back - 1 > start and carried + lengths[back - 1] <= overlap:
            back -= 1
            carried += lengths[back]
        start = back
    return chunks


@dataclass
class ContentIndex:
    """Chunk and movie vectors, aligned with the catalog order of `movie_ids`."""

    movie_ids: np.ndarray  # (n_movies,)
    chunk_vecs: np.ndarray  # (n_chunks, dim), grouped by movie in catalog order
    chunk_owner: np.ndarray  # (n_chunks,) position of the owning movie
    chunk_texts: list[str]  # raw chunk text, for evidence excerpts
    movie_vecs: np.ndarray  # (n_movies, dim), normalized mean of chunk vectors

    def position(self, movie_id: int) -> int:
        return int(np.searchsorted(self.movie_ids, movie_id))

    def query_similarity(self, query_vec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Max-chunk cosine similarity per movie, and the index of that best chunk."""
        sims = self.chunk_vecs @ query_vec
        order = np.lexsort((-sims, self.chunk_owner))
        first = np.r_[0, np.flatnonzero(np.diff(self.chunk_owner[order])) + 1]
        best_chunk = order[first]
        return sims[best_chunk], best_chunk

    def movie_similarity(self, movie_ids: list[int]) -> np.ndarray:
        """Max cosine between each catalog movie and any of `movie_ids` (movie vectors)."""
        if not movie_ids:
            return np.zeros(len(self.movie_ids), dtype=np.float32)
        pos = np.searchsorted(self.movie_ids, np.asarray(movie_ids))
        return (self.movie_vecs @ self.movie_vecs[pos].T).max(axis=1)

    def best_chunk_against(self, movie_id: int, target_vec: np.ndarray) -> int:
        """Index of the chunk of `movie_id` most similar to `target_vec`."""
        chunks = np.flatnonzero(self.chunk_owner == self.position(movie_id))
        return int(chunks[np.argmax(self.chunk_vecs[chunks] @ target_vec)])

    def profile(self, history: dict[int, float], liked_abs: float) -> np.ndarray | None:
        """User content profile: liked movie vectors weighted by positive centred rating.

        Falls back to equal weights on movies rated >= `liked_abs` when no rating is above
        the user's mean (e.g. a user who rated everything 5.0). None if nothing is liked.
        """
        if not history:
            return None
        ids = np.fromiter(history.keys(), dtype=np.int64)
        ratings = np.fromiter(history.values(), dtype=np.float64)
        weights = np.maximum(ratings - ratings.mean(), 0.0)
        if weights.sum() == 0:
            weights = (ratings >= liked_abs).astype(np.float64)
        if weights.sum() == 0:
            return None
        vec = weights @ self.movie_vecs[np.searchsorted(self.movie_ids, ids)]
        norm = np.linalg.norm(vec)
        return (vec / norm).astype(np.float32) if norm > 0 else None


def build_content_index(
    movies: pd.DataFrame,
    embedder: Embedder,
    cfg: ContentConfig,
    cache_dir: Path,
    genre_exclude: list[str],
) -> ContentIndex:
    """Chunk every plot, embed the chunks and cache the result in `cache_dir`.

    Each chunk is embedded with a "Title. Genres." prefix; the stored text omits it.
    The cache key covers the model name, chunk settings and the movie table contents.
    """
    key = _cache_key(movies, embedder.name, cfg)
    vec_path = cache_dir / f"content_{key}.npz"
    text_path = cache_dir / f"content_{key}.json"
    movie_ids = movies.index.to_numpy(dtype=np.int64)
    if vec_path.exists() and text_path.exists():
        arrays = np.load(vec_path)
        texts = json.loads(text_path.read_text())
        return ContentIndex(
            movie_ids, arrays["chunk_vecs"], arrays["chunk_owner"], texts, arrays["movie_vecs"]
        )

    sentences = [split_sentences(p) or [p] for p in movies["plot"]]
    flat = [s for group in sentences for s in group]
    flat_lengths = embedder.count_tokens(flat)
    texts, owners, prefixed = [], [], []
    cursor = 0
    for pos, (title, genres, group) in enumerate(
        zip(movies["title"], movies["genres"], sentences, strict=True)
    ):
        lengths = flat_lengths[cursor : cursor + len(group)]
        cursor += len(group)
        prefix = _chunk_prefix(title, genres, genre_exclude)
        for chunk in pack_chunks(group, lengths, cfg.chunk_tokens, cfg.chunk_overlap):
            texts.append(chunk)
            owners.append(pos)
            prefixed.append(f"{prefix} {chunk}")
    chunk_vecs = embedder.encode(prefixed).astype(np.float32)
    chunk_owner = np.asarray(owners, dtype=np.int64)
    sums = np.zeros((len(movie_ids), chunk_vecs.shape[1]), dtype=np.float64)
    np.add.at(sums, chunk_owner, chunk_vecs)
    movie_vecs = (sums / np.linalg.norm(sums, axis=1, keepdims=True)).astype(np.float32)

    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(vec_path, chunk_vecs=chunk_vecs, chunk_owner=chunk_owner, movie_vecs=movie_vecs)
    text_path.write_text(json.dumps(texts))
    return ContentIndex(movie_ids, chunk_vecs, chunk_owner, texts, movie_vecs)


def _chunk_prefix(title: str, genres: list[str], genre_exclude: list[str]) -> str:
    main, _ = split_title(title)
    shown = [g for g in genres if g not in genre_exclude]
    return f"{move_article(main)}. {', '.join(shown)}." if shown else f"{move_article(main)}."


def _cache_key(movies: pd.DataFrame, model: str, cfg: ContentConfig) -> str:
    digest = hashlib.sha256()
    digest.update(f"{model}|{cfg.chunk_tokens}|{cfg.chunk_overlap}".encode())
    table = movies[["title", "genres", "plot"]].astype(str)
    digest.update(pd.util.hash_pandas_object(table, index=True).to_numpy().tobytes())
    return digest.hexdigest()[:16]
