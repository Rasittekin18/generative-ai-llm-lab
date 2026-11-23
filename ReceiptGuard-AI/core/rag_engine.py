"""Çok dilli yerel embedding ve kalıcı FAISS / NumPy vektör arama motoru."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol

import numpy as np


try:
    import faiss  # type: ignore

    HAS_FAISS = True
except ImportError:
    faiss = None
    HAS_FAISS = False


class EmbedderProtocol(Protocol):
    """Testlerde sahte (mock) veya gerçek gömme modeli takılabilmesi için arayüz."""

    def embed(self, texts: list[str]) -> np.ndarray:
        ...


class LocalTurkishEmbedder:
    """Hugging Face transformers ile yerel Türkçe/çok dilli SBERT embedding."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from transformers import AutoModel, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModel.from_pretrained(self.model_name)
            self._model.eval()

    def embed(self, texts: list[str]) -> np.ndarray:
        """Metin listesini L2-normalize edilmiş float32 vektör matrisine çevirir."""
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)

        self._load()
        import torch

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.no_grad():
            out = self._model(**encoded)
            token_embeddings = out.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
            summed = torch.sum(token_embeddings * mask, dim=1)
            counts = torch.clamp(mask.sum(dim=1), min=1e-9)
            pooled = summed / counts
            normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
            return normalized.cpu().numpy().astype(np.float32)


