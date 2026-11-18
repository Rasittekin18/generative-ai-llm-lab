"""Semantik parçalama (chunking) ve otomatik konu bölümlendirme modülü."""

import re
from typing import Any, Callable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


EncodeFn = Callable[[list[str]], np.ndarray]

STOP_WORDS = {
    # Türkçe
    "acaba", "ama", "aslında", "az", "bazı", "belki", "ben", "beni", "benim", "bir",
    "biraz", "birkaç", "biri", "birşey", "biz", "bize", "bizi", "bizim", "bu",
    "bunu", "bunun", "burada", "çok", "çünkü", "da", "daha", "de", "defa", "diğer",
    "diye", "eğer", "en", "gibi", "hem", "hep", "hepsi", "her", "hiç", "için",
    "ile", "ise", "işte", "kadar", "kez", "ki", "kim", "mı", "mi", "mu", "mü",
    "nasıl", "ne", "neden", "nerde", "nerede", "nereye", "niçin", "niye", "o",
    "olan", "olarak", "oldu", "olduğu", "olur", "olacak", "onlar", "onu", "onun",
    "öyle", "sadece", "sanki", "sen", "siz", "şey", "şimdi", "şöyle", "şu",
    "tarafından", "tüm", "ve", "veya", "ya", "yani", "yine", "yok", "zaten",
    # İngilizce
    "a", "about", "above", "after", "again", "all", "am", "an", "and", "any",
    "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing",
    "down", "during", "each", "few", "for", "from", "further", "had", "has",
    "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "let", "like", "me", "more", "most", "my", "myself", "no", "nor", "not",
    "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
    "out", "over", "own", "right", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "whom", "why", "will", "with", "would", "you",
    "your", "yours", "yourself", "going", "actually", "basically", "okay", "yeah",
}


def format_timestamp(seconds: float) -> str:
    """Saniyeyi MM:SS veya HH:MM:SS formatına çevirir."""
    total = max(0, int(round(seconds)))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def build_semantic_chunks(
    segments: list[dict[str, Any]],
    target_words: int = 85,
    max_duration_sec: float = 42.0,
) -> list[dict[str, Any]]:
    """Ham Whisper segmentlerini anlam bütünlüğü koruyan parçalarda birleştirir."""
    if not segments:
        return []

    chunks: list[dict[str, Any]] = []
    buf_texts: list[str] = []
    buf_start = float(segments[0]["start"])
    buf_end = float(segments[0]["end"])
    buf_words = 0

    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        words = len(text.split())
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])

        should_flush = buf_texts and (
            (buf_words + words > target_words and buf_texts[-1].endswith((".", "!", "?")))
            or (buf_words + words > int(target_words * 1.35))
            or (seg_end - buf_start > max_duration_sec)
        )
        if should_flush:
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "start_sec": round(buf_start, 2),
                    "end_sec": round(buf_end, 2),
                    "text": " ".join(buf_texts),
                }
            )
            buf_texts = []
            buf_start = seg_start
            buf_words = 0

        if not buf_texts:
            buf_start = seg_start
        buf_texts.append(text)
        buf_end = seg_end
        buf_words += words

    if buf_texts:
        chunks.append(
            {
                "chunk_index": len(chunks),
                "start_sec": round(buf_start, 2),
                "end_sec": round(buf_end, 2),
                "text": " ".join(buf_texts),
            }
        )
    return chunks


def _extract_keywords(texts: list[str], top_k: int = 4) -> list[list[str]]:
    """Her bölüm metni için TF-IDF tabanlı ayırt edici anahtar kelimeler çıkarır."""
    if not texts:
        return []

    def tokenizer(s: str) -> list[str]:
        tokens = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]{3,}", s.lower())
        return [t for t in tokens if t not in STOP_WORDS and not t.isdigit()]

    try:
        vec = TfidfVectorizer(
            tokenizer=tokenizer,
            token_pattern=None,
            lowercase=False,
            max_features=300,
        )
        mat = vec.fit_transform(texts)
        names = np.array(vec.get_feature_names_out())
    except ValueError:
        return [[] for _ in texts]

    keywords_per_doc: list[list[str]] = []
    for row_idx in range(mat.shape[0]):
        row = mat[row_idx].toarray().ravel()
        if not np.any(row):
            keywords_per_doc.append([])
            continue
        top_indices = np.argsort(row)[::-1][:top_k]
        kws = [str(names[i]) for i in top_indices if row[i] > 0]
        keywords_per_doc.append(kws)
    return keywords_per_doc


def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return mat / norms


