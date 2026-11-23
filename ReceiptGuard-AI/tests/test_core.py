"""Çekirdek güvenlik, veritabanı, RAG, çıkarım ve FastAPI uç nokta testleri."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from config import Settings
from core.database import DatabaseManager, validate_readonly_sql
from core.llm_provider import VisionModelUnavailableError, extract_json_object
from core.rag_engine import RAGEngine
from core.schemas import DocumentCreateRequest, LineItemIn, compute_warranty_end_date


class FakeEmbedder:
    """Testler için deterministik hafif metin gömme modeli (ağ veya ağır model yüklemez)."""

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = []
        keywords = ["kulaklık", "garanti", "sıvı", "kahve", "market", "zeytinyağı", "iade", "fatura"]
        for t in texts:
            low = t.lower()
            v = np.array([float(low.count(k)) for k in keywords] + [1.0], dtype=np.float32)
            v = v / np.linalg.norm(v)
            vecs.append(v)
        return np.vstack(vecs).astype(np.float32)


class FakeLLMRouter:
    """Testler için kontrol edilebilir sahte LLM/VLM yönlendiricisi."""

    def __init__(self, vision_available: bool = True):
        self.vision_available = vision_available

    def check_ollama_health(self) -> dict[str, Any]:
        return {
            "running": True,
            "error": None,
            "models": ["qwen3:4b", "qwen2.5:3b"] + (["qwen2.5vl:3b"] if self.vision_available else []),
            "vision_models": ["qwen2.5vl:3b"] if self.vision_available else [],
            "recommended_llm": "qwen3:4b",
        }

    def chat_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> tuple[dict[str, Any], str]:
        sys_prompt = messages[0]["content"]
        user_msg = messages[-1]["content"]

        if "yönlendiricisisin" in sys_prompt:
            if "toplam" in user_msg.lower() and "şart" in user_msg.lower():
                return {"route": "hybrid", "reason": "hem sayısal hem metin"}, "fake/qwen3:4b"
            if "toplam" in user_msg.lower() or "kaç" in user_msg.lower():
                return {"route": "sql", "reason": "sayısal sorgu"}, "fake/qwen3:4b"
            return {"route": "rag", "reason": "şart arama"}, "fake/qwen3:4b"

        if "SQLite SQL üreticisisin" in sys_prompt:
            return {
                "sql": "SELECT category, SUM(total_amount) AS toplam FROM documents GROUP BY category"
            }, "fake/qwen3:4b"

        # PDF extraction
        return {
            "document_type": "fatura",
            "merchant_name": "PDF Test Mağaza",
            "document_date": "2026-10-01",
            "currency": "TRY",
            "total_amount": 1500.0,
            "category": "Teknoloji",
            "warranty_months": 24,
            "summary": "PDF fatura testi",
            "warranty_terms": "24 ay garanti kapsamındadır.",
            "items": [{"name": "Bluetooth Mouse", "quantity": 1, "total_price": 1500.0}],
        }, "fake/qwen3:4b"

    def chat_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        images_b64: list[str],
        mime_type: str = "image/png",
    ) -> tuple[dict[str, Any], str]:
        if not self.vision_available:
            raise VisionModelUnavailableError("VLM modeli yüklü değil. 'ollama pull qwen2.5vl:3b' çalıştırın.")
        return {
            "document_type": "fis",
            "merchant_name": "VLM Test Market",
            "document_date": "2026-11-10",
            "currency": "TRY",
            "total_amount": 450.25,
            "vat_amount": 40.0,
            "category": "Market",
            "summary": "VLM ile okunan market fişi",
            "warranty_terms": "",
            "raw_text": "VLM Test Market Zeytinyağı 450.25 TL",
            "items": [{"name": "Zeytinyağı", "quantity": 1, "total_price": 450.25}],
        }, "fake/qwen2.5vl:3b"

    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> tuple[str, str]:
        user_content = messages[-1]["content"]
        return f"Test yanıtı (kaynaklı): {user_content[:120]}", "fake/qwen3:4b"


@pytest.fixture()
def temp_settings(tmp_path: Path) -> Settings:
    cfg = Settings(
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        db_path=tmp_path / "data" / "app.db",
        vector_dir=tmp_path / "data" / "vector_index",
    )
    cfg.ensure_dirs()
    return cfg


def test_sql_guardrail_blocks_dangerous_queries(temp_settings: Settings) -> None:
    db = DatabaseManager(temp_settings.db_path)

    assert validate_readonly_sql("SELECT COUNT(*) FROM documents;") == "SELECT COUNT(*) FROM documents"
    assert validate_readonly_sql("WITH x AS (SELECT * FROM documents) SELECT * FROM x")

    dangerous = [
        "DROP TABLE documents",
        "DELETE FROM documents WHERE id = 1",
        "UPDATE documents SET total_amount = 0",
        "INSERT INTO documents (file_name, file_path, file_hash) VALUES ('a','b','c')",
        "SELECT * FROM documents; DROP TABLE documents",
        "SELECT * FROM documents -- comment",
        "PRAGMA writable_schema = ON",
        "ATTACH DATABASE 'evil.db' AS evil",
    ]
    for sql in dangerous:
        with pytest.raises(ValueError):
            db.execute_safe_readonly_sql(sql)


def test_extract_json_handles_qwen3_think_and_fences() -> None:
    raw = """<think>Düşünüyorum...</think>
    ```json
    {"route": "sql", "reason": "sayısal"}
    ```"""
    parsed = extract_json_object(raw)
    assert parsed["route"] == "sql"


def test_warranty_end_date_calculation() -> None:
    assert compute_warranty_end_date("2025-01-15", 24) == "2027-01-15"
    assert compute_warranty_end_date("2025-01-15", None) is None


def test_rag_index_search_and_delete(temp_settings: Settings) -> None:
    rag = RAGEngine(temp_settings.vector_dir, FakeEmbedder())
    rag.index_document(
        {
            "id": 1,
            "file_name": "kulaklik.png",
            "merchant_name": "TeknoMarket",
            "document_date": "2026-01-01",
            "document_type": "fatura",
            "category": "Teknoloji",
            "total_amount": 3500,
            "currency": "TRY",
            "summary": "Kulaklık faturası",
            "warranty_terms": "Sıvı teması kullanıcı hatasıdır ve garanti kapsamı dışındadır.",
            "items": [{"name": "Kulaklık", "quantity": 1, "total_price": 3500}],
        }
    )
    rag.index_document(
        {
            "id": 2,
            "file_name": "market.png",
            "merchant_name": "Migros",
            "document_date": "2026-01-02",
            "document_type": "fis",
            "category": "Market",
            "total_amount": 400,
            "currency": "TRY",
            "summary": "Zeytinyağı ve kahve fişi",
            "warranty_terms": "",
            "items": [{"name": "Zeytinyağı", "quantity": 1, "total_price": 400}],
        }
    )

    hits = rag.search("Kulaklık sıvı teması garanti dışı mı?", top_k=2)
    assert hits[0]["document_id"] == 1

    rag.delete_document(1)
    hits_after = rag.search("Kulaklık", top_k=2)
    assert all(h["document_id"] != 1 for h in hits_after)


def test_fastapi_end_to_end_upload_save_dashboard_chat_delete(temp_settings: Settings) -> None:
    app = create_app(
        app_settings=temp_settings,
        embedder=FakeEmbedder(),
        llm_router=FakeLLMRouter(vision_available=True),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    # 1. Status check
    st = client.get("/api/status")
    assert st.status_code == 200
    assert st.json()["ollama"]["running"] is True

    # 2. Image extract preview
    img = Image.new("RGB", (120, 120), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    ext_res = client.post(
        "/api/documents/extract",
        files={"file": ("test_fis.png", buf.getvalue(), "image/png")},
    )
    assert ext_res.status_code == 200
    ext_json = ext_res.json()
    assert ext_json["status"] == "extracted"
    assert ext_json["extracted"]["merchant_name"] == "VLM Test Market"

    # 3. Confirm & Save
    save_payload = {
        **ext_json["extracted"],
        "file_name": ext_json["file_name"],
        "file_path": ext_json["file_path"],
        "file_hash": ext_json["file_hash"],
        "mime_type": ext_json["mime_type"],
        "extraction_method": ext_json["extraction_method"],
    }
    save_res = client.post("/api/documents", json=save_payload)
    assert save_res.status_code == 200
    doc_id = save_res.json()["document"]["id"]

    # 4. Duplicate upload check
    dup_res = client.post(
        "/api/documents/extract",
        files={"file": ("test_fis.png", buf.getvalue(), "image/png")},
    )
    assert dup_res.status_code == 200
    assert dup_res.json()["status"] == "duplicate"
    assert dup_res.json()["duplicate_document_id"] == doc_id

    # 5. Dashboard check
    dash = client.get("/api/dashboard").json()
    assert dash["doc_count"] == 1
    assert dash["total_spend"] == pytest.approx(450.25)

    # 6. Chat SQL + Hybrid check
    chat_res = client.post("/api/chat", json={"question": "Toplam ne kadar harcadım?"})
    assert chat_res.status_code == 200
    chat_json = chat_res.json()
    assert chat_json["route_used"] == "sql"
    assert "SELECT" in (chat_json["sql_query"] or "")

    # 7. Delete check
    del_res = client.delete(f"/api/documents/{doc_id}")
    assert del_res.status_code == 200
    assert client.get("/api/dashboard").json()["doc_count"] == 0


def test_missing_vlm_gracefully_returns_manual_review(temp_settings: Settings) -> None:
    app = create_app(
        app_settings=temp_settings,
        embedder=FakeEmbedder(),
        llm_router=FakeLLMRouter(vision_available=False),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    img = Image.new("RGB", (60, 60), color="gray")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    res = client.post(
        "/api/documents/extract",
        files={"file": ("fis.png", buf.getvalue(), "image/png")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "needs_manual_review"
    assert "ollama pull" in body["message"]


def test_pdf_extraction_flow(temp_settings: Settings) -> None:
    from reportlab.pdfgen import canvas

    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf)
    c.drawString(72, 750, "TeknoMarket Elektronik Fatura - Tarih: 2026-10-01")
    c.drawString(72, 730, "Urun: Bluetooth Mouse - Toplam: 1500.00 TRY - Garanti: 24 ay")
    c.save()

    app = create_app(
        app_settings=temp_settings,
        embedder=FakeEmbedder(),
        llm_router=FakeLLMRouter(vision_available=False),  # type: ignore[arg-type]
    )
    client = TestClient(app)
    res = client.post(
        "/api/documents/extract",
        files={"file": ("fatura.pdf", pdf_buf.getvalue(), "application/pdf")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "extracted"
    assert body["extracted"]["merchant_name"] == "PDF Test Mağaza"
    assert body["extracted"]["warranty_end_date"] == "2028-10-01"
