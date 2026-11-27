"""FastAPI uygulaması ve REST API uç noktaları."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from config import BASE_DIR, Settings, settings as default_settings
from core.agent import HybridAgent
from core.database import DatabaseManager, compute_file_hash
from core.extractor import InvalidDocumentError, extract_document_preview
from core.llm_provider import LLMRouter, ProviderError
from core.rag_engine import EmbedderProtocol, LocalTurkishEmbedder, RAGEngine
from core.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentCreateRequest,
    DocumentUpdateRequest,
    ExtractionPreviewResponse,
    LineItemIn,
    RuntimeSettingsUpdate,
)


def create_app(
    app_settings: Optional[Settings] = None,
    embedder: Optional[EmbedderProtocol] = None,
    llm_router: Optional[LLMRouter] = None,
) -> FastAPI:
    """Test edilebilir FastAPI uygulama fabrikası."""
    cfg = app_settings or default_settings
    cfg.ensure_dirs()

    db = DatabaseManager(cfg.db_path)
    emb = embedder or LocalTurkishEmbedder(cfg.embedding_model)
    rag = RAGEngine(cfg.vector_dir, emb)
    llm = llm_router or LLMRouter(cfg)
    agent = HybridAgent(db=db, rag=rag, llm=llm)

    app = FastAPI(
        title="Fiş, Fatura ve Garanti Takip Ajanı",
        description="Hibrit VLM + SQL + RAG tabanlı kişisel evrak ve harcama zekâsı",
        version="1.0.0",
    )

    static_dir = BASE_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Testler ve dahili erişim için state
    app.state.settings = cfg
    app.state.db = db
    app.state.rag = rag
    app.state.llm = llm
    app.state.agent = agent

    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    MAX_FILE_BYTES = 25 * 1024 * 1024

    @app.get("/", response_class=HTMLResponse)
    def serve_index() -> HTMLResponse:
        index_file = static_dir / "index.html"
        if not index_file.exists():
            return HTMLResponse("<h1>index.html bulunamadı</h1>", status_code=404)
        return HTMLResponse(index_file.read_text(encoding="utf-8"))

    @app.get("/api/status")
    def get_status() -> dict[str, Any]:
        ollama = llm.check_ollama_health()
        stats = db.get_dashboard_stats()
        return {
            "ollama": ollama,
            "active_config": {
                "llm_provider": cfg.llm_provider,
                "vlm_provider": cfg.vlm_provider,
                "ollama_llm_model": cfg.ollama_llm_model,
                "ollama_vlm_model": cfg.ollama_vlm_model,
                "embedding_model": cfg.embedding_model,
                "has_gemini_key": bool(cfg.gemini_api_key),
                "gemini_model": cfg.gemini_model,
                "has_openai_key": bool(cfg.openai_api_key),
                "openai_base_url": cfg.openai_base_url,
                "openai_model": cfg.openai_model,
            },
            "rag": {
                "backend": rag.backend_name,
                "total_chunks": rag.total_chunks,
            },
            "database": {
                "doc_count": stats["doc_count"],
                "expiring_30_days": stats["expiring_30_days"],
            },
        }

    @app.post("/api/settings")
    def update_settings(req: RuntimeSettingsUpdate) -> dict[str, Any]:
        if req.llm_provider is not None:
            cfg.llm_provider = req.llm_provider
        if req.vlm_provider is not None:
            cfg.vlm_provider = req.vlm_provider
        if req.ollama_llm_model is not None and req.ollama_llm_model.strip():
            cfg.ollama_llm_model = req.ollama_llm_model.strip()
        if req.ollama_vlm_model is not None and req.ollama_vlm_model.strip():
            cfg.ollama_vlm_model = req.ollama_vlm_model.strip()
        if req.gemini_api_key is not None and req.gemini_api_key.strip():
            cfg.gemini_api_key = req.gemini_api_key.strip()
        if req.gemini_model is not None and req.gemini_model.strip():
            cfg.gemini_model = req.gemini_model.strip()
        if req.openai_api_key is not None and req.openai_api_key.strip():
            cfg.openai_api_key = req.openai_api_key.strip()
        if req.openai_base_url is not None and req.openai_base_url.strip():
            cfg.openai_base_url = req.openai_base_url.strip()
        if req.openai_model is not None and req.openai_model.strip():
            cfg.openai_model = req.openai_model.strip()
        return {"ok": True, "status": get_status()}

    @app.get("/api/dashboard")
    def get_dashboard() -> dict[str, Any]:
        return db.get_dashboard_stats()

    @app.post("/api/documents/extract", response_model=ExtractionPreviewResponse)
    async def extract_document(file: UploadFile = File(...)) -> ExtractionPreviewResponse:
        file_name = file.filename or "belge.bin"
        ext = Path(file_name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Desteklenmeyen dosya türü ({ext}). İzin verilenler: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Boş dosya yüklenemez.")
        if len(raw_bytes) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="Dosya boyutu 25 MB sınırını aşıyor.")

        try:
            return extract_document_preview(
                raw_bytes=raw_bytes,
                file_name=file_name,
                mime_type=file.content_type or "application/octet-stream",
                upload_dir=cfg.upload_dir,
                db=db,
                llm_router=llm,
            )
        except InvalidDocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/documents")
    def save_document(req: DocumentCreateRequest) -> dict[str, Any]:
        resolved_path = Path(req.file_path).resolve()
        if not resolved_path.is_relative_to(cfg.upload_dir.resolve()):
            raise HTTPException(status_code=400, detail="Geçersiz dosya yolu.")
        existing = db.find_by_hash(req.file_hash)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Bu belge zaten #{existing['id']} numarasıyla kayıtlı.",
            )
        doc_id = db.insert_document(req)
        saved = db.get_document(doc_id)
        if saved:
            rag.index_document(saved)
        return {"ok": True, "document": saved}

    @app.get("/api/documents")
    def list_documents(
        category: Optional[str] = Query(default=None),
        document_type: Optional[str] = Query(default=None),
        search: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        docs = db.list_documents(category=category, document_type=document_type, search=search)
        return {"documents": docs, "count": len(docs)}

    @app.get("/api/documents/export/csv")
    def export_documents_csv(
        category: Optional[str] = Query(default=None),
        document_type: Optional[str] = Query(default=None),
        search: Optional[str] = Query(default=None),
    ) -> Response:
        csv_content = db.export_documents_csv(
            category=category,
            document_type=document_type,
            search=search,
        )
        return Response(
            content=csv_content.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="belgeler_harcamalar.csv"'},
        )

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: int) -> dict[str, Any]:
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Belge bulunamadı.")
        return doc

    @app.put("/api/documents/{doc_id}")
    def update_document(doc_id: int, payload: DocumentUpdateRequest) -> dict[str, Any]:
        ok = db.update_document(doc_id, payload)
        if not ok:
            raise HTTPException(status_code=404, detail="Belge bulunamadı.")
        updated = db.get_document(doc_id)
        if updated:
            rag.index_document(updated)
        return {"ok": True, "document": updated}

    @app.delete("/api/documents/{doc_id}")
    def delete_document(doc_id: int) -> dict[str, Any]:
        deleted = db.delete_document(doc_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Belge bulunamadı.")
        rag.delete_document(doc_id)
        file_path = Path(deleted["file_path"])
        try:
            if file_path.exists() and file_path.resolve().is_relative_to(cfg.upload_dir.resolve()):
                file_path.unlink()
        except Exception:
            pass
        return {"ok": True, "deleted_id": doc_id}

    @app.get("/api/documents/{doc_id}/file")
    def serve_document_file(doc_id: int) -> FileResponse:
        doc = db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Belge bulunamadı.")
        file_path = Path(doc["file_path"]).resolve()
        if not file_path.is_relative_to(cfg.upload_dir.resolve()) or not file_path.exists():
            raise HTTPException(status_code=404, detail="Belge dosyası diskte bulunamadı.")
        return FileResponse(path=str(file_path), media_type=doc.get("mime_type") or "application/octet-stream")

    @app.get("/api/uploads/{filename}")
    def serve_upload_preview(filename: str) -> FileResponse:
        target = (cfg.upload_dir / filename).resolve()
        if not target.is_relative_to(cfg.upload_dir.resolve()) or not target.exists():
            raise HTTPException(status_code=404, detail="Önizleme dosyası bulunamadı.")
        return FileResponse(path=str(target))

    @app.post("/api/chat", response_model=ChatResponse)
    def chat_endpoint(req: ChatRequest) -> ChatResponse:
        try:
            return agent.answer(req.question, session_id=req.session_id)
        except ProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/chat/history")
    def chat_history(session_id: str = "default") -> dict[str, Any]:
        return {"messages": db.get_chat_history(session_id=session_id)}

    @app.delete("/api/chat/history")
    def clear_history(session_id: str = "default") -> dict[str, Any]:
        db.clear_chat_history(session_id=session_id)
        return {"ok": True}

    @app.post("/api/demo/seed")
    def seed_demo_data() -> dict[str, Any]:
        """Hızlı test için örnek Türkçe fiş, fatura ve garanti belgeleri yükler."""
        from datetime import date, timedelta

        today = date.today()
        d1 = (today - timedelta(days=12)).isoformat()
        d2 = (today - timedelta(days=710)).isoformat()  # ~20 gün sonra 24 aylık garantisi bitecek
        d3 = (today - timedelta(days=5)).isoformat()
        d4 = (today - timedelta(days=180)).isoformat()

        demo_specs = [
            {
                "file_name": "teknomarket_kulaklik_fatura.txt",
                "document_type": "fatura",
                "merchant_name": "TeknoMarket Elektronik A.Ş.",
                "document_date": d2,
                "currency": "TRY",
                "subtotal": 2916.67,
                "vat_amount": 583.33,
                "total_amount": 3500.0,
                "category": "Teknoloji",
                "warranty_months": 24,
                "summary": "Kablosuz gürültü önleyici kulaklık alımı ve 24 ay resmi distribütör garantisi.",
                "warranty_terms": (
                    "Resmi distribütör garantisi 24 aydır. Pil kapasitesinin olağan yıpranması ilk 12 ay kapsamındadır. "
                    "Sıvı teması, yetkisiz tamir müdahalesi, düşmeye bağlı fiziksel kırılma ve orijinal olmayan şarj adaptörü "
                    "kullanımı kullanıcı hatası sayılır ve garanti kapsamı dışındadır."
                ),
                "raw_text": "TeknoMarket Fatura - SoundPro ANC Kulaklık - Toplam 3500 TRY - Garanti 24 ay. Kullanıcı hatası halleri: sıvı teması, darbe, yetkisiz servis.",
                "items": [
                    LineItemIn(name="SoundPro ANC Kablosuz Kulaklık", quantity=1, unit_price=3500.0, total_price=3500.0, warranty_months=24),
                ],
            },
            {
                "file_name": "migros_market_fisi.txt",
                "document_type": "fis",
                "merchant_name": "Migros Ticaret A.Ş.",
                "document_date": d1,
                "currency": "TRY",
                "subtotal": 1150.0,
                "vat_amount": 95.5,
                "total_amount": 1245.5,
                "category": "Market",
                "warranty_months": None,
                "summary": "Haftalık gıda ve temizlik market alışverişi fişi.",
                "warranty_terms": "Gıda ürünlerinde açılmamış ambalaj ile 14 gün içinde fiş ibrazı ile iade mümkündür.",
                "raw_text": "Migros Fişi: Zeytinyağı 1L (380 TL), Kahve Çekirdeği 500g (420 TL), Deterjan (245.50 TL), Süt & Yoğurt (200 TL). Toplam 1245.50 TRY.",
                "items": [
                    LineItemIn(name="Sızma Zeytinyağı 1L", quantity=1, unit_price=380.0, total_price=380.0),
                    LineItemIn(name="Filtre Kahve Çekirdeği 500g", quantity=1, unit_price=420.0, total_price=420.0),
                    LineItemIn(name="Çamaşır Deterjanı", quantity=1, unit_price=245.5, total_price=245.5),
                    LineItemIn(name="Süt ve Yoğurt", quantity=1, unit_price=200.0, total_price=200.0),
                ],
            },
            {
                "file_name": "arcelik_kahve_makinesi_garanti.txt",
                "document_type": "garanti_belgesi",
                "merchant_name": "Arçelik Yetkili Bayi",
                "document_date": d4,
                "currency": "TRY",
                "subtotal": 7500.0,
                "vat_amount": 1500.0,
                "total_amount": 9000.0,
                "category": "Ev & Yaşam",
                "warranty_months": 36,
                "summary": "Otomatik espresso kahve makinesi ve 36 ay üretici garanti belgesi.",
                "warranty_terms": (
                    "36 ay üretici garantisi geçerlidir. Kireç çözme bakımının düzenli yapılmamasından kaynaklanan "
                    "pompa tıkanıklıkları garanti dışı bırakılabilir. İlk 6 ay içinde üretim kaynaklı arızalarda birebir değişim hakkı vardır."
                ),
                "raw_text": "Arçelik Espresso Makinesi Garanti Belgesi. Süre: 36 ay. Kireç bakımı yapılmaması garanti dışı kalma sebebidir.",
                "items": [
                    LineItemIn(name="Otomatik Espresso Makinesi", quantity=1, unit_price=9000.0, total_price=9000.0, warranty_months=36),
                ],
            },
            {
                "file_name": "kahve_dunyasi_fis.txt",
                "document_type": "fis",
                "merchant_name": "Kahve Dünyası",
                "document_date": d3,
                "currency": "TRY",
                "subtotal": 290.91,
                "vat_amount": 29.09,
                "total_amount": 320.0,
                "category": "Yemek",
                "warranty_months": None,
                "summary": "İki kişilik kahve ve tatlı restoran fişi.",
                "warranty_terms": "",
                "raw_text": "Kahve Dünyası Fiş: 2x Latte (220 TL), 1x Cheesecake (100 TL). Toplam 320.00 TRY.",
                "items": [
                    LineItemIn(name="Latte", quantity=2, unit_price=110.0, total_price=220.0),
                    LineItemIn(name="Cheesecake", quantity=1, unit_price=100.0, total_price=100.0),
                ],
            },
        ]

        inserted_ids = []
        for spec in demo_specs:
            raw_bytes = spec["raw_text"].encode("utf-8")
            fhash = compute_file_hash(raw_bytes)
            if db.find_by_hash(fhash):
                continue
            fpath = cfg.upload_dir / f"{fhash[:12]}_{spec['file_name']}"
            fpath.write_bytes(raw_bytes)
            req = DocumentCreateRequest(
                file_name=spec["file_name"],
                file_path=str(fpath),
                file_hash=fhash,
                mime_type="text/plain",
                extraction_method="demo_seed",
                **{k: v for k, v in spec.items() if k != "file_name"},
            )
            doc_id = db.insert_document(req)
            doc = db.get_document(doc_id)
            if doc:
                rag.index_document(doc)
            inserted_ids.append(doc_id)

        return {"ok": True, "inserted_count": len(inserted_ids), "inserted_ids": inserted_ids}

    return app


app = create_app()
