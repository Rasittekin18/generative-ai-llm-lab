from __future__ import annotations

import asyncio
from typing import Optional

from google import genai
from google.genai import types

from app.schemas import IngestedContent, LearningNote, NoteRecord

SYSTEM_PROMPT = """Sen kişisel bir 'İkinci Beyin ve Öğrenme Asistanı'sın.
Görevin, sana verilen YouTube video transkriptini, web makalesini veya ham notu analiz ederek
kullanıcının konuyu hızlıca kavramasını ve uzun vadede hatırlamasını sağlayacak yapılandırılmış,
net ve öğretici Türkçe öğrenme notları üretmektir.

Kurallar:
1. Çıktı dili kesinlikle doğal, akıcı ve teknik açıdan doğru Türkçe olmalıdır (kaynak İngilizce olsa bile).
2. 'tldr' alanı konunun özünü 2-3 cümlede vermelidir.
3. 'key_points' en önemli, somut ve içi dolu 5-10 madde içermelidir; yüzeysel genellemeler yazma.
4. 'detailed_sections' konuyu mantıksal başlıklara bölüp önemli detayları örneklerle açıklamalıdır.
5. 'action_items' okuyucunun hemen uygulayabileceği somut adımlar vermelidir.
6. 'code_or_tools' içerikte geçen kütüphaneleri, araçları, komutları veya temel kavramları listelemelidir (yoksa boş liste döndür).
7. 'review_questions' aktif hatırlama (active recall) için 3-6 adet soru-cevap kartı üretmelidir.
8. 'tags' Obsidian uyumlu küçük harfli, boşluksuz (tireli) 3-7 etiket olmalıdır (ör. 'yapay-zeka', 'python').
9. Yalnızca verilen kaynak metne sadık kal; kaynakta olmayan bilgileri uydurma."""


TRANSCRIPT_SYSTEM_PROMPT = """Sen profesyonel bir içerik editörü ve teknik çevirmensin.
Görevin, sana verilen ham video transkriptini (altyazı dökümünü) veya makale metnini
neredeyse tüm bilgiyi, örnekleri ve açıklamaları koruyarak DAHA UZUN, akıcı, noktalama işaretleri
düzgün ve konu başlıklarına bölünmüş temiz bir Türkçe metin haline getirmektir.

Kurallar:
1. Kesinlikle kısa özet çıkarma; konuşmacının veya yazarın anlattığı neredeyse tüm detayları, örnekleri, araçları ve akıl yürütmeleri koru.
2. Otomatik altyazıdan kaynaklanan yazım/konuşma tanıma hatalarını bağlama göre düzelt, 'ee/şey/yani' gibi gereksiz tekrarları temizle ve akıcı cümleler kur.
3. Kaynak yabancı dildeyse (ör. İngilizce) doğal ve teknik terimleri doğru koruyan Türkçeye çevir.
4. Metni okunabilir paragraflara ayır ve konu değişimlerinde kısa `### Başlık` alt başlıkları ekle.
5. Yalnızca temizlenmiş Markdown metni (düz paragraflar ve `###` alt başlıklar) döndür; giriş/kapanış yorumu ekleme."""

FALLBACK_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
]


