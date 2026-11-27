"""Pydantic veri doğrulama ve API sözleşme şemaları."""

import re
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

_DOC_TYPE_ALIASES = {
    "fis": "fis",
    "fiş": "fis",
    "receipt": "fis",
    "kasa fişi": "fis",
    "kasa fisi": "fis",
    "fatura": "fatura",
    "e-fatura": "fatura",
    "efatura": "fatura",
    "e-arşiv": "fatura",
    "e-arsiv": "fatura",
    "invoice": "fatura",
    "garanti_belgesi": "garanti_belgesi",
    "garanti belgesi": "garanti_belgesi",
    "garanti": "garanti_belgesi",
    "warranty": "garanti_belgesi",
    "sozlesme": "sozlesme",
    "sözleşme": "sozlesme",
    "contract": "sozlesme",
    "agreement": "sozlesme",
    "diger": "diger",
    "diğer": "diger",
    "other": "diger",
}

_CURRENCY_ALIASES = {
    "tl": "TRY",
    "try": "TRY",
    "₺": "TRY",
    "türk lirası": "TRY",
    "turk lirasi": "TRY",
    "usd": "USD",
    "$": "USD",
    "dolar": "USD",
    "eur": "EUR",
    "€": "EUR",
    "euro": "EUR",
    "gbp": "GBP",
    "£": "GBP",
}


def _normalize_doc_type(v: Any) -> str:
    if not v or not isinstance(v, str):
        return "fis"
    cleaned = v.strip().lower()
    return _DOC_TYPE_ALIASES.get(cleaned, "diger")


def _normalize_currency(v: Any) -> str:
    if not v or not isinstance(v, str):
        return "TRY"
    cleaned = v.strip()
    if not cleaned:
        return "TRY"
    alias = _CURRENCY_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    alpha = re.sub(r"[^A-Za-z]", "", cleaned).upper()
    return (alpha or "TRY")[:8]


def _normalize_category_val(v: Any) -> str:
    if not v or not isinstance(v, str):
        return "Diğer"
    cleaned = v.strip()
    for valid in VALID_CATEGORIES:
        if cleaned.lower() == valid.lower():
            return valid
    return "Diğer"


def _normalize_date_val(v: Any) -> Optional[str]:
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


def _parse_optional_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    s = str(v).strip()
    if not s or s.lower() in {"null", "none", "yok", "n/a", "-"}:
        return None
    num_str = re.sub(r"[^\d.,-]", "", s)
    if not num_str:
        return None
    if "," in num_str and "." in num_str:
        if num_str.rfind(",") > num_str.rfind("."):
            num_str = num_str.replace(".", "").replace(",", ".")
        else:
            num_str = num_str.replace(",", "")
    elif "," in num_str:
        num_str = num_str.replace(",", ".")
    try:
        val = float(num_str)
        return val if val >= 0 else None
    except ValueError:
        return None


