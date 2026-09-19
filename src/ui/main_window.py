"""轻录 — main panel (Claude-Code terminal-panel skin).

Frameless warm-monospace window: custom title bar (logo / brand / theme toggle
/ pin / min / close), a `$ rec --status` prompt line with blinking caret and
tabular clock, CLI-flag config rows (--mode / --quality / --source|--region),
an accent record button with an F9 keycap, and a flat footer. Light & dark
themes are token-driven (see theme.py) and switch at runtime.
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes as wt
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QTimer, Signal, QObject, Slot, QUrl, QPoint
from PySide6.QtGui import QGuiApplication, QIcon, QAction, QDesktopServices, QFont, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSystemTrayIcon,
    QMenu, QLabel, QPushButton, QFrame, QGraphicsDropShadowEffect,
)

from ..core import config as cfg_mod
from ..core import ffmpeg_builder as fb
from ..core.display import (
    logical_rect_to_physical,
    logical_screen_to_physical,
    native_geometry,
    physical_rect_to_logical,
    physical_screen_geometries,
)
from ..core.recorder import Recorder, RecorderState, StopResult
from ..core.ffmpeg_builder import CaptureRegion
from ..core.hotkey import HotkeyManager
from .region_overlay import RegionOverlay
from .window_picker import list_windows, get_window_rect, WindowInfo
from .settings_dialog import SettingsDialog
from . import theme as thm
from .widgets import (
    Logo, Dot, RecordButton, FooterButton, FlagSelect, RegionRow, mono_font,
)

SHADOW = 16          # transparent margin around the card for the drop shadow
CARD_W = 340         # visible card width (matches prototype)


class _RecorderBridge(QObject):
    state_changed = Signal(object)
    error = Signal(str)
    status = Signal(str)
    stop_finished = Signal(object)  # StopResult


class _TitleBar(QFrame):
    """Draggable title bar — moves the frameless window on empty-area drag."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self._win = win
        self._drag: QPoint | None = None
        self.setObjectName("titleBar")
        self.setFixedHeight(42)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None


