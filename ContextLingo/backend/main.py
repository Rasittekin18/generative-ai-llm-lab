"""FastAPI Backend Sunucusu: Paralel HF+LLM analizi, önbellek, kelime defteri ve ayarlar."""

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import List, Tuple

from fastapi import FastAPI, HTTPException

from backend.config import load_settings, save_settings
from backend.db import AssistantDB
from backend.llm_client import SmartLLMClient
from backend.nlp_pipeline import LocalNLPPipeline
from backend.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AppSettings,
    HistoryRecord,
    VocabCreate,
    VocabRecord,
    WriteRequest,
    WriteResponse,
)

db = AssistantDB()
nlp_pipeline = LocalNLPPipeline()
llm_client = SmartLLMClient()
_executor = ThreadPoolExecutor(max_workers=4)

# Son 100 çeviriyi bellekte tutarak aynı metin tekrar seçilirse anında (<5ms) yanıt verir
_analyze_cache: "OrderedDict[Tuple[str, str, str], AnalyzeResponse]" = OrderedDict()
_CACHE_MAX = 100


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    settings = load_settings()
    if settings.local_hf_enabled:
        threading.Thread(target=nlp_pipeline.warmup, args=(settings,), daemon=True).start()
    yield


app = FastAPI(
    title="Akıllı İngilizce Okuma & Yazma Asistanı API",
    version="1.1.0",
    lifespan=_lifespan,
)


@app.get("/health")
def health_check() -> dict:
    settings = load_settings()
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "local_hf_enabled": settings.local_hf_enabled,
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_text(req: AnalyzeRequest) -> AnalyzeResponse:
    settings = load_settings()
    cleaned = req.text.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Metin boş olamaz.")

    source_lang = nlp_pipeline.detect_language_simple(cleaned)
    user_level = req.user_level or settings.user_level
    cache_key = (cleaned, source_lang, f"{settings.llm_provider}:{settings.llm_model}:{user_level}")
    if cache_key in _analyze_cache:
        _analyze_cache.move_to_end(cache_key)
        return _analyze_cache[cache_key]

    # LLM bağlam+çeviri+kelime analizini yaparken paralel olarak yerel Hugging Face NER çalıştır
    quick_ctx, quick_conf = nlp_pipeline.classify_context(cleaned, settings)
    ner_future = _executor.submit(nlp_pipeline.extract_entities, cleaned, settings)
    llm_future = _executor.submit(
        llm_client.analyze_reading,
        text=cleaned,
        detected_context=quick_ctx,
        context_confidence=quick_conf,
        entities=[],
        user_level=user_level,
        settings=settings,
        source_context_hint=req.source_context_hint or "",
        source_language=source_lang,
    )

    result = llm_future.result()
    try:
        result.entities = ner_future.result(timeout=2.0)
    except Exception:
        result.entities = nlp_pipeline._heuristic_entities(cleaned)

    if result.provider_used not in ("offline-demo", "error"):
        _analyze_cache[cache_key] = result
        if len(_analyze_cache) > _CACHE_MAX:
            _analyze_cache.popitem(last=False)

    db.save_history("analyze", cleaned, result.model_dump_json())
    return result


@app.post("/api/write", response_model=WriteResponse)
def coach_writing(req: WriteRequest) -> WriteResponse:
    settings = load_settings()
    cleaned = req.text.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Metin boş olamaz.")

    detected_lang = nlp_pipeline.detect_language_simple(cleaned)
    result = llm_client.coach_writing(
        text=cleaned,
        detected_language=detected_lang,
        tone=req.tone,
        mode=req.mode,
        settings=settings,
    )
    db.save_history("write", cleaned, result.model_dump_json())
    return result


@app.get("/api/vocab", response_model=List[VocabRecord])
def get_vocab(only_unmastered: bool = False) -> List[VocabRecord]:
    return db.list_vocab(only_unmastered=only_unmastered)


@app.post("/api/vocab", response_model=VocabRecord)
def create_vocab(item: VocabCreate) -> VocabRecord:
    return db.add_vocab(item)


@app.patch("/api/vocab/{vocab_id}/toggle", response_model=VocabRecord)
def toggle_vocab(vocab_id: int) -> VocabRecord:
    updated = db.toggle_vocab_mastered(vocab_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Kelime bulunamadı.")
    return updated


@app.delete("/api/vocab/{vocab_id}")
def delete_vocab(vocab_id: int) -> dict:
    deleted = db.delete_vocab(vocab_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Kelime bulunamadı.")
    return {"deleted": True}


@app.get("/api/history", response_model=List[HistoryRecord])
def get_history(limit: int = 30) -> List[HistoryRecord]:
    return db.list_history(limit=limit)


@app.get("/api/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    return load_settings()


@app.post("/api/settings", response_model=AppSettings)
def update_settings(payload: AppSettings) -> AppSettings:
    _analyze_cache.clear()
    return save_settings(payload)
