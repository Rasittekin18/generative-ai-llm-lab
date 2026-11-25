from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class SectionItem(BaseModel):
    heading: str = Field(description="Bölüm başlığı")
    content: str = Field(description="Bu bölümün anlaşılır ve ayrıntılı Türkçe özeti")


class FlashcardItem(BaseModel):
    question: str = Field(description="Aktif hatırlama (active recall) tekrar sorusu")
    answer: str = Field(description="Sorunun net ve öğretici yanıtı")


class LearningNote(BaseModel):
    """Gemini Structured Output tarafından üretilen öğrenme notu şeması."""

    title: str = Field(description="İçeriği en iyi özetleyen net Türkçe başlık")
    tldr: str = Field(description="2-3 cümlelik hızlı tek bakışta özet")
    key_points: list[str] = Field(
        description="En kritik 5-10 temel nokta ve çıkarım",
        min_length=3,
    )
    detailed_sections: list[SectionItem] = Field(
        description="Konuyu mantıksal alt başlıklara bölen ayrıntılı açıklamalar"
    )
    action_items: list[str] = Field(
        description="Hemen uygulanabilecek pratik adımlar veya kontrol listesi"
    )
    code_or_tools: list[str] = Field(
        description="Bahsedilen araçlar, kütüphaneler, komutlar veya teknik kavramlar"
    )
    review_questions: list[FlashcardItem] = Field(
        description="Bilgiyi pekiştirmek için 3-6 adet soru-cevap tekrar kartı"
    )
    tags: list[str] = Field(
        description="Obsidian uyumlu küçük harfli, boşluksuz/tireli Türkçe veya teknik etiketler (3-7 adet)"
    )
    category: str = Field(
        description="Tek bir ana kategori (ör. Yapay Zeka, Yazılım, Verimlilik, İş & Kariyer, Genel Kültür)"
    )
    estimated_read_minutes: int = Field(
        default=3,
        ge=1,
        le=60,
        description="Notun tahmini okuma süresi (dakika)",
    )


class IngestedContent(BaseModel):
    """IngestorAgent tarafından çıkarılan ham içerik ve meta veriler."""

    source_type: Literal["youtube", "article", "text"]
    source_url: Optional[str] = None
    title: str
    author: Optional[str] = None
    raw_text: str
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    language: Optional[str] = None


class SummarizeRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    focus: Optional[str] = None


class AskRequest(BaseModel):
    question: str = Field(min_length=2)


class ChannelCreateRequest(BaseModel):
    url_or_id: str = Field(min_length=2)


class NoteRecord(BaseModel):
    id: int
    title: str
    source_type: str
    source_url: Optional[str] = None
    author: Optional[str] = None
    category: str
    tags: list[str]
    tldr: str
    key_points: list[str]
    detailed_sections: list[SectionItem]
    action_items: list[str]
    code_or_tools: list[str]
    review_questions: list[FlashcardItem]
    estimated_read_minutes: int
    cleaned_transcript: str = ""
    markdown_path: str
    markdown_content: str
    created_at: str


class ChannelRecord(BaseModel):
    id: int
    channel_id: str
    title: str
    handle_or_url: str
    created_at: str


class ChannelVideoItem(BaseModel):
    video_id: str
    title: str
    url: str
    published_at: str
    thumbnail_url: Optional[str] = None


class PipelineEvent(BaseModel):
    stage: Literal["ingestor", "synthesizer", "archivist", "complete", "error"]
    status: Literal["running", "done", "error"]
    message: str
    data: Optional[dict[str, Any]] = None
