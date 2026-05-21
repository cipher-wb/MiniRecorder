"""Global hotkeys via the `keyboard` library, bridged to Qt via QMetaObject."""
from __future__ import annotations
from typing import Callable

try:
    import keyboard  # type: ignore
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class HotkeyManager:
    def __init__(self):
        self._handles: list = []

    def available(self) -> bool:
        return _AVAILABLE

    def register(self, combo: str, callback: Callable[[], None]) -> bool:
        if not _AVAILABLE:
            return False
        try:
            h = keyboard.add_hotkey(combo, callback, suppress=False, trigger_on_release=False)
            self._handles.append(h)
            return True
        except Exception:
            return False

    def unregister_all(self):
        if not _AVAILABLE:
            return
        try:
            for h in self._handles:
                keyboard.remove_hotkey(h)
        except Exception:
            pass
        self._handles.clear()
