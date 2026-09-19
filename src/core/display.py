"""Map Qt logical (DIP) coordinates to Windows physical pixels.

Qt widgets, QScreen.geometry() and QMouseEvent.globalPosition() are in
device-independent pixels. ffmpeg gdigrab / ddagrab expect the virtual-desktop
physical pixels reported by Win32 (GetMonitorInfo / GetWindowRect).

On a 4K screen at 150% or 200% scale those spaces diverge: a custom overlay
rect in logical pixels is smaller than the real capture area, so the recorded
region comes out cropped unless we convert before building the ffmpeg command.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Sequence

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QScreen


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
if _user32 is not None:
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL


def _enum_native_monitors() -> list[tuple[str, int, int, int, int]]:
    """Return (device, x, y, w, h) in Windows virtual-desktop physical pixels."""
    if _user32 is None:
        return []
    out: list[tuple[str, int, int, int, int]] = []

    def _cb(hmon, _hdc, _lprect, _lparam):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out.append((
                info.szDevice,
                int(r.left),
                int(r.top),
                int(r.right - r.left),
                int(r.bottom - r.top),
            ))
        return 1

    proc_t = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(_RECT), wintypes.LPARAM,
    )
    cb = proc_t(_cb)
    _user32.EnumDisplayMonitors(None, None, cb, 0)
    return out


def _fallback_native(screen: QScreen) -> tuple[int, int, int, int]:
    g = screen.geometry()
    dpr = float(screen.devicePixelRatio())
    return (
        round(g.x() * dpr),
        round(g.y() * dpr),
        max(1, round(g.width() * dpr)),
        max(1, round(g.height() * dpr)),
    )


def native_geometry(
    screen: QScreen,
    natives: list[tuple[str, int, int, int, int]] | None = None,
) -> tuple[int, int, int, int]:
    """Physical virtual-desktop rect of a QScreen: (x, y, w, h)."""
    if natives is None:
        natives = _enum_native_monitors()
    name = (screen.name() or "").casefold()
    if name:
        for device, x, y, w, h in natives:
            if device.casefold() == name:
                return x, y, w, h
    g = screen.geometry()
    dpr = float(screen.devicePixelRatio())
    tw, th = max(1, round(g.width() * dpr)), max(1, round(g.height() * dpr))
    size_hits = [(x, y, w, h) for _, x, y, w, h in natives if w == tw and h == th]
    if len(size_hits) == 1:
        return size_hits[0]
    return _fallback_native(screen)


def physical_screen_geometries() -> list[tuple[int, int, int, int]]:
    """Native rects in the same order as QGuiApplication.screens()."""
    natives = _enum_native_monitors()
    return [native_geometry(s, natives) for s in QGuiApplication.screens()]


def _clamp_if_near_monitor(
    x: int, y: int, w: int, h: int,
    natives: list[tuple[str, int, int, int, int]],
    slop: int = 2,
) -> tuple[int, int, int, int]:
    """Pull a 1–2px rounding overflow back onto the containing monitor.

    Larger overflows (true multi-monitor spans) are left untouched so gdigrab
    can still capture across screens.
    """
    if not natives:
        return x, y, w, h
    cx, cy = x + w // 2, y + h // 2
    hit: tuple[int, int, int, int] | None = None
    for _, sx, sy, sw, sh in natives:
        if sx <= cx < sx + sw and sy <= cy < sy + sh:
            hit = (sx, sy, sw, sh)
            break
    if hit is None:
        return x, y, w, h
    sx, sy, sw, sh = hit
    overflow = (
        max(0, sx - x),
        max(0, sy - y),
        max(0, (x + w) - (sx + sw)),
        max(0, (y + h) - (sy + sh)),
    )
    if any(v > slop for v in overflow):
        return x, y, w, h
    if not any(overflow):
        return x, y, w, h
    nx = min(max(x, sx), sx + sw - 2)
    ny = min(max(y, sy), sy + sh - 2)
    x2 = min(max(x + w, nx + 2), sx + sw)
    y2 = min(max(y + h, ny + 2), sy + sh)
    return nx, ny, max(2, x2 - nx), max(2, y2 - ny)


def _screen_at(x: int, y: int) -> QScreen | None:
    app = QGuiApplication.instance()
    if app is None:
        return None
    return QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()


def _logical_point_to_physical(
    x: int, y: int,
    natives: list[tuple[str, int, int, int, int]],
) -> tuple[int, int]:
    screen = _screen_at(x, y)
    if screen is None:
        return x, y
    dpr = float(screen.devicePixelRatio())
    sg = screen.geometry()
    nx, ny, _, _ = native_geometry(screen, natives)
    return (
        nx + round((x - sg.x()) * dpr),
        ny + round((y - sg.y()) * dpr),
    )


def logical_rect_to_physical(rect: QRect) -> tuple[int, int, int, int]:
    """Convert a Qt logical QRect to gdigrab/ddagrab physical pixels."""
    if rect.width() <= 0 or rect.height() <= 0:
        return rect.x(), rect.y(), max(0, rect.width()), max(0, rect.height())
    natives = _enum_native_monitors()
    tl = _screen_at(rect.x(), rect.y())
    br = _screen_at(rect.x() + rect.width() - 1, rect.y() + rect.height() - 1)
    if tl is not None and tl is br:
        dpr = float(tl.devicePixelRatio())
        sg = tl.geometry()
        nx, ny, _, _ = native_geometry(tl, natives)
        mapped = (
            nx + round((rect.x() - sg.x()) * dpr),
            ny + round((rect.y() - sg.y()) * dpr),
            max(2, round(rect.width() * dpr)),
            max(2, round(rect.height() * dpr)),
        )
        return _clamp_if_near_monitor(*mapped, natives)
    x1, y1 = _logical_point_to_physical(rect.x(), rect.y(), natives)
    x2, y2 = _logical_point_to_physical(rect.x() + rect.width(), rect.y() + rect.height(), natives)
    return _clamp_if_near_monitor(x1, y1, max(2, x2 - x1), max(2, y2 - y1), natives)


def logical_screen_to_physical(geom: QRect) -> tuple[int, int, int, int]:
    """Map a QScreen.geometry() rect to the matching Win32 monitor pixels."""
    natives = _enum_native_monitors()
    for sc in QGuiApplication.screens():
        if sc.geometry() == geom:
            return native_geometry(sc, natives)
    return logical_rect_to_physical(geom)


def _physical_point_to_logical(x: int, y: int) -> tuple[int, int]:
    natives = _enum_native_monitors()
    screens: Sequence[QScreen] = QGuiApplication.screens()
    for screen in screens:
        nx, ny, nw, nh = native_geometry(screen, natives)
        if nx <= x < nx + nw and ny <= y < ny + nh:
            dpr = float(screen.devicePixelRatio()) or 1.0
            sg = screen.geometry()
            return (
                sg.x() + round((x - nx) / dpr),
                sg.y() + round((y - ny) / dpr),
            )
    primary = QGuiApplication.primaryScreen()
    if primary is None:
        return x, y
    dpr = float(primary.devicePixelRatio()) or 1.0
    return round(x / dpr), round(y / dpr)


def physical_rect_to_logical(x: int, y: int, w: int, h: int) -> QRect:
    """Convert a Win32 physical rect (GetWindowRect) to a Qt logical QRect."""
    if w <= 0 or h <= 0:
        return QRect(x, y, max(0, w), max(0, h))
    x1, y1 = _physical_point_to_logical(x, y)
    x2, y2 = _physical_point_to_logical(x + w, y + h)
    return QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
