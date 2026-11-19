"""Yerel Hugging Face NLP Hattı (Bölüm 1, 2 & 3 teknikleri).

- Bağlam / Alan Sınıflandırması (Zero-Shot Classification)
- Varlık İsmi Tanıma (NER, aggregation_strategy='simple')
- `transformers` kurulu değilse veya yerel modeller kapalıysa hızlı kural tabanlı yedek çalışır.
"""

import logging
import re
import threading
from typing import Dict, List, Tuple

from backend.schemas import AppSettings, EntityItem

logger = logging.getLogger(__name__)

CONTEXT_LABELS_MAP: Dict[str, str] = {
    "software engineering and coding": "Teknik / Yazılım",
    "business email and professional communication": "İş / Profesyonel",
    "daily casual conversation": "Günlük Sohbet",
    "academic article or educational explanation": "Akademik / Eğitim",
}


class LocalNLPPipeline:
    """Bölüm 2 & 3'teki Hugging Face sınıflandırma ve NER modellerini yönetir."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._context_clf = None
        self._ner_pipe = None
        self._loaded_context_model: str = ""
        self._loaded_ner_model: str = ""
        self._transformers_available = self._check_transformers()

    def warmup(self, settings: AppSettings) -> None:
        """NER modelini uygulama açılışında arka planda RAM'e yükler (bağlam tespiti LLM'den gelir)."""
        self._ensure_ner_pipeline(settings)

    @staticmethod
    def _check_transformers() -> bool:
        try:
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_ner_pipeline(self, settings: AppSettings) -> None:
        if not settings.local_hf_enabled or not self._transformers_available:
            return

        with self._lock:
            from transformers import pipeline

            if self._ner_pipe is None or self._loaded_ner_model != settings.hf_ner_model:
                try:
                    logger.info("Hugging Face NER modeli yükleniyor: %s", settings.hf_ner_model)
                    self._ner_pipe = pipeline(
                        "token-classification",
                        model=settings.hf_ner_model,
                        aggregation_strategy="simple",
                    )
                    self._loaded_ner_model = settings.hf_ner_model
                except Exception as exc:
                    logger.warning("NER modeli yüklenemedi (%s), yedek moda geçiliyor.", exc)
                    self._ner_pipe = None

    def classify_context(self, text: str, settings: AppSettings) -> Tuple[str, float]:
        """Hızlı ön bağlam tahmini döndürür (ana bağlam etiketi LLM JSON yanıtından gelir)."""
        return self._heuristic_context(text)

    def extract_entities(self, text: str, settings: AppSettings) -> List[EntityItem]:
        """Metindeki kişi, kurum, yer ve özel terimleri çıkarır (Bölüm 3)."""
        self._ensure_ner_pipeline(settings)
        if self._ner_pipe is not None:
            try:
                raw = self._ner_pipe(text[:1500])
                seen = set()
                entities: List[EntityItem] = []
                for item in raw:
                    word = str(item.get("word", "")).strip()
                    group = str(item.get("entity_group", "MISC"))
                    score = round(float(item.get("score", 0.0)), 3)
                    if word and (word.lower(), group) not in seen and score >= 0.55:
                        seen.add((word.lower(), group))
                        entities.append(EntityItem(word=word, entity_group=group, score=score))
                return entities[:10]
            except Exception as exc:
                logger.warning("NER çalıştırma hatası: %s", exc)

        return self._heuristic_entities(text)

    @staticmethod
    def _heuristic_context(text: str) -> Tuple[str, float]:
        lower = text.lower()
        tech_kw = ("api", "bug", "error", "deploy", "python", "model", "token", "server", "code", "git", "database", "prompt", "async")
        biz_kw = ("meeting", "deadline", "schedule", "attached", "regards", "sincerely", "invoice", "client", "project", "proposal")
        acad_kw = ("research", "paper", "experiment", "hypothesis", "methodology", "benchmark", "abstract", "therefore", "moreover")

        if any(k in lower for k in tech_kw):
            return "Teknik / Yazılım", 0.72
        if any(k in lower for k in biz_kw):
            return "İş / Profesyonel", 0.70
        if any(k in lower for k in acad_kw):
            return "Akademik / Eğitim", 0.68
        return "Günlük Sohbet", 0.60

    @staticmethod
    def _heuristic_entities(text: str) -> List[EntityItem]:
        matches = re.findall(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b", text)
        stop = {"The", "This", "That", "When", "Where", "What", "How", "Why", "Please", "Thanks", "Hello"}
        seen = set()
        items: List[EntityItem] = []
        for m in matches:
            if m not in stop and m.lower() not in seen:
                seen.add(m.lower())
                items.append(EntityItem(word=m, entity_group="TERM", score=0.5))
        return items[:6]

    @staticmethod
    def detect_language_simple(text: str) -> str:
        """Türkçe karakterler ve yaygın Türkçe kelimelere (ASCII dahil) bakarak hızlı dil tahmini yapar."""
        tr_chars = set("çğıöşüÇĞİÖŞÜ")
        if any(ch in tr_chars for ch in text):
            return "tr"
        tr_words = {
            "ve", "bir", "bu", "su", "o", "icin", "ile", "ama", "fakat", "ancak",
            "nasil", "nasilsin", "naber", "nedir", "neden", "niye", "kim", "nerede",
            "lutfen", "merhaba", "selam", "istiyorum", "cevir", "yap", "yardim",
            "tesekkur", "tesekkurler", "oldu", "olur", "degil", "var", "yok",
            "bana", "sana", "ben", "sen", "biz", "siz", "herhangi", "yeterli",
            "kodu", "hata", "mesaji", "pencere", "cikti", "calismiyor", "calisiyor",
        }
        en_words = {
            "the", "is", "are", "was", "were", "have", "has", "had", "this", "that",
            "with", "from", "for", "not", "you", "your", "can", "could", "would",
            "should", "please", "what", "where", "when", "how", "why", "which",
        }
        tokens = set(re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]+", text.lower()))
        tr_hits = len(tokens & tr_words)
        en_hits = len(tokens & en_words)
        if tr_hits > en_hits:
            return "tr"
        return "en"
