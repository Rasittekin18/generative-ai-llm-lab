"""LectureMind FastAPI ana uygulaması."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="LectureMind",
    description="Ders, Seminer & Video Bilgi Çıkarım Stüdyosu (Faster-Whisper + Semantic Chunking + Hybrid RAG)",
    version="1.0.0",
)

app.include_router(api_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_frontend() -> FileResponse:
    """Ana web stüdyo arayüzünü sunar."""
    return FileResponse(str(STATIC_DIR / "index.html"))
