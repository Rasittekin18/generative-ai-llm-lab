"""Medya işleme, transkripsiyon, konu bölümleme ve indeksleme boru hattı."""

from pathlib import Path
import shutil

from app.config import settings
from app.core.chunker import build_semantic_chunks, segment_topics
from app.core.database import Database
from app.core.media_ingestor import IngestedMedia, ingest_local_file, ingest_url
from app.core.summarizer import build_extractive_summary
from app.core.transcriber import LectureTranscriber
from app.core.vector_store import EmbeddingEngine


class LecturePipeline:
    """Tüm video/ses analiz aşamalarını yöneten orkestratör."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.transcriber = LectureTranscriber()
        self.embedder = EmbeddingEngine(settings.EMBEDDING_MODEL)

    def _run_nlp_stages(
        self,
        lecture_id: str,
        media: IngestedMedia,
        whisper_model: str,
        language: str | None,
    ) -> None:
        self.db.update_lecture_metadata(
            lecture_id,
            title=media.title,
            platform=media.platform,
            youtube_id=media.youtube_id,
            audio_path=str(media.audio_path),
            duration_sec=media.duration_sec,
        )

        # 2. Transkripsiyon
        def on_progress(pct: int, msg: str) -> None:
            self.db.update_status(lecture_id, "transcribing", pct, msg)

        tr_result = self.transcriber.transcribe(
            audio_path=media.audio_path,
            model_size=whisper_model,
            device_pref=settings.WHISPER_DEVICE,
            language=language,
            duration_sec=media.duration_sec,
            on_progress=on_progress,
        )
        segments = tr_result["segments"]
        if not segments:
            raise RuntimeError("Kayıtta konuşma metni tespit edilemedi.")

        self.db.update_lecture_metadata(
            lecture_id,
            language=tr_result["language"],
            duration_sec=tr_result["duration"] or media.duration_sec,
        )
        self.db.replace_segments(lecture_id, segments)

        # 3. Semantik Parçalama ve Embedding
        self.db.update_status(
            lecture_id,
            "indexing",
            72,
            "Semantik parçalar ve çok dilli vektörler oluşturuluyor...",
        )
        chunks = build_semantic_chunks(segments)
        chunk_texts = [c["text"] for c in chunks]
        embeddings = self.embedder.encode(chunk_texts)

        # 4. Konu Bölümleme
        self.db.update_status(
            lecture_id,
            "chunking",
            85,
            "Ders otomatik konu başlıklarına bölünüyor...",
        )
        chapters = segment_topics(
            chunks=chunks,
            embeddings=embeddings,
            source_chapters=media.source_chapters,
        )

        # 5. Özet & Sınav/Ödev Vurguları
        self.db.update_status(
            lecture_id,
            "summarizing",
            93,
            "Özet, önemli kavramlar ve sınav/ödev vurguları çıkarılıyor...",
        )
        summary_data = build_extractive_summary(
            chunks=chunks,
            embeddings=embeddings,
            chapters=chapters,
            segments=segments,
        )

        self.db.replace_chapters(lecture_id, chapters)
        self.db.replace_chunks(lecture_id, chunks, embeddings)
        self.db.update_lecture_metadata(lecture_id, summary_json=summary_data)
        self.db.update_status(
            lecture_id,
            "completed",
            100,
            f"Hazır ({tr_result['language'].upper()} · {tr_result['device_used']})",
        )

    def process_url(
        self,
        lecture_id: str,
        url: str,
        whisper_model: str,
        language: str | None,
    ) -> None:
        try:
            self.db.update_status(
                lecture_id,
                "downloading",
                8,
                "Bağlantıdan medya indiriliyor (yt-dlp)...",
            )
            media = ingest_url(url, lecture_id, settings.MEDIA_DIR)
            self._run_nlp_stages(lecture_id, media, whisper_model, language)
        except Exception as exc:
            self.db.update_status(
                lecture_id,
                "failed",
                0,
                "İşlem başarısız oldu",
                error_message=str(exc),
            )

    def process_upload(
        self,
        lecture_id: str,
        temp_file: Path,
        original_filename: str,
        whisper_model: str,
        language: str | None,
    ) -> None:
        try:
            self.db.update_status(
                lecture_id,
                "downloading",
                10,
                "Yüklenen dosya ses formatına hazırlanıyor (FFmpeg)...",
            )
            media = ingest_local_file(
                uploaded_path=temp_file,
                original_filename=original_filename,
                lecture_id=lecture_id,
                media_dir=settings.MEDIA_DIR,
            )
            self._run_nlp_stages(lecture_id, media, whisper_model, language)
        except Exception as exc:
            self.db.update_status(
                lecture_id,
                "failed",
                0,
                "İşlem başarısız oldu",
                error_message=str(exc),
            )
        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def delete_media_files(self, lecture_id: str) -> None:
        folder = settings.MEDIA_DIR / lecture_id
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
