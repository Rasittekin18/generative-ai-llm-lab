from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Optional

from app.agents.pipeline import run_pipeline_stream
from app.config import Settings
from app.database import Database
from app.schemas import NoteRecord, SummarizeRequest

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"https?://[^\s<>\"']+")


def split_telegram_message(text: str, max_len: int = 3900) -> list[str]:
    """Telegram'ın 4096 karakter sınırına takılmamak için metni satır bazlı böler."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_len and current:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current).strip())
    return chunks


def format_note_for_telegram(note: NoteRecord) -> str:
    """Not özetini Telegram'da okunaklı biçimde formatlar."""
    lines = [
        f"🧠 {note.title}",
        f"📂 {note.category} · ⏱ {note.estimated_read_minutes} dk okuma",
        "",
        f"📌 TEK BAKIŞTA ÖZET",
        note.tldr,
        "",
        "💡 ÖNEMLİ NOKTALAR",
    ]
    for kp in note.key_points:
        lines.append(f"• {kp}")

    if note.action_items:
        lines.extend(["", "✅ UYGULANABİLİR ADIMLAR"])
        for act in note.action_items[:5]:
            lines.append(f"☐ {act}")

    if note.review_questions:
        lines.extend(["", "🎯 TEKRAR SORULARI"])
        for idx, qa in enumerate(note.review_questions[:4], start=1):
            lines.append(f"{idx}. S: {qa.question}")
            lines.append(f"   C: {qa.answer}")

    tags_str = " ".join(f"#{t}" for t in note.tags)
    lines.extend(
        [
            "",
            f"🏷 {tags_str}",
            f"💾 Arşiv: {Path(note.markdown_path).name}",
        ]
    )
    return "\n".join(lines)


