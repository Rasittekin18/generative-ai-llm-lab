"""Backend, Veritabanı, JSON ayrıştırıcı ve NLP hattı için birim ve entegrasyon testleri."""

import pytest
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.db import AssistantDB
from backend.llm_client import extract_json_object
from backend.nlp_pipeline import LocalNLPPipeline
from backend.schemas import AppSettings, VocabCreate


def test_extract_json_with_markdown_fences():
    raw = """İşte yanıtınız:
```json
{
  "natural_translation": "Merhaba dünya",
  "nuance_explanation": "Klasik selamlama.",
  "vocabulary": []
}
```"""
    parsed = extract_json_object(raw)
    assert parsed["natural_translation"] == "Merhaba dünya"


def test_db_vocab_crud_and_history(tmp_path):
    db = AssistantDB(db_path=tmp_path / "test.db")
    created = db.add_vocab(
        VocabCreate(
            word="circle back",
            meaning_tr="sonradan tekrar dönmek",
            cefr_level="B2",
            example_en="Let's circle back tomorrow.",
            source_sentence="Let's circle back after deploy.",
        )
    )
    assert created.id > 0
    assert created.mastered is False

    items = db.list_vocab(only_unmastered=True)
    assert len(items) == 1

    toggled = db.toggle_vocab_mastered(created.id)
    assert toggled is not None
    assert toggled.mastered is True
    assert toggled.review_count == 1
    assert db.list_vocab(only_unmastered=True) == []

    hist = db.save_history("analyze", "Hello world", '{"natural_translation":"Merhaba"}')
    assert hist.id == 1
    assert len(db.list_history()) == 1

    assert db.delete_vocab(created.id) is True
    assert db.list_vocab() == []


def test_nlp_pipeline_heuristics_and_lang_detection():
    pipe = LocalNLPPipeline()
    settings = AppSettings(local_hf_enabled=False)

    ctx, conf = pipe.classify_context("Please deploy the Python API after fixing this bug.", settings)
    assert ctx == "Teknik / Yazılım"
    assert conf > 0.5

    ents = pipe.extract_entities("John works at Google in Berlin.", settings)
    words = {e.word for e in ents}
    assert "Google" in words
    assert "Berlin" in words

    assert pipe.detect_language_simple("Bu cümleyi profesyonel İngilizceye çevir") == "tr"
    assert pipe.detect_language_simple("naber nasilsin bu kodu cevir") == "tr"
    assert pipe.detect_language_simple("Could you review this pull request?") == "en"


def test_fastapi_endpoints_with_isolated_db(tmp_path, monkeypatch):
    test_db = AssistantDB(db_path=tmp_path / "api_test.db")
    test_settings = AppSettings(local_hf_enabled=False, llm_provider="groq", llm_api_key="")

    monkeypatch.setattr(backend_main, "db", test_db)
    monkeypatch.setattr(backend_main, "load_settings", lambda: test_settings)
    monkeypatch.setattr(backend_main, "save_settings", lambda s: s)

    client = TestClient(backend_main.app)

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_analyze = client.post(
        "/api/analyze",
        json={"text": "We need to deploy the FastAPI service to Google Cloud.", "source_context_hint": "VS Code"},
    )
    assert r_analyze.status_code == 200
    data = r_analyze.json()
    assert data["detected_context"] == "Teknik / Yazılım"
    assert data["source_language"] == "en"
    assert data["target_language"] == "tr"
    assert any(e["word"] == "Google" for e in data["entities"])

    r_analyze_tr = client.post(
        "/api/analyze",
        json={"text": "Herhangi bir hata mesajı görürseniz çıktıyı bana gönderin."},
    )
    assert r_analyze_tr.status_code == 200
    assert r_analyze_tr.json()["source_language"] == "tr"
    assert r_analyze_tr.json()["target_language"] == "en"

    r_write = client.post(
        "/api/write",
        json={"text": "Bu hatayı düzeltmeme yardım et", "tone": "Technical Prompt", "mode": "tr_to_en"},
    )
    assert r_write.status_code == 200
    assert r_write.json()["detected_language"] == "tr"

    r_vocab = client.post(
        "/api/vocab",
        json={"word": "deploy", "meaning_tr": "canlıya almak", "cefr_level": "B2"},
    )
    assert r_vocab.status_code == 200
    vid = r_vocab.json()["id"]

    assert len(client.get("/api/vocab").json()) == 1
    assert client.patch(f"/api/vocab/{vid}/toggle").json()["mastered"] is True
    assert client.delete(f"/api/vocab/{vid}").json()["deleted"] is True
    assert len(client.get("/api/history").json()) == 3


def test_win64_sendinput_struct_size():
    import ctypes
    import sys

    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        from desktop.clipboard_capture import INPUT

        assert ctypes.sizeof(INPUT) == 40
