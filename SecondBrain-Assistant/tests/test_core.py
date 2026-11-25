from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.archivist import ArchivistAgent, slugify_tr
from app.agents.ingestor import extract_youtube_id, parse_youtube_rss
from app.config import Settings
from app.database import Database
from app.main import create_app
from app.schemas import FlashcardItem, IngestedContent, LearningNote, SectionItem


class FakeSynthesizer:
    model = "gemini-2.5-flash"

    async def synthesize(self, ingested: IngestedContent, focus=None) -> LearningNote:
        return LearningNote(
            title=f"{ingested.title} — Özet",
            tldr="Bu içerik modern çoklu ajan otomasyonunun temel adımlarını anlatır.",
            key_points=[
                "İçerik çekme, analiz ve arşivleme rolleri ayrıştırılır.",
                "Structured Outputs ile JSON şeması garanti edilir.",
                "Aktif hatırlama kartları öğrenmeyi pekiştirir.",
            ],
            detailed_sections=[
                SectionItem(
                    heading="Mimari Akış",
                    content="Üç ajan sırayla çalışarak ham metni Obsidian notuna dönüştürür.",
                )
            ],
            action_items=["İlk notu Obsidian klasörüne kaydet"],
            code_or_tools=["FastAPI", "google-genai", "Obsidian"],
            review_questions=[
                FlashcardItem(
                    question="Structured Outputs neden önemlidir?",
                    answer="Ajanlar arası veri aktarımında format bozulmasını engeller.",
                )
            ],
            tags=["yapay-zeka", "ikinci-beyin", "otomasyon"],
            category="Yapay Zeka",
            estimated_read_minutes=3,
        )

    async def format_transcript(self, ingested: IngestedContent) -> str:
        return (
            "### Düzenlenmiş Giriş\n\n"
            f"{ingested.raw_text}\n\n"
            "Bu bölüm konuşmanın noktalama ve başlıklarla düzenlenmiş tam metnidir."
        )

    async def ask_about_note(self, note, raw_excerpt: str, question: str) -> str:
        return f"'{note.title}' notuna göre yanıt: {question}"


def test_youtube_id_extraction():
    assert extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://youtu.be/dQw4w9WgXcQ?t=10") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://example.com/makale") is None


