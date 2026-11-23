"""Pydantic veri doğrulama ve API sözleşme şemaları."""

from datetime import date, datetime
from typing import Any, Literal, Optional
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field, field_validator


DocumentType = Literal["fis", "fatura", "garanti_belgesi", "sozlesme", "diger"]
CategoryType = Literal[
    "Market",
    "Teknoloji",
    "Yemek",
    "Sağlık",
    "Giyim",
    "Fatura",
    "Ulaşım",
    "Ev & Yaşam",
    "Diğer",
]

VALID_CATEGORIES = {
    "Market",
    "Teknoloji",
    "Yemek",
    "Sağlık",
    "Giyim",
    "Fatura",
    "Ulaşım",
    "Ev & Yaşam",
    "Diğer",
}


def compute_warranty_end_date(
    document_date: Optional[str],
    warranty_months: Optional[int],
) -> Optional[str]:
    """Belge tarihine garanti ayını ekleyerek YYYY-MM-DD bitiş tarihi hesaplar."""
    if not document_date or not warranty_months or warranty_months <= 0:
        return None
    try:
        start = date.fromisoformat(document_date[:10])
        end = start + relativedelta(months=int(warranty_months))
        return end.isoformat()
    except Exception:
        return None


class LineItemIn(BaseModel):
    """Belgedeki tek bir ürün veya hizmet satırı."""

    name: str = Field(..., min_length=1, description="Ürün veya hizmet adı")
    quantity: float = Field(default=1.0, ge=0, description="Adet / Miktar")
    unit_price: Optional[float] = Field(default=None, ge=0, description="Birim fiyat")
    total_price: Optional[float] = Field(default=None, ge=0, description="Satır toplamı")
    warranty_months: Optional[int] = Field(default=None, ge=0, le=240)
    warranty_end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")


class ExtractedDocument(BaseModel):
    """VLM veya PDF çıkarıcıdan dönen yapılandırılmış belge modeli."""

    document_type: DocumentType = "fis"
    merchant_name: str = Field(default="Bilinmeyen Satıcı", min_length=1)
    document_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    currency: str = Field(default="TRY", min_length=1, max_length=8)
    subtotal: Optional[float] = Field(default=None, ge=0)
    vat_amount: Optional[float] = Field(default=None, ge=0)
    total_amount: Optional[float] = Field(default=None, ge=0)
    category: str = "Diğer"
    warranty_months: Optional[int] = Field(default=None, ge=0, le=240)
    warranty_end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    summary: str = ""
    warranty_terms: str = ""
    raw_text: str = ""
    items: list[LineItemIn] = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: Any) -> str:
        if not v or not isinstance(v, str):
            return "Diğer"
        cleaned = v.strip()
        for valid in VALID_CATEGORIES:
            if cleaned.lower() == valid.lower():
                return valid
        return "Diğer"

    @field_validator("document_date", "warranty_end_date", mode="before")
    @classmethod
    def normalize_date_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() in {"null", "none", "yok", "n/a"}:
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s[:10], fmt).date().isoformat()
            except ValueError:
                continue
        return None


class DocumentCreateRequest(ExtractedDocument):
    """Kullanıcı onayından sonra veritabanına kaydedilecek belge isteği."""

    file_name: str
    file_path: str
    file_hash: str
    mime_type: str = "application/octet-stream"
    extraction_method: str = "manual"


class ExtractionPreviewResponse(BaseModel):
    """Belge yüklendiğinde arayüze döndürülen önizleme yanıtı."""

    status: Literal["extracted", "needs_manual_review", "duplicate"]
    message: str
    extraction_method: str
    file_name: str
    file_path: str
    file_hash: str
    mime_type: str
    duplicate_document_id: Optional[int] = None
    extracted: ExtractedDocument


class ChatRequest(BaseModel):
    """Hibrit ajan sohbet isteği."""

    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)


class SourceCitation(BaseModel):
    """RAG kaynağındaki belge referansı."""

    document_id: int
    file_name: str
    merchant_name: str
    document_date: Optional[str] = None
    document_type: str
    score: float
    excerpt: str


class ChatResponse(BaseModel):
    """Hibrit ajan sohbet yanıtı."""

    answer: str
    route_used: Literal["sql", "rag", "hybrid", "direct"]
    sql_query: Optional[str] = None
    sql_rows: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    latency_ms: int
    model_used: str


class RuntimeSettingsUpdate(BaseModel):
    """Çalışma zamanında model/sağlayıcı güncelleme isteği."""

    llm_provider: Optional[str] = None
    vlm_provider: Optional[str] = None
    ollama_llm_model: Optional[str] = None
    ollama_vlm_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