def segment_topics(
    chunks: list[dict[str, Any]],
    embeddings: np.ndarray,
    source_chapters: list[dict[str, Any]] | None = None,
    min_chunks_per_chapter: int = 3,
    max_chapters: int = 10,
) -> list[dict[str, Any]]:
    """Vektör benzerliği düşüş noktalarına göre otomatik konu bölümleri oluşturur."""
    if not chunks:
        return []

    # Video kaynağında (ör. YouTube) hazır bölümler varsa öncelikle onları kullan
    if source_chapters and len(source_chapters) >= 2:
        chapters = []
        for idx, ch in enumerate(source_chapters):
            start_s = float(ch["start_sec"])
            end_s = float(ch["end_sec"]) or (chunks[-1]["end_sec"] if idx == len(source_chapters) - 1 else start_s)
            ch_chunks = [
                c for c in chunks if c["end_sec"] > start_s and c["start_sec"] < end_s
            ]
            for c in ch_chunks:
                c["chapter_index"] = idx
            chapters.append(
                {
                    "chapter_index": idx,
                    "title": ch["title"],
                    "start_sec": round(start_s, 2),
                    "end_sec": round(end_s, 2),
                    "chunk_indices": [c["chunk_index"] for c in ch_chunks],
                    "text": " ".join(c["text"] for c in ch_chunks),
                }
            )
        for c in chunks:
            c.setdefault("chapter_index", 0)
        kw_lists = _extract_keywords([c["text"] for c in chapters])
        for ch, kws in zip(chapters, kw_lists):
            ch["keywords"] = kws
        return chapters

    n = len(chunks)
    if n <= min_chunks_per_chapter * 2:
        for c in chunks:
            c["chapter_index"] = 0
        full_text = " ".join(c["text"] for c in chunks)
        kws = _extract_keywords([full_text])[0] if full_text else []
        title = " / ".join(w.capitalize() for w in kws[:3]) or "Genel Ders Özeti"
        return [
            {
                "chapter_index": 0,
                "title": title,
                "start_sec": chunks[0]["start_sec"],
                "end_sec": chunks[-1]["end_sec"],
                "chunk_indices": [c["chunk_index"] for c in chunks],
                "keywords": kws,
                "text": full_text,
            }
        ]

    norm_emb = _normalize_rows(embeddings)
    # Ardışık 2'li pencere ortalamaları arasındaki kosinüs benzerliğini ölç (TextTiling mantığı)
    sims: list[tuple[int, float]] = []
    for i in range(min_chunks_per_chapter, n - min_chunks_per_chapter + 1):
        left = norm_emb[max(0, i - 2) : i].mean(axis=0)
        right = norm_emb[i : min(n, i + 2)].mean(axis=0)
        left_n = left / (np.linalg.norm(left) or 1.0)
        right_n = right / (np.linalg.norm(right) or 1.0)
        sim = float(np.dot(left_n, right_n))
        sims.append((i, sim))

    # Benzerliğin en keskin düştüğü noktaları sınır adayı olarak seç
    sim_vals = np.array([s for _, s in sims])
    threshold = float(np.percentile(sim_vals, 30))
    candidates = sorted([idx for idx, s in sims if s <= threshold])

    boundaries = [0]
    for cand in candidates:
        if cand - boundaries[-1] >= min_chunks_per_chapter and (n - cand) >= min_chunks_per_chapter:
            boundaries.append(cand)
            if len(boundaries) >= max_chapters:
                break
    boundaries.append(n)

    chapters: list[dict[str, Any]] = []
    chapter_texts: list[str] = []
    for ch_idx in range(len(boundaries) - 1):
        s_i, e_i = boundaries[ch_idx], boundaries[ch_idx + 1]
        group = chunks[s_i:e_i]
        for c in group:
            c["chapter_index"] = ch_idx
        combined = " ".join(c["text"] for c in group)
        chapter_texts.append(combined)
        chapters.append(
            {
                "chapter_index": ch_idx,
                "start_sec": group[0]["start_sec"],
                "end_sec": group[-1]["end_sec"],
                "chunk_indices": [c["chunk_index"] for c in group],
                "text": combined,
            }
        )

    kw_lists = _extract_keywords(chapter_texts)
    for ch_idx, (ch, kws) in enumerate(zip(chapters, kw_lists)):
        ch["keywords"] = kws
        if kws:
            ch["title"] = f"Bölüm {ch_idx + 1}: " + ", ".join(w.capitalize() for w in kws[:3])
        else:
            ch["title"] = f"Bölüm {ch_idx + 1} ({format_timestamp(ch['start_sec'])})"

    return chapters
