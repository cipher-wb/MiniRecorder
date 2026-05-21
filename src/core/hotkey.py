"""Global hotkeys via Win32 RegisterHotKey + Qt native event filter.

Why not the `keyboard` library: its LL hook can silently fail to receive events
in PyInstaller bundles and across UAC boundaries. RegisterHotKey is processed
by the OS itself and dispatches WM_HOTKEY to the calling thread's message queue,
which on Qt's main thread is pumped continuously — works regardless of which
window has focus, which monitor it's on, or whether games hold raw input.
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wt
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication


user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_VK_MAP = {f"f{i}": 0x70 + (i - 1) for i in range(1, 13)}  # F1..F12 → 0x70..0x7B
_MOD_MAP = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}


def _parse_combo(combo: str) -> tuple[int, int]:
    mods = 0
    vk = 0
    for tok in (p.strip().lower() for p in combo.split("+")):
        if tok in _MOD_MAP:
            mods |= _MOD_MAP[tok]
        elif tok in _VK_MAP:
            vk = _VK_MAP[tok]
        elif len(tok) == 1 and tok.isalnum():
            vk = ord(tok.upper())
    return (mods | MOD_NOREPEAT, vk)


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND), ("message", wt.UINT),
        ("wParam", wt.WPARAM), ("lParam", wt.LPARAM),
        ("time", wt.DWORD), ("pt_x", wt.LONG), ("pt_y", wt.LONG),
    ]


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "HotkeyManager"):
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG":
                msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
                if msg.message == WM_HOTKEY:
                    self._manager._dispatch(int(msg.wParam))
        except Exception:
            pass
        return False, 0


class HotkeyManager:
    def __init__(self):
        self._handlers: dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._filter = _NativeFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)

    def available(self) -> bool:
        return True

    def register(self, combo: str, callback: Callable[[], None]) -> bool:
        mods, vk = _parse_combo(combo)
        if not vk:
            return False
        hid = self._next_id
        self._next_id += 1
        if not user32.RegisterHotKey(None, hid, mods, vk):
            return False
        self._handlers[hid] = callback
        return True

    def unregister_all(self):
        for hid in list(self._handlers.keys()):
            user32.UnregisterHotKey(None, hid)
        self._handlers.clear()

    def _dispatch(self, hid: int):
        cb = self._handlers.get(hid)
        if cb:
            try: cb()
            except Exception: pass
