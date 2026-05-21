"""Resizable capture-region overlay + indicator overlay.

Two styles share the same multi-window architecture:
- "edit": thick solid border + 8 resize handles + center move handle (custom region)
- "indicator": thin dashed border, no handles (fullscreen / window mode preview)

When recording starts, both styles switch to a red blinking color. In edit
style, the handles are also hidden since they overlap the capture rect by
half their size and would otherwise appear in the recorded video.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize, QTimer, QObject
from PySide6.QtGui import QColor, QPainter, QMouseEvent, QCursor, QPen, QBrush
from PySide6.QtWidgets import QWidget


BORDER_THICKNESS = 3
INDICATOR_THICKNESS = 8
HANDLE_SIZE = 14
MIN_SIZE = 80

IDLE_COLOR = QColor(80, 200, 255, 235)        # cyan-blue, high contrast
INDICATOR_COLOR = QColor(255, 200, 0, 240)    # warm amber/yellow — stands out on any wallpaper
RECORDING_COLOR_A = QColor(255, 50, 50, 240)
RECORDING_COLOR_B = QColor(255, 50, 50, 90)


class _Handle(QWidget):
    moved = Signal(QPoint)

    def __init__(self, parent_overlay: "RegionOverlay", role: str):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(HANDLE_SIZE, HANDLE_SIZE)
        self._overlay = parent_overlay
        self._role = role
        self._drag_origin: QPoint | None = None
        self._start_rect: QRect | None = None
        cursor_map = {
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "move": Qt.SizeAllCursor,
        }
        self.setCursor(QCursor(cursor_map.get(self._role, Qt.ArrowCursor)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(80, 150, 255) if self._role != "move" else QColor(120, 200, 255)
        p.setBrush(color)
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton:
            self._drag_origin = ev.globalPosition().toPoint()
            self._start_rect = QRect(self._overlay.region_rect())

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self._drag_origin is None or self._start_rect is None:
            return
        delta = ev.globalPosition().toPoint() - self._drag_origin
        r = QRect(self._start_rect)
        if self._role == "move":
            r.translate(delta)
        else:
            x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
            if "l" in self._role: x1 += delta.x()
            if "r" in self._role: x2 += delta.x()
            if "t" in self._role: y1 += delta.y()
            if "b" in self._role: y2 += delta.y()
            if x2 - x1 < MIN_SIZE:
                if "l" in self._role: x1 = x2 - MIN_SIZE
                else: x2 = x1 + MIN_SIZE
            if y2 - y1 < MIN_SIZE:
                if "t" in self._role: y1 = y2 - MIN_SIZE
                else: y2 = y1 + MIN_SIZE
            r = QRect(QPoint(x1, y1), QPoint(x2, y2))
        self._overlay.set_region_rect(r)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        self._drag_origin = None
        self._start_rect = None
        self._overlay.region_changed.emit(self._overlay.region_rect())


class _BorderStrip(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._color = IDLE_COLOR
        self._dashed = False
        self._orientation = "h"  # "h" or "v"

    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def set_dashed(self, dashed: bool, orientation: str):
        self._dashed = dashed
        self._orientation = orientation
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not self._dashed:
            p.fillRect(self.rect(), self._color)
            return
        # Dashed thick line — visible against any background
        p.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(self._color)
        pen.setWidth(4)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([6, 4])   # in units of pen-width = 24/16 px
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        r = self.rect()
        if self._orientation == "h":
            y = r.height() // 2
            p.drawLine(0, y, r.width(), y)
        else:
            x = r.width() // 2
            p.drawLine(x, 0, x, r.height())


class _SignalProxy(QObject):
    changed = Signal(QRect)


class RegionOverlay:
    """Composite overlay supporting two visual styles."""

    def __init__(self):
        self._sig = _SignalProxy()
        self.region_changed = self._sig.changed

        self._rect = QRect(200, 200, 960, 540)
        self._strips = [_BorderStrip() for _ in range(4)]  # T B L R
        self._handles: dict[str, _Handle] = {
            r: _Handle(self, r) for r in ("tl", "t", "tr", "l", "r", "bl", "b", "br", "move")
        }
        self._visible = False
        self._style = "edit"            # "edit" | "indicator"
        self._recording = False
        self._blink_state = False
        self._blink_timer = QTimer()
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink_tick)

    # ---------- visibility ----------

    def show(self, style: str = "edit"):
        self._style = style
        self._visible = True
        self._apply_style()
        for s in self._strips: s.show()
        self._reposition()

    def hide(self):
        self._visible = False
        for s in self._strips: s.hide()
        for h in self._handles.values(): h.hide()

    def set_style(self, style: str):
        """Switch between 'edit' and 'indicator' without hiding."""
        if self._style == style:
            return
        self._style = style
        self._apply_style()
        self._reposition()

    def _apply_style(self):
        is_edit = self._style == "edit" and not self._recording
        for h in self._handles.values():
            h.setVisible(is_edit and self._visible)
        dashed = self._style == "indicator"
        orientations = ["h", "h", "v", "v"]  # T B L R
        for s, o in zip(self._strips, orientations):
            s.set_dashed(dashed, o)
        # Pick idle color per style
        color = INDICATOR_COLOR if dashed else IDLE_COLOR
        self._apply_strip_color(color)

    # ---------- recording state ----------

    def set_recording(self, recording: bool):
        self._recording = recording
        for h in self._handles.values():
            h.setVisible(self._style == "edit" and not recording and self._visible)
        # In indicator style the border is drawn INSIDE the rect and would
        # appear in the recording — hide strips entirely during record.
        if self._style == "indicator":
            self._blink_timer.stop()
            for s in self._strips:
                s.setVisible(not recording and self._visible)
            return
        # edit style: keep visible, switch to blinking red
        if recording:
            self._blink_state = False
            self._blink_timer.start()
            self._apply_strip_color(RECORDING_COLOR_A)
        else:
            self._blink_timer.stop()
            self._apply_strip_color(IDLE_COLOR)

    def _blink_tick(self):
        self._blink_state = not self._blink_state
        self._apply_strip_color(RECORDING_COLOR_B if self._blink_state else RECORDING_COLOR_A)

    def _apply_strip_color(self, color: QColor):
        for s in self._strips:
            s.set_color(color)

    # ---------- rect ----------

    def region_rect(self) -> QRect:
        return QRect(self._rect)

    def set_region_rect(self, r: QRect):
        if r.width() < MIN_SIZE: r.setWidth(MIN_SIZE)
        if r.height() < MIN_SIZE: r.setHeight(MIN_SIZE)
        self._rect = r
        self._reposition()

    def _reposition(self):
        if not self._visible:
            return
        r = self._rect
        t, b, l, rt = self._strips
        if self._style == "indicator":
            # Draw INSIDE the rect — for fullscreen mode the rect is the
            # screen edge, so outside positioning would be off-screen.
            th = INDICATOR_THICKNESS
            t.setGeometry(r.left(), r.top(), r.width(), th)
            b.setGeometry(r.left(), r.bottom() - th + 1, r.width(), th)
            l.setGeometry(r.left(), r.top(), th, r.height())
            rt.setGeometry(r.right() - th + 1, r.top(), th, r.height())
        else:
            # edit style: border sits OUTSIDE so it doesn't get recorded
            th = BORDER_THICKNESS
            t.setGeometry(r.left() - th, r.top() - th, r.width() + 2 * th, th)
            b.setGeometry(r.left() - th, r.bottom() + 1, r.width() + 2 * th, th)
            l.setGeometry(r.left() - th, r.top(), th, r.height())
            rt.setGeometry(r.right() + 1, r.top(), th, r.height())

        if self._style == "edit":
            h = HANDLE_SIZE // 2
            positions = {
                "tl": (r.left() - h, r.top() - h),
                "t":  (r.center().x() - h, r.top() - h),
                "tr": (r.right() - h, r.top() - h),
                "l":  (r.left() - h, r.center().y() - h),
                "r":  (r.right() - h, r.center().y() - h),
                "bl": (r.left() - h, r.bottom() - h),
                "b":  (r.center().x() - h, r.bottom() - h),
                "br": (r.right() - h, r.bottom() - h),
                "move": (r.center().x() - h, r.center().y() - h),
            }
            for k, (x, y) in positions.items():
                self._handles[k].move(x, y)

    def destroy(self):
        for w in (*self._strips, *self._handles.values()):
            w.close()
