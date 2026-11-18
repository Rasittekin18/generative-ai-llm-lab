"""LectureMind FastAPI entegrasyon testleri."""

from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient

from app.api import routes
from app.core.database import Database
from app.main import app


def test_api_lifecycle_and_export(tmp_path: Path, monkeypatch) -> None:
    test_db = Database(tmp_path / "test.db")
    monkeypatch.setattr(routes, "db", test_db)
    monkeypatch.setattr(routes.pipeline, "db", test_db)
    monkeypatch.setattr(
        routes.pipeline.embedder,
        "encode",
        lambda texts: np.ones((len(texts), 4), dtype=np.float32),
    )

    # Örnek tamamlanmış bir ders kaydı yerleştir
    test_db.create_lecture("lec01", "Örnek Seminer", "url", "https://youtu.be/dQw4w9WgXcQ")
    test_db.update_lecture_metadata(
        "lec01",
        platform="youtube",
        youtube_id="dQw4w9WgXcQ",
        duration_sec=120.0,
        language="tr",
        summary_json={
            "overview": "[00:00] Ders özeti.",
            "highlights": {"exams": [], "assignments": [], "keypoints": []},
            "word_count": 10,
        },
    )
    test_db.replace_segments(
        "lec01",
        [{"start": 0.0, "end": 12.0, "text": "Merhaba arkadaşlar, bugün Transformer mimarisini işliyoruz."}],
    )
    test_db.replace_chapters(
        "lec01",
        [{"chapter_index": 0, "title": "Giriş", "start_sec": 0.0, "end_sec": 12.0, "summary": "Özet", "keywords": ["transformer"]}],
    )
    test_db.replace_chunks(
        "lec01",
        [{"chunk_index": 0, "chapter_index": 0, "start_sec": 0.0, "end_sec": 12.0, "text": "Merhaba arkadaşlar, bugün Transformer mimarisini işliyoruz."}],
        np.ones((1, 4), dtype=np.float32),
    )
    test_db.update_status("lec01", "completed", 100, "Hazır")

    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200

    lectures = client.get("/api/lectures").json()
    assert len(lectures) == 1 and lectures[0]["id"] == "lec01"

    search_res = client.get("/api/lectures/lec01/search?q=Transformer").json()
    assert len(search_res["results"]) == 1

    ask_res = client.post("/api/lectures/lec01/ask", json={"question": "Bugün ne işleniyor?"})
    assert ask_res.status_code == 200
    assert "00:00" in ask_res.json()["answer"]

    assert client.get("/api/lectures/lec01/export?fmt=md").status_code == 200
    assert client.get("/api/lectures/lec01/export?fmt=srt").status_code == 200
    assert client.delete("/api/lectures/lec01").status_code == 200
    assert client.get("/api/lectures/lec01").status_code == 404
