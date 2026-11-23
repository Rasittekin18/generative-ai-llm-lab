"""SQLite veritabanı yönetimi ve salt-okunur güvenli SQL yürütücü."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

from core.schemas import DocumentCreateRequest, compute_warranty_end_date


FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|"
    r"PRAGMA|VACUUM|REINDEX|TRANSACTION|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|TRIGGER|VIEW)\b",
    re.IGNORECASE,
)


SCHEMA_DESCRIPTION = """
SQLite Veritabanı Şeması:
1) documents tablosu:
   - id INTEGER PRIMARY KEY
   - file_name TEXT (orijinal dosya adı)
   - document_type TEXT ('fis', 'fatura', 'garanti_belgesi', 'sozlesme', 'diger')
   - merchant_name TEXT (mağaza/satıcı/firma adı)
   - document_date TEXT ('YYYY-MM-DD' biçiminde belge tarihi)
   - currency TEXT ('TRY', 'USD', 'EUR')
   - subtotal REAL (ara toplam)
   - vat_amount REAL (KDV tutarı)
   - total_amount REAL (genel toplam tutar)
   - category TEXT ('Market', 'Teknoloji', 'Yemek', 'Sağlık', 'Giyim', 'Fatura', 'Ulaşım', 'Ev & Yaşam', 'Diğer')
   - warranty_months INTEGER (garanti süresi ay cinsinden, yoksa NULL)
   - warranty_end_date TEXT ('YYYY-MM-DD' garanti bitiş tarihi, yoksa NULL)
   - summary TEXT (belge özeti)
   - warranty_terms TEXT (garanti ve iade koşulları)
   - created_at TEXT

2) line_items tablosu (documents tablosuna document_id ile bağlıdır):
   - id INTEGER PRIMARY KEY
   - document_id INTEGER (documents.id)
   - name TEXT (ürün/hizmet adı)
   - quantity REAL (miktar)
   - unit_price REAL (birim fiyat)
   - total_price REAL (satır toplamı)
   - warranty_months INTEGER
   - warranty_end_date TEXT ('YYYY-MM-DD')