class MainWindow(QMainWindow):
    def __init__(self, theme_qss: str = ""):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("轻录")

        from ..core.paths import assets_dir
        icon_path = assets_dir() / "icons" / "app.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ---- State ----
        self.cfg = cfg_mod.load()
        self.theme_name = self.cfg.theme if self.cfg.theme in thm.TOKENS else "dark"
        self._themed: list = []           # widgets with a set_theme(t) method

        self.bridge = _RecorderBridge()
        self.bridge.state_changed.connect(self._on_state)
        self.bridge.error.connect(self._on_error)
        self.bridge.status.connect(self._on_status)
        self.bridge.stop_finished.connect(self._on_stop_finished)
        self.recorder = Recorder(
            on_state_change=lambda s: self.bridge.state_changed.emit(s),
            on_error=lambda msg: self.bridge.error.emit(msg),
            on_status=lambda msg: self.bridge.status.emit(msg),
        )
        self._stopping = False

        self.overlay = RegionOverlay()
        self.overlay.region_changed.connect(self._on_region_changed)
        if self.cfg.last_region:
            x, y, w, h = self.cfg.last_region
            self._custom_rect = QRect(x, y, w, h)
        else:
            self._custom_rect = QRect(200, 200, 960, 540)

        self._window_choices: list[WindowInfo] = []
        self._window_follow_timer = QTimer(self)
        self._window_follow_timer.setInterval(500)
        self._window_follow_timer.timeout.connect(self._refresh_window_rect)
        self._selected_hwnd: int | None = None
        self._selected_screen_geom: QRect | None = None
        self._screen_values: list[QRect | None] = []

        self._mode_values = ["fullscreen", "window", "custom"]
        self._preset_values = ["ultra", "high", "medium", "low", "custom"]
        self._preset_meta = {"ultra": "30M · 60fps", "high": "12M · 60fps",
                             "medium": "6M · 30fps", "low": "3M · 30fps", "custom": ""}

        # ---- Timers (created before UI so status rendering can touch them) ----
        self._elapsed = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._caret_on = True
        self._caret_timer = QTimer(self)
        self._caret_timer.setInterval(530)
        self._caret_timer.timeout.connect(self._blink_caret)
        self._pulse_on = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(560)
        self._pulse_timer.timeout.connect(self._pulse_dot)

        # ---- Build UI ----
        self._build_ui()
        self._apply_theme()
        self._update_mode_ui()
        self._update_buttons()
        self._render_status(RecorderState.IDLE)

        # Fix size to content (row count is constant across modes/themes).
        self.adjustSize()
        self.setFixedSize(self.size())

        # Hotkeys (Win32 RegisterHotKey)
        self.hotkeys = HotkeyManager()
        self.hotkeys.register(self.cfg.hotkey_toggle, self.toggle_record)
        self.hotkeys.register(self.cfg.hotkey_pause, self.toggle_pause)

        self._build_tray()
        self._caret_timer.start()

        threading.Thread(target=fb.detect_capabilities, daemon=True).start()

        gapp = QGuiApplication.instance()
        gapp.screenAdded.connect(self._on_screens_changed)
        gapp.screenRemoved.connect(self._on_screens_changed)

    # ---------- UI construction ----------

    def _build_ui(self):
        # Translucent container holds the card with a margin for the shadow.
        container = QWidget()
        container.setAttribute(Qt.WA_TranslucentBackground)
        self.setCentralWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(CARD_W)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        card_lay.addWidget(self._build_title_bar())
        card_lay.addWidget(self._build_body())

    def _build_title_bar(self) -> QFrame:
        bar = _TitleBar(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(9)

        self.logo = Logo()
        self._themed.append(self.logo)
        brand = QLabel("轻录"); brand.setObjectName("brand")
        sub = QLabel("recorder"); sub.setObjectName("brandSub")
        sub.setFont(mono_font(11))
        lay.addWidget(self.logo)
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addStretch(1)

        self.theme_btn = self._wc_button("", "切换浅色/深色", "themeBtn")
        self.theme_btn.setFont(mono_font(13))
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.pin_btn = self._wc_button("置顶", "置顶", "pinBtn")
        self.pin_btn.setFont(mono_font(11))
        self.pin_btn.setCheckable(True)
        self.pin_btn.toggled.connect(self._on_pin_toggled)
        self.min_btn = self._wc_button("—", "最小化", "minBtn")
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = self._wc_button("✕", "关闭", "closeBtn")
        self.close_btn.clicked.connect(self.close)
        for b in (self.theme_btn, self.pin_btn, self.min_btn, self.close_btn):
            lay.addWidget(b)
        return bar

    def _wc_button(self, text: str, tip: str, name: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(name)
        b.setProperty("wc", True)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(22)
        b.setMinimumWidth(22)
        if not b.font().pixelSize():
            b.setFont(mono_font(12))
        return b

    def _build_body(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(14, 12, 14, 13)
        root.setSpacing(9)

        # --- prompt / status line ---
        prompt = QHBoxLayout()
        prompt.setSpacing(7)
        ps1 = QLabel("$"); ps1.setObjectName("ps1"); ps1.setFont(mono_font(13, QFont.Weight.Bold))
        cmd = QLabel("rec --status"); cmd.setObjectName("cmd"); cmd.setFont(mono_font(12))
        self.status_dot = Dot(7)
        self.status_word = QLabel("idle"); self.status_word.setObjectName("statusWord")
        self.status_word.setFont(mono_font(12, QFont.Weight.DemiBold))
        self.caret = QLabel("▋"); self.caret.setObjectName("caret"); self.caret.setFont(mono_font(12))
        self.clock = QLabel("00:00:00"); self.clock.setObjectName("clock")
        self.clock.setFont(mono_font(13))
        prompt.addWidget(ps1)
        prompt.addWidget(cmd)
        prompt.addSpacing(2)
        prompt.addWidget(self.status_dot)
        prompt.addWidget(self.status_word)
        prompt.addWidget(self.caret)
        prompt.addStretch(1)
        prompt.addWidget(self.clock)
        root.addLayout(prompt)

        self.rule_top = QLabel("─" * 30)
        self.rule_top.setObjectName("rule"); self.rule_top.setFont(mono_font(12))
        root.addWidget(self.rule_top)

        # --- config flag rows ---
        self.mode_select = FlagSelect("--mode")
        self.mode_select.set_items([("全屏", ""), ("窗口", ""), ("自定义", "")])
        try:
            self.mode_select.set_current_index(self._mode_values.index(self.cfg.region_mode))
        except ValueError:
            self.mode_select.set_current_index(0)
        self.mode_select.currentIndexChanged.connect(self._on_mode_changed)
        root.addWidget(self.mode_select)

        self.preset_select = FlagSelect("--quality")
        self.preset_select.set_items(
            [("超高清", "30M·60"), ("高清", "12M·60"), ("标清", "6M·30"),
             ("流畅", "3M·30"), ("自定义", "")])
        try:
            self.preset_select.set_current_index(self._preset_values.index(self.cfg.quality_preset))
        except ValueError:
            self.preset_select.set_current_index(2)
        self.preset_select.currentIndexChanged.connect(self._on_preset_changed)
        root.addWidget(self.preset_select)

        # --- third row: source picker (fullscreen/window) OR region (custom) ---
        third = QWidget()
        tr = QHBoxLayout(third)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(8)
        self.source_select = FlagSelect("--source")
        self.source_select.currentIndexChanged.connect(self._on_source_changed)
        self.source_refresh = QPushButton("⟳")
        self.source_refresh.setProperty("mini", True)
        self.source_refresh.setFixedSize(30, 30)
        self.source_refresh.setCursor(Qt.PointingHandCursor)
        self.source_refresh.setToolTip("刷新")
        self.source_refresh.setFont(mono_font(15))
        self.source_refresh.clicked.connect(self._on_source_refresh)
        self.region_row = RegionRow()
        self.region_row.edit_clicked.connect(self._edit_region)
        tr.addWidget(self.source_select, 1)
        tr.addWidget(self.source_refresh)
        tr.addWidget(self.region_row, 1)
        root.addWidget(third)
        self._themed += [self.mode_select, self.preset_select,
                         self.source_select, self.region_row]

        self.rule_dim = QLabel("·  " * 16)
        self.rule_dim.setObjectName("rule"); self.rule_dim.setFont(mono_font(12))
        root.addWidget(self.rule_dim)

        # --- record button ---
        self.record_btn = RecordButton()
        self.record_btn.clicked.connect(self.toggle_record)
        self._themed.append(self.record_btn)
        root.addWidget(self.record_btn)

        # --- footer ---
        footer = QHBoxLayout()
        footer.setSpacing(4)
        footer.setContentsMargins(0, 0, 0, 0)
        self.pause_btn = FooterButton("pause", "暂停", keycap="F10")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)
        self.open_btn = FooterButton("folder", "输出")
        self.open_btn.clicked.connect(self.open_output_dir)
        self.settings_btn = FooterButton("gear", "设置")
        self.settings_btn.clicked.connect(self.open_settings)
        footer.addWidget(self.pause_btn)
        footer.addStretch(1)
        footer.addWidget(self.open_btn)
        footer.addWidget(self.settings_btn)
        root.addLayout(footer)
        self._themed += [self.pause_btn, self.open_btn, self.settings_btn]

        # --- saved toast (constant-height line, empty when idle) ---
        self.saved_label = QLabel("")
        self.saved_label.setFont(mono_font(11))
        self.saved_label.setFixedHeight(16)
        root.addWidget(self.saved_label)

        return body

    # ---------- Theme ----------

    def _apply_theme(self):
        t = thm.tokens(self.theme_name)
        self._t = t
        # Keep qfluentwidgets (InfoBar, SettingsDialog) in step with our theme.
        from qfluentwidgets import setTheme, Theme, setThemeColor
        setThemeColor(thm.ACCENT)
        setTheme(Theme.DARK if self.theme_name == "dark" else Theme.LIGHT)
        self.setStyleSheet(thm.build_qss(t))
        for w in self._themed:
            w.set_theme(t)
        self.theme_btn.setText("☀" if self.theme_name == "dark" else "☾")
        self.saved_label.setStyleSheet(f"color:{t['t3']};")
        # repaint painted glyphs / dot that depend on current state
        self._render_status(self.recorder.state)
        self._update_buttons()

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.cfg.theme = self.theme_name
        self._apply_theme()
        cfg_mod.save(self.cfg)

    def set_theme(self, name: str):
        """Called by the settings dialog when the theme changes there."""
        if name in thm.TOKENS and name != self.theme_name:
            self.theme_name = name
            self.cfg.theme = name
            self._apply_theme()

    # ---------- Tray ----------

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        a_show = QAction("显示主窗口", self); a_show.triggered.connect(self._show_from_tray)
        a_toggle = QAction("开始/停止录制", self); a_toggle.triggered.connect(self.toggle_record)
        a_quit = QAction("退出", self); a_quit.triggered.connect(self._real_quit)
        menu.addAction(a_show); menu.addAction(a_toggle); menu.addSeparator(); menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("轻录")
        self.tray.activated.connect(
            lambda r: self._show_from_tray() if r == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def showEvent(self, ev):
        super().showEvent(ev)
        if hasattr(self, "pin_btn") and self.pin_btn.isChecked():
            self._on_pin_toggled(True)
        if hasattr(self, "overlay"):
            self._update_mode_ui()

    def _real_quit(self):
        cfg_mod.save(self.cfg)
        if self.recorder.state is not RecorderState.IDLE or self._stopping:
            # Must finalize on the GUI thread path carefully: block with a
            # modal-ish wait so moov is written before process exits.
            self._status_toast("正在安全结束录制后退出…")
            if not self._stopping:
                result = self.recorder.stop()
                self._apply_stop_result(result)
            else:
                # Stop already in flight — spin until idle (max ~5 min)
                for _ in range(3000):
                    if self.recorder.state is RecorderState.IDLE and not self._stopping:
                        break
                    QApplication.processEvents()
                    threading.Event().wait(0.1)
        self.hotkeys.unregister_all()
        self.overlay.destroy()
        QApplication.instance().quit()

    # ---------- Mode / region ----------

    def _on_mode_changed(self, idx: int):
        if 0 <= idx < len(self._mode_values):
            self.cfg.region_mode = self._mode_values[idx]
        self._update_mode_ui()

    def _update_mode_ui(self):
        mode = self.cfg.region_mode
        is_window = mode == "window"
        is_fullscreen = mode == "fullscreen"
        is_custom = mode == "custom"

        self.source_select.setVisible(is_window or is_fullscreen)
        self.source_refresh.setVisible(is_window or is_fullscreen)
        self.region_row.setVisible(is_custom)

        if is_custom:
            self._sync_region_row(self._custom_rect)
            self.overlay.set_region_rect(QRect(self._custom_rect))
            self.overlay.show(style="edit")
            self.overlay.set_recording(False)
        elif is_fullscreen:
            self._refresh_screen_list()
            self._show_screen_indicator()
        elif is_window:
            self._refresh_window_list()

        if not is_window:
            self._window_follow_timer.stop()
            self._selected_hwnd = None

    def _on_source_changed(self, idx: int):
        if self.cfg.region_mode == "fullscreen":
            self._on_screen_selected(idx)
        elif self.cfg.region_mode == "window":
            self._on_window_selected(idx)

    def _on_source_refresh(self):
        if self.cfg.region_mode == "fullscreen":
            self._refresh_screen_list()
        elif self.cfg.region_mode == "window":
            self._refresh_window_list()

    def _edit_region(self):
        self.overlay.set_region_rect(QRect(self._custom_rect))
        self.overlay.show(style="edit")
        self.overlay.set_recording(False)

    # ---------- Screen picker ----------

    def _refresh_screen_list(self):
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        primary_idx = 0
        items: list[tuple[str, str]] = []
        self._screen_values = []
        for i, sc in enumerate(screens):
            g = sc.geometry()
            _, _, nw, nh = native_geometry(sc)
            tag = " · 主屏" if sc is primary else ""
            items.append((f"屏幕{i + 1}", f"{nw}×{nh}{tag}"))
            self._screen_values.append(QRect(g))
            if sc is primary:
                primary_idx = i
        if len(screens) > 1:
            items.append(("全部屏幕", ""))
            self._screen_values.append(None)
        self.source_select.set_items(items)
        self.source_select.set_current_index(primary_idx)
        self._on_screen_selected(primary_idx)

    def _on_screen_selected(self, idx: int | None = None):
        if self.cfg.region_mode != "fullscreen":
            return
        if idx is None:
            idx = self.source_select.current_index()
        if 0 <= idx < len(self._screen_values):
            self._selected_screen_geom = self._screen_values[idx]
        else:
            self._selected_screen_geom = None
        self._show_screen_indicator()

    def _show_screen_indicator(self):
        geom = self._selected_screen_geom
        if geom is None:
            self.overlay.hide()
            return
        self.overlay.set_region_rect(QRect(geom))
        self.overlay.show(style="indicator")
        self.overlay.set_recording(False)

    def _on_screens_changed(self, *_):
        if self.cfg.region_mode == "fullscreen":
            self._refresh_screen_list()

    # ---------- Window picker ----------

    def _refresh_window_list(self):
        self._window_choices = list_windows()
        items: list[tuple[str, str]] = []
        for w in self._window_choices:
            title = w.title if len(w.title) <= 26 else (w.title[:24] + "…")
            items.append((title, f"{w.rect[2]}×{w.rect[3]}"))
        self.source_select.set_items(items)
        if self._window_choices:
            self.source_select.set_current_index(0)
            self._on_window_selected(0)

    def _on_window_selected(self, idx: int | None = None):
        if idx is None:
            idx = self.source_select.current_index()
        if not (0 <= idx < len(self._window_choices)):
            return
        self._selected_hwnd = int(self._window_choices[idx].hwnd)
        self._window_follow_timer.start()
        self._refresh_window_rect()
        self.overlay.show(style="indicator")
        self.overlay.set_recording(self.recorder.state.name != "IDLE")

    def _refresh_window_rect(self):
        if self._selected_hwnd is None:
            return
        r = get_window_rect(self._selected_hwnd)
        if r is None:
            return
        x, y, w, h = r
        self.overlay.set_region_rect(physical_rect_to_logical(x, y, w, h))

    def _sync_region_row(self, r: QRect):
        px, py, pw, ph = logical_rect_to_physical(r)
        self.region_row.set_region(px, py, pw, ph)

    def _on_region_changed(self, r: QRect):
        if self.cfg.region_mode == "custom":
            self._custom_rect = QRect(r)
            self.cfg.last_region = [r.x(), r.y(), r.width(), r.height()]
            self._sync_region_row(r)

    def _on_preset_changed(self, idx: int):
        if 0 <= idx < len(self._preset_values):
            self.cfg.quality_preset = self._preset_values[idx]

    # ---------- Recorder ----------

    def _current_region(self) -> CaptureRegion | None:
        mode = self.cfg.region_mode
        if mode == "fullscreen":
            geom = self._selected_screen_geom
            if geom is None:
                return CaptureRegion(fullscreen=True)
            x, y, w, h = logical_screen_to_physical(geom)
            return CaptureRegion(x, y, w, h, fullscreen=False)
        if mode == "window":
            if self._selected_hwnd is None:
                self._show_warning("请先选择一个窗口")
                return None
            r = get_window_rect(self._selected_hwnd)
            if r is None:
                self._show_warning("无法获取窗口位置，可能已关闭")
                return None
            x, y, w, h = r  # Win32 physical pixels
            return CaptureRegion(x, y, w, h, fullscreen=False)
        x, y, w, h = logical_rect_to_physical(self._custom_rect)
        return CaptureRegion(x, y, w, h, fullscreen=False)

    def _show_warning(self, content: str):
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.warning(title="提示", content=content, orient=Qt.Horizontal,
                        isClosable=True, position=InfoBarPosition.TOP,
                        duration=3000, parent=self)

    def toggle_record(self):
        if self._stopping or self.recorder.state is RecorderState.FINALIZING:
            return
        if self.recorder.state is RecorderState.IDLE:
            self.start_record()
        else:
            self.stop_record()

    def start_record(self):
        if self._stopping or self.recorder.state is not RecorderState.IDLE:
            return
        region = self._current_region()
        if region is None:
            return
        overlay_visible = (self.cfg.region_mode == "custom" or
                           (self.cfg.region_mode == "fullscreen" and self._selected_screen_geom is not None) or
                           self.cfg.region_mode == "window")
        if overlay_visible:
            self.overlay.set_recording(True)
        screens = physical_screen_geometries()
        try:
            self.recorder.start(self.cfg, region, screens=screens)
        except Exception as e:
            self._on_error(f"启动失败：{e}")
            if overlay_visible:
                self.overlay.set_recording(False)
            return
        self._elapsed = 0
        self.saved_label.setText("")
        self._elapsed_timer.start()
        cfg_mod.save(self.cfg)

    def stop_record(self):
        """Stop on a background thread so long finalize/remux does not freeze UI."""
        if self._stopping or self.recorder.state is RecorderState.IDLE:
            return
        self._stopping = True
        self._elapsed_timer.stop()
        self.overlay.set_recording(False)
        self.saved_label.setText("正在封装，请勿关闭…")
        self.saved_label.setStyleSheet(f"color:{self._t.get('warn', self._t['t2'])};")
        self._update_buttons()

        def worker():
            result = self.recorder.stop()
            self.bridge.stop_finished.emit(result)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(object)
    def _on_stop_finished(self, result: object):
        self._stopping = False
        self._apply_stop_result(result if isinstance(result, StopResult) else StopResult(ok=False, message="unknown"))
        self._update_buttons()

    def _apply_stop_result(self, result: StopResult) -> None:
        if result.ok and result.path and result.path.exists():
            size_mb = result.bytes_written / (1024 * 1024) if result.bytes_written else (
                result.path.stat().st_size / (1024 * 1024)
            )
            self.saved_label.setText(f"✓ saved   {result.path.name} · {size_mb:.1f} MB")
            self.saved_label.setStyleSheet(f"color:{self._t['ok']};")
            self.tray.showMessage(
                "录制完成",
                f"{result.path.name}  ({size_mb:.1f} MB)\n{result.path.parent}",
                QSystemTrayIcon.Information, 5000,
            )
            self._last_output = result.path
        else:
            msg = (result.message or "录制失败").split("\n")[0]
            self.saved_label.setText(f"✗ {msg[:48]}")
            self.saved_label.setStyleSheet(f"color:{self._t.get('err', self._t['t3'])};")
            if result.message:
                self.tray.showMessage("录制异常", result.message[:200],
                                      QSystemTrayIcon.Warning, 8000)

    @Slot(str)
    def _on_status(self, msg: str):
        if self._stopping or self.recorder.state is RecorderState.FINALIZING:
            self.saved_label.setText(msg[:60])
            self.saved_label.setStyleSheet(f"color:{self._t.get('warn', self._t['t2'])};")

    def _status_toast(self, msg: str) -> None:
        self.saved_label.setText(msg[:60])

    def toggle_pause(self):
        if self._stopping or self.recorder.state is RecorderState.FINALIZING:
            return
        if self.recorder.state is RecorderState.RECORDING:
            self.recorder.pause()
        elif self.recorder.state is RecorderState.PAUSED:
            self.recorder.resume()

    @Slot(object)
    def _on_state(self, state):
        self._update_buttons()
        self._render_status(state)

    def _render_status(self, state):
        """Drive the prompt line (word + dot + caret) for the given state."""
        if not hasattr(self, "status_word"):
            return
        t = self._t
        if state is RecorderState.RECORDING:
            word, st, dot = "recording", "recording", t["accent"]
            self.caret.setVisible(False)
            if not self._pulse_timer_active():
                self._pulse_timer.start()
        elif state is RecorderState.PAUSED:
            word, st, dot = "paused", "paused", t["paused"]
            self.caret.setVisible(False)
            self._pulse_timer.stop()
        elif state is RecorderState.FINALIZING:
            word, st, dot = "finalizing", "paused", t.get("warn", t["paused"])
            self.caret.setVisible(False)
            self._pulse_timer.stop()
        else:
            word, st, dot = "idle", "", t["t3"]
            self.caret.setVisible(True)
            self._pulse_timer.stop()
        self.status_word.setText(word)
        self.status_word.setProperty("state", st)
        self._repolish(self.status_word)
        self.clock.setProperty("state", st)
        self._repolish(self.clock)
        self.status_dot.set_color(dot)
        self.clock.setText(self._format_elapsed())

    def _pulse_timer_active(self) -> bool:
        return hasattr(self, "_pulse_timer") and self._pulse_timer.isActive()

    def _pulse_dot(self):
        self._pulse_on = not self._pulse_on
        c = QColor(self._t["accent"])
        c.setAlphaF(0.4 if self._pulse_on else 1.0)
        self.status_dot.set_color(c)

    def _blink_caret(self):
        if self.recorder.state is RecorderState.IDLE:
            self._caret_on = not self._caret_on
            self.caret.setVisible(self._caret_on)

    def _repolish(self, w):
        w.style().unpolish(w); w.style().polish(w)

    @Slot(str)
    def _on_error(self, msg: str):
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.error(title="录制错误", content=msg[:200], orient=Qt.Horizontal,
                      isClosable=True, position=InfoBarPosition.TOP,
                      duration=6000, parent=self)

    def _update_buttons(self):
        if not hasattr(self, "record_btn"):
            return
        s = self.recorder.state
        busy = self._stopping or s is RecorderState.FINALIZING
        recording_now = s is not RecorderState.IDLE
        self.record_btn.set_recording(recording_now and not busy)
        self.record_btn.setEnabled(not busy)
        self.pause_btn.setEnabled(recording_now and not busy and s is not RecorderState.FINALIZING)
        self.pause_btn.set_glyph_kind("play" if s is RecorderState.PAUSED else "pause")
        self.pause_btn.set_label("继续" if s is RecorderState.PAUSED else "暂停")
        if hasattr(self, "_t"):
            self.pause_btn.set_theme(self._t)

    def _tick_elapsed(self):
        if self.recorder.state is RecorderState.RECORDING:
            self._elapsed += 1
            self.clock.setText(self._format_elapsed())

    def _format_elapsed(self) -> str:
        m, s = divmod(self._elapsed, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    # ---------- Actions ----------

    def open_output_dir(self):
        last = getattr(self, "_last_output", None)
        if last and last.exists():
            try:
                subprocess.Popen(["explorer", "/select,", str(last)])
                return
            except Exception:
                pass
        out_dir = Path(self.cfg.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            dlg.apply_to(self.cfg)
            try:
                self.preset_select.set_current_index(self._preset_values.index(self.cfg.quality_preset))
            except ValueError:
                pass
            if self.cfg.theme != self.theme_name:
                self.set_theme(self.cfg.theme)
            cfg_mod.save(self.cfg)
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(title="已保存", content="设置已生效", orient=Qt.Horizontal,
                            isClosable=True, position=InfoBarPosition.TOP,
                            duration=2000, parent=self)

    def _on_pin_toggled(self, on: bool):
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        wt.UINT]
        user32.SetWindowPos.restype = wt.BOOL
        HWND_TOPMOST = wt.HWND(-1)
        HWND_NOTOPMOST = wt.HWND(-2)
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
        user32.SetWindowPos(
            wt.HWND(int(self.winId())),
            HWND_TOPMOST if on else HWND_NOTOPMOST,
            0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        )

    # ---------- Lifecycle ----------

    def closeEvent(self, ev):
        """Closing the window hides to tray; never kill an in-progress finalize.

        If user is recording, keep recording in background (tray) instead of
        aborting — avoids moov-less broken MP4s from force-close mid-capture.
        """
        cfg_mod.save(self.cfg)
        self.overlay.hide()
        if self.recorder.state is not RecorderState.IDLE or self._stopping:
            # Hide instead of quitting while capture/finalize is active
            self.hide()
            self.tray.showMessage(
                "轻录仍在后台运行",
                "录制/封装进行中，已最小化到托盘。请用托盘菜单停止或退出。",
                QSystemTrayIcon.Information,
                4000,
            )
            ev.ignore()
            return
        # Idle: just hide to tray (historical behaviour via close button)
        self.hide()
        ev.ignore()
