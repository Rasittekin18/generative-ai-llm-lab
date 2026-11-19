"""Tek komutla hem FastAPI backend'i hem Windows masaüstü uygulamasını başlatır."""

import os
import threading
import time

import httpx
import uvicorn

from backend.config import get_backend_url
from backend.main import app as fastapi_app
from desktop.app import run_desktop


def _is_healthy(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/health", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


def _start_backend_server(host: str, port: int) -> None:
    config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def _wait_until_healthy(url: str, timeout_s: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _is_healthy(url):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8765"))
    backend_url = get_backend_url()

    print("==============================================")
    print("  Akilli Ingilizce Okuma & Yazma Asistani")
    print("==============================================")

    if not _is_healthy(backend_url):
        print(f"Backend baslatiliyor ({backend_url})...")
        t = threading.Thread(target=_start_backend_server, args=(host, port), daemon=True)
        t.start()
        if not _wait_until_healthy(backend_url):
            print("UYARI: Backend beklenen surede hazir olmadi.")
    else:
        print(f"Mevcut backend kullaniliyor ({backend_url}).")

    print("Hazir! Sistem tepsisinde (sag alt 'EN' ikonu) calisiyor.")
    print("  - Secili metni cevir : Alt + Q  (veya fareyle secince cikan 'Cevir' butonu)")
    print("  - Yazma & Prompt kocu: Alt + W")
    return run_desktop(backend_url)


if __name__ == "__main__":
    raise SystemExit(main())
