"""FastAPI ve LLM istemcisi için Pydantic veri şemaları."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class EntityItem(BaseModel):
    word: str
    entity_group: str
    score: float = 0.0


class VocabItem(BaseModel):
    word: str
    meaning_tr: str
    cefr_level: str = "B1"
    example_en: str = ""


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=6000)
    source_context_hint: Optional[str] = None
    user_level: str = "B1"


class AnalyzeResponse(BaseModel):
    original_text: str
    source_language: str = "en"
    target_language: str = "tr"
    detected_context: str
    context_confidence: float = 0.0
    entities: List[EntityItem] = Field(default_factory=list)
    natural_translation: str
    nuance_explanation: str
    vocabulary: List[VocabItem] = Field(default_factory=list)
    provider_used: str = "unknown"


class WriteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=6000)
    tone: Literal["Casual", "Professional", "Technical Prompt", "Academic"] = "Professional"
    mode: Literal["auto", "tr_to_en", "improve_en"] = "auto"


class WriteResponse(BaseModel):
    original_text: str
    detected_language: str
    tone: str
    english_result: str
    alternatives: List[str] = Field(default_factory=list)
    explanation_tr: str
    key_phrases: List[VocabItem] = Field(default_factory=list)
    provider_used: str = "unknown"


class VocabCreate(BaseModel):
    word: str = Field(..., min_length=1, max_length=200)
    meaning_tr: str = Field(..., min_length=1, max_length=500)
    cefr_level: str = "B1"
    example_en: str = ""
    source_sentence: str = ""


class VocabRecord(VocabCreate):
    id: int
    mastered: bool = False
    review_count: int = 0
    created_at: str


class HistoryRecord(BaseModel):
    id: int
    mode: str
    source_text: str
    result_json: str
    created_at: str


class AppSettings(BaseModel):
    llm_provider: str = "ollama"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_api_key: str = ""
    local_hf_enabled: bool = True
    hf_context_model: str = "typeform/distilbert-base-uncased-mnli"
    hf_ner_model: str = "dslim/bert-base-NER"
    enable_mouse_selection_popup: bool = True
    hotkey_translate: str = "<alt>+q"
    hotkey_writer: str = "<alt>+w"
    user_level: str = "B1"
