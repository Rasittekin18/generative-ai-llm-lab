"""LectureMind REST API uç noktaları."""

from pathlib import Path
import shutil
from typing import Literal
import uuid

import ctranslate2
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.core.chunker import format_timestamp
from app.core.database import Database
from app.core.pipeline import LecturePipeline
from app.core.summarizer import answer_question
from app.core.vector_store import hybrid_search


db = Database(settings.DB_PATH)
pipeline = LecturePipeline(db)
router = APIRouter(prefix="/api", tags=["LectureMind"])

ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".wav", ".m4a", ".webm", ".mkv", ".ogg", ".flac", ".avi"}


class UrlIngestRequest(BaseModel):
    url: str = Field(..., min_length=8)
    whisper_model: Literal["tiny", "base", "small", "medium"] = "small"
    language: str = "auto"


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=800)
    top_k: int = Field(default=5, ge=1, le=12)


def _format_srt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


@router.get("/health")
def health_check() -> dict:
    """Sistem, GPU ve yapılandırma durumunu döndürür."""
    try:
        cuda_count = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_count = 0
    return {
        "status": "ok",
        "cuda_available": cuda_count > 0,
        "cuda_device_count": cuda_count,
        "default_whisper_model": settings.WHISPER_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "llm_provider": settings.LLM_PROVIDER,
    }


@router.get("/lectures")
def list_lectures() -> list[dict]:
    """Kayıtlı tüm ders ve videoları listeler."""
    return db.list_lectures()


@router.post("/lectures/url")
def ingest_from_url(payload: UrlIngestRequest, background_tasks: BackgroundTasks) -> dict:
    """YouTube veya desteklenen herhangi bir siteden video/ses analizini başlatır."""
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Geçerli bir http/https bağlantısı girin.")

    lecture_id = uuid.uuid4().hex[:12]
    lecture = db.create_lecture(
        lecture_id=lecture_id,
        title=url,
        source_type="url",
        source_url=url,
        whisper_model=payload.whisper_model,
        language=None if payload.language == "auto" else payload.language,
    )
    background_tasks.add_task(
        pipeline.process_url,
        lecture_id,
        url,
        payload.whisper_model,
        payload.language,
    )
    return lecture


@router.post("/lectures/upload")
def ingest_from_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    whisper_model: Literal["tiny", "base", "small", "medium"] = Form("small"),
    language: str = Form("auto"),
) -> dict:
    """Yerel ses veya video dosyasını yükleyip analiz boru hattını başlatır."""
    filename = file.filename or "recording.mp3"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya türü ({ext}). Desteklenenler: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    lecture_id = uuid.uuid4().hex[:12]
    temp_dir = settings.MEDIA_DIR / "_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{lecture_id}{ext}"

    with temp_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    lecture = db.create_lecture(
        lecture_id=lecture_id,
        title=Path(filename).stem,
        source_type="upload",
        source_url=None,
        whisper_model=whisper_model,
        language=None if language == "auto" else language,
    )
    background_tasks.add_task(
        pipeline.process_upload,
        lecture_id,
        temp_path,
        filename,
        whisper_model,
        language,
    )
    return lecture


@router.get("/lectures/{lecture_id}")
def get_lecture_detail(lecture_id: str) -> dict:
    """Bir dersin tüm durumunu, bölümlerini, transkriptini ve özetini döndürür."""
    lecture = db.get_lecture(lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="Ders kaydı bulunamadı.")

    return {
        "lecture": lecture,
        "chapters": db.get_chapters(lecture_id),
        "segments": db.get_segments(lecture_id),
        "qa_history": db.get_qa_history(lecture_id),
    }


