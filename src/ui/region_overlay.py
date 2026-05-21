"""Resizable, draggable transparent overlay that defines the capture rectangle.

The overlay shows only a thin border + corner handles. The interior is fully
transparent and click-through so the user can interact with what's behind it
(e.g. a game window). When recording starts, the four border strips can be
toggled invisible so they don't appear in the captured video.

Implementation uses four child border widgets positioned around an interior
"hole" rather than a single window with a hole — Qt's transparency + Windows
DWM make true hit-testing holes painful. Four thin windows is robust.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize, QTimer
from PySide6.QtGui import QColor, QPainter, QMouseEvent, QCursor, QPen
from PySide6.QtWidgets import QWidget


IDLE_COLOR = QColor(80, 150, 255, 220)        # calm blue
RECORDING_COLOR_A = QColor(255, 50, 50, 240)  # bright red
RECORDING_COLOR_B = QColor(255, 50, 50, 90)   # dim red (for blink)


BORDER_THICKNESS = 3
HANDLE_SIZE = 14
MIN_SIZE = 80


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
        self._role = role  # tl tr bl br t b l r move
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
    """One of the 4 thin frameless windows that draw the border."""
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

    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)


class RegionOverlay:
    """Composite overlay: 4 border strips + 8 resize handles + 1 move handle."""

    region_changed = Signal(QRect)  # imitated via a small holder below

    def __init__(self):
        # Use a tiny QObject for the signal — RegionOverlay isn't QWidget itself.
        from PySide6.QtCore import QObject
        class _Sig(QObject):
            from PySide6.QtCore import Signal as _S
            changed = _S(QRect)
        self._sig = _Sig()
        self.region_changed = self._sig.changed

        self._rect = QRect(200, 200, 960, 540)
        self._strips = [_BorderStrip() for _ in range(4)]  # top, bottom, left, right
        self._handles: dict[str, _Handle] = {
            r: _Handle(self, r) for r in ("tl", "t", "tr", "l", "r", "bl", "b", "br", "move")
        }
        self._visible = False
        self._recording = False
        self._blink_state = False
        self._blink_timer = QTimer()
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink_tick)

    def show(self):
        self._visible = True
        for s in self._strips: s.show()
        for h in self._handles.values(): h.show()
        self._reposition()

    def hide(self):
        self._visible = False
        for s in self._strips: s.hide()
        for h in self._handles.values(): h.hide()

    def set_recording(self, recording: bool):
        """Switch overlay to recording style: red blinking border + handles hidden.

        Border strips sit just outside the capture rect so they don't appear in
        the recorded video. Handles overlap the rect by half their size, so they
        DO get captured — hide them while recording.
        """
        self._recording = recording
        for h in self._handles.values():
            h.setVisible(not recording and self._visible)
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
        t.setGeometry(r.left() - BORDER_THICKNESS, r.top() - BORDER_THICKNESS,
                      r.width() + 2 * BORDER_THICKNESS, BORDER_THICKNESS)
        b.setGeometry(r.left() - BORDER_THICKNESS, r.bottom() + 1,
                      r.width() + 2 * BORDER_THICKNESS, BORDER_THICKNESS)
        l.setGeometry(r.left() - BORDER_THICKNESS, r.top(),
                      BORDER_THICKNESS, r.height())
        rt.setGeometry(r.right() + 1, r.top(), BORDER_THICKNESS, r.height())

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