def chunk_text(text: str, chunk_size: int = 450, overlap: int = 90) -> list[str]:
    """Metni cümle/satır sınırlarını gözeterek örtüşen parçalara böler."""
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    step = max(chunk_size - overlap, 50)
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            # En yakın satır veya cümle sonundan kesmeye çalış
            for sep in ("\n", ". ", "; ", " "):
                pos = cleaned.rfind(sep, start + step // 2, end)
                if pos != -1:
                    end = pos + len(sep)
                    break
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_indexable_document_text(doc: dict[str, Any]) -> str:
    """Bir belgenin RAG tarafından aranabilecek zenginleştirilmiş Türkçe metnini üretir."""
    lines = [
        f"Belge Tipi: {doc.get('document_type', '')}",
        f"Mağaza/Satıcı: {doc.get('merchant_name', '')}",
        f"Tarih: {doc.get('document_date') or 'Belirtilmemiş'}",
        f"Kategori: {doc.get('category', '')}",
        f"Toplam Tutar: {doc.get('total_amount')} {doc.get('currency', 'TRY')}",
    ]
    if doc.get("warranty_months") or doc.get("warranty_end_date"):
        lines.append(
            f"Garanti: {doc.get('warranty_months') or '?'} ay (Bitiş: {doc.get('warranty_end_date') or '?'})"
        )
    if doc.get("summary"):
        lines.append(f"Özet: {doc['summary']}")
    if doc.get("warranty_terms"):
        lines.append(f"Garanti ve İade Şartları: {doc['warranty_terms']}")
    items = doc.get("items") or []
    if items:
        item_desc = ", ".join(
            f"{it.get('name')} ({it.get('quantity', 1)} adet, {it.get('total_price') or it.get('unit_price') or '-'} {doc.get('currency', 'TRY')})"
            for it in items
        )
        lines.append(f"Ürün Kalemleri: {item_desc}")
    if doc.get("raw_text"):
        lines.append(f"Belge Ham Metni:\n{doc['raw_text']}")
    return "\n".join(lines)


class RAGEngine:
    """Kalıcı disk destekli FAISS / NumPy vektör veritabanı yöneticisi."""

    def __init__(self, index_dir: Path, embedder: EmbedderProtocol):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.vectors_path = self.index_dir / "vectors.npy"
        self.meta_path = self.index_dir / "chunks.json"
        self.faiss_path = self.index_dir / "index.faiss"

        self.chunks: list[dict[str, Any]] = []
        self.vectors: Optional[np.ndarray] = None
        self._faiss_index = None
        self._lock = threading.Lock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self.meta_path.exists() and self.vectors_path.exists():
            try:
                self.chunks = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self.vectors = np.load(self.vectors_path).astype(np.float32)
                if len(self.chunks) != len(self.vectors):
                    self.chunks = []
                    self.vectors = None
            except Exception:
                self.chunks = []
                self.vectors = None
        self._rebuild_faiss()

    def _rebuild_faiss(self) -> None:
        if HAS_FAISS and self.vectors is not None and len(self.vectors) > 0:
            dim = self.vectors.shape[1]
            idx = faiss.IndexFlatIP(dim)
            idx.add(self.vectors)
            self._faiss_index = idx
        else:
            self._faiss_index = None

    def _save_to_disk(self) -> None:
        self.meta_path.write_text(
            json.dumps(self.chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.vectors is not None and len(self.vectors) > 0:
            np.save(self.vectors_path, self.vectors)
            if HAS_FAISS and self._faiss_index is not None:
                faiss.write_index(self._faiss_index, str(self.faiss_path))
        else:
            if self.vectors_path.exists():
                self.vectors_path.unlink()
            if self.faiss_path.exists():
                self.faiss_path.unlink()

    def index_document(self, doc: dict[str, Any]) -> int:
        """Belgeyi parçalara ayırıp vektör indeksine ekler (varsa eski parçaları değiştirir)."""
        doc_id = int(doc["id"])
        full_text = build_indexable_document_text(doc)
        pieces = chunk_text(full_text)
        if not pieces:
            return 0

        new_vecs = self.embedder.embed(pieces)
        new_meta = [
            {
                "document_id": doc_id,
                "file_name": doc.get("file_name", ""),
                "merchant_name": doc.get("merchant_name", ""),
                "document_date": doc.get("document_date"),
                "document_type": doc.get("document_type", "fis"),
                "category": doc.get("category", "Diğer"),
                "chunk_index": idx,
                "text": piece,
            }
            for idx, piece in enumerate(pieces)
        ]

        with self._lock:
            self._remove_doc_locked(doc_id)
            if self.vectors is None or len(self.vectors) == 0:
                self.vectors = new_vecs
            else:
                self.vectors = np.vstack([self.vectors, new_vecs]).astype(np.float32)
            self.chunks.extend(new_meta)
            self._rebuild_faiss()
            self._save_to_disk()
        return len(pieces)

    def _remove_doc_locked(self, doc_id: int) -> None:
        if not self.chunks or self.vectors is None:
            return
        keep_indices = [i for i, c in enumerate(self.chunks) if c.get("document_id") != doc_id]
        if len(keep_indices) == len(self.chunks):
            return
        if not keep_indices:
            self.chunks = []
            self.vectors = None
        else:
            self.chunks = [self.chunks[i] for i in keep_indices]
            self.vectors = self.vectors[keep_indices]

    def delete_document(self, doc_id: int) -> None:
        """Belgeye ait tüm vektör parçalarını indeksten kaldırır."""
        with self._lock:
            self._remove_doc_locked(doc_id)
            self._rebuild_faiss()
            self._save_to_disk()

    def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """Sorguya en yakın metin parçalarını benzerlik skoruyla döndürür."""
        with self._lock:
            if not self.chunks or self.vectors is None or len(self.chunks) == 0:
                return []
            q_vec = self.embedder.embed([query])
            k = min(top_k, len(self.chunks))

            if HAS_FAISS and self._faiss_index is not None:
                scores, indices = self._faiss_index.search(q_vec, k)
                raw_pairs = [
                    (int(idx), float(score))
                    for idx, score in zip(indices[0], scores[0])
                    if idx >= 0
                ]
            else:
                sims = (self.vectors @ q_vec[0]).astype(float)
                top_idx = np.argsort(-sims)[:k]
                raw_pairs = [(int(i), float(sims[i])) for i in top_idx]

            results = []
            for idx, score in raw_pairs:
                chunk = dict(self.chunks[idx])
                chunk["score"] = round(score, 4)
                results.append(chunk)
            return results

    @property
    def backend_name(self) -> str:
        return "FAISS (IndexFlatIP)" if HAS_FAISS else "NumPy Cosine Index"

    @property
    def total_chunks(self) -> int:
        return len(self.chunks)