def test_parse_youtube_rss():
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
          xmlns:media="http://search.yahoo.com/mrss/"
          xmlns="http://www.w3.org/2005/Atom">
      <title>Tuncer Byte</title>
      <entry>
        <yt:videoId>abcDEF12345</yt:videoId>
        <title>AI Agent Otomasyonu</title>
        <published>2026-04-20T10:00:00+00:00</published>
        <media:group>
          <media:thumbnail url="https://i.ytimg.com/vi/abcDEF12345/hqdefault.jpg"/>
        </media:group>
      </entry>
    </feed>"""
    items = parse_youtube_rss(sample_xml, limit=5)
    assert len(items) == 1
    video, ch_title = items[0]
    assert ch_title == "Tuncer Byte"
    assert video.video_id == "abcDEF12345"
    assert video.url == "https://www.youtube.com/watch?v=abcDEF12345"


def test_archivist_turkish_slug_and_markdown(tmp_path: Path):
    assert slugify_tr("Öğrenme Şablonu & Çıktılar!") == "ogrenme-sablonu-ciktilar"
    archivist = ArchivistAgent()
    ingested = IngestedContent(
        source_type="youtube",
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Örnek Video",
        author="Tuncer Byte",
        raw_text="Merhaba dünya",
    )
    note = LearningNote(
        title="Türkçe Öğrenme Özeti",
        tldr="Kısa özet.",
        key_points=["Madde 1", "Madde 2", "Madde 3"],
        detailed_sections=[SectionItem(heading="Giriş", content="Detaylı bilgi.")],
        action_items=["Test çalıştır"],
        code_or_tools=["FastAPI"],
        review_questions=[FlashcardItem(question="Soru?", answer="Cevap.")],
        tags=["yapay-zeka", "test"],
        category="Yazılım",
        estimated_read_minutes=2,
    )
    md = archivist.render_obsidian_markdown(
        note,
        ingested,
        "2026-11-25 13:00:00",
        cleaned_transcript="### Bölüm 1\n\nDüzenlenmiş uzun transkript metni.",
    )
    assert "title: \"Türkçe Öğrenme Özeti\"" in md
    assert "> [!summary] Tek Bakışta Özet" in md
    assert "> [!question]- 1. Soru?" in md
    assert "## Düzenlenmiş Tam Transkript" in md
    assert "Düzenlenmiş uzun transkript metni." in md
    saved_path = archivist.save_markdown_file(tmp_path, note.title, md, "2026-11-25 13:00:00")
    assert saved_path.exists()
    assert saved_path.name == "2026-11-25_turkce-ogrenme-ozeti.md"
    assert "Türkçe Öğrenme Özeti" in saved_path.read_text(encoding="utf-8")


def test_sqlite_and_fastapi_end_to_end(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    settings = Settings(
        gemini_api_key="test-key",
        notes_dir=str(notes_dir),
    )
    # Override data_dir via db_path using custom app with tmp db
    app = create_app(settings)
    app.state.db = Database(tmp_path / "test.db")
    app.state.db.init_db()
    app.state.synthesizer = FakeSynthesizer()

    with TestClient(app) as client:
        r_home = client.get("/")
        assert r_home.status_code == 200
        assert "İkinci Beyin" in r_home.text

        r_status = client.get("/api/status")
        assert r_status.status_code == 200
        assert r_status.json()["gemini_configured"] is True

        # Summarize plain text via JSON endpoint
        r_sum = client.post(
            "/api/summarize",
            json={
                "title": "Test Ders Notu",
                "text": "Bu uzun bir yapay zeka dersi metnidir ve ajan mimarisini anlatır.",
            },
        )
        assert r_sum.status_code == 200
        created_note = r_sum.json()["note"]
        note_id = created_note["id"]
        assert "Düzenlenmiş Giriş" in created_note["cleaned_transcript"]
        assert Path(created_note["markdown_path"]).exists()

        # SSE stream endpoint
        with client.stream(
            "POST",
            "/api/summarize/stream",
            json={"title": "Akış Testi", "text": "Streaming pipeline test içeriği burada."},
        ) as stream_resp:
            assert stream_resp.status_code == 200
            events = []
            for line in stream_resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
            stages = [e["stage"] for e in events]
            assert "ingestor" in stages
            assert "synthesizer" in stages
            assert "archivist" in stages
            assert stages[-1] == "complete"

        # List & search notes
        r_list = client.get("/api/notes", params={"q": "Structured Outputs"})
        assert r_list.status_code == 200
        assert len(r_list.json()["notes"]) == 2

        # Ask follow-up question
        r_ask = client.post(f"/api/notes/{note_id}/ask", json={"question": "Özet nedir?"})
        assert r_ask.status_code == 200
        assert "Özet nedir?" in r_ask.json()["answer"]

        # Download markdown & transcript
        r_md = client.get(f"/api/notes/{note_id}/markdown")
        assert r_md.status_code == 200
        assert "Tek Bakışta Özet" in r_md.text
        assert "Düzenlenmiş Tam Transkript" in r_md.text

        r_tr = client.get(f"/api/notes/{note_id}/transcript")
        assert r_tr.status_code == 200
        assert "Düzenlenmiş Giriş" in r_tr.text

        # Delete note
        r_del = client.delete(f"/api/notes/{note_id}")
        assert r_del.status_code == 200
        assert r_del.json()["deleted"] is True
        assert not Path(created_note["markdown_path"]).exists()


def test_legacy_db_migration(tmp_path: Path):
    import sqlite3

    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE notes (
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
            markdown_path TEXT NOT NULL,
            markdown_content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_file)
    db.init_db()
    conn2 = sqlite3.connect(str(db_file))
    cols = {r[1] for r in conn2.execute("PRAGMA table_info(notes)").fetchall()}
    conn2.close()
    assert "cleaned_transcript" in cols
