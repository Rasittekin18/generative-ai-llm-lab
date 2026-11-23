"""Hibrit (SQL + RAG) yönlendirici ajan ve kaynaklı yanıt sentezleyici."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Optional

from core.database import SCHEMA_DESCRIPTION, DatabaseManager
from core.llm_provider import LLMRouter, ProviderError
from core.rag_engine import RAGEngine
from core.schemas import ChatResponse, SourceCitation


ROUTER_SYSTEM_PROMPT = """Sen bir kişisel finans, fiş/fatura ve garanti takip ajanının yönlendiricisisin (Router).
Kullanıcının sorusunu incele ve hangi aracın/araçların çalışması gerektiğine karar ver:
- "sql": Toplam harcama, adet, ortalama, tarih aralığı, en pahalı ürün, mağaza bazlı toplam, bitmek üzere olan garanti tarihleri, kategori dağılımı gibi KESİN SAYISAL veya LİSTE soruları.
- "rag": Garanti şartları, kullanıcı hatası, kapsam dışı durumlar, iade/değişim koşulları, ürün açıklaması veya sözleşme maddesi gibi ANLAMSAL METİN arama soruları.
- "hybrid": Hem harcama/ürün/tarih sorgulayıp hem de garanti şartı, koşul veya belge içeriği yorumu isteyen karma sorular.
- "direct": Merhaba, nasılsın veya sistemin nasıl çalıştığı gibi veritabanı/belge gerektirmeyen genel sohbet.

YALNIZCA şu JSON formatında yanıt ver:
{"route": "sql | rag | hybrid | direct", "reason": "kısa gerekçe"}""".strip()


SQL_GEN_SYSTEM_PROMPT = f"""Sen uzman bir SQLite SQL üreticisisin.
Görevin kullanıcının sorusunu yanıtlayacak TEK BİR güvenli salt-okunur SELECT sorgusu üretmektir.

{SCHEMA_DESCRIPTION}

