"""Windows'ta herhangi bir aktif uygulamadan seçili metni güvenli şekilde yakalar."""

import ctypes
import time
from ctypes import wintypes
from typing import Tuple

from PySide6.QtGui import QGuiApplication

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_MENU = 0x12
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_C = 0x43
VK_Q = 0x51
VK_INSERT = 0x2D


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


def _send_key(vk: int, key_up: bool = False, extended: bool = False) -> int:
    flags = 0
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP
    scan = user32.MapVirtualKeyW(vk, 0)
    inp = INPUT(
        type=INPUT_KEYBOARD,
        union=_INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)),
    )
    return int(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)))


def _is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _wait_modifiers_released(app: QGuiApplication, max_wait_s: float = 0.35) -> None:
    """Alt+Q basıldıysa Alt/Q bırakılana kadar bekler; fare tıklamasında 0ms bekler."""
    any_down = _is_key_down(VK_MENU) or _is_key_down(VK_LMENU) or _is_key_down(VK_RMENU) or _is_key_down(VK_Q)
    if not any_down:
        return

    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        if not (_is_key_down(VK_MENU) or _is_key_down(VK_LMENU) or _is_key_down(VK_RMENU) or _is_key_down(VK_Q)):
            break
        app.processEvents()
        time.sleep(0.01)

    for vk in (VK_LMENU, VK_RMENU, VK_MENU, VK_LSHIFT, VK_RSHIFT, VK_SHIFT, VK_LCONTROL, VK_RCONTROL, VK_CONTROL):
        _send_key(vk, key_up=True)
    time.sleep(0.015)


def _send_copy_combo(use_insert: bool = False) -> None:
    _send_key(VK_LCONTROL, key_up=False)
    time.sleep(0.01)
    if use_insert:
        _send_key(VK_INSERT, key_up=False, extended=True)
        time.sleep(0.01)
        _send_key(VK_INSERT, key_up=True, extended=True)
    else:
        _send_key(VK_C, key_up=False)
        time.sleep(0.01)
        _send_key(VK_C, key_up=True)
    time.sleep(0.01)
    _send_key(VK_LCONTROL, key_up=True)


def get_active_window_title() -> str:
    """Kullanıcının o an çalıştığı pencerenin başlığını döndürür (bağlam ipucu için)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def capture_selected_text(timeout_ms: int = 220, allow_clipboard_fallback: bool = False) -> Tuple[str, str]:
    """Aktif uygulamadaki seçili metni panoyu kalıcı olarak bozmadan yakalar.

    Dönüş: (yakalanan_metin, aktif_pencere_basligi)
    """
    app = QGuiApplication.instance()
    if app is None:
        return "", ""

    window_title = get_active_window_title()
    clipboard = app.clipboard()
    previous_text = clipboard.text()

    _wait_modifiers_released(app)

    for use_insert in (False, True):
        seq_before = user32.GetClipboardSequenceNumber()
        _send_copy_combo(use_insert=use_insert)

        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            app.processEvents()
            if user32.GetClipboardSequenceNumber() != seq_before:
                captured = clipboard.text()
                if previous_text is not None:
                    time.sleep(0.02)
                    clipboard.setText(previous_text)
                if captured and captured.strip():
                    return captured.strip(), window_title
                break
            time.sleep(0.02)

    if allow_clipboard_fallback and previous_text and previous_text.strip():
        return previous_text.strip(), window_title

    return "", window_title
