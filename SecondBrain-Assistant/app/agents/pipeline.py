from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator, Optional

from app.agents.archivist import ArchivistAgent
from app.agents.ingestor import IngestorAgent
from app.agents.synthesizer import SynthesizerAgent
from app.config import Settings
from app.database import Database
from app.schemas import NoteRecord, PipelineEvent, SummarizeRequest


async def run_pipeline_stream(
    request: SummarizeRequest,
    settings: Settings,
    db: Database,
    ingestor: Optional[IngestorAgent] = None,
    synthesizer: Optional[SynthesizerAgent] = None,
    archivist: Optional[ArchivistAgent] = None,
) -> AsyncIterator[PipelineEvent]:
    """3 aşamalı çoklu ajan iş akışını (Ingestor -> Synthesizer -> Archivist) yürütür."""
    ingestor_agent = ingestor or IngestorAgent()
    synth_agent = synthesizer or SynthesizerAgent(
        api_key=settings.gemini_api_key, model=settings.gemini_model
    )
    archivist_agent = archivist or ArchivistAgent()

    try:
        yield PipelineEvent(
            stage="ingestor",
            status="running",
            message="1/3 İçerik Ajanı: Kaynak okunuyor ve metin çıkarılıyor...",
        )
        ingested = await ingestor_agent.ingest(
            url=request.url, text=request.text, title=request.title
        )
        yield PipelineEvent(
            stage="ingestor",
            status="done",
            message=f"İçerik alındı: {ingested.title} ({len(ingested.raw_text)} karakter)",
            data={
                "source_type": ingested.source_type,
                "title": ingested.title,
                "chars": len(ingested.raw_text),
            },
        )

        yield PipelineEvent(
            stage="synthesizer",
            status="running",
            message=f"2/3 Gemini Ajanı ({synth_agent.model}): Özet, tekrar kartları ve düzenlenmiş transkript hazırlanıyor...",
        )
        learning_note, cleaned_transcript = await asyncio.gather(
            synth_agent.synthesize(ingested, focus=request.focus),
            synth_agent.format_transcript(ingested),
        )
        yield PipelineEvent(
            stage="synthesizer",
            status="done",
            message=f"Analiz tamamlandı: {len(learning_note.key_points)} önemli nokta, {len(learning_note.review_questions)} tekrar kartı ve düzenlenmiş transkript.",
            data={"title": learning_note.title, "category": learning_note.category},
        )

        yield PipelineEvent(
            stage="archivist",
            status="running",
            message="3/3 Arşiv Ajanı: Obsidian Markdown dosyası ve SQLite kaydı oluşturuluyor...",
        )
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md_content = archivist_agent.render_obsidian_markdown(
            learning_note,
            ingested,
            created_at,
            cleaned_transcript=cleaned_transcript,
        )
        md_path = archivist_agent.save_markdown_file(
            settings.resolved_notes_dir, learning_note.title, md_content, created_at
        )
        record = db.save_note(
            note=learning_note,
            ingested=ingested,
            markdown_path=md_path,
            markdown_content=md_content,
            created_at=created_at,
            cleaned_transcript=cleaned_transcript,
        )
        yield PipelineEvent(
            stage="archivist",
            status="done",
            message=f"Kaydedildi: {md_path.name}",
            data={"markdown_path": str(md_path), "note_id": record.id},
        )

        yield PipelineEvent(
            stage="complete",
            status="done",
            message="Tüm ajanlar görevini tamamladı!",
            data={"note": record.model_dump()},
        )
    except Exception as exc:
        yield PipelineEvent(
            stage="error",
            status="error",
            message=str(exc),
        )


async def run_pipeline(
    request: SummarizeRequest,
    settings: Settings,
    db: Database,
    ingestor: Optional[IngestorAgent] = None,
    synthesizer: Optional[SynthesizerAgent] = None,
    archivist: Optional[ArchivistAgent] = None,
) -> NoteRecord:
    """İş akışını çalıştırır ve son NoteRecord nesnesini döndürür."""
    final_record: Optional[NoteRecord] = None
    async for event in run_pipeline_stream(
        request,
        settings,
        db,
        ingestor=ingestor,
        synthesizer=synthesizer,
        archivist=archivist,
    ):
        if event.stage == "error":
            raise RuntimeError(event.message)
        if event.stage == "complete" and event.data and "note" in event.data:
            final_record = NoteRecord(**event.data["note"])
    if final_record is None:
        raise RuntimeError("İş akışı beklenmedik şekilde sonuçsuz tamamlandı.")
    return final_record
