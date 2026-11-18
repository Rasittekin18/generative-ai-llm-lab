"""LectureMind birim testleri (chunking, hibrit arama, akademik vurgu çıkarımı, YouTube ID)."""

import numpy as np

from app.core.chunker import build_semantic_chunks, format_timestamp, segment_topics
from app.core.media_ingestor import extract_youtube_id
from app.core.summarizer import answer_question, build_extractive_summary, extract_academic_highlights
from app.core.vector_store import hybrid_search


def test_extract_youtube_id_variants() -> None:
    assert extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://youtu.be/dQw4w9WgXcQ?t=42") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/shorts/abc123XYZ00") == "abc123XYZ00"
    assert extract_youtube_id("https://vimeo.com/123456") is None


def test_format_timestamp() -> None:
    assert format_timestamp(5) == "00:05"
    assert format_timestamp(125) == "02:05"
    assert format_timestamp(3665) == "01:01:05"


def test_build_chunks_and_segment_topics() -> None:
    segments = [
        {"start": 0.0, "end": 10.0, "text": "Bugün derin öğrenme temellerini inceliyoruz. Yapay nöronlar ağırlıklarla çalışır."},
        {"start": 10.0, "end": 22.0, "text": "Aktivasyon fonksiyonları doğrusal olmayan dönüşümler sağlar."},
        {"start": 22.0, "end": 35.0, "text": "Gradient descent optimizasyon algoritmasıdır ve kayıp fonksiyonunu azaltır."},
        {"start": 35.0, "end": 50.0, "text": "Şimdi tamamen farklı bir konuya geçelim: Docker konteynerleri dağıtımı kolaylaştırır."},
        {"start": 50.0, "end": 65.0, "text": "Kubernetes ile mikroservisler otomatik ölçeklenir."},
        {"start": 65.0, "end": 80.0, "text": "CI/CD boru hatları test ve yayın sürecini otomatikleştirir."},
    ]
    chunks = build_semantic_chunks(segments, target_words=12, max_duration_sec=16.0)
    assert len(chunks) >= 6

    # İlk yarı ve ikinci yarı için belirgin şekilde ayrışan yapay embedding'ler
    embs = []
    for c in chunks:
        if c["start_sec"] < 34:
            embs.append([1.0, 0.0, 0.0, 0.0])
        else:
            embs.append([0.0, 1.0, 0.0, 0.0])
    emb_arr = np.asarray(embs, dtype=np.float32)

    chapters = segment_topics(chunks, emb_arr, min_chunks_per_chapter=2, max_chapters=5)
    assert len(chapters) >= 2
    assert chapters[0]["start_sec"] == 0.0
    assert chapters[-1]["end_sec"] == 80.0


def test_hybrid_search_and_local_qa() -> None:
    chunks = [
        {"chunk_index": 0, "chapter_index": 0, "start_sec": 0.0, "end_sec": 15.0, "text": "Giriş bölümünde dersin izlencesi tanıtıldı."},
        {"chunk_index": 1, "chapter_index": 0, "start_sec": 15.0, "end_sec": 35.0, "text": "Attention mekanizması uzun cümlelerde bağlamı korur."},
        {"chunk_index": 2, "chapter_index": 1, "start_sec": 35.0, "end_sec": 55.0, "text": "Vize sınavı gelecek hafta Cuma günü yapılacak ve proje teslimi istenecek."},
    ]

    def fake_encode(texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            tl = t.lower()
            if "attention" in tl or "bağlam" in tl:
                out.append([0.9, 0.1, 0.0])
            elif "sınav" in tl or "vize" in tl or "proje" in tl:
                out.append([0.0, 0.9, 0.1])
            else:
                out.append([0.1, 0.1, 0.9])
        return np.asarray(out, dtype=np.float32)

    emb = fake_encode([c["text"] for c in chunks])
    hits = hybrid_search("attention mekanizması ne işe yarar?", chunks, emb, fake_encode, top_k=2)
    assert len(hits) == 2
    assert hits[0]["chunk_index"] == 1

    chapters = [
        {"chapter_index": 0, "title": "Giriş ve Attention", "start_sec": 0.0, "end_sec": 35.0, "chunk_indices": [0, 1]},
        {"chapter_index": 1, "title": "Değerlendirme", "start_sec": 35.0, "end_sec": 55.0, "chunk_indices": [2]},
    ]

    class DummyCfg:
        LLM_PROVIDER = "local"

    ans = answer_question("attention", hits, chapters, DummyCfg())
    assert "00:15" in ans["answer"]
    assert ans["mode"] == "local"
    assert len(ans["citations"]) == 2

    hl = extract_academic_highlights(
        [{"start": 35.0, "end": 55.0, "text": chunks[2]["text"]}]
    )
    assert len(hl["exams"]) == 1

    summary = build_extractive_summary(
        chunks, emb, chapters, [{"start": 35.0, "end": 55.0, "text": chunks[2]["text"]}]
    )
    assert summary["word_count"] > 0
    assert len(summary["highlights"]["exams"]) == 1
