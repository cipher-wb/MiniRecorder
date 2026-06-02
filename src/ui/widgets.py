"""Custom terminal-panel widgets for the Claude-Code skin.

All visuals come from the theme token dict (see theme.py). Each widget takes a
`set_theme(t)` so a runtime light/dark switch is just new tokens + repaint.
Glyphs are painted geometry (no emoji), matching the prototype's CSS shapes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF, QSize, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QFontDatabase
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QFrame, QHBoxLayout, QVBoxLayout, QSizePolicy,
)

from .theme import MONO_FAMILIES


# ---------- font helpers ----------

def load_mono_fonts(fonts_dir) -> None:
    """Register bundled IBM Plex Mono weights with Qt (call once at startup)."""
    from pathlib import Path
    d = Path(fonts_dir)
    if not d.exists():
        return
    for ttf in d.glob("IBMPlexMono-*.ttf"):
        QFontDatabase.addApplicationFont(str(ttf))


def mono_font(size: int, weight: QFont.Weight = QFont.Weight.Normal,
              spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES)
    f.setPixelSize(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing)
    return f


def _rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


# ---------- painted glyphs ----------

class Glyph(QWidget):
    """A single geometric glyph painted in one color."""

    def __init__(self, kind: str, color: str = "#000000", size: int = 14, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def set_kind(self, kind: str):
        self._kind = kind
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._color
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        k = self._kind
        if k == "rec":
            ring = QColor(c); ring.setAlphaF(0.26)
            p.setPen(Qt.NoPen); p.setBrush(ring)
            p.drawEllipse(QRectF(cx - 6.5, cy - 6.5, 13, 13))
            p.setBrush(c); p.drawEllipse(QRectF(cx - 4.3, cy - 4.3, 8.6, 8.6))
        elif k == "stop":
            p.setPen(Qt.NoPen); p.setBrush(c)
            p.drawRoundedRect(QRectF(cx - 5, cy - 5, 10, 10), 2, 2)
        elif k == "pause":
            p.setPen(Qt.NoPen); p.setBrush(c)
            p.drawRoundedRect(QRectF(cx - 4, cy - 5.5, 3, 11), 1, 1)
            p.drawRoundedRect(QRectF(cx + 1, cy - 5.5, 3, 11), 1, 1)
        elif k == "play":
            path = QPainterPath()
            path.moveTo(cx - 4, cy - 5.5); path.lineTo(cx + 5, cy)
            path.lineTo(cx - 4, cy + 5.5); path.closeSubpath()
            p.setPen(Qt.NoPen); p.setBrush(c); p.drawPath(path)
        elif k == "folder":
            pen = QPen(c, 1.3); pen.setJoinStyle(Qt.RoundJoin); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 5.5, cy - 4)
            path.lineTo(cx - 1.6, cy - 4)
            path.lineTo(cx - 0.4, cy - 2.6)
            path.lineTo(cx + 5.5, cy - 2.6)
            path.lineTo(cx + 5.5, cy + 4.2)
            path.lineTo(cx - 5.5, cy + 4.2)
            path.closeSubpath()
            p.drawPath(path)
        elif k == "gear":
            pen = QPen(c, 1.25); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - 2.1, cy - 2.1, 4.2, 4.2))
            import math
            for i in range(8):
                a = math.radians(i * 45)
                dx, dy = math.cos(a), math.sin(a)
                p.drawLine(QPoint(int(cx + dx * 4.2), int(cy + dy * 4.2)),
                           QPoint(int(cx + dx * 6.2), int(cy + dy * 6.2)))
        elif k == "sync":
            pen = QPen(c, 1.3); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(cx - 5, cy - 5, 10, 10), 60 * 16, 250 * 16)
            ah = QPainterPath()
            ah.moveTo(cx + 4.4, cy - 5.2); ah.lineTo(cx + 5.6, cy - 1.4)
            ah.lineTo(cx + 1.8, cy - 2.6)
            p.setPen(Qt.NoPen); p.setBrush(c); p.drawPath(ah)
        elif k in ("dot", "logodot"):
            d = min(w, h) - 1
            p.setPen(Qt.NoPen); p.setBrush(c)
            p.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))


class Logo(QWidget):
    """Rounded accent square with an ink dot — the app mark."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._accent = QColor("#D97757")
        self._ink = QColor("#FFFFFF")

    def set_theme(self, t: dict):
        self._accent = QColor(t["accent"]); self._ink = QColor(t["ink"])
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(self._accent)
        p.drawRoundedRect(QRectF(0, 0, 18, 18), 5, 5)
        dot = QColor(self._ink); dot.setAlphaF(0.92)
        p.setBrush(dot)
        p.drawEllipse(QRectF(6, 6, 6, 6))


