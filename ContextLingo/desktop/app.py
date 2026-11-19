"""Ana masaüstü uygulaması: Sistem tepsisi, arka plan HTTP worker'ları ve pencere orkestrasyonu."""

import sys
from typing import Any, Callable, Dict, Optional

import httpx
from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from backend.config import get_backend_url, load_settings
from desktop.clipboard_capture import capture_selected_text
from desktop.hotkey_mouse import InputListenerManager
from desktop.ui_popup import MiniTriggerPill, TranslationPopup
from desktop.ui_settings import SettingsWindow
from desktop.ui_vocab import VocabHistoryWindow
from desktop.ui_writer import WriterWindow


def _create_tray_icon() -> QIcon:
    """Harici ikon dosyasına ihtiyaç duymadan temiz bir sistem tepsisi ikonu üretir."""
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#2F6FEB"))
    painter.setPen(QColor("#6BA0FF"))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#FFFFFF"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(22)
    painter.setFont(font)
    painter.drawText(pix.rect(), 0x0084, "EN")
    painter.end()
    return QIcon(pix)


class ApiWorker(QThread):
    """UI donmasını önlemek için HTTP isteklerini arka plan thread'inde çalıştırır."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            res = self._fn()
            self.finished_ok.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class DesktopCoordinator(QObject):
    """Sistem tepsisi, native Win32 kısayollar, fare tetikleyici ve pencereler arası köprü."""

    def __init__(self, qt_app: QApplication, backend_url: str, show_startup_window: bool = True) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.backend_url = backend_url.rstrip("/")
        self.qt_app.setQuitOnLastWindowClosed(False)
        self._workers = []

        settings = load_settings()

        # Pencereler
        self.mini_pill = MiniTriggerPill()
        self.popup = TranslationPopup()
        self.writer = WriterWindow()
        self.vocab_win = VocabHistoryWindow()
        self.settings_win = SettingsWindow()

        # Dinleyiciler (Native Win32 Alt+Q / Alt+W + Fare seçimi)
        self.listener = InputListenerManager(qt_app)
        self.listener.set_mouse_popup_enabled(settings.enable_mouse_selection_popup)

        # Sinyaller
        self.listener.translate_hotkey_triggered.connect(self._handle_hotkey_translate)
        self.listener.writer_hotkey_triggered.connect(lambda: self.writer.prefill_and_show(""))
        self.listener.mouse_selection_detected.connect(self._handle_mouse_selection)
        self.mini_pill.clicked_at.connect(self._handle_pill_translate)

        self.popup.save_vocab_requested.connect(self._save_vocab)
        self.popup.open_in_writer_requested.connect(self.writer.prefill_and_show)

        self.writer.submit_write.connect(self._run_writer)
        self.writer.save_vocab_requested.connect(self._save_vocab)

        self.vocab_win.refresh_requested.connect(self._refresh_vocab_and_history)
        self.vocab_win.toggle_mastered_requested.connect(self._toggle_vocab)
        self.vocab_win.delete_vocab_requested.connect(self._delete_vocab)

        self.settings_win.save_requested.connect(self._save_settings)

        # Sistem Tepsisi
        self.tray = QSystemTrayIcon(_create_tray_icon(), self)
        self.tray.setToolTip("Akıllı İngilizce Asistanı (Alt+Q: Çevir | Alt+W: Yazma Koçu)")
        self.tray.activated.connect(self._on_tray_activated)
        self._build_tray_menu(settings.enable_mouse_selection_popup)
        self.tray.show()

        self.listener.start()

        if show_startup_window:
            QTimer.singleShot(
                400,
                lambda: self.tray.showMessage(
                    "Akıllı İngilizce Asistanı Hazır",
                    "Herhangi bir uygulamada metin seçip Alt+Q'ya basın (veya çıkan '✨ Çevir' butonuna tıklayın). Yazma Koçu: Alt+W",
                    QSystemTrayIcon.Information,
                    4500,
                ),
            )
            QTimer.singleShot(250, lambda: self.writer.prefill_and_show(""))

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.writer.prefill_and_show("")

    def _build_tray_menu(self, mouse_enabled: bool) -> None:
        menu = QMenu()

        act_writer = QAction("✍️ Yazma & Prompt Koçu (Alt+W)", self)
        act_writer.triggered.connect(lambda: self.writer.prefill_and_show(""))
        menu.addAction(act_writer)

        act_vocab = QAction("📚 Kelime Defterim & Geçmiş", self)
        act_vocab.triggered.connect(self.vocab_win.open_and_refresh)
        menu.addAction(act_vocab)

        menu.addSeparator()

        self.act_mouse_toggle = QAction("🖱️ Fareyle Seçince 'Çevir' Butonu", self)
        self.act_mouse_toggle.setCheckable(True)
        self.act_mouse_toggle.setChecked(mouse_enabled)
        self.act_mouse_toggle.triggered.connect(self._toggle_mouse_from_tray)
        menu.addAction(self.act_mouse_toggle)

        act_settings = QAction("⚙️ Ayarlar", self)
        act_settings.triggered.connect(self._open_settings)
        menu.addAction(act_settings)

        menu.addSeparator()
        act_quit = QAction("Çıkış", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)

    def _is_own_window_at(self, pt: QPoint) -> bool:
        for win in (self.mini_pill, self.popup, self.writer, self.vocab_win, self.settings_win):
            if win.isVisible() and win.frameGeometry().contains(pt):
                return True
        return False

    def _handle_mouse_selection(self) -> None:
        pos = QCursor.pos()
        if self._is_own_window_at(pos):
            return
        self.mini_pill.show_at(pos.x(), pos.y())

    def _handle_hotkey_translate(self) -> None:
        pos = QCursor.pos()
        self._trigger_translate(pos.x(), pos.y(), allow_clipboard_fallback=True)

    def _handle_pill_translate(self, x: int, y: int) -> None:
        self._trigger_translate(x, y, allow_clipboard_fallback=False)

    def _trigger_translate(self, x: int, y: int, allow_clipboard_fallback: bool) -> None:
        self.mini_pill.hide()
        text, win_title = capture_selected_text(allow_clipboard_fallback=allow_clipboard_fallback)
        if not text:
            if allow_clipboard_fallback:
                self.tray.showMessage(
                    "Metin Seçilmedi",
                    "Önce çevirmek istediğiniz metni fareyle seçin (veya kopyalayın), sonra Alt+Q'ya basın.",
                    QSystemTrayIcon.Information,
                    2500,
                )
            return

        self.popup.show_loading(text, win_title, x, y)

        def call_api() -> Dict:
            with httpx.Client(timeout=60.0) as client:
                r = client.post(
                    f"{self.backend_url}/api/analyze",
                    json={"text": text, "source_context_hint": win_title},
                )
                r.raise_for_status()
                return r.json()

        self._spawn_worker(call_api, self.popup.show_result, self.popup.show_error)

    def _run_writer(self, text: str, tone: str, mode: str) -> None:
        def call_api() -> Dict:
            with httpx.Client(timeout=60.0) as client:
                r = client.post(
                    f"{self.backend_url}/api/write",
                    json={"text": text, "tone": tone, "mode": mode},
                )
                r.raise_for_status()
                return r.json()

        self._spawn_worker(call_api, self.writer.show_result, self.writer.show_error)

    def _save_vocab(self, item: Dict, source_sentence: str) -> None:
        payload = {
            "word": item.get("word", ""),
            "meaning_tr": item.get("meaning_tr", ""),
            "cefr_level": item.get("cefr_level", "B1"),
            "example_en": item.get("example_en", ""),
            "source_sentence": source_sentence,
        }

        def call_api() -> Dict:
            with httpx.Client(timeout=15.0) as client:
                r = client.post(f"{self.backend_url}/api/vocab", json=payload)
                r.raise_for_status()
                return r.json()

        self._spawn_worker(call_api, lambda _res: None, lambda _err: None)

    def _refresh_vocab_and_history(self, only_unmastered: bool) -> None:
        def call_api() -> tuple:
            with httpx.Client(timeout=15.0) as client:
                v = client.get(f"{self.backend_url}/api/vocab", params={"only_unmastered": only_unmastered})
                v.raise_for_status()
                h = client.get(f"{self.backend_url}/api/history", params={"limit": 30})
                h.raise_for_status()
                return v.json(), h.json()

        self._spawn_worker(call_api, lambda res: self.vocab_win.set_data(res[0], res[1]), lambda _err: None)

    def _toggle_vocab(self, vocab_id: int) -> None:
        def call_api() -> Dict:
            with httpx.Client(timeout=15.0) as client:
                r = client.patch(f"{self.backend_url}/api/vocab/{vocab_id}/toggle")
                r.raise_for_status()
                return r.json()

        self._spawn_worker(
            call_api,
            lambda _res: self._refresh_vocab_and_history(self.vocab_win.only_unmastered_chk.isChecked()),
            lambda _err: None,
        )

    def _delete_vocab(self, vocab_id: int) -> None:
        def call_api() -> Dict:
            with httpx.Client(timeout=15.0) as client:
                r = client.delete(f"{self.backend_url}/api/vocab/{vocab_id}")
                r.raise_for_status()
                return r.json()

        self._spawn_worker(
            call_api,
            lambda _res: self._refresh_vocab_and_history(self.vocab_win.only_unmastered_chk.isChecked()),
            lambda _err: None,
        )

    def _open_settings(self) -> None:
        def call_api() -> Dict:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(f"{self.backend_url}/api/settings")
                r.raise_for_status()
                return r.json()

        self._spawn_worker(call_api, self.settings_win.load_and_show, lambda _err: None)

    def _save_settings(self, payload: Dict) -> None:
        self.listener.set_mouse_popup_enabled(bool(payload.get("enable_mouse_selection_popup", True)))
        self.act_mouse_toggle.setChecked(bool(payload.get("enable_mouse_selection_popup", True)))

        def call_api() -> Dict:
            with httpx.Client(timeout=15.0) as client:
                r = client.post(f"{self.backend_url}/api/settings", json=payload)
                r.raise_for_status()
                return r.json()

        self._spawn_worker(call_api, lambda _res: None, lambda _err: None)

    def _toggle_mouse_from_tray(self, checked: bool) -> None:
        self.listener.set_mouse_popup_enabled(checked)

        def call_api() -> Dict:
            with httpx.Client(timeout=15.0) as client:
                cur = client.get(f"{self.backend_url}/api/settings").json()
                cur["enable_mouse_selection_popup"] = checked
                r = client.post(f"{self.backend_url}/api/settings", json=cur)
                r.raise_for_status()
                return r.json()

        self._spawn_worker(call_api, lambda _res: None, lambda _err: None)

    def _spawn_worker(self, fn: Callable[[], Any], on_ok: Callable[[Any], None], on_err: Callable[[str], None]) -> None:
        worker = ApiWorker(fn)
        self._workers.append(worker)
        worker.finished_ok.connect(on_ok)
        worker.failed.connect(on_err)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()

    def _cleanup_worker(self, worker: ApiWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _quit(self) -> None:
        self.listener.stop()
        self.tray.hide()
        self.qt_app.quit()


def run_desktop(backend_url: Optional[str] = None) -> int:
    app = QApplication(sys.argv)
    url = backend_url or get_backend_url()
    _coordinator = DesktopCoordinator(app, url)
    return app.exec()