""".strip()


def compute_file_hash(data: bytes) -> str:
    """Dosyanın SHA-256 özetini hesaplar (mükerrer yüklemeyi önlemek için)."""
    return hashlib.sha256(data).hexdigest()


def validate_readonly_sql(sql: str) -> str:
    """Agent tarafından üretilen SQL sorgusunun yalnızca güvenli SELECT olduğunu doğrular."""
    if not sql or not isinstance(sql, str):
        raise ValueError("Boş SQL sorgusu reddedildi.")

    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()

    if ";" in cleaned:
        raise ValueError("Çoklu SQL ifadesine (;) izin verilmez.")
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise ValueError("SQL yorum satırlarına izin verilmez.")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise ValueError("Yalnızca SELECT veya WITH ... SELECT sorgularına izin verilir.")
    if FORBIDDEN_SQL_PATTERN.search(cleaned):
        raise ValueError("Salt-okunur olmayan veya yasaklı SQL anahtar sözcüğü tespit edildi.")

    return cleaned


class DatabaseManager:
    """SQLite veritabanı işlemleri yöneticisi."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
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

    def init_db(self) -> None:
        """Tabloları oluşturur."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    document_type TEXT NOT NULL DEFAULT 'fis',
                    merchant_name TEXT NOT NULL DEFAULT 'Bilinmeyen Satıcı',
                    document_date TEXT,
                    currency TEXT NOT NULL DEFAULT 'TRY',
                    subtotal REAL,
                    vat_amount REAL,
                    total_amount REAL,
                    category TEXT NOT NULL DEFAULT 'Diğer',
                    warranty_months INTEGER,
                    warranty_end_date TEXT,
                    summary TEXT DEFAULT '',
                    warranty_terms TEXT DEFAULT '',
                    raw_text TEXT DEFAULT '',
                    extraction_method TEXT DEFAULT 'manual',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS line_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1.0,
                    unit_price REAL,
                    total_price REAL,
                    warranty_months INTEGER,
                    warranty_end_date TEXT,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(document_date);
                CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
                CREATE INDEX IF NOT EXISTS idx_documents_warranty ON documents(warranty_end_date);
                """
            )

    def find_by_hash(self, file_hash: str) -> Optional[dict[str, Any]]:
        """Aynı hash'e sahip kayıt varsa döndürür."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE file_hash = ?",
                (file_hash,),
            ).fetchone()
            return dict(row) if row else None

    def insert_document(self, doc: DocumentCreateRequest) -> int:
        """Belgeyi ve satır kalemlerini kaydedip yeni document_id döndürür."""
        warranty_end = doc.warranty_end_date or compute_warranty_end_date(
            doc.document_date, doc.warranty_months
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO documents (
                    file_name, file_path, file_hash, mime_type,
                    document_type, merchant_name, document_date, currency,
                    subtotal, vat_amount, total_amount, category,
                    warranty_months, warranty_end_date, summary, warranty_terms,
                    raw_text, extraction_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.file_name,
                    doc.file_path,
                    doc.file_hash,
                    doc.mime_type,
                    doc.document_type,
                    doc.merchant_name,
                    doc.document_date,
                    doc.currency,
                    doc.subtotal,
                    doc.vat_amount,
                    doc.total_amount,
                    doc.category,
                    doc.warranty_months,
                    warranty_end,
                    doc.summary,
                    doc.warranty_terms,
                    doc.raw_text,
                    doc.extraction_method,
                ),
            )
            doc_id = int(cur.lastrowid)

            for item in doc.items:
                item_warranty_months = item.warranty_months or doc.warranty_months
                item_warranty_end = (
                    item.warranty_end_date
                    or compute_warranty_end_date(doc.document_date, item_warranty_months)
                    or warranty_end
                )
                conn.execute(
                    """
                    INSERT INTO line_items (
                        document_id, name, quantity, unit_price, total_price,
                        warranty_months, warranty_end_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        item.name,
                        item.quantity,
                        item.unit_price,
                        item.total_price,
                        item_warranty_months,
                        item_warranty_end,
                    ),
                )
            return doc_id

    def update_document(self, doc_id: int, payload: dict[str, Any]) -> bool:
        """Var olan belgenin alanlarını ve kalemlerini günceller."""
        doc = self.get_document(doc_id)
        if not doc:
            return False

        doc_date = payload.get("document_date", doc["document_date"])
        w_months = payload.get("warranty_months", doc["warranty_months"])
        w_end = payload.get("warranty_end_date") or compute_warranty_end_date(doc_date, w_months)

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE documents
                SET document_type = ?, merchant_name = ?, document_date = ?,
                    currency = ?, subtotal = ?, vat_amount = ?, total_amount = ?,
                    category = ?, warranty_months = ?, warranty_end_date = ?,
                    summary = ?, warranty_terms = ?
                WHERE id = ?
                """,
                (
                    payload.get("document_type", doc["document_type"]),
                    payload.get("merchant_name", doc["merchant_name"]),
                    doc_date,
                    payload.get("currency", doc["currency"]),
                    payload.get("subtotal", doc["subtotal"]),
                    payload.get("vat_amount", doc["vat_amount"]),
                    payload.get("total_amount", doc["total_amount"]),
                    payload.get("category", doc["category"]),
                    w_months,
                    w_end,
                    payload.get("summary", doc["summary"]),
                    payload.get("warranty_terms", doc["warranty_terms"]),
                    doc_id,
                ),
            )
            if "items" in payload and isinstance(payload["items"], list):
                conn.execute("DELETE FROM line_items WHERE document_id = ?", (doc_id,))
                for item in payload["items"]:
                    im = item.get("warranty_months") or w_months
                    ie = (
                        item.get("warranty_end_date")
                        or compute_warranty_end_date(doc_date, im)
                        or w_end
                    )
                    conn.execute(
                        """
                        INSERT INTO line_items (
                            document_id, name, quantity, unit_price, total_price,
                            warranty_months, warranty_end_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc_id,
                            item.get("name", "Ürün"),
                            float(item.get("quantity") or 1.0),
                            item.get("unit_price"),
                            item.get("total_price"),
                            im,
                            ie,
                        ),
                    )
        return True

    def delete_document(self, doc_id: int) -> Optional[dict[str, Any]]:
        """Belgeyi siler ve dosya yolunu temizlemek için silinen kaydı döndürür."""
        doc = self.get_document(doc_id)
        if not doc:
            return None
        with self._connect() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return doc

    def get_document(self, doc_id: int) -> Optional[dict[str, Any]]:
        """Belgeyi ve bağlı kalemlerini döndürür."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                return None
            doc = dict(row)
            items = conn.execute(
                "SELECT * FROM line_items WHERE document_id = ? ORDER BY id ASC",
                (doc_id,),
            ).fetchall()
            doc["items"] = [dict(i) for i in items]
            return doc

    def list_documents(
        self,
        category: Optional[str] = None,
        document_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Belgeleri filtreleyerek listeler."""
        query = "SELECT * FROM documents WHERE 1=1"
        params: list[Any] = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if document_type:
            query += " AND document_type = ?"
            params.append(document_type)
        if search:
            query += " AND (merchant_name LIKE ? OR summary LIKE ? OR raw_text LIKE ? OR file_name LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like, like])
        query += " ORDER BY COALESCE(document_date, created_at) DESC, id DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            docs = []
            for r in rows:
                d = dict(r)
                items = conn.execute(
                    "SELECT * FROM line_items WHERE document_id = ? ORDER BY id ASC",
                    (d["id"],),
                ).fetchall()
                d["items"] = [dict(i) for i in items]
                docs.append(d)
            return docs

    def get_dashboard_stats(self, reference_date: Optional[date] = None) -> dict[str, Any]:
        """Dashboard özet kartları, kategori/ay grafikleri ve yaklaşan garantileri döndürür."""
        today = reference_date or date.today()
        month_prefix = today.strftime("%Y-%m")
        in_30_days = (today + timedelta(days=30)).isoformat()
        in_90_days = (today + timedelta(days=90)).isoformat()
        today_iso = today.isoformat()

        with self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS doc_count,
                    COALESCE(SUM(total_amount), 0) AS total_spend
                FROM documents
                """
            ).fetchone()

            month_spend_row = conn.execute(
                """
                SELECT COALESCE(SUM(total_amount), 0) AS month_spend
                FROM documents
                WHERE document_date LIKE ?
                """,
                (f"{month_prefix}%",),
            ).fetchone()

            by_category = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT category, COUNT(*) AS count, COALESCE(SUM(total_amount), 0) AS total
                    FROM documents
                    GROUP BY category
                    ORDER BY total DESC
                    """
                ).fetchall()
            ]

            by_month = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT substr(document_date, 1, 7) AS month,
                           COUNT(*) AS count,
                           COALESCE(SUM(total_amount), 0) AS total
                    FROM documents
                    WHERE document_date IS NOT NULL AND length(document_date) >= 7
                    GROUP BY substr(document_date, 1, 7)
                    ORDER BY month ASC
                    LIMIT 12
                    """
                ).fetchall()
            ]

            warranties = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT id, merchant_name, file_name, document_date,
                           warranty_months, warranty_end_date, total_amount, summary
                    FROM documents
                    WHERE warranty_end_date IS NOT NULL
                    ORDER BY warranty_end_date ASC
                    """
                ).fetchall()
            ]

        expiring_30 = 0
        active_warranties = 0
        for w in warranties:
            w_end = w["warranty_end_date"]
            try:
                days_left = (date.fromisoformat(w_end[:10]) - today).days
            except ValueError:
                days_left = None
            w["days_left"] = days_left
            if days_left is not None:
                if days_left < 0:
                    w["status"] = "expired"
                elif days_left <= 30:
                    w["status"] = "expiring_soon"
                    expiring_30 += 1
                    active_warranties += 1
                elif w_end <= in_90_days:
                    w["status"] = "watch"
                    active_warranties += 1
                else:
                    w["status"] = "active"
                    active_warranties += 1

        return {
            "reference_date": today_iso,
            "doc_count": int(totals["doc_count"]),
            "total_spend": round(float(totals["total_spend"]), 2),
            "month_spend": round(float(month_spend_row["month_spend"]), 2),
            "active_warranties": active_warranties,
            "expiring_30_days": expiring_30,
            "by_category": by_category,
            "by_month": by_month,
            "warranties": warranties,
            "in_30_days_cutoff": in_30_days,
        }

    def execute_safe_readonly_sql(self, sql: str, max_rows: int = 50) -> list[dict[str, Any]]:
        """Salt-okunur URI bağlantısı üzerinden doğrulanmış SELECT sorgusu çalıştırır."""
        cleaned = validate_readonly_sql(sql)
        ro_uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(ro_uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only = ON;")
            rows = conn.execute(cleaned).fetchmany(max_rows)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def append_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_history (session_id, role, content, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def get_chat_history(self, session_id: str = "default", limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, metadata_json, created_at
                FROM chat_history
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        items = []
        for r in reversed(rows):
            d = dict(r)
            try:
                d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                d["metadata"] = {}
            items.append(d)
        return items

    def clear_chat_history(self, session_id: str = "default") -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
