"""SQLite veritabanı katmanı: Kelime defteri ve çeviri geçmişi."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from backend.config import DB_FILE
from backend.schemas import HistoryRecord, VocabCreate, VocabRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class AssistantDB:
    """Kelime kartları ve çeviri/yazım geçmişi için hafif SQLite deposu."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vocab (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT NOT NULL UNIQUE,
                    meaning_tr TEXT NOT NULL,
                    cefr_level TEXT NOT NULL DEFAULT 'B1',
                    example_en TEXT NOT NULL DEFAULT '',
                    source_sentence TEXT NOT NULL DEFAULT '',
                    mastered INTEGER NOT NULL DEFAULT 0,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def add_vocab(self, item: VocabCreate) -> VocabRecord:
        now = _utc_now()
        clean_word = item.word.strip()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vocab (word, meaning_tr, cefr_level, example_en, source_sentence, mastered, review_count, created_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, ?)
                ON CONFLICT(word) DO UPDATE SET
                    meaning_tr = excluded.meaning_tr,
                    cefr_level = excluded.cefr_level,
                    example_en = CASE WHEN excluded.example_en != '' THEN excluded.example_en ELSE vocab.example_en END,
                    source_sentence = CASE WHEN excluded.source_sentence != '' THEN excluded.source_sentence ELSE vocab.source_sentence END
                """,
                (
                    clean_word,
                    item.meaning_tr.strip(),
                    item.cefr_level.strip(),
                    item.example_en.strip(),
                    item.source_sentence.strip(),
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM vocab WHERE word = ?", (clean_word,)).fetchone()
            return self._row_to_vocab(row)

    def list_vocab(self, only_unmastered: bool = False) -> List[VocabRecord]:
        query = "SELECT * FROM vocab"
        if only_unmastered:
            query += " WHERE mastered = 0"
        query += " ORDER BY id DESC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
            return [self._row_to_vocab(r) for r in rows]

    def toggle_vocab_mastered(self, vocab_id: int) -> Optional[VocabRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM vocab WHERE id = ?", (vocab_id,)).fetchone()
            if row is None:
                return None
            new_mastered = 0 if row["mastered"] else 1
            conn.execute(
                "UPDATE vocab SET mastered = ?, review_count = review_count + 1 WHERE id = ?",
                (new_mastered, vocab_id),
            )
            updated = conn.execute("SELECT * FROM vocab WHERE id = ?", (vocab_id,)).fetchone()
            return self._row_to_vocab(updated)

    def delete_vocab(self, vocab_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM vocab WHERE id = ?", (vocab_id,))
            return cur.rowcount > 0

    def save_history(self, mode: str, source_text: str, result_json: str) -> HistoryRecord:
        now = _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO history (mode, source_text, result_json, created_at) VALUES (?, ?, ?, ?)",
                (mode, source_text, result_json, now),
            )
            row = conn.execute("SELECT * FROM history WHERE id = ?", (cur.lastrowid,)).fetchone()
            return HistoryRecord(**dict(row))

    def list_history(self, limit: int = 30) -> List[HistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [HistoryRecord(**dict(r)) for r in rows]

    @staticmethod
    def _row_to_vocab(row: sqlite3.Row) -> VocabRecord:
        return VocabRecord(
            id=row["id"],
            word=row["word"],
            meaning_tr=row["meaning_tr"],
            cefr_level=row["cefr_level"],
            example_en=row["example_en"],
            source_sentence=row["source_sentence"],
            mastered=bool(row["mastered"]),
            review_count=row["review_count"],
            created_at=row["created_at"],
        )