class Dot(QWidget):
    """Status dot (idle/recording/paused) — color set by the panel."""

    def __init__(self, size: int = 8, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._color = QColor("#706B5F")

    def set_color(self, color: str):
        self._color = QColor(color); self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen); p.setBrush(self._color)
        d = min(self.width(), self.height())
        p.drawEllipse(QRectF(0, 0, d, d))


# ---------- keycap ----------

class Keycap(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(mono_font(10, QFont.Weight.DemiBold, spacing=3))
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def restyle(self, bg: str, border: str, fg: str):
        self.setStyleSheet(
            f"background:{bg}; border:1px solid {border}; border-radius:5px;"
            f" color:{fg}; padding:1px 5px;")


# ---------- record button ----------

class RecordButton(QPushButton):
    """Primary action: accent-filled (idle) / inset-outlined (recording)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self._t: dict | None = None
        self._recording = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 12, 0)
        lay.setSpacing(10)
        self._glyph = Glyph("rec", "#000000", 14)
        self._label = QLabel("开始录制")
        self._label.setFont(mono_font(14, QFont.Weight.DemiBold))
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._kc = Keycap("F9")
        lay.addWidget(self._glyph)
        lay.addWidget(self._label)
        lay.addStretch(1)
        lay.addWidget(self._kc)

    def set_recording(self, on: bool):
        self._recording = on
        self._glyph.set_kind("stop" if on else "rec")
        self._label.setText("停止录制" if on else "开始录制")
        self._restyle()

    def set_theme(self, t: dict):
        self._t = t
        self._restyle()

    def _restyle(self):
        t = self._t
        if not t:
            return
        if not self._recording:
            self.setStyleSheet(
                f"RecordButton {{ background-color:{t['accent']}; border:1px solid transparent;"
                f" border-radius:9px; }}"
                f"RecordButton:hover {{ background-color:{t['accent_hover']}; }}")
            self._glyph.set_color(t["ink"])
            self._label.setStyleSheet(f"color:{t['ink']};")
            self._kc.restyle(_rgba(t["ink"], 0.18), _rgba(t["ink"], 0.30), t["ink"])
        else:
            self.setStyleSheet(
                f"RecordButton {{ background-color:{t['inset']}; border:1px solid {t['line2']};"
                f" border-radius:9px; }}"
                f"RecordButton:hover {{ background-color:{t['sel_bg']}; }}")
            self._glyph.set_color(t["accent"])
            self._label.setStyleSheet(f"color:{t['t1']};")
            self._kc.restyle(t["keycap_bg"], t["keycap_border"], t["t2"])


# ---------- footer flat button ----------

class FooterButton(QPushButton):
    def __init__(self, kind: str, text: str, keycap: str | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("foot", True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 5, 9, 5)
        lay.setSpacing(6)
        self._glyph = Glyph(kind, "#888888", 14) if kind else None
        self._label = QLabel(text)
        self._label.setFont(mono_font(12))
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        if self._glyph:
            lay.addWidget(self._glyph)
        lay.addWidget(self._label)
        self._kc = None
        if keycap:
            self._kc = Keycap(keycap)
            lay.addSpacing(2)
            lay.addWidget(self._kc)

    # QAbstractButton sizes itself from its own text/icon and ignores the child
    # layout we add — without these it collapses to the glyph and clips labels.
    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().sizeHint()

    def set_glyph_kind(self, kind: str):
        if self._glyph:
            self._glyph.set_kind(kind)

    def set_label(self, text: str):
        self._label.setText(text)

    def set_theme(self, t: dict):
        col = t["t2"]
        if not self.isEnabled():
            col = t["t3"]
        if self._glyph:
            self._glyph.set_color(col)
        self._label.setStyleSheet(f"color:{col};")
        if self._kc:
            self._kc.restyle(t["keycap_bg"], t["keycap_border"], t["t2"])


# ---------- flag dropdown (flag label + value box + popup) ----------

class _Opt(QFrame):
    clicked = Signal()

    def __init__(self, label: str, meta: str, selected: bool, t: dict, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._t = t
        self._selected = selected
        self._hover = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 7, 8, 7)
        lay.setSpacing(7)
        dot = QLabel("›" if selected else " ")
        dot.setFont(mono_font(12, QFont.Weight.Bold))
        dot.setFixedWidth(9)
        dot.setStyleSheet(f"color:{t['accent']};")
        lab = QLabel(label)
        lab.setFont(mono_font(12, QFont.Weight.Medium))
        lab.setStyleSheet(f"color:{t['accent'] if selected else t['t1']};")
        lay.addWidget(dot)
        lay.addWidget(lab)
        lay.addStretch(1)
        if meta:
            m = QLabel(meta)
            m.setFont(mono_font(11))
            m.setStyleSheet(f"color:{t['t3']};")
            lay.addWidget(m)
        for w in (dot, lab):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._refresh()

    def _refresh(self):
        bg = self._t["hover"] if self._hover else "transparent"
        self.setStyleSheet(f"_Opt {{ background:{bg}; border-radius:6px; }}")

    def enterEvent(self, _):
        self._hover = True; self._refresh()

    def leaveEvent(self, _):
        self._hover = False; self._refresh()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class _Menu(QWidget):
    chosen = Signal(int)

    def __init__(self, items, index: int, width: int, t: dict, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)   # room for shadow-free border breathing
        card = QFrame()
        card.setObjectName("menuCard")
        card.setStyleSheet(
            f"#menuCard {{ background:{t['menubg']}; border:1px solid {t['line2']};"
            f" border-radius:8px; }}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(1)
        for i, (label, meta) in enumerate(items):
            opt = _Opt(label, meta, i == index, t)
            opt.clicked.connect(lambda i=i: self._pick(i))
            cl.addWidget(opt)
        outer.addWidget(card)
        self.setFixedWidth(width + 16)

    def _pick(self, i: int):
        self.chosen.emit(i)
        self.close()


class FlagSelect(QWidget):
    """A `--flag  [ value  meta  ▾ ]` row. Drop-in-ish for the old ComboBox."""

    currentIndexChanged = Signal(int)

    def __init__(self, flag: str, flag_width: int = 70, parent=None):
        super().__init__(parent)
        self._t: dict | None = None
        self._items: list[tuple[str, str]] = []
        self._index = -1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._flag = QLabel(flag)
        self._flag.setObjectName("flag")
        self._flag.setFont(mono_font(12, QFont.Weight.Medium, spacing=10))
        self._flag.setFixedWidth(flag_width)
        lay.addWidget(self._flag)

        self._box = QFrame()
        self._box.setProperty("sel", True)
        self._box.setMinimumHeight(32)
        self._box.setCursor(Qt.PointingHandCursor)
        bl = QHBoxLayout(self._box)
        bl.setContentsMargins(10, 5, 10, 5)
        bl.setSpacing(7)
        self._val = QLabel("")
        self._val.setFont(mono_font(12, QFont.Weight.Medium))
        self._meta = QLabel("")
        self._meta.setFont(mono_font(11))
        self._caret = QLabel("▾")
        self._caret.setFont(mono_font(11))
        for w in (self._val, self._meta, self._caret):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        bl.addWidget(self._val)
        bl.addWidget(self._meta)
        bl.addStretch(1)
        bl.addWidget(self._caret)
        self._box.mousePressEvent = self._open_menu
        lay.addWidget(self._box, 1)

    # ---- theming ----
    def set_theme(self, t: dict):
        self._t = t
        self._val.setStyleSheet(f"color:{t['t1']};")
        self._meta.setStyleSheet(f"color:{t['t3']};")
        self._caret.setStyleSheet(f"color:{t['t3']};")

    # ---- data API ----
    def set_items(self, items):
        norm = []
        for it in items:
            if isinstance(it, (tuple, list)):
                norm.append((str(it[0]), str(it[1]) if len(it) > 1 else ""))
            else:
                norm.append((str(it), ""))
        self._items = norm
        if self._index >= len(norm):
            self._index = len(norm) - 1
        if self._index < 0 and norm:
            self._index = 0
        self._sync_display()

    def clear(self):
        self._items = []
        self._index = -1
        self._sync_display()

    def count(self) -> int:
        return len(self._items)

    def current_index(self) -> int:
        return self._index

    def set_current_index(self, i: int, *, emit: bool = False):
        if 0 <= i < len(self._items):
            self._index = i
            self._sync_display()
            if emit:
                self.currentIndexChanged.emit(i)

    def _sync_display(self):
        if 0 <= self._index < len(self._items):
            label, meta = self._items[self._index]
            self._val.setText(label)
            self._meta.setText(meta)
            self._meta.setVisible(bool(meta))
        else:
            self._val.setText("—"); self._meta.setText(""); self._meta.setVisible(False)

    # ---- popup ----
    def _set_open(self, on: bool):
        self._box.setProperty("open", "true" if on else "false")
        self._box.style().unpolish(self._box)
        self._box.style().polish(self._box)

    def _open_menu(self, ev):
        if ev.button() != Qt.LeftButton or not self._items or self._t is None:
            return
        self._set_open(True)
        menu = _Menu(self._items, self._index, self._box.width(), self._t, self)
        menu.chosen.connect(self._on_chosen)
        menu.destroyed.connect(lambda: self._set_open(False))
        pos = self._box.mapToGlobal(QPoint(-8, self._box.height() - 3))
        menu.move(pos)
        menu.show()

    def _on_chosen(self, i: int):
        if i != self._index:
            self._index = i
            self._sync_display()
            self.currentIndexChanged.emit(i)


class RegionRow(QWidget):
    """`--region [ W × H  @ x,y          编辑 ✎ ]` for custom-region mode."""

    edit_clicked = Signal()

    def __init__(self, flag_width: int = 70, parent=None):
        super().__init__(parent)
        self._t: dict | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        flag = QLabel("--region")
        flag.setObjectName("flag")
        flag.setFont(mono_font(12, QFont.Weight.Medium, spacing=10))
        flag.setFixedWidth(flag_width)
        lay.addWidget(flag)
        self._flag = flag

        self._box = QFrame()
        self._box.setProperty("sel", True)
        self._box.setMinimumHeight(32)
        self._box.setCursor(Qt.PointingHandCursor)
        bl = QHBoxLayout(self._box)
        bl.setContentsMargins(10, 5, 10, 5)
        bl.setSpacing(7)
        self._size = QLabel("960 × 540")
        self._size.setFont(mono_font(12, QFont.Weight.Medium))
        self._pos = QLabel("@ 200,200")
        self._pos.setFont(mono_font(11))
        self._edit = QLabel("编辑 ✎")
        self._edit.setFont(mono_font(11))
        for w in (self._size, self._pos, self._edit):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        bl.addWidget(self._size)
        bl.addWidget(self._pos)
        bl.addStretch(1)
        bl.addWidget(self._edit)
        self._box.mousePressEvent = self._clicked
        lay.addWidget(self._box, 1)

    def set_theme(self, t: dict):
        self._t = t
        self._size.setStyleSheet(f"color:{t['t1']};")
        self._pos.setStyleSheet(f"color:{t['t3']};")
        self._edit.setStyleSheet(f"color:{t['accent']};")

    def set_region(self, x: int, y: int, w: int, h: int):
        self._size.setText(f"{w} × {h}")
        self._pos.setText(f"@ {x},{y}")

    def _clicked(self, ev):
        if ev.button() == Qt.LeftButton:
            self.edit_clicked.emit()
