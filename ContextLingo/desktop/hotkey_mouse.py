"""Native Win32 global kısayolları (Alt+Q / Alt+W) ve fare seçim dinleyicisi."""

import ctypes
import math
import time
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication
from pynput import mouse

user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000

HOTKEY_ID_TRANSLATE = 1001
HOTKEY_ID_WRITER = 1002

VK_Q = 0x51
VK_W = 0x57


class _WinHotkeyFilter(QAbstractNativeEventFilter):
    """Qt native event döngüsünde Windows WM_HOTKEY mesajlarını yakalar."""

    def __init__(self, on_translate, on_writer) -> None:
        super().__init__()
        self._on_translate = on_translate
        self._on_writer = on_writer

    def nativeEventFilter(self, eventType, message):
        if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID_TRANSLATE:
                    self._on_translate()
                    return True, 0
                if msg.wParam == HOTKEY_ID_WRITER:
                    self._on_writer()
                    return True, 0
        return False, 0


class InputListenerManager(QObject):
    """Windows genelinde native kısayollar (Alt+Q, Alt+W) ve fare seçim olaylarını yönetir."""

    translate_hotkey_triggered = Signal()
    writer_hotkey_triggered = Signal()
    mouse_selection_detected = Signal()

    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self._qt_app = qt_app
        self.mouse_popup_enabled: bool = True
        self._registered = False

        self._event_filter = _WinHotkeyFilter(
            on_translate=self.translate_hotkey_triggered.emit,
            on_writer=self.writer_hotkey_triggered.emit,
        )
        self._mouse_listener: Optional[mouse.Listener] = None

        self._press_pos = (0, 0)
        self._press_time = 0.0
        self._last_click_pos = (0, 0)
        self._last_click_time = 0.0

    def start(self) -> None:
        self.stop()
        self._qt_app.installNativeEventFilter(self._event_filter)

        ok_q = user32.RegisterHotKey(None, HOTKEY_ID_TRANSLATE, MOD_ALT | MOD_NOREPEAT, VK_Q)
        ok_w = user32.RegisterHotKey(None, HOTKEY_ID_WRITER, MOD_ALT | MOD_NOREPEAT, VK_W)
        self._registered = bool(ok_q or ok_w)

        try:
            self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
            self._mouse_listener.start()
        except Exception:
            self._mouse_listener = None

    def stop(self) -> None:
        if self._registered:
            user32.UnregisterHotKey(None, HOTKEY_ID_TRANSLATE)
            user32.UnregisterHotKey(None, HOTKEY_ID_WRITER)
            self._registered = False

        try:
            self._qt_app.removeNativeEventFilter(self._event_filter)
        except Exception:
            pass

        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def set_mouse_popup_enabled(self, enabled: bool) -> None:
        self.mouse_popup_enabled = enabled

    def _on_mouse_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        if not self.mouse_popup_enabled or button != mouse.Button.left:
            return

        now = time.monotonic()
        if pressed:
            self._press_pos = (x, y)
            self._press_time = now
            return

        dx = x - self._press_pos[0]
        dy = y - self._press_pos[1]
        drag_dist = math.hypot(dx, dy)
        hold_dur = now - self._press_time

        is_drag_select = drag_dist >= 16 and hold_dur >= 0.08
        is_double_click = (
            (now - self._last_click_time) <= 0.35
            and math.hypot(x - self._last_click_pos[0], y - self._last_click_pos[1]) <= 8
        )

        self._last_click_pos = (x, y)
        self._last_click_time = now

        if is_drag_select or is_double_click:
            self.mouse_selection_detected.emit()
