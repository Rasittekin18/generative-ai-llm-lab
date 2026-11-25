from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agents.ingestor import IngestorAgent
from app.agents.pipeline import run_pipeline, run_pipeline_stream
from app.agents.synthesizer import SynthesizerAgent
from app.bot.telegram_bot import TelegramBotRunner
from app.config import BASE_DIR, Settings, get_settings
from app.database import Database
from app.schemas import AskRequest, ChannelCreateRequest, SummarizeRequest

WEB_DIR = BASE_DIR / "web"


def create_app(custom_settings: Optional[Settings] = None) -> FastAPI:
    settings = custom_settings or get_settings()
    db = Database(settings.db_path)
    bot_runner = TelegramBotRunner(settings, db)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        db.init_db()
        await bot_runner.start()
        try:
            yield
        finally:
            await bot_runner.stop()

    app = FastAPI(
        title="Kişisel İkinci Beyin & Öğrenme Asistanı",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = settings
    app.state.db = db
    app.state.bot_runner = bot_runner
    app.state.ingestor = IngestorAgent()
    app.state.synthesizer = SynthesizerAgent(
        api_key=settings.gemini_api_key, model=settings.gemini_model
    )

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    async def serve_home() -> FileResponse:
        index_path = WEB_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Web arayüzü bulunamadı.")
        return FileResponse(str(index_path))

    @app.get("/api/status")
    async def api_status() -> dict[str, object]:
        s: Settings = app.state.settings
        database: Database = app.state.db
        runner: TelegramBotRunner = app.state.bot_runner
        return {
            "gemini_configured": s.gemini_configured,
            "gemini_model": s.gemini_model,
            "telegram_configured": s.telegram_configured,
            "telegram_running": runner.running,
            "telegram_error": runner.last_error,
            "notes_dir": str(s.resolved_notes_dir),
            "stats": database.get_stats(),
        }

    @app.post("/api/summarize")
    async def api_summarize(req: SummarizeRequest) -> dict[str, object]:
        try:
            record = await run_pipeline(
                req,
                app.state.settings,
                app.state.db,
                ingestor=app.state.ingestor,
                synthesizer=app.state.synthesizer,
            )
            return {"note": record.model_dump()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/summarize/stream")
    async def api_summarize_stream(req: SummarizeRequest) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[str]:
            async for event in run_pipeline_stream(
                req,
                app.state.settings,
                app.state.db,
                ingestor=app.state.ingestor,
                synthesizer=app.state.synthesizer,
            ):
                payload = json.dumps(event.model_dump(), ensure_ascii=False)
                yield f"data: {payload}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/notes")
    async def api_list_notes(
        q: Optional[str] = Query(default=None),
        category: Optional[str] = Query(default=None),
        source_type: Optional[str] = Query(default=None),
        tag: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, object]:
        notes = app.state.db.list_notes(
            query=q, category=category, source_type=source_type, tag=tag, limit=limit
        )
        return {
            "notes": [n.model_dump() for n in notes],
            "stats": app.state.db.get_stats(),
        }

    @app.get("/api/notes/{note_id}")
    async def api_get_note(note_id: int) -> dict[str, object]:
        note = app.state.db.get_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Not bulunamadı.")
        return {"note": note.model_dump()}

    @app.get("/api/notes/{note_id}/markdown")
    async def api_download_markdown(note_id: int) -> Response:
        note = app.state.db.get_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Not bulunamadı.")
        filename = Path(note.markdown_path).name or f"not-{note_id}.md"
        return Response(
            content=note.markdown_content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.get("/api/notes/{note_id}/transcript")
    async def api_download_transcript(note_id: int) -> Response:
        note = app.state.db.get_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Not bulunamadı.")
        if not note.cleaned_transcript.strip():
            raise HTTPException(
                status_code=404, detail="Bu not için düzenlenmiş transkript bulunmuyor."
            )
        stem = Path(note.markdown_path).stem or f"not-{note_id}"
        filename = f"{stem}_transkript.md"
        body = f"# {note.title} — Düzenlenmiş Transkript\n\n{note.cleaned_transcript}\n"
        return Response(
            content=body.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.delete("/api/notes/{note_id}")
    async def api_delete_note(
        note_id: int, delete_file: bool = Query(default=True)
    ) -> dict[str, object]:
        deleted = app.state.db.delete_note(note_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Not bulunamadı.")

        file_removed = False
        if delete_file and deleted.markdown_path:
            try:
                p = Path(deleted.markdown_path).resolve()
                notes_root = app.state.settings.resolved_notes_dir.resolve()
                if p.exists() and p.parent == notes_root:
                    p.unlink()
                    file_removed = True
            except Exception:
                pass

        return {"deleted": True, "id": note_id, "file_removed": file_removed}

    @app.post("/api/notes/{note_id}/ask")
    async def api_ask_note(note_id: int, req: AskRequest) -> dict[str, str]:
        found = app.state.db.get_note_context(note_id)
        if not found:
            raise HTTPException(status_code=404, detail="Not bulunamadı.")
        note, raw_excerpt = found
        try:
            answer = await app.state.synthesizer.ask_about_note(
                note, raw_excerpt, req.question
            )
            return {"answer": answer}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/channels")
    async def api_list_channels() -> dict[str, object]:
        channels = app.state.db.list_channels()
        return {"channels": [c.model_dump() for c in channels]}

    @app.post("/api/channels")
    async def api_add_channel(req: ChannelCreateRequest) -> dict[str, object]:
        try:
            channel_id, ch_title = await app.state.ingestor.resolve_youtube_channel(
                req.url_or_id
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = app.state.db.add_channel(
            channel_id=channel_id,
            title=ch_title,
            handle_or_url=req.url_or_id.strip(),
            created_at=created_at,
        )
        return {"channel": record.model_dump()}

    @app.delete("/api/channels/{channel_row_id}")
    async def api_delete_channel(channel_row_id: int) -> dict[str, bool]:
        ok = app.state.db.delete_channel(channel_row_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
        return {"deleted": True}

    @app.get("/api/channels/{channel_row_id}/videos")
    async def api_channel_videos(
        channel_row_id: int, limit: int = Query(default=6, ge=1, le=15)
    ) -> dict[str, object]:
        channels = app.state.db.list_channels()
        target = next((c for c in channels if c.id == channel_row_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
        try:
            items = await app.state.ingestor.fetch_channel_videos(
                target.channel_id, limit=limit
            )
            return {"videos": [v.model_dump() for v, _ in items]}
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"RSS akışı okunamadı: {exc}"
            ) from exc

    return app


app = create_app()
