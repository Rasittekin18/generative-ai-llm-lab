from __future__ import annotations

import re
from pathlib import Path

from app.schemas import IngestedContent, LearningNote

TR_CHAR_MAP = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)


def slugify_tr(text: str, max_len: int = 70) -> str:
    """Türkçe karakterleri güvenli dosya adına dönüştürür."""
    normalized = text.translate(TR_CHAR_MAP).lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not normalized:
        normalized = "ogrenme-notu"
    return normalized[:max_len].rstrip("-")


def _yaml_escape(value: str) -> str:
    escaped = value.replace('"', '\\"').replace("\n", " ").strip()
    return f'"{escaped}"'


class ArchivistAgent:
    """3. Ajan: Obsidian uyumlu Markdown (.md) dosyalarını üretir ve diske yazar."""

    def render_obsidian_markdown(
        self,
        note: LearningNote,
        ingested: IngestedContent,
        created_at: str,
        cleaned_transcript: str = "",
    ) -> str:
        clean_tags = [slugify_tr(t.lstrip("#"), max_len=32) for t in note.tags if t.strip()]
        if not clean_tags:
            clean_tags = ["ikinci-beyin"]

        lines: list[str] = [
            "---",
            f"title: {_yaml_escape(note.title)}",
            f"source_type: {ingested.source_type}",
            f"source_url: {_yaml_escape(ingested.source_url or '')}",
            f"author: {_yaml_escape(ingested.author or 'Bilinmiyor')}",
            f"category: {_yaml_escape(note.category)}",
            f"estimated_read_minutes: {note.estimated_read_minutes}",
            f"created_at: {created_at}",
            "tags:",
        ]
        for tag in clean_tags:
            lines.append(f"  - {tag}")
        lines.extend(["---", ""])

        lines.append(f"# {note.title}")
        lines.append("")
        source_badge = {
            "youtube": "YouTube Videosu",
            "article": "Web Makalesi",
            "text": "Kişisel Metin",
        }.get(ingested.source_type, ingested.source_type)

        meta_parts = [f"**Tür:** {source_badge}", f"**Kategori:** {note.category}"]
        if ingested.author:
            meta_parts.append(f"**Kaynak / Kanal:** {ingested.author}")
        if ingested.source_url:
            meta_parts.append(f"**Bağlantı:** [Kaynağa Git]({ingested.source_url})")
        lines.append(" · ".join(meta_parts))
        lines.append("")

        lines.append("> [!summary] Tek Bakışta Özet (TL;DR)")
        lines.append(f"> {note.tldr}")
        lines.append("")

        lines.append("## Önemli Noktalar")
        lines.append("")
        for kp in note.key_points:
            lines.append(f"- {kp}")
        lines.append("")

        if note.detailed_sections:
            lines.append("## Ayrıntılı Bölüm Özeti")
            lines.append("")
            for sec in note.detailed_sections:
                lines.append(f"### {sec.heading}")
                lines.append("")
                lines.append(sec.content)
                lines.append("")

        if note.action_items:
            lines.append("## Uygulanabilir Adımlar")
            lines.append("")
            for action in note.action_items:
                lines.append(f"- [ ] {action}")
            lines.append("")

        if note.code_or_tools:
            lines.append("## Araçlar, Kütüphaneler ve Teknik Kavramlar")
            lines.append("")
            for item in note.code_or_tools:
                lines.append(f"- `{item}`")
            lines.append("")

        if note.review_questions:
            lines.append("## Tekrar Soruları (Aktif Hatırlama)")
            lines.append("")
            for idx, qa in enumerate(note.review_questions, start=1):
                lines.append(f"> [!question]- {idx}. {qa.question}")
                lines.append(f"> {qa.answer}")
                lines.append("")

        if cleaned_transcript.strip():
            lines.append("## Düzenlenmiş Tam Transkript")
            lines.append("")
            lines.append(cleaned_transcript.strip())
            lines.append("")

        lines.append("---")
        lines.append(
            f"*Oluşturulma: {created_at} · Etiketler: "
            + " ".join(f"#{t}" for t in clean_tags)
            + "*"
        )
        lines.append("")
        return "\n".join(lines)

    def save_markdown_file(
        self,
        notes_dir: Path,
        title: str,
        markdown_content: str,
        created_at: str,
    ) -> Path:
        notes_dir.mkdir(parents=True, exist_ok=True)
        date_prefix = created_at[:10]
        slug = slugify_tr(title)
        candidate = notes_dir / f"{date_prefix}_{slug}.md"
        counter = 2
        while candidate.exists():
            candidate = notes_dir / f"{date_prefix}_{slug}-{counter}.md"
            counter += 1

        candidate.write_text(markdown_content, encoding="utf-8")
        return candidate
