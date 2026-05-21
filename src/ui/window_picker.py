"""Enumerate visible top-level windows for window-mode capture."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
DWMWA_EXTENDED_FRAME_BOUNDS = 9


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]  # x, y, w, h


def _get_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Prefer DWM extended frame bounds (excludes invisible drop-shadow)."""
    rect = wintypes.RECT()
    res = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect), ctypes.sizeof(rect),
    )
    if res != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    x, y = rect.left, rect.top
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def list_windows() -> list[WindowInfo]:
    results: list[WindowInfo] = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _get_title(hwnd)
        if not title:
            return True
        if title in ("Program Manager", "Windows 输入体验"):
            return True
        r = _get_rect(hwnd)
        if r is None:
            return True
        if r[2] < 100 or r[3] < 100:
            return True
        results.append(WindowInfo(hwnd, title, r))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return results


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    return _get_rect(hwnd)
