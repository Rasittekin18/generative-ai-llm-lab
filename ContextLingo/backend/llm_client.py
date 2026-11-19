"""Bağlam Odaklı Çeviri ve İngilizce Yazma Koçu için LLM İstemcisi.

OpenAI uyumlu tüm sağlayıcılarla (Ollama, Groq, Hugging Face Inference Router, OpenAI) çalışır.
"""

import json
import re
from typing import Any, Dict, List

from openai import OpenAI

from backend.schemas import (
    AnalyzeResponse,
    AppSettings,
    EntityItem,
    VocabItem,
    WriteResponse,
)

ANALYZE_EN_TO_TR_PROMPT = """Sen uzman bir İngilizce-Türkçe dil koçu ve bağlam odaklı çevirmensin.
Kullanıcı İngilizce bir metin seçtiğinde sadece kelime kelime çeviri yapmazsın; metnin gerçek bağlamını, deyimlerini ve teknik/kültürel nüanslarını yakalarsın.
Yanıtını YALNIZCA geçerli bir JSON nesnesi olarak döndür. Başka hiçbir metin veya açıklama ekleme.

JSON şeması:
{
  "detected_context": "Metnin bağlamına göre tam olarak şu 5 seçenekten biri: Teknik / Yazılım | İş / Profesyonel | Günlük Sohbet | Akademik / Eğitim | Genel",
  "natural_translation": "Bağlama uygun, akıcı ve doğal Türkçe çeviri",
  "nuance_explanation": "Google Translate'ten farkını, cümledeki deyim/kalıp/gramer mantığını açıklayan kısa Türkçe not (1-2 cümle)",
  "vocabulary": [
    {
      "word": "metinden seçilen önemli İngilizce kelime veya kalıp (phrasal verb / idiom)",
      "meaning_tr": "bu bağlamdaki Türkçe anlamı",
      "cefr_level": "A2 | B1 | B2 | C1 | C2",
      "example_en": "kısa ve anlaşılır örnek İngilizce cümle"
    }
  ]
}
En fazla 3 adet vocabulary öğesi seç (kısa, öz ve öğretici olsun)."""

ANALYZE_TR_TO_EN_PROMPT = """Sen uzman bir Türkçe-İngilizce dil koçu ve bağlam odaklı çevirmensin.
Kullanıcı TÜRKÇE bir metin seçti. Görevin bu Türkçe metni bağlamını koruyarak son derece doğal, akıcı İNGİLİZCEYE çevirmek ve bu çeviride kullanılan önemli İngilizce kalıpları Türkçe açıklamaktır.
DİKKAT: natural_translation alanı MUTLAKA İNGİLİZCE olmalıdır!
Yanıtını YALNIZCA geçerli bir JSON nesnesi olarak döndür. Başka hiçbir metin veya açıklama ekleme.

JSON şeması:
{
  "detected_context": "Metnin bağlamına göre tam olarak şu 5 seçenekten biri: Teknik / Yazılım | İş / Profesyonel | Günlük Sohbet | Akademik / Eğitim | Genel",
  "natural_translation": "Bağlama uygun, akıcı ve doğal İNGİLİZCE çeviri",
  "nuance_explanation": "Bu Türkçe cümleyi İngilizceye çevirirken neden bu yapıyı/kalıbı seçtiğini açıklayan kısa Türkçe not (1-2 cümle)",
  "vocabulary": [
    {
      "word": "İngilizce çeviride kullanılan önemli kelime veya kalıp",
      "meaning_tr": "Türkçe karşılığı",
      "cefr_level": "A2 | B1 | B2 | C1 | C2",
      "example_en": "kısa örnek İngilizce cümle"
    }
  ]
}
En fazla 3 adet vocabulary öğesi seç (kısa ve öz olsun)."""

