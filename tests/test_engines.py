import numpy as np

from movie_agent.engines import EASE, UserKNN, build_content_index, pack_chunks
from tests.conftest import HashingEmbedder


def test_ease_matches_closed_form_on_tiny_matrix(ds):
    ids = ds.movies.index.to_numpy()
    ease = EASE(ids, lam=2.0).fit(ds.ratings)
    users = np.unique(ds.ratings.userId)
    x = np.zeros((len(users), len(ids)))
    for u, m in ds.ratings[["userId", "movieId"]].to_numpy():
        x[np.searchsorted(users, u), np.searchsorted(ids, m)] = 1
    p = np.linalg.inv(x.T @ x + 2.0 * np.eye(len(ids)))
    b = -p / np.diag(p)
    np.fill_diagonal(b, 0)
    assert np.allclose(ease.B, b, atol=1e-5)
    assert not ease.has_signal[np.searchsorted(ids, 14)]  # movie 14 has no ratings
    hist = [2, 5, 6]
    assert np.allclose(
        ease.contributions(hist, 15).sum(), ease.scores(hist)[np.searchsorted(ids, 15)]
    )


def test_user_knn_similarity_by_hand(ds, cfg):
    knn = UserKNN(ds.movies.index.to_numpy(), cfg.user_knn).fit(ds.ratings)
    r = ds.ratings
    u1, u2 = (
        r[r.userId == 1].set_index("movieId").rating,
        r[r.userId == 2].set_index("movieId").rating,
    )
    common = u1.index.intersection(u2.index)  # 2, 5, 6, 7, 10, 15
    a, b = u1[common] - u1.mean(), u2[common] - u2.mean()
    pearson = (a * b).sum() / np.sqrt((a**2).sum() * (b**2).sum())
    expected = pearson * min(len(common), cfg.user_knn.gamma) / cfg.user_knn.gamma
    neighbours = {n.user_id: n for n in knn.neighbours(1)}
    assert neighbours[2].n_common == len(common) == 6
    assert abs(neighbours[2].similarity - expected) < 1e-9
    assert knn.neighbours(4) == []  # zero-variance user: no defined correlation
    assert knn.rating(2, 12) == 4.0 and knn.rating(1, 12) is None


def test_pack_chunks_overlap_and_long_sentences():
    sentences = ["a", "b", "c", "d"]
    assert pack_chunks(sentences, [4, 4, 4, 4], size=8, overlap=4) == ["a b", "b c", "c d"]
    assert pack_chunks(sentences, [4, 4, 4, 4], size=8, overlap=0) == ["a b", "c d"]
    assert pack_chunks(["long", "x"], [20, 1], size=8, overlap=2) == ["long", "x"]


def test_content_index_query_profile_and_cache(ds, cfg):
    embedder = HashingEmbedder()
    args = (ds.movies, embedder, cfg.content, cfg.paths.cache_dir, cfg.data.genre_exclude)
    index = build_content_index(*args)
    assert len(index.chunk_texts) > len(ds.movies)  # some plots span several chunks
    sims, best = index.query_similarity(embedder.encode(["deadly alien creature hunts crew"])[0])
    top = int(index.movie_ids[np.argmax(sims)])
    assert top == 5
    assert "alien" in index.chunk_texts[best[np.argmax(sims)]].lower()
    # zero-variance user (all 5.0) falls back to equal weights on liked movies
    assert index.profile({1: 5.0, 11: 5.0}, liked_abs=4.0) is not None
    assert index.profile({1: 2.0}, liked_abs=4.0) is None
    again = build_content_index(*args)  # loaded from cache
    assert np.array_equal(again.chunk_vecs, index.chunk_vecs)


def test_user_knn_recommender_is_the_unnormalized_neighbour_sum(ds, cfg):
    knn = UserKNN(ds.movies.index.to_numpy(), cfg.user_knn).fit(ds.ratings)
    scores, support = knn.score_all()
    row, col = knn.row_of(1), int(np.searchsorted(knn.movie_ids, 12))
    raters = [(n, knn.rating(n.user_id, 12)) for n in knn.neighbours(1)]
    raters = [(n, r) for n, r in raters if r is not None]
    expected = sum(n.similarity * (r - knn.user_mean(n.user_id)) for n, r in raters)
    assert support[row, col] == len(raters)
    if len(raters) >= cfg.user_knn.min_support:
        assert abs(scores[row, col] - expected) < 1e-9
    else:
        assert np.isnan(scores[row, col])
