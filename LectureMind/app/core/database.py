"""LectureMind SQLite veri tabanı katmanı."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

import numpy as np


class Database:
    """Video, transkript, konu bölümü, vektör parçası ve soru-cevap kalıcılığı."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS lectures (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    platform TEXT,
                    youtube_id TEXT,
                    audio_path TEXT,
                    duration_sec REAL DEFAULT 0,
                    language TEXT,
                    whisper_model TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress_pct INTEGER NOT NULL DEFAULT 0,
                    status_message TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    summary_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lecture_id TEXT NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
                    seq_index INTEGER NOT NULL,
                    start_sec REAL NOT NULL,
                    end_sec REAL NOT NULL,
                    text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lecture_id TEXT NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
                    chapter_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    start_sec REAL NOT NULL,
                    end_sec REAL NOT NULL,
                    summary TEXT DEFAULT '',
                    keywords_json TEXT DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lecture_id TEXT NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    chapter_index INTEGER NOT NULL DEFAULT 0,
                    start_sec REAL NOT NULL,
                    end_sec REAL NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS qa_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lecture_id TEXT NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
                    question TEXT NOT NULL,
                    answer_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_lecture(
        self,
        lecture_id: str,
        title: str,
        source_type: str,
        source_url: str | None = None,
        whisper_model: str = "small",
        language: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO lectures (
                    id, title, source_type, source_url, whisper_model, language,
                    status, progress_pct, status_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, 'İşlem sıraya alındı', ?)
                """,
                (lecture_id, title, source_type, source_url, whisper_model, language, now),
            )
        return self.get_lecture(lecture_id)  # type: ignore[return-value]

    def update_status(
        self,
        lecture_id: str,
        status: str,
        progress_pct: int,
        status_message: str,
        error_message: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE lectures
                SET status = ?, progress_pct = ?, status_message = ?, error_message = ?
                WHERE id = ?
                """,
                (status, progress_pct, status_message, error_message, lecture_id),
            )

    def update_lecture_metadata(self, lecture_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "summary_json" in fields and isinstance(fields["summary_json"], dict):
            fields["summary_json"] = json.dumps(fields["summary_json"], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [lecture_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE lectures SET {cols} WHERE id = ?", vals)

    def replace_segments(self, lecture_id: str, segments: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM segments WHERE lecture_id = ?", (lecture_id,))
            conn.executemany(
                """
                INSERT INTO segments (lecture_id, seq_index, start_sec, end_sec, text)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (lecture_id, idx, s["start"], s["end"], s["text"])
                    for idx, s in enumerate(segments)
                ],
            )

    def replace_chapters(self, lecture_id: str, chapters: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chapters WHERE lecture_id = ?", (lecture_id,))
            conn.executemany(
                """
                INSERT INTO chapters (
                    lecture_id, chapter_index, title, start_sec, end_sec, summary, keywords_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        lecture_id,
                        c["chapter_index"],
                        c["title"],
                        c["start_sec"],
                        c["end_sec"],
                        c.get("summary", ""),
                        json.dumps(c.get("keywords", []), ensure_ascii=False),
                    )
                    for c in chapters
                ],
            )

    def replace_chunks(
        self,
        lecture_id: str,
        chunks: list[dict[str, Any]],
        embeddings: np.ndarray,
    ) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE lecture_id = ?", (lecture_id,))
            rows = []
            for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                emb_bytes = np.asarray(emb, dtype=np.float32).tobytes()
                rows.append(
                    (
                        lecture_id,
                        idx,
                        chunk.get("chapter_index", 0),
                        chunk["start_sec"],
                        chunk["end_sec"],
                        chunk["text"],
                        emb_bytes,
                    )
                )
            conn.executemany(
                """
                INSERT INTO chunks (
                    lecture_id, chunk_index, chapter_index, start_sec, end_sec, text, embedding
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def add_qa(self, lecture_id: str, question: str, answer_payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO qa_history (lecture_id, question, answer_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (lecture_id, question, json.dumps(answer_payload, ensure_ascii=False), now),
            )

    def list_lectures(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source_type, source_url, platform, youtube_id,
                       duration_sec, language, whisper_model, status, progress_pct,
                       status_message, error_message, created_at
                FROM lectures
                ORDER BY created_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lecture(self, lecture_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
            if row is None:
                return None
            data = dict(row)
            try:
                data["summary"] = json.loads(data.get("summary_json") or "{}")
            except json.JSONDecodeError:
                data["summary"] = {}
            return data

    def get_segments(self, lecture_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq_index, start_sec, end_sec, text
                FROM segments
                WHERE lecture_id = ?
                ORDER BY seq_index ASC
                """,
                (lecture_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chapters(self, lecture_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chapter_index, title, start_sec, end_sec, summary, keywords_json
                FROM chapters
                WHERE lecture_id = ?
                ORDER BY chapter_index ASC
                """,
                (lecture_id,),
            ).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["keywords"] = json.loads(item.pop("keywords_json") or "[]")
                result.append(item)
            return result

    def get_chunks(self, lecture_id: str) -> tuple[list[dict[str, Any]], np.ndarray]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_index, chapter_index, start_sec, end_sec, text, embedding
                FROM chunks
                WHERE lecture_id = ?
                ORDER BY chunk_index ASC
                """,
                (lecture_id,),
            ).fetchall()
        if not rows:
            return [], np.empty((0, 0), dtype=np.float32)
        chunks = []
        vecs = []
        for r in rows:
            chunks.append(
                {
                    "chunk_index": r["chunk_index"],
                    "chapter_index": r["chapter_index"],
                    "start_sec": r["start_sec"],
                    "end_sec": r["end_sec"],
                    "text": r["text"],
                }
            )
            vecs.append(np.frombuffer(r["embedding"], dtype=np.float32))
        return chunks, np.vstack(vecs)

    def get_qa_history(self, lecture_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, question, answer_json, created_at
                FROM qa_history
                WHERE lecture_id = ?
                ORDER BY id DESC
                """,
                (lecture_id,),
            ).fetchall()
            result = []
            for r in rows:
                result.append(
                    {
                        "id": r["id"],
                        "question": r["question"],
                        "answer": json.loads(r["answer_json"]),
                        "created_at": r["created_at"],
                    }
                )
            return result

    def delete_lecture(self, lecture_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))
            return cur.rowcount > 0
