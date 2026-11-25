from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

from app.config import get_settings


def _is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(host: str, preferred_port: int, max_tries: int = 50) -> int:
    """Tercih edilen port doluysa sıradaki ilk boş portu döndürür."""
    for candidate in range(preferred_port, preferred_port + max_tries):
        if _is_port_free(host, candidate):
            return candidate
    raise RuntimeError(
        f"{preferred_port} - {preferred_port + max_tries - 1} aralığında boş port bulunamadı."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="İkinci Beyin & Öğrenme Asistanı")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Sunucu başlarken tarayıcıyı otomatik aç",
    )
    args = parser.parse_args()

    settings = get_settings()
    port = find_free_port(settings.host, settings.port)
    if port != settings.port:
        print(
            f"[Bilgi] Port {settings.port} dolu, otomatik olarak {port} portuna geçiliyor."
        )

    url = f"http://{settings.host}:{port}"
    print(f"[Baslatiliyor] Ikinci Beyin ve Ogrenme Asistani -> {url}")

    if args.open_browser:
        timer = threading.Timer(1.2, webbrowser.open, args=[url])
        timer.daemon = True
        timer.start()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
