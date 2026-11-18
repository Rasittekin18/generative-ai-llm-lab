"""Çok dilli Sentence-Transformers embedding ve Hibrit Arama (Dense + BM25) modülü."""

import re
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+", text.lower())


class EmbeddingEngine:
    """Çok dilli cümle vektörü üretici (Türkçe + İngilizce)."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        model = self._get_model()
        vecs = model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)


def hybrid_search(
    query: str,
    chunks: list[dict[str, Any]],
    embeddings: np.ndarray,
    encode_fn: Any,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Dense kosinüs benzerliği ile BM25 anahtar kelime skorunu RRF ile birleştirir."""
    if not chunks or embeddings.size == 0 or not query.strip():
        return []

    # 1. Dense semantik skor (vektörler normalize olduğu için nokta çarpımı = kosinüs benzerliği)
    q_vec = encode_fn([query])[0]
    norm_q = q_vec / (np.linalg.norm(q_vec) or 1.0)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    norm_emb = embeddings / norms
    dense_scores = norm_emb @ norm_q

    # 2. BM25 sözcüksel skor
    corpus_tokens = [_tokenize(c["text"]) for c in chunks]
    query_tokens = _tokenize(query)
    if query_tokens and any(corpus_tokens):
        bm25 = BM25Okapi(corpus_tokens)
        bm25_scores = np.asarray(bm25.get_scores(query_tokens), dtype=np.float32)
    else:
        bm25_scores = np.zeros(len(chunks), dtype=np.float32)

    # 3. Reciprocal Rank Fusion (RRF) + normalize edilmiş ağırlıklı skor
    dense_ranks = np.argsort(np.argsort(-dense_scores)) + 1
    bm25_ranks = np.argsort(np.argsort(-bm25_scores)) + 1
    rrf = (1.0 / (60.0 + dense_ranks)) * 0.65 + (1.0 / (60.0 + bm25_ranks)) * 0.35

    max_bm25 = float(np.max(bm25_scores)) if np.max(bm25_scores) > 0 else 1.0
    norm_bm25 = bm25_scores / max_bm25
    norm_dense = np.clip((dense_scores + 1.0) / 2.0, 0.0, 1.0)
    combined_score = 0.70 * norm_dense + 0.30 * norm_bm25 + rrf

    top_indices = np.argsort(-combined_score)[:top_k]
    results: list[dict[str, Any]] = []
    for idx in top_indices:
        item = dict(chunks[int(idx)])
        item["score"] = round(float(combined_score[int(idx)]), 4)
        item["semantic_score"] = round(float(dense_scores[int(idx)]), 4)
        item["lexical_score"] = round(float(norm_bm25[int(idx)]), 4)
        results.append(item)
    return results