def _parse_optional_int(v: Any, max_val: int = 240) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        iv = int(v)
        return iv if 0 <= iv <= max_val else None
    m = re.search(r"\d+", str(v))
    if not m:
        return None
    iv = int(m.group(0))
    return iv if 0 <= iv <= max_val else None


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

    name: str = Field(default="Ürün", min_length=1, description="Ürün veya hizmet adı")
    quantity: float = Field(default=1.0, ge=0, description="Adet / Miktar")
    unit_price: Optional[float] = Field(default=None, ge=0, description="Birim fiyat")
    total_price: Optional[float] = Field(default=None, ge=0, description="Satır toplamı")
    warranty_months: Optional[int] = Field(default=None, ge=0, le=240)
    warranty_end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        return s or "Ürün"

    @field_validator("quantity", mode="before")
    @classmethod
    def normalize_quantity(cls, v: Any) -> float:
        parsed = _parse_optional_float(v)
        return parsed if parsed is not None else 1.0

    @field_validator("unit_price", "total_price", mode="before")
    @classmethod
    def normalize_prices(cls, v: Any) -> Optional[float]:
        return _parse_optional_float(v)

    @field_validator("warranty_months", mode="before")
    @classmethod
    def normalize_item_warranty_months(cls, v: Any) -> Optional[int]:
        return _parse_optional_int(v)

    @field_validator("warranty_end_date", mode="before")
    @classmethod
    def normalize_item_warranty_end(cls, v: Any) -> Optional[str]:
        return _normalize_date_val(v)


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

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, v: Any) -> str:
        return _normalize_doc_type(v)

    @field_validator("merchant_name", mode="before")
    @classmethod
    def normalize_merchant_name(cls, v: Any) -> str:
        if v is None:
            return "Bilinmeyen Satıcı"
        s = str(v).strip()
        return s or "Bilinmeyen Satıcı"

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, v: Any) -> str:
        return _normalize_currency(v)

    @field_validator("subtotal", "vat_amount", "total_amount", mode="before")
    @classmethod
    def normalize_amounts(cls, v: Any) -> Optional[float]:
        return _parse_optional_float(v)

    @field_validator("warranty_months", mode="before")
    @classmethod
    def normalize_warranty_months(cls, v: Any) -> Optional[int]:
        return _parse_optional_int(v)

    @field_validator("summary", "warranty_terms", "raw_text", mode="before")
    @classmethod
    def normalize_text_fields(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("items", mode="before")
    @classmethod
    def normalize_items(cls, v: Any) -> list[Any]:
        if not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            if isinstance(item, LineItemIn):
                cleaned.append(item)
            elif isinstance(item, dict) and str(item.get("name") or "").strip():
                cleaned.append(item)
        return cleaned

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: Any) -> str:
        return _normalize_category_val(v)

    @field_validator("document_date", "warranty_end_date", mode="before")
    @classmethod
    def normalize_date_str(cls, v: Any) -> Optional[str]:
        return _normalize_date_val(v)


class DocumentCreateRequest(ExtractedDocument):
    """Kullanıcı onayından sonra veritabanına kaydedilecek belge isteği."""

    file_name: str
    file_path: str
    file_hash: str
    mime_type: str = "application/octet-stream"
    extraction_method: str = "manual"


class DocumentUpdateRequest(BaseModel):
    """Var olan belgeyi düzenleme isteği."""

    document_type: Optional[DocumentType] = None
    merchant_name: Optional[str] = None
    document_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = Field(default=None, ge=0)
    vat_amount: Optional[float] = Field(default=None, ge=0)
    total_amount: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = None
    warranty_months: Optional[int] = Field(default=None, ge=0, le=240)
    warranty_end_date: Optional[str] = None
    summary: Optional[str] = None
    warranty_terms: Optional[str] = None
    items: Optional[list[LineItemIn]] = None

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, v: Any) -> Optional[str]:
        return None if v is None else _normalize_doc_type(v)

    @field_validator("merchant_name", mode="before")
    @classmethod
    def normalize_merchant_name(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or "Bilinmeyen Satıcı"

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, v: Any) -> Optional[str]:
        return None if v is None else _normalize_currency(v)

    @field_validator("subtotal", "vat_amount", "total_amount", mode="before")
    @classmethod
    def normalize_amounts(cls, v: Any) -> Optional[float]:
        return _parse_optional_float(v)

    @field_validator("warranty_months", mode="before")
    @classmethod
    def normalize_warranty_months(cls, v: Any) -> Optional[int]:
        return _parse_optional_int(v)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: Any) -> Optional[str]:
        return None if v is None else _normalize_category_val(v)

    @field_validator("document_date", "warranty_end_date", mode="before")
    @classmethod
    def normalize_date_str(cls, v: Any) -> Optional[str]:
        return _normalize_date_val(v)

    @field_validator("summary", "warranty_terms", mode="before")
    @classmethod
    def normalize_text_fields(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v).strip()


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

    llm_provider: Optional[Literal["ollama", "gemini", "openai"]] = None
    vlm_provider: Optional[Literal["auto", "ollama", "gemini", "openai"]] = None
    ollama_llm_model: Optional[str] = None
    ollama_vlm_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
