"""Bos port bulan, sunucuyu baslatan ve hazir olunca tarayiciyi acan baslatici."""

import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def find_free_port(start_port: int = 8000, end_port: int = 8099) -> int:
    """Kullanilabilir ilk bos TCP portunu bulur."""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"{start_port}-{end_port} araliginda bos port bulunamadi.")


def open_browser_when_ready(port: int, timeout_sec: float = 90.0) -> None:
    """Sunucu /api/health yaniti verene kadar bekler ve tarayiciyi acar."""
    url = f"http://127.0.0.1:{port}"
    health_url = f"{url}/api/health"
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as resp:
                if resp.status == 200:
                    print(f"[LectureMind] Hazir! Tarayici aciliyor -> {url}", flush=True)
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.4)


def main() -> None:
    port = find_free_port(8000, 8099)
    if port != 8000:
        print(f"[LectureMind] Port 8000 dolu oldugu icin otomatik olarak {port} secildi.", flush=True)
    else:
        print(f"[LectureMind] Port {port} secildi.", flush=True)

    print("[LectureMind] Yapay zeka modulleri yukleniyor, hazir olunca tarayici acilacak...", flush=True)
    print(f"[LectureMind] Adres: http://127.0.0.1:{port} (Kapatmak icin Ctrl+C)", flush=True)

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