@router.delete("/lectures/{lecture_id}")
def remove_lecture(lecture_id: str) -> dict:
    """Ders kaydını ve medya dosyalarını siler."""
    deleted = db.delete_lecture(lecture_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Ders kaydı bulunamadı.")
    pipeline.delete_media_files(lecture_id)
    return {"deleted": True, "lecture_id": lecture_id}


@router.get("/lectures/{lecture_id}/audio")
def stream_audio(lecture_id: str) -> FileResponse:
    """İşlenmiş MP3 ses dosyasını oynatıcıya sunar."""
    lecture = db.get_lecture(lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="Ders kaydı bulunamadı.")
    audio_path = Path(lecture.get("audio_path") or "")
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Ses dosyası bulunamadı.")
    return FileResponse(path=str(audio_path), media_type="audio/mpeg", filename="audio.mp3")


@router.get("/lectures/{lecture_id}/search")
def search_lecture(
    lecture_id: str,
    q: str = Query(..., min_length=2),
    top_k: int = Query(6, ge=1, le=20),
) -> dict:
    """Hibrit (Semantik + BM25) zaman damgalı arama yapar."""
    lecture = db.get_lecture(lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="Ders kaydı bulunamadı.")
    chunks, embeddings = db.get_chunks(lecture_id)
    hits = hybrid_search(
        query=q,
        chunks=chunks,
        embeddings=embeddings,
        encode_fn=pipeline.embedder.encode,
        top_k=top_k,
    )
    for h in hits:
        h["timestamp"] = format_timestamp(h["start_sec"])
    return {"query": q, "results": hits}


@router.post("/lectures/{lecture_id}/ask")
def ask_lecture(lecture_id: str, payload: AskRequest) -> dict:
    """Ders içeriğine dayalı zaman damgalı soru-cevap (RAG) çalıştırır."""
    lecture = db.get_lecture(lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="Ders kaydı bulunamadı.")
    if lecture["status"] != "completed":
        raise HTTPException(status_code=400, detail="Ders henüz işleniyor, lütfen tamamlanmasını bekleyin.")

    chunks, embeddings = db.get_chunks(lecture_id)
    chapters = db.get_chapters(lecture_id)
    hits = hybrid_search(
        query=payload.question,
        chunks=chunks,
        embeddings=embeddings,
        encode_fn=pipeline.embedder.encode,
        top_k=payload.top_k,
    )
    response = answer_question(
        question=payload.question,
        hits=hits,
        chapters=chapters,
        config=settings,
    )
    db.add_qa(lecture_id, payload.question, response)
    return response


@router.get("/lectures/{lecture_id}/export")
def export_lecture(
    lecture_id: str,
    fmt: Literal["md", "txt", "srt"] = Query("md"),
) -> PlainTextResponse:
    """Ders notlarını Markdown, düz metin veya SRT altyazı olarak dışa aktarır."""
    lecture = db.get_lecture(lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="Ders kaydı bulunamadı.")

    chapters = db.get_chapters(lecture_id)
    segments = db.get_segments(lecture_id)

    if fmt == "srt":
        lines = []
        for idx, seg in enumerate(segments, 1):
            lines.append(str(idx))
            lines.append(f"{_format_srt_time(seg['start_sec'])} --> {_format_srt_time(seg['end_sec'])}")
            lines.append(seg["text"])
            lines.append("")
        return PlainTextResponse(
            "\n".join(lines),
            headers={"Content-Disposition": f'attachment; filename="{lecture_id}.srt"'},
        )

    if fmt == "txt":
        lines = [
            f"[{format_timestamp(s['start_sec'])}] {s['text']}"
            for s in segments
        ]
        return PlainTextResponse(
            "\n".join(lines),
            headers={"Content-Disposition": f'attachment; filename="{lecture_id}.txt"'},
        )

    # Markdown çalışma notu
    summary = lecture.get("summary") or {}
    highlights = summary.get("highlights") or {}
    md = [
        f"# {lecture['title']}",
        "",
        f"- **Dil:** {lecture.get('language') or '-'} | **Süre:** {format_timestamp(lecture.get('duration_sec') or 0)}",
    ]
    if lecture.get("source_url"):
        md.append(f"- **Kaynak:** {lecture['source_url']}")
    md.extend(["", "## Genel Özet", "", summary.get("overview") or "Özet yok.", "", "## Konu Bölümleri", ""])
    for ch in chapters:
        kws = ", ".join(ch.get("keywords") or [])
        md.append(f"### [{format_timestamp(ch['start_sec'])}] {ch['title']}")
        if kws:
            md.append(f"*Anahtar kelimeler:* {kws}")
        if ch.get("summary"):
            md.append(ch["summary"])
        md.append("")

    for label, key in [("Sınav / Değerlendirme Vurguları", "exams"), ("Ödev / Proje / Teslimler", "assignments"), ("Kritik Noktalar", "keypoints")]:
        items = highlights.get(key) or []
        if items:
            md.append(f"## {label}")
            for it in items:
                md.append(f"- **[{it['timestamp']}]** {it['text']}")
            md.append("")

    md.extend(["## Tam Zaman Damgalı Transkript", ""])
    for s in segments:
        md.append(f"- **[{format_timestamp(s['start_sec'])}]** {s['text']}")

    return PlainTextResponse(
        "\n".join(md),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{lecture_id}_notlar.md"'},
    )
