from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.schemas import (
    ChannelRecord,
    FlashcardItem,
    IngestedContent,
    LearningNote,
    NoteRecord,
    SectionItem,
)


class Database:
    """SQLite tabanlı kalıcı not ve kanal arşivi."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    author TEXT,
                    category TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    tldr TEXT NOT NULL,
                    key_points_json TEXT NOT NULL,
                    detailed_sections_json TEXT NOT NULL,
                    action_items_json TEXT NOT NULL,
                    code_or_tools_json TEXT NOT NULL,
                    review_questions_json TEXT NOT NULL,
                    estimated_read_minutes INTEGER NOT NULL DEFAULT 3,
                    raw_excerpt TEXT NOT NULL DEFAULT '',
                    cleaned_transcript TEXT NOT NULL DEFAULT '',
                    markdown_path TEXT NOT NULL,
                    markdown_content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(notes)").fetchall()
            }
            if "cleaned_transcript" not in cols:
                conn.execute(
                    "ALTER TABLE notes ADD COLUMN cleaned_transcript TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    handle_or_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save_note(
        self,
        note: LearningNote,
        ingested: IngestedContent,
        markdown_path: Path,
        markdown_content: str,
        created_at: str,
        cleaned_transcript: str = "",
    ) -> NoteRecord:
        tags_clean = [t.lstrip("#").strip() for t in note.tags if t.strip()]
        raw_excerpt = ingested.raw_text[:12000]
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO notes (
                    title, source_type, source_url, author, category,
                    tags_json, tldr, key_points_json, detailed_sections_json,
                    action_items_json, code_or_tools_json, review_questions_json,
                    estimated_read_minutes, raw_excerpt, cleaned_transcript,
                    markdown_path, markdown_content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note.title,
                    ingested.source_type,
                    ingested.source_url,
                    ingested.author,
                    note.category,
                    json.dumps(tags_clean, ensure_ascii=False),
                    note.tldr,
                    json.dumps(note.key_points, ensure_ascii=False),
                    json.dumps(
                        [s.model_dump() for s in note.detailed_sections],
                        ensure_ascii=False,
                    ),
                    json.dumps(note.action_items, ensure_ascii=False),
                    json.dumps(note.code_or_tools, ensure_ascii=False),
                    json.dumps(
                        [q.model_dump() for q in note.review_questions],
                        ensure_ascii=False,
                    ),
                    note.estimated_read_minutes,
                    raw_excerpt,
                    cleaned_transcript,
                    str(markdown_path),
                    markdown_content,
                    created_at,
                ),
            )
            note_id = cur.lastrowid
        record = self.get_note(int(note_id))
        assert record is not None
        return record

    def _row_to_note(self, row: sqlite3.Row) -> NoteRecord:
        keys = row.keys()
        cleaned = row["cleaned_transcript"] if "cleaned_transcript" in keys else ""
        return NoteRecord(
            id=row["id"],
            title=row["title"],
            source_type=row["source_type"],
            source_url=row["source_url"],
            author=row["author"],
            category=row["category"],
            tags=json.loads(row["tags_json"]),
            tldr=row["tldr"],
            key_points=json.loads(row["key_points_json"]),
            detailed_sections=[
                SectionItem(**s) for s in json.loads(row["detailed_sections_json"])
            ],
            action_items=json.loads(row["action_items_json"]),
            code_or_tools=json.loads(row["code_or_tools_json"]),
            review_questions=[
                FlashcardItem(**q) for q in json.loads(row["review_questions_json"])
            ],
            estimated_read_minutes=row["estimated_read_minutes"],
            cleaned_transcript=cleaned or "",
            markdown_path=row["markdown_path"],
            markdown_content=row["markdown_content"],
            created_at=row["created_at"],
        )

    def list_notes(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        source_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> list[NoteRecord]:
        sql = "SELECT * FROM notes WHERE 1=1"
        params: list[object] = []

        if category:
            sql += " AND LOWER(category) = LOWER(?)"
            params.append(category.strip())
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type.strip())
        if tag:
            sql += " AND LOWER(tags_json) LIKE LOWER(?)"
            params.append(f'%"{tag.lstrip("#").strip()}"%')
        if query:
            like = f"%{query.strip()}%"
            sql += (
                " AND (title LIKE ? OR tldr LIKE ? OR key_points_json LIKE ?"
                " OR tags_json LIKE ? OR cleaned_transcript LIKE ? OR markdown_content LIKE ?)"
            )
            params.extend([like, like, like, like, like, like])

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_note(r) for r in rows]

    def get_note(self, note_id: int) -> Optional[NoteRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return self._row_to_note(row) if row else None

    def get_note_context(self, note_id: int) -> Optional[tuple[NoteRecord, str]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            return None
        return self._row_to_note(row), row["raw_excerpt"]

    def delete_note(self, note_id: int) -> Optional[NoteRecord]:
        existing = self.get_note(note_id)
        if not existing:
            return None
        with self._connect() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return existing

    def get_stats(self) -> dict[str, object]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"]
            by_type_rows = conn.execute(
                "SELECT source_type, COUNT(*) AS c FROM notes GROUP BY source_type"
            ).fetchall()
            cat_rows = conn.execute(
                "SELECT DISTINCT category FROM notes ORDER BY category"
            ).fetchall()
            ch_count = conn.execute("SELECT COUNT(*) AS c FROM channels").fetchone()["c"]

        by_type = {r["source_type"]: r["c"] for r in by_type_rows}
        categories = [r["category"] for r in cat_rows]
        return {
            "total_notes": total,
            "by_source_type": by_type,
            "categories": categories,
            "followed_channels": ch_count,
        }

    def add_channel(
        self, channel_id: str, title: str, handle_or_url: str, created_at: str
    ) -> ChannelRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO channels (channel_id, title, handle_or_url, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    title = excluded.title,
                    handle_or_url = excluded.handle_or_url
                """,
                (channel_id, title, handle_or_url, created_at),
            )
            row = conn.execute(
                "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
            ).fetchone()
        assert row is not None
        return ChannelRecord(**dict(row))

    def list_channels(self) -> list[ChannelRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM channels ORDER BY id DESC").fetchall()
        return [ChannelRecord(**dict(r)) for r in rows]

    def delete_channel(self, row_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM channels WHERE id = ?", (row_id,))
        return cur.rowcount > 0