Kurallar:
1. YALNIZCA SELECT (veya WITH ... SELECT) sorgusu yaz. INSERT/UPDATE/DELETE/DROP/ALTER KESİNLİKLE YASAK.
2. Tek bir sorgu yaz; noktalı virgül (;) ve SQL yorumu (--, /*) kullanma.
3. Türkçe karakter veya mağaza/ürün aramalarında LIKE '%anahtar%' kullanabilirsin.
4. Tarih karşılaştırmaları 'YYYY-MM-DD' biçimindedir (ör. date('2026-11-23')).
5. En fazla 30 satır döndürmek için uygun olduğunda LIMIT ekle.
6. Yanıtını YALNIZCA şu JSON biçiminde ver:
{{"sql": "SELECT ..."}}""".strip()


SYNTHESIS_SYSTEM_PROMPT = """Sen kişisel fiş, fatura ve garanti takip asistanısın.
Kurallar:
1. Yanıtını YALNIZCA sana verilen SQL sonuçlarına ve RAG belge parçalarına dayandır.
2. Veritabanında veya belgelerde olmayan hiçbir tutar, tarih, mağaza ya da garanti şartı UYDURMA. Bilgi yoksa açıkça "Kayıtlı belgelerde bu bilgi bulunamadı" de.
3. Sayısal tutarları para birimiyle (ör. TRY / TL) açık yaz ve hangi belgeye/mağazaya dayandığını kaynak olarak belirt.
4. Kısa, net, düzenli ve Türkçe yanıt ver.""".strip()


class HybridAgent:
    """SQL Aracı + RAG Aracını birleştiren Hibrit Ajan."""

    def __init__(self, db: DatabaseManager, rag: RAGEngine, llm: LLMRouter):
        self.db = db
        self.rag = rag
        self.llm = llm

    def _route(self, question: str) -> tuple[str, str]:
        data, model = self.llm.chat_json(
            [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
        )
        route = str(data.get("route", "hybrid")).strip().lower()
        if route not in {"sql", "rag", "hybrid", "direct"}:
            route = "hybrid"
        return route, model

    def _run_sql_tool(self, question: str, today_iso: str) -> tuple[Optional[str], list[dict[str, Any]], Optional[str], str]:
        messages = [
            {"role": "system", "content": SQL_GEN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Bugünün tarihi: {today_iso}\nKullanıcı sorusu: {question}",
            },
        ]
        data, model = self.llm.chat_json(messages, temperature=0.0)
        sql = str(data.get("sql", "")).strip()
        try:
            rows = self.db.execute_safe_readonly_sql(sql)
            return sql, rows, None, model
        except Exception as first_err:
            # 1 kez otomatik SQL hata düzeltme denemesi
            retry_msgs = messages + [
                {"role": "assistant", "content": f'{{"sql": "{sql}"}}'},
                {
                    "role": "user",
                    "content": f"Bu SQL sorgusu şu hatayı verdi: {first_err}. Lütfen şemaya uygun, geçerli ve güvenli bir SELECT sorgusu olarak düzelt.",
                },
            ]
            try:
                data2, model = self.llm.chat_json(retry_msgs, temperature=0.0)
                sql2 = str(data2.get("sql", "")).strip()
                rows2 = self.db.execute_safe_readonly_sql(sql2)
                return sql2, rows2, None, model
            except Exception as second_err:
                return sql, [], str(second_err), model

    def _run_rag_tool(self, question: str, top_k: int = 4) -> list[SourceCitation]:
        hits = self.rag.search(question, top_k=top_k)
        return [
            SourceCitation(
                document_id=int(h["document_id"]),
                file_name=h.get("file_name", ""),
                merchant_name=h.get("merchant_name", ""),
                document_date=h.get("document_date"),
                document_type=h.get("document_type", "fis"),
                score=float(h.get("score", 0.0)),
                excerpt=h.get("text", "")[:320],
            )
            for h in hits
        ]

    def answer(self, question: str, session_id: str = "default") -> ChatResponse:
        t0 = time.perf_counter()
        today_iso = date.today().isoformat()

        self.db.append_chat_message(session_id, "user", question)
        history = self.db.get_chat_history(session_id, limit=8)

        route, model_used = self._route(question)
        sql_query: Optional[str] = None
        sql_rows: list[dict[str, Any]] = []
        sql_error: Optional[str] = None
        sources: list[SourceCitation] = []

        if route in {"sql", "hybrid"}:
            sql_query, sql_rows, sql_error, model_used = self._run_sql_tool(question, today_iso)
            # SQL boş veya hatalı dönerse ek bağlam için RAG fallback
            if (sql_error or not sql_rows) and route == "sql":
                sources = self._run_rag_tool(question, top_k=4)
                if sources:
                    route = "hybrid"

        if route in {"rag", "hybrid"} and not sources:
            sources = self._run_rag_tool(question, top_k=4)

        if route == "direct":
            ans_text, model_used = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": "Sen kişisel fiş, fatura ve garanti takip asistanısın. Kısa ve yardımcı Türkçe yanıt ver.",
                    },
                    {"role": "user", "content": question},
                ],
                temperature=0.2,
            )
        else:
            context_blocks = [f"Bugünün tarihi: {today_iso}"]
            if sql_query:
                context_blocks.append(f"Çalıştırılan SQL Sorgusu:\n{sql_query}")
                if sql_error:
                    context_blocks.append(f"SQL Hatası: {sql_error}")
                else:
                    context_blocks.append(f"SQL Sonuçları ({len(sql_rows)} satır):\n{sql_rows}")
            if sources:
                rag_str = "\n\n".join(
                    f"[Belge #{s.document_id} | {s.merchant_name} | {s.document_date or 'Tarihsiz'} | {s.file_name} | Skor: {s.score}]\n{s.excerpt}"
                    for s in sources
                )
                context_blocks.append(f"RAG Belge Parçaları:\n{rag_str}")

            recent_turns = [
                {"role": h["role"], "content": h["content"]}
                for h in history[:-1][-4:]
                if h["role"] in {"user", "assistant"}
            ]
            synth_messages = [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                *recent_turns,
                {
                    "role": "user",
                    "content": (
                        f"Kullanıcı Sorusu: {question}\n\n"
                        + "\n\n---\n\n".join(context_blocks)
                        + "\n\nYukarıdaki gerçek verilere dayanarak soruyu yanıtla."
                    ),
                },
            ]
            ans_text, model_used = self.llm.chat(synth_messages, temperature=0.1)

        latency_ms = int((time.perf_counter() - t0) * 1000)
        self.db.append_chat_message(
            session_id,
            "assistant",
            ans_text,
            metadata={
                "route_used": route,
                "sql_query": sql_query,
                "sources": [s.model_dump() for s in sources],
                "latency_ms": latency_ms,
                "model_used": model_used,
            },
        )

        return ChatResponse(
            answer=ans_text,
            route_used=route,  # type: ignore[arg-type]
            sql_query=sql_query,
            sql_rows=sql_rows,
            sources=sources,
            latency_ms=latency_ms,
            model_used=model_used,
        )