WRITE_SYSTEM_PROMPT = """Sen uzman bir İngilizce yazma ve iletişim koçusun.
Kullanıcı sana Türkçe bir düşünce/prompt veya bozuk/eksik bir İngilizce cümle verecek.
Görevin: Kullanıcının asıl anlatmak istediği bağlamı ve niyeti anlayıp istenen tonda (Casual, Professional, Technical Prompt veya Academic) son derece doğal, akıcı İngilizceye dönüştürmek ve neden böyle kurulduğunu Türkçe öğretmektir.
Yanıtını YALNIZCA geçerli bir JSON nesnesi olarak döndür.

JSON şeması:
{
  "english_result": "İstenen tona uygun en doğal İngilizce ifade",
  "alternatives": [
    "Alternatif 1 (biraz daha kısa veya farklı vurgu)",
    "Alternatif 2 (doğal başka bir söyleyiş)"
  ],
  "explanation_tr": "Neden bu kalıp/kelime seçildi? Türkçe düşünen birinin dikkat etmesi gereken gramer veya kelime farkı nedir? (2-3 net Türkçe cümle)",
  "key_phrases": [
    {
      "word": "cümlede kullanılan faydalı İngilizce kalıp",
      "meaning_tr": "Türkçe karşılığı",
      "cefr_level": "B1 | B2 | C1",
      "example_en": "kısa ek örnek"
    }
  ]
}"""


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Model çıktısı think etiketi veya markdown kod bloğu içerse bile JSON nesnesini güvenli şekilde ayıklar."""
    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


class SmartLLMClient:
    """Ayarlara göre yerel Ollama veya uzak API sağlayıcılarıyla konuşan keep-alive istemcisi."""

    def __init__(self) -> None:
        self._cached_key: tuple = ("", "")
        self._cached_client: Any = None

    def _build_client(self, settings: AppSettings) -> OpenAI:
        base_url = settings.llm_base_url.strip()
        api_key = settings.llm_api_key.strip() or "ollama"
        cache_key = (base_url, api_key)
        if self._cached_client is None or self._cached_key != cache_key:
            self._cached_client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=30.0,
            )
            self._cached_key = cache_key
        return self._cached_client

    def _is_configured(self, settings: AppSettings) -> bool:
        provider = settings.llm_provider.lower().strip()
        if provider == "ollama":
            return bool(settings.llm_base_url.strip() and settings.llm_model.strip())
        return bool(settings.llm_api_key.strip() and settings.llm_base_url.strip() and settings.llm_model.strip())

    def _chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        settings: AppSettings,
        temperature: float = 0.25,
        max_tokens: int = 450,
    ) -> Dict[str, Any]:
        client = self._build_client(settings)
        response = client.chat.completions.create(
            model=settings.llm_model.strip(),
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return extract_json_object(content)

    def analyze_reading(
        self,
        text: str,
        detected_context: str,
        context_confidence: float,
        entities: List[EntityItem],
        user_level: str,
        settings: AppSettings,
        source_context_hint: str = "",
        source_language: str = "en",
    ) -> AnalyzeResponse:
        """Seçili metni diline göre çift yönlü (EN->TR veya TR->EN) bağlama uygun çevirir ve açıklar."""
        target_language = "en" if source_language == "tr" else "tr"
        if not self._is_configured(settings):
            return self._fallback_analyze(
                text,
                detected_context,
                context_confidence,
                entities,
                "Ayarlar'dan API anahtarı veya Ollama bağlantısı yapılandırılmadı.",
                source_language=source_language,
                target_language=target_language,
            )

        entity_summary = ", ".join(f"{e.word} ({e.entity_group})" for e in entities) or "Yok"
        system_prompt = ANALYZE_TR_TO_EN_PROMPT if source_language == "tr" else ANALYZE_EN_TO_TR_PROMPT
        direction_note = "Türkçe → İngilizce" if source_language == "tr" else "İngilizce → Türkçe"
        user_msg = (
            f"Çeviri Yönü: {direction_note}\n"
            f"Öğrenci Seviyesi: {user_level}\n"
            f"Tespit Edilen Bağlam: {detected_context}\n"
            f"Uygulama/Kaynak İpucu: {source_context_hint or 'Belirtilmedi'}\n"
            f"Tespit Edilen Kavram/Varlıklar: {entity_summary}\n\n"
            f"Çevrilecek ve Açıklanacak Metin:\n\"\"\"\n{text}\n\"\"\""
        )

        try:
            data = self._chat_json(system_prompt, user_msg, settings, temperature=0.2)
            vocab = [VocabItem(**v) for v in data.get("vocabulary", []) if isinstance(v, dict) and v.get("word")]
            llm_ctx = str(data.get("detected_context", "")).strip()
            final_ctx = llm_ctx if llm_ctx else detected_context
            final_conf = 0.95 if llm_ctx else context_confidence
            return AnalyzeResponse(
                original_text=text,
                source_language=source_language,
                target_language=target_language,
                detected_context=final_ctx,
                context_confidence=final_conf,
                entities=entities,
                natural_translation=str(data.get("natural_translation", "")).strip() or "Çeviri üretilemedi.",
                nuance_explanation=str(data.get("nuance_explanation", "")).strip(),
                vocabulary=vocab[:4],
                provider_used=f"{settings.llm_provider}:{settings.llm_model}",
            )
        except Exception as exc:
            return self._fallback_analyze(
                text,
                detected_context,
                context_confidence,
                entities,
                f"LLM bağlantı hatası: {exc}",
                source_language=source_language,
                target_language=target_language,
            )

    def coach_writing(
        self,
        text: str,
        detected_language: str,
        tone: str,
        mode: str,
        settings: AppSettings,
    ) -> WriteResponse:
        """Türkçe düşünceyi veya kaba İngilizceyi bağlama uygun doğal İngilizceye dönüştürür."""
        if not self._is_configured(settings):
            return WriteResponse(
                original_text=text,
                detected_language=detected_language,
                tone=tone,
                english_result="[Demo Modu] LLM bağlantısı kurulmadığı için gerçek çeviri üretilemedi.",
                alternatives=[],
                explanation_tr="Ayarlar penceresinden ücretsiz yerel Ollama veya Groq/OpenAI/Hugging Face API anahtarınızı girin.",
                key_phrases=[],
                provider_used="offline-demo",
            )

        task_desc = {
            "tr_to_en": "Kullanıcı Türkçe yazdı; bağlamı ve asıl niyeti koruyarak doğal İngilizceye çevir.",
            "improve_en": "Kullanıcı İngilizce yazdı; gramer ve doğallık açısından düzeltip geliştir.",
            "auto": f"Tespit edilen dil '{detected_language}'. Türkçeyse doğal İngilizceye çevir, İngilizceyse düzeltip geliştir.",
        }.get(mode, "Bağlamı koruyarak doğal İngilizce üret.")

        user_msg = (
            f"Görev: {task_desc}\n"
            f"Hedef Ton: {tone}\n\n"
            f"Kullanıcı Girdisi:\n\"\"\"\n{text}\n\"\"\""
        )

        try:
            data = self._chat_json(WRITE_SYSTEM_PROMPT, user_msg, settings, temperature=0.35)
            phrases = [VocabItem(**p) for p in data.get("key_phrases", []) if isinstance(p, dict) and p.get("word")]
            alts = [str(a).strip() for a in data.get("alternatives", []) if str(a).strip()]
            return WriteResponse(
                original_text=text,
                detected_language=detected_language,
                tone=tone,
                english_result=str(data.get("english_result", "")).strip(),
                alternatives=alts[:3],
                explanation_tr=str(data.get("explanation_tr", "")).strip(),
                key_phrases=phrases[:4],
                provider_used=f"{settings.llm_provider}:{settings.llm_model}",
            )
        except Exception as exc:
            return WriteResponse(
                original_text=text,
                detected_language=detected_language,
                tone=tone,
                english_result=f"Hata oluştu: {exc}",
                alternatives=[],
                explanation_tr="LLM sağlayıcısına erişilemedi. Ollama'nın çalıştığından veya API anahtarının doğru olduğundan emin olun.",
                key_phrases=[],
                provider_used="error",
            )

    @staticmethod
    def _fallback_analyze(
        text: str,
        detected_context: str,
        context_confidence: float,
        entities: List[EntityItem],
        reason: str,
        source_language: str = "en",
        target_language: str = "tr",
    ) -> AnalyzeResponse:
        return AnalyzeResponse(
            original_text=text,
            source_language=source_language,
            target_language=target_language,
            detected_context=detected_context,
            context_confidence=context_confidence,
            entities=entities,
            natural_translation="[Çevrimdışı / Demo] " + text,
            nuance_explanation=f"Bağlam ({detected_context}) ve varlıklar analiz edildi, ancak LLM yanıtı alınamadı. Sebep: {reason}",
            vocabulary=[],
            provider_used="offline-demo",
        )