class TelegramBotRunner:
    """FastAPI lifespan içinde arka planda çalışan ücretsiz polling Telegram botu."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.app = None
        self.running = False
        self.last_error: Optional[str] = None

    def _is_authorized(self, user_id: Optional[int]) -> bool:
        allowed = self.settings.allowed_telegram_ids
        if not allowed:
            return True
        return user_id is not None and user_id in allowed

    async def start(self) -> None:
        if not self.settings.telegram_configured:
            return

        try:
            from telegram import BotCommand, Update
            from telegram.ext import (
                Application,
                CommandHandler,
                ContextTypes,
                MessageHandler,
                filters,
            )

            app = (
                Application.builder()
                .token(self.settings.telegram_bot_token.strip())
                .build()
            )

            async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message:
                    return
                uid = update.effective_user.id if update.effective_user else None
                if not self._is_authorized(uid):
                    await update.message.reply_text(
                        f"Bu bot yalnızca yetkili kullanıcılara açıktır. Telegram ID: {uid}"
                    )
                    return
                await update.message.reply_text(
                    "👋 Merhaba! Ben Kişisel İkinci Beyin & Öğrenme Asistanınım.\n\n"
                    "Bana bir YouTube video linki veya teknik makale URL'si gönder:\n"
                    "• Altyazıyı / içeriği çıkarırım\n"
                    "• Gemini ile Türkçe özet + tekrar soruları hazırlarım\n"
                    "• Obsidian uyumlu .md dosyası olarak kaydedip sana gönderirim\n\n"
                    "Komutlar:\n"
                    "/son — Son kaydedilen 5 not\n"
                    "/transkript — Son notun düzenlenmiş tam transkripti\n"
                    "/ara <kelime> — Arşivde arama\n"
                    "/yardim — Kullanım bilgisi"
                )

            async def _send_transcript_delivery(
                message, note: NoteRecord, force_chat: bool = False
            ) -> None:
                cleaned = (note.cleaned_transcript or "").strip()
                if not cleaned:
                    if force_chat:
                        await message.reply_text(
                            "Bu not için düzenlenmiş transkript bulunmuyor."
                        )
                    return

                header = f"📝 DÜZENLENMİŞ TRANSKRİPT — {note.title}\n\n"
                full_text = header + cleaned
                stem = Path(note.markdown_path).stem or f"not-{note.id}"

                if len(full_text) <= 10500:
                    for chunk in split_telegram_message(full_text):
                        await message.reply_text(chunk, disable_web_page_preview=True)
                else:
                    preview = (
                        f"📝 DÜZENLENMİŞ TRANSKRİPT (Önizleme — tamamı ekteki dosyada)\n"
                        f"{note.title}\n\n"
                        + cleaned[:3500].rstrip()
                        + "..."
                    )
                    await message.reply_text(preview, disable_web_page_preview=True)
                    transcript_bytes = (
                        f"# {note.title} — Düzenlenmiş Transkript\n\n{cleaned}\n"
                    ).encode("utf-8")
                    buf = io.BytesIO(transcript_bytes)
                    buf.name = f"{stem}_transkript.md"
                    await message.reply_document(
                        document=buf,
                        filename=f"{stem}_transkript.md",
                        caption="📄 Düzenlenmiş tam transkript dosyası.",
                    )

            async def cmd_transcript(
                update: Update, context: ContextTypes.DEFAULT_TYPE
            ) -> None:
                if not update.message:
                    return
                uid = update.effective_user.id if update.effective_user else None
                if not self._is_authorized(uid):
                    return
                target_note: Optional[NoteRecord] = None
                if context.args and context.args[0].isdigit():
                    target_note = self.db.get_note(int(context.args[0]))
                else:
                    notes = self.db.list_notes(limit=1)
                    target_note = notes[0] if notes else None
                if not target_note:
                    await update.message.reply_text("Henüz kaydedilmiş bir not yok.")
                    return
                await _send_transcript_delivery(
                    update.message, target_note, force_chat=True
                )

            async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message:
                    return
                uid = update.effective_user.id if update.effective_user else None
                if not self._is_authorized(uid):
                    return
                notes = self.db.list_notes(limit=5)
                if not notes:
                    await update.message.reply_text("Henüz kaydedilmiş bir not yok.")
                    return
                lines = ["📚 Son 5 Öğrenme Notun:\n"]
                for n in notes:
                    lines.append(f"• [{n.category}] {n.title}\n  {n.tldr[:120]}...")
                await update.message.reply_text("\n".join(lines))

            async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message:
                    return
                uid = update.effective_user.id if update.effective_user else None
                if not self._is_authorized(uid):
                    return
                query = " ".join(context.args).strip()
                if not query:
                    await update.message.reply_text("Kullanım: /ara <aranacak kelime>")
                    return
                notes = self.db.list_notes(query=query, limit=5)
                if not notes:
                    await update.message.reply_text(f"'{query}' için kayıtlı not bulunamadı.")
                    return
                lines = [f"🔍 '{query}' için sonuçlar:\n"]
                for n in notes:
                    lines.append(f"• {n.title} ({n.category})\n  {n.tldr[:120]}...")
                await update.message.reply_text("\n".join(lines))

            async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                if not update.message or not update.message.text:
                    return
                uid = update.effective_user.id if update.effective_user else None
                if not self._is_authorized(uid):
                    await update.message.reply_text(
                        f"Yetkisiz erişim. Telegram ID: {uid}"
                    )
                    return

                raw_text = update.message.text.strip()
                url_match = URL_REGEX.search(raw_text)
                if url_match:
                    found_url = url_match.group(0)
                    extra_focus = URL_REGEX.sub("", raw_text).strip() or None
                    req = SummarizeRequest(url=found_url, focus=extra_focus)
                elif len(raw_text) >= 40:
                    req = SummarizeRequest(text=raw_text)
                else:
                    await update.message.reply_text(
                        "Özetlemem için geçerli bir YouTube/makale linki veya en az 40 karakterlik bir metin gönder."
                    )
                    return

                status_msg = await update.message.reply_text(
                    "⏳ Ajanlar çalışmaya başladı..."
                )
                final_note: Optional[NoteRecord] = None
                error_msg: Optional[str] = None

                async for ev in run_pipeline_stream(req, self.settings, self.db):
                    if ev.stage in ("ingestor", "synthesizer", "archivist") and ev.status == "running":
                        try:
                            await status_msg.edit_text(f"⏳ {ev.message}")
                        except Exception:
                            pass
                    elif ev.stage == "complete" and ev.data and "note" in ev.data:
                        final_note = NoteRecord(**ev.data["note"])
                    elif ev.stage == "error":
                        error_msg = ev.message

                if error_msg or final_note is None:
                    await status_msg.edit_text(
                        f"❌ İşlem başarısız: {error_msg or 'Bilinmeyen hata'}"
                    )
                    return

                try:
                    await status_msg.delete()
                except Exception:
                    pass

                formatted = format_note_for_telegram(final_note)
                for chunk in split_telegram_message(formatted):
                    await update.message.reply_text(chunk, disable_web_page_preview=True)

                await _send_transcript_delivery(update.message, final_note)

                md_path = Path(final_note.markdown_path)
                if md_path.exists():
                    with md_path.open("rb") as f:
                        await update.message.reply_document(
                            document=f,
                            filename=md_path.name,
                            caption="📎 Özet + transkript içeren Obsidian Markdown notun hazır.",
                        )

            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("yardim", cmd_start))
            app.add_handler(CommandHandler("help", cmd_start))
            app.add_handler(CommandHandler("son", cmd_recent))
            app.add_handler(CommandHandler("transkript", cmd_transcript))
            app.add_handler(CommandHandler("ara", cmd_search))
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            )

            await app.initialize()
            try:
                await app.bot.set_my_commands(
                    [
                        BotCommand("start", "Asistanı başlat ve kullanımı gör"),
                        BotCommand("son", "Son kaydedilen 5 notu listele"),
                        BotCommand("transkript", "Son notun düzenlenmiş transkriptini getir"),
                        BotCommand("ara", "Not arşivinde kelime ara"),
                        BotCommand("yardim", "Komut listesi ve kullanım bilgisi"),
                    ]
                )
            except Exception as cmd_exc:
                logger.warning("Telegram komut menüsü ayarlanamadı: %s", cmd_exc)
            await app.start()
            if app.updater is not None:
                await app.updater.start_polling(drop_pending_updates=True)

            self.app = app
            self.running = True
            self.last_error = None
            logger.info("Telegram bot polling başlatıldı.")
        except Exception as exc:
            self.running = False
            self.last_error = str(exc)
            logger.warning("Telegram bot başlatılamadı: %s", exc)

    async def stop(self) -> None:
        if self.app is None:
            return
        try:
            if self.app.updater is not None and self.app.updater.running:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        except Exception as exc:
            logger.warning("Telegram bot durdurulurken uyarı: %s", exc)
        finally:
            self.running = False
            self.app = None
