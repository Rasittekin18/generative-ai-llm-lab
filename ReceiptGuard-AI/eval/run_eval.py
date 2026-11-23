"""Gerçek Ollama modeli ve Türkçe Embedding ile uçtan uca Eval (Değerlendirme) betiği."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from config import Settings


def main() -> int:
    cases_path = Path(__file__).resolve().parent / "test_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cfg = Settings(
            data_dir=tmp_path / "data",
            upload_dir=tmp_path / "data" / "uploads",
            db_path=tmp_path / "data" / "app.db",
            vector_dir=tmp_path / "data" / "vector_index",
        )
        app = create_app(app_settings=cfg)
        client = TestClient(app)

        st = client.get("/api/status").json()
        if not st["ollama"]["running"]:
            print("HATA: Ollama sunucusu çalışmıyor (127.0.0.1:11434). Lütfen 'ollama serve' başlatın.")
            return 1

        print(f"Aktif Ollama LLM: {st['ollama']['recommended_llm']}")
        seed_res = client.post("/api/demo/seed").json()
        print(f"Demo verisi yüklendi: {seed_res['inserted_count']} belge.\n")

        route_hits = 0
        answer_hits = 0
        total_latency = 0

        for case in cases:
            res = client.post("/api/chat", json={"question": case["question"]})
            if res.status_code != 200:
                print(f"[FAIL] {case['id']} -> HTTP {res.status_code}: {res.text}")
                continue
            body = res.json()
            route_ok = body["route_used"] == case["expected_route"]
            # Hybrid sorgularda sql+rag birlikte çalışmışsa da kabul et
            if case["expected_route"] == "hybrid" and body["route_used"] in ("hybrid", "sql", "rag"):
                if body.get("sql_query") and body.get("sources"):
                    route_ok = True

            ans_low = body["answer"].lower()
            ans_ok = any(sub.lower() in ans_low for sub in case["expected_substrings"])

            route_hits += int(route_ok)
            answer_hits += int(ans_ok)
            total_latency += body["latency_ms"]

            print(
                f"[{case['id']}] route={body['route_used']} (beklenen={case['expected_route']}, ok={route_ok}) | "
                f"ans_ok={ans_ok} | {body['latency_ms']} ms"
            )
            if body.get("sql_query"):
                print(f"   SQL: {body['sql_query']}")
            print(f"   Yanıt: {body['answer'][:220].replace(chr(10), ' ')}...\n")

        n = len(cases)
        print("====================================")
        print(f"Rota Doğruluğu  : {route_hits}/{n} ({route_hits / n * 100:.1f}%)")
        print(f"İçerik Doğruluğu: {answer_hits}/{n} ({answer_hits / n * 100:.1f}%)")
        print(f"Ortalama Gecikme: {total_latency / max(n, 1):.0f} ms")
        print("====================================")
        return 0 if answer_hits == n else 2


if __name__ == "__main__":
    raise SystemExit(main())