class SynthesizerAgent:
    """2. Ajan: Google Gemini Structured Outputs ile yapılandırılmış öğrenme notu üretir."""

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview") -> None:
        self.api_key = api_key.strip()
        self.model = model.strip() or "gemini-3-flash-preview"

    def _candidate_models(self) -> list[str]:
        candidates = [self.model]
        for m in FALLBACK_MODELS:
            if m not in candidates:
                candidates.append(m)
        return candidates

    def _client(self) -> genai.Client:
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY ayarlı değil. Google AI Studio'dan ücretsiz anahtar alıp "
                "ikinci-beyin-asistani/.env dosyasına ekleyin."
            )
        return genai.Client(api_key=self.api_key)

    async def synthesize(
        self, ingested: IngestedContent, focus: Optional[str] = None
    ) -> LearningNote:
        client = self._client()
        max_chars = 80000
        raw_body = ingested.raw_text
        if len(raw_body) > max_chars:
            raw_body = (
                raw_body[:max_chars]
                + "\n\n[Not: İçerik çok uzun olduğu için ilk 80.000 karakter analiz edildi.]"
            )

        focus_block = (
            f"\nKullanıcının Özel Odak İsteği: {focus.strip()}\n"
            if focus and focus.strip()
            else ""
        )

        prompt = (
            f"Kaynak Türü: {ingested.source_type}\n"
            f"Başlık: {ingested.title}\n"
            f"Yazar / Kanal: {ingested.author or 'Bilinmiyor'}\n"
            f"Kaynak URL: {ingested.source_url or 'Yok'}\n"
            f"{focus_block}\n"
            f"--- HAM İÇERİK BAŞLANGICI ---\n"
            f"{raw_body}\n"
            f"--- HAM İÇERİK SONU ---"
        )

        def _call() -> LearningNote:
            last_exc: Optional[Exception] = None
            for model_name in self._candidate_models():
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=LearningNote,
                            temperature=0.3,
                        ),
                    )
                    if resp.parsed is not None and isinstance(resp.parsed, LearningNote):
                        return resp.parsed
                    if resp.text:
                        return LearningNote.model_validate_json(resp.text)
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc)
                    if any(code in msg for code in ("503", "UNAVAILABLE", "404", "NOT_FOUND")):
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("Gemini boş yanıt döndürdü.")

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise RuntimeError(
                    "Gemini ücretsiz katman istek/dakika kotası geçici olarak doldu (429). "
                    "Lütfen 30-60 saniye bekleyip tekrar deneyin."
                ) from exc
            if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
                raise RuntimeError(
                    "GEMINI_API_KEY geçersiz görünüyor. Google AI Studio'dan aldığınız anahtarı .env dosyasında kontrol edin."
                ) from exc
            raise RuntimeError(f"Gemini analiz hatası: {msg}") from exc

    async def format_transcript(self, ingested: IngestedContent) -> str:
        """Ham transkripti ayrıntıyı koruyarak temizlenmiş, uzun ve okunaklı Türkçe metne dönüştürür."""
        raw = ingested.raw_text.strip()
        if not raw:
            return ""

        client = self._client()
        chunk_size = 18000
        max_chunks = 4
        chunks: list[str] = []
        idx = 0
        while idx < len(raw) and len(chunks) < max_chunks:
            end = min(idx + chunk_size, len(raw))
            if end < len(raw):
                space_pos = raw.rfind(" ", idx + int(chunk_size * 0.8), end)
                if space_pos > idx:
                    end = space_pos
            chunks.append(raw[idx:end].strip())
            idx = end

        def _format_chunk(chunk_text: str, part_num: int, total_parts: int) -> str:
            part_note = (
                f" (Bölüm {part_num}/{total_parts})" if total_parts > 1 else ""
            )
            prompt = (
                f"Başlık: {ingested.title}{part_note}\n"
                f"Yazar / Kanal: {ingested.author or 'Bilinmiyor'}\n\n"
                f"--- HAM METİN ---\n{chunk_text}\n--- SON ---"
            )
            last_exc: Optional[Exception] = None
            for model_name in self._candidate_models():
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=TRANSCRIPT_SYSTEM_PROMPT,
                            temperature=0.2,
                        ),
                    )
                    text = (resp.text or "").strip()
                    if text:
                        return text
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc)
                    if any(code in msg for code in ("503", "UNAVAILABLE", "404", "NOT_FOUND")):
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            return chunk_text

        formatted_parts: list[str] = []
        try:
            for i, chunk in enumerate(chunks, start=1):
                part_out = await asyncio.to_thread(
                    _format_chunk, chunk, i, len(chunks)
                )
                formatted_parts.append(part_out)
            combined = "\n\n".join(p for p in formatted_parts if p).strip()
            if len(raw) > chunk_size * max_chunks:
                combined += "\n\n*[Not: Çok uzun içerik nedeniyle ilk ~72.000 karakterlik kısım düzenlendi.]*"
            return combined
        except Exception:
            return raw

    async def ask_about_note(
        self, note: NoteRecord, raw_excerpt: str, question: str
    ) -> str:
        """Kaydedilmiş bir notun içeriğine dayalı takip sorularını yanıtlar."""
        client = self._client()
        prompt = (
            f"Aşağıdaki öğrenme notuna ve kaynak özetine dayanarak kullanıcının sorusunu "
            f"net, anlaşılır Türkçe ve Markdown formatında yanıtla. Notun dışına çıkma.\n\n"
            f"Başlık: {note.title}\n"
            f"TL;DR: {note.tldr}\n"
            f"Önemli Noktalar:\n- " + "\n- ".join(note.key_points) + "\n\n"
            f"Ayrıntılar:\n"
            + "\n".join(f"### {s.heading}\n{s.content}" for s in note.detailed_sections)
            + f"\n\nKaynak Ham Kesit:\n{raw_excerpt[:6000]}\n\n"
            f"Kullanıcının Sorusu: {question.strip()}"
        )

        def _call() -> str:
            last_exc: Optional[Exception] = None
            for model_name in self._candidate_models():
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.3),
                    )
                    return (resp.text or "Yanıt üretilemedi.").strip()
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc)
                    if any(code in msg for code in ("503", "UNAVAILABLE", "404", "NOT_FOUND")):
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            return "Yanıt üretilemedi."

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            raise RuntimeError(f"Soru yanıtlanırken hata oluştu: {exc}") from exc
