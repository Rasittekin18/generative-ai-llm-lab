"""Çift modlu (Yerel Extractive + İsteğe Bağlı LLM) özetleme, aksiyon çıkarımı ve zaman damgalı RAG."""

import json
import re
from typing import Any

import httpx
import numpy as np

from app.core.chunker import format_timestamp


EXAM_PATTERNS = re.compile(
    r"\b(sınav|vize|final|quiz|test|soru gelir|çıkabilir|exam|midterm|testable)\b",
    re.IGNORECASE,
)
ASSIGNMENT_PATTERNS = re.compile(
    r"\b(ödev|proje|teslim|rapor|sunum|assignment|homework|deadline|project|submit|due)\b",
    re.IGNORECASE,
)
KEYPOINT_PATTERNS = re.compile(
    r"\b(önemli|dikkat|unutmayın|kısacası|özetle|temel olarak|burası kritik|"
    r"important|crucial|key takeaway|remember|note that|in summary|therefore)\b",
    re.IGNORECASE,
)


def extract_academic_highlights(segments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Derste geçen sınav, ödev ve kritik kavram vurgularını zaman damgasıyla çıkarır."""
    exams: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    keypoints: list[dict[str, Any]] = []

    for seg in segments:
        text = seg["text"].strip()
        if len(text) < 12:
            continue
        item = {
            "start_sec": seg["start"],
            "timestamp": format_timestamp(seg["start"]),
            "text": text,
        }
        if EXAM_PATTERNS.search(text) and len(exams) < 12:
            exams.append(item)
        elif ASSIGNMENT_PATTERNS.search(text) and len(assignments) < 12:
            assignments.append(item)
        elif KEYPOINT_PATTERNS.search(text) and len(keypoints) < 15:
            keypoints.append(item)

    return {
        "exams": exams,
        "assignments": assignments,
        "keypoints": keypoints,
    }


def build_extractive_summary(
    chunks: list[dict[str, Any]],
    embeddings: np.ndarray,
    chapters: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Vektör merkezine en yakın (LexRank/Centroid) parçalarla bölüm ve genel özet üretir."""
    if not chunks or embeddings.size == 0:
        return {
            "overview": "Transkript için özet çıkarılacak yeterli metin bulunamadı.",
            "highlights": {"exams": [], "assignments": [], "keypoints": []},
            "word_count": 0,
        }

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    norm_emb = embeddings / norms

    # Her bölüm için merkez vektöre en yakın parçayı bölüm özeti yap
    for ch in chapters:
        idxs = [i for i in ch.get("chunk_indices", []) if i < len(chunks)]
        if not idxs:
            ch["summary"] = ""
            continue
        sub = norm_emb[idxs]
        centroid = sub.mean(axis=0)
        centroid /= np.linalg.norm(centroid) or 1.0
        scores = sub @ centroid
        best_local = int(np.argmax(scores))
        best_text = chunks[idxs[best_local]]["text"]
        ch["summary"] = best_text[:420] + ("..." if len(best_text) > 420 else "")

    # Genel özet: global merkeze en yakın en fazla 4 parça (zaman sırasıyla)
    global_centroid = norm_emb.mean(axis=0)
    global_centroid /= np.linalg.norm(global_centroid) or 1.0
    global_scores = norm_emb @ global_centroid
    top_k = min(4, len(chunks))
    chosen_idxs = sorted(np.argsort(-global_scores)[:top_k].tolist())
    overview_bullets = [
        f"[{format_timestamp(chunks[i]['start_sec'])}] {chunks[i]['text']}"
        for i in chosen_idxs
    ]
    total_words = sum(len(c["text"].split()) for c in chunks)

    return {
        "overview": "\n\n".join(overview_bullets),
        "highlights": extract_academic_highlights(segments),
        "word_count": total_words,
    }


def _call_optional_llm(
    provider: str,
    question: str,
    context_block: str,
    config: Any,
) -> str | None:
    """Yapılandırılmışsa Ollama / OpenAI / Gemini üzerinden akıcı RAG yanıtı üretir."""
    system_prompt = (
        "Sen bir akademik ders ve video analiz asistanısın. "
        "Yalnızca verilen zaman damgalı transkript parçalarına dayanarak Türkçe cevap ver. "
        "Her bilginin yanına ilgili zaman damgasını [MM:SS] biçiminde ekle. "
        "Metinde olmayan hiçbir bilgiyi uydurma."
    )
    user_prompt = f"Soru: {question}\n\nTranskript Alıntıları:\n{context_block}"

    try:
        if provider == "ollama":
            resp = httpx.post(
                f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=45.0,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()

        if provider == "openai" and config.OPENAI_API_KEY:
            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                json={
                    "model": config.OPENAI_MODEL,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

        if provider == "gemini" and config.GEMINI_API_KEY:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
            )
            resp = httpx.post(
                url,
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": f"{system_prompt}\n\n{user_prompt}"}
                            ]
                        }
                    ]
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None
    return None


def answer_question(
    question: str,
    hits: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    config: Any,
) -> dict[str, Any]:
    """Hibrit aramadan dönen parçalara dayanarak zaman damgalı yanıt üretir."""
    if not hits:
        return {
            "answer": "Sorunuzla eşleşen bir bölüm bulunamadı. Farklı anahtar kelimeler deneyebilirsiniz.",
            "mode": "local",
            "citations": [],
        }

    chapter_map = {c["chapter_index"]: c["title"] for c in chapters}
    citations = []
    context_lines = []
    for h in hits:
        ts = format_timestamp(h["start_sec"])
        ch_title = chapter_map.get(h.get("chapter_index", 0), "Genel")
        citations.append(
            {
                "start_sec": h["start_sec"],
                "end_sec": h["end_sec"],
                "timestamp": ts,
                "chapter_title": ch_title,
                "score": h["score"],
                "text": h["text"],
            }
        )
        context_lines.append(f"[{ts}] ({ch_title}) {h['text']}")

    context_block = "\n\n".join(context_lines)
    provider = (getattr(config, "LLM_PROVIDER", "local") or "local").lower()

    llm_answer = None
    if provider != "local":
        llm_answer = _call_optional_llm(provider, question, context_block, config)

    if llm_answer:
        return {
            "answer": llm_answer,
            "mode": provider,
            "citations": citations,
        }

    # Yerel Extractive RAG Sentezi (Sıfır API maliyeti, tam kaynak doğrulamalı)
    best = citations[0]
    lines = [
        f"Sorunuzla en yüksek eşleşme **{best['timestamp']}** zamanında "
        f"(_{best['chapter_title']}_) bulundu:",
        "",
        f"> \"{best['text']}\"",
    ]
    if len(citations) > 1:
        lines.append("")
        lines.append("İlgili diğer zaman damgaları:")
        for c in citations[1:4]:
            snippet = c["text"][:180] + ("..." if len(c["text"]) > 180 else "")
            lines.append(f"- **[{c['timestamp']}]** ({c['chapter_title']}): {snippet}")

    return {
        "answer": "\n".join(lines),
        "mode": "local",
        "citations": citations,
    }
