"""Main control panel: start/pause/stop + mode/preset + status."""
from __future__ import annotations
from pathlib import Path
import os
import subprocess
import threading
from PySide6.QtCore import Qt, QRect, QTimer, Signal, QObject, Slot, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSystemTrayIcon, QMenu, QFrame, QSizePolicy, QLabel,
)
from qfluentwidgets import (
    PushButton, PrimaryPushButton, TransparentToolButton, ToolButton,
    ComboBox, BodyLabel, CaptionLabel, StrongBodyLabel, SimpleCardWidget,
    FluentIcon as FIF, setTheme, Theme, setThemeColor, InfoBar, InfoBarPosition,
    MessageBox,
)

from ..core import config as cfg_mod
from ..core import ffmpeg_builder as fb
from ..core.recorder import Recorder, RecorderState
from ..core.ffmpeg_builder import CaptureRegion
from ..core.hotkey import HotkeyManager
from .region_overlay import RegionOverlay
from .window_picker import list_windows, get_window_rect, WindowInfo
from .settings_dialog import SettingsDialog


class _RecorderBridge(QObject):
    state_changed = Signal(object)
    error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, theme_qss: str = ""):
        super().__init__()
        self.setWindowTitle("轻录")
        self.resize(480, 320)
        self.setMinimumSize(440, 300)

        self.cfg = cfg_mod.load()
        self.bridge = _RecorderBridge()
        self.bridge.state_changed.connect(self._on_state)
        self.bridge.error.connect(self._on_error)

        self.recorder = Recorder(
            on_state_change=lambda s: self.bridge.state_changed.emit(s),
            on_error=lambda msg: self.bridge.error.emit(msg),
        )

        self.overlay = RegionOverlay()
        self.overlay.region_changed.connect(self._on_region_changed)
        # Custom region is owned by MainWindow, not the overlay. The overlay's
        # internal rect gets overwritten when we use it to indicate fullscreen
        # or window mode, so we restore from this when entering custom mode.
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
        # Screen picker for fullscreen mode. None = all screens.
        self._selected_screen_geom: QRect | None = None

        self._build_ui()
        self._apply_theme(theme_qss)
        self._update_mode_ui()
        self._update_buttons()

        # Hotkeys
        self.hotkeys = HotkeyManager()
        self._register_hotkeys()

        # Tray
        self._build_tray()

        # Status timer (elapsed time)
        self._elapsed = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        # Probe audio device in background so first record isn't laggy
        threading.Thread(target=fb.pick_audio_device, daemon=True).start()

        # Re-enumerate screens if user plugs/unplugs a monitor
        gapp = QGuiApplication.instance()
        gapp.screenAdded.connect(self._on_screens_changed)
        gapp.screenRemoved.connect(self._on_screens_changed)

    def _on_screens_changed(self, *_):
        if self.cfg.region_mode == "fullscreen":
            self._refresh_screen_list()

    # ---------- UI ----------

    def _build_ui(self):
        # Fluent dark theme + cyan-blue accent
        setTheme(Theme.DARK)
        setThemeColor("#4cc2ff")

        # Apply explicit dark bg — QMainWindow itself ignores Fluent's palette
        self.setStyleSheet("""
            QMainWindow { background-color: #1c1c1c; }
            #centralWidget { background-color: #1c1c1c; }
            #headerBar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2a2230, stop:1 #1c2840);
                border-bottom: 1px solid #2e2e2e;
            }
            #headerStatus { color: #d0d0d0; font-size: 13px; }
            #headerStatus[state="recording"] { color: #ff5050; font-weight: 600; }
            #headerStatus[state="paused"] { color: #ffaa30; font-weight: 600; }
            #headerStatus[state="ok"] { color: #4cd97b; }
            #statusLabel { color: #888; padding: 4px; font-size: 12px; }
            #statusLabel[state="ok"] { color: #4cd97b; }
        """)

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Slim header bar: status on left, pin on right ----
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(44)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 0, 10, 0)
        hl.setSpacing(10)
        self.rec_dot = QLabel()
        self.rec_dot.setFixedSize(10, 10)
        self.rec_dot.setStyleSheet("background:#4a4a4a; border-radius:5px;")
        hl.addWidget(self.rec_dot)
        self.header_status = QLabel("待机")
        self.header_status.setObjectName("headerStatus")
        hl.addWidget(self.header_status)
        hl.addStretch(1)
        self.pin_btn = TransparentToolButton(FIF.PIN)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFixedSize(32, 32)
        self.pin_btn.setToolTip("置顶窗口")
        self.pin_btn.toggled.connect(self._toggle_always_on_top)
        hl.addWidget(self.pin_btn)
        root.addWidget(header)

        # ---- Body container ----
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 14, 16, 14)
        body_lay.setSpacing(12)
        root.addWidget(body, 1)

        # ---- Settings card ----
        card = SimpleCardWidget()
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 12)
        card_lay.setSpacing(10)

        # Row: mode + preset
        # Note: QFluentWidgets ComboBox.addItem doesn't reliably store userData,
        # so we maintain parallel value lists indexed by combo position.
        self._mode_values = ["fullscreen", "window", "custom"]
        self._preset_values = ["high", "medium", "low", "custom"]
        row = QHBoxLayout()
        row.setSpacing(8)
        mode_lbl = BodyLabel("模式")
        mode_lbl.setFixedWidth(36)
        row.addWidget(mode_lbl)
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["全屏", "窗口", "自定义区域"])
        try:
            self.mode_combo.setCurrentIndex(self._mode_values.index(self.cfg.region_mode))
        except ValueError:
            self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        row.addWidget(self.mode_combo, 1)

        row.addSpacing(4)
        q_lbl = BodyLabel("质量")
        q_lbl.setFixedWidth(36)
        row.addWidget(q_lbl)
        self.preset_combo = ComboBox()
        self.preset_combo.addItems(["高 10M/60", "中 6M/30", "低 3M/30", "自定义"])
        try:
            self.preset_combo.setCurrentIndex(self._preset_values.index(self.cfg.quality_preset))
        except ValueError:
            self.preset_combo.setCurrentIndex(1)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        row.addWidget(self.preset_combo, 1)
        card_lay.addLayout(row)

        # Row: screen picker (only fullscreen)
        self.screen_row = QHBoxLayout()
        self.screen_label = BodyLabel("屏幕")
        self.screen_label.setFixedWidth(36)
        self.screen_combo = ComboBox()
        self.screen_combo.setMinimumWidth(240)
        self.screen_combo.currentIndexChanged.connect(self._on_screen_selected)
        self.screen_refresh_btn = TransparentToolButton(FIF.SYNC)
        self.screen_refresh_btn.setToolTip("刷新屏幕列表")
        self.screen_refresh_btn.clicked.connect(self._refresh_screen_list)
        self.screen_row.addWidget(self.screen_label)
        self.screen_row.addWidget(self.screen_combo, 1)
        self.screen_row.addWidget(self.screen_refresh_btn)
        card_lay.addLayout(self.screen_row)

        # Row: window picker (only window mode)
        self.window_row = QHBoxLayout()
        self.window_label = BodyLabel("窗口")
        self.window_label.setFixedWidth(36)
        self.window_combo = ComboBox()
        self.window_combo.setMinimumWidth(220)
        self.refresh_btn = TransparentToolButton(FIF.SYNC)
        self.refresh_btn.setToolTip("刷新窗口列表")
        self.refresh_btn.clicked.connect(self._refresh_window_list)
        self.window_combo.currentIndexChanged.connect(self._on_window_selected)
        self.window_row.addWidget(self.window_label)
        self.window_row.addWidget(self.window_combo, 1)
        self.window_row.addWidget(self.refresh_btn)
        card_lay.addLayout(self.window_row)

        body_lay.addWidget(card)

        # ---- Action buttons ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.start_btn = PushButton("●  开始录制    F9")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setObjectName("recordBtn")
        self.start_btn.clicked.connect(self.toggle_record)
        self._apply_record_btn_style(recording=False)
        self.pause_btn = PushButton(FIF.PAUSE, "暂停  F10")
        self.pause_btn.setMinimumHeight(44)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.open_dir_btn = ToolButton(FIF.FOLDER)
        self.open_dir_btn.setFixedSize(44, 44)
        self.open_dir_btn.setToolTip("打开输出目录")
        self.open_dir_btn.clicked.connect(self.open_output_dir)
        self.settings_btn = ToolButton(FIF.SETTING)
        self.settings_btn.setFixedSize(44, 44)
        self.settings_btn.setToolTip("设置")
        self.settings_btn.clicked.connect(self.open_settings)
        btn_row.addWidget(self.start_btn, 3)
        btn_row.addWidget(self.pause_btn, 2)
        btn_row.addWidget(self.open_dir_btn)
        btn_row.addWidget(self.settings_btn)
        body_lay.addLayout(btn_row)

        # ---- Status ----
        self.status_label = QLabel("待机")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        body_lay.addWidget(self.status_label)
        body_lay.addStretch(1)

    def _apply_theme(self, qss: str):
        # Most styling comes from QFluentWidgets' Theme.DARK; user QSS overrides last.
        if qss:
            self.setStyleSheet(self.styleSheet() + "\n" + qss)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        a_show = QAction("显示主窗口", self); a_show.triggered.connect(self._show_from_tray)
        a_toggle = QAction("开始/停止录制", self); a_toggle.triggered.connect(self.toggle_record)
        a_quit = QAction("退出", self); a_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(a_show); menu.addAction(a_toggle); menu.addSeparator(); menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("轻录")
        self.tray.activated.connect(lambda r: self._show_from_tray() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    # ---------- Mode / region ----------

    def _on_mode_changed(self):
        idx = self.mode_combo.currentIndex()
        if 0 <= idx < len(self._mode_values):
            self.cfg.region_mode = self._mode_values[idx]
        self._update_mode_ui()

    def _update_mode_ui(self):
        mode = self.cfg.region_mode
        is_window = mode == "window"
        is_fullscreen = mode == "fullscreen"

        self.window_label.setVisible(is_window)
        self.window_combo.setVisible(is_window)
        self.refresh_btn.setVisible(is_window)
        self.screen_label.setVisible(is_fullscreen)
        self.screen_combo.setVisible(is_fullscreen)

        if mode == "custom":
            # Restore the user's saved custom rect — don't reuse whatever the
            # overlay was last showing (could have been a screen or window rect).
            self.overlay.set_region_rect(QRect(self._custom_rect))
            self.overlay.show(style="edit")
            self.overlay.set_recording(False)
        elif mode == "fullscreen":
            self._refresh_screen_list()
            self._show_screen_indicator()
        elif mode == "window":
            self._refresh_window_list()
        else:
            self.overlay.hide()

        if not is_window:
            self._window_follow_timer.stop()
            self._selected_hwnd = None

    # ---------- Screen picker ----------

    def _refresh_screen_list(self):
        self.screen_combo.blockSignals(True)
        self.screen_combo.clear()
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        primary_idx = 0
        labels: list[str] = []
        self._screen_values: list[QRect | None] = []
        for i, sc in enumerate(screens):
            g = sc.geometry()
            tag = "（主屏）" if sc is primary else ""
            labels.append(f"屏幕 {i + 1}{tag}  {g.width()}×{g.height()}  @({g.x()},{g.y()})")
            self._screen_values.append(QRect(g))
            if sc is primary:
                primary_idx = i
        if len(screens) > 1:
            labels.append("全部屏幕（拼接录制）")
            self._screen_values.append(None)
        self.screen_combo.addItems(labels)
        self.screen_combo.setCurrentIndex(primary_idx)
        self.screen_combo.blockSignals(False)
        self._on_screen_selected()

    def _on_screen_selected(self):
        if self.cfg.region_mode != "fullscreen":
            return
        idx = self.screen_combo.currentIndex()
        if 0 <= idx < len(getattr(self, "_screen_values", [])):
            self._selected_screen_geom = self._screen_values[idx]
        else:
            self._selected_screen_geom = None
        self._show_screen_indicator()

    def _show_screen_indicator(self):
        """Show dashed indicator border around the selected screen."""
        geom = self._selected_screen_geom
        if geom is None:
            # "all screens" — no single rect to indicate; hide overlay
            self.overlay.hide()
            return
        self.overlay.set_region_rect(QRect(geom))
        self.overlay.show(style="indicator")
        self.overlay.set_recording(False)

    def _refresh_window_list(self):
        self._window_choices = list_windows()
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        labels = [f"{w.title}  ({w.rect[2]}x{w.rect[3]})" for w in self._window_choices]
        self.window_combo.addItems(labels)
        self.window_combo.blockSignals(False)
        if self._window_choices:
            self.window_combo.setCurrentIndex(0)
            self._on_window_selected()

    def _on_window_selected(self):
        idx = self.window_combo.currentIndex()
        if not (0 <= idx < len(self._window_choices)):
            return
        self._selected_hwnd = int(self._window_choices[idx].hwnd)
        self._window_follow_timer.start()
        self._refresh_window_rect()
        self.overlay.show(style="indicator")
        self.overlay.set_recording(self.recorder.state.name != "IDLE")

    def _refresh_window_rect(self):
        if self._selected_hwnd is None: return
        r = get_window_rect(self._selected_hwnd)
        if r is None: return
        x, y, w, h = r
        self.overlay.set_region_rect(QRect(x, y, w, h))

    def _on_region_changed(self, r: QRect):
        # Only persist when the user actively dragged in custom mode.
        if self.cfg.region_mode == "custom":
            self._custom_rect = QRect(r)
            self.cfg.last_region = [r.x(), r.y(), r.width(), r.height()]

    def _on_preset_changed(self):
        idx = self.preset_combo.currentIndex()
        if 0 <= idx < len(self._preset_values):
            self.cfg.quality_preset = self._preset_values[idx]

    # ---------- Recorder ----------

    def _current_region(self) -> CaptureRegion | None:
        mode = self.cfg.region_mode
        if mode == "fullscreen":
            geom = self._selected_screen_geom
            if geom is None:
                return CaptureRegion(fullscreen=True)
            return CaptureRegion(geom.x(), geom.y(), geom.width(), geom.height(), fullscreen=False)
        if mode == "window":
            if self._selected_hwnd is None:
                self._show_warning("提示", "请先选择一个窗口")
                return None
            r = get_window_rect(self._selected_hwnd)
            if r is None:
                self._show_warning("提示", "无法获取窗口位置，可能已关闭")
                return None
            x, y, w, h = r
            return CaptureRegion(x, y, w, h, fullscreen=False)
        # custom — use the MainWindow-owned custom rect (overlay may be hidden)
        r = self._custom_rect
        return CaptureRegion(r.x(), r.y(), r.width(), r.height(), fullscreen=False)

    def toggle_record(self):
        if self.recorder.state is RecorderState.IDLE:
            self.start_record()
        else:
            self.stop_record()

    def _show_warning(self, title: str, content: str):
        InfoBar.warning(
            title=title, content=content, orient=Qt.Horizontal,
            isClosable=True, position=InfoBarPosition.TOP, duration=4000, parent=self,
        )

    def start_record(self):
        region = self._current_region()
        if region is None:
            return
        # Switch overlay to recording look (any mode that has a visible overlay)
        overlay_visible = self.cfg.region_mode == "custom" or (
            self.cfg.region_mode == "fullscreen" and self._selected_screen_geom is not None
        ) or self.cfg.region_mode == "window"
        if overlay_visible:
            self.overlay.set_recording(True)
        try:
            self.recorder.start(self.cfg, region)
        except Exception as e:
            self._on_error(f"启动失败：{e}")
            if overlay_visible:
                self.overlay.set_recording(False)
            return
        self._elapsed = 0
        self._elapsed_timer.start()
        cfg_mod.save(self.cfg)

    def stop_record(self):
        out = self.recorder.stop()
        self._elapsed_timer.stop()
        # Restore overlay to idle look in any mode that shows it
        self.overlay.set_recording(False)
        if out and out.exists():
            size_mb = out.stat().st_size / (1024 * 1024)
            self.status_label.setText(f"✔ 已保存：{out.name}  ({size_mb:.1f} MB)")
            self._set_status_state("ok")
            self.tray.showMessage(
                "录制完成",
                f"{out.name}  ({size_mb:.1f} MB)\n位置：{out.parent}",
                QSystemTrayIcon.Information, 5000,
            )
            self._last_output = out
        else:
            self.status_label.setText("⚠ 录制失败 — 查看输出目录或重试")
            self._set_status_state("")

    def toggle_pause(self):
        if self.recorder.state is RecorderState.RECORDING:
            self.recorder.pause()
        elif self.recorder.state is RecorderState.PAUSED:
            self.recorder.resume()

    @Slot(object)
    def _on_state(self, state):
        self._update_buttons()
        if state is RecorderState.RECORDING:
            txt = f"录制中  {self._format_elapsed()}"
            self.header_status.setText(txt)
            self.status_label.setText(txt)
            self._set_status_state("recording")
            self._set_dot_color("#ff4040")
        elif state is RecorderState.PAUSED:
            txt = f"已暂停  {self._format_elapsed()}"
            self.header_status.setText(txt)
            self.status_label.setText(txt)
            self._set_status_state("paused")
            self._set_dot_color("#ffaa30")
        else:
            self.header_status.setText("待机")
            self.status_label.setText("待机")
            self._set_status_state("")
            self._set_dot_color("#4a4a4a")

    def _set_status_state(self, state: str):
        for w in (self.header_status, self.status_label):
            w.setProperty("state", state)
            w.style().unpolish(w); w.style().polish(w)

    def _set_dot_color(self, hex_color: str):
        self.rec_dot.setStyleSheet(f"background:{hex_color}; border-radius:5px;")

    @Slot(str)
    def _on_error(self, msg: str):
        InfoBar.error(
            title="录制错误", content=msg[:200], orient=Qt.Horizontal,
            isClosable=True, position=InfoBarPosition.TOP, duration=6000, parent=self,
        )

    def _update_buttons(self):
        s = self.recorder.state
        recording_now = s is not RecorderState.IDLE
        if s is RecorderState.IDLE:
            self.start_btn.setText("●  开始录制    F9")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("暂停  F10")
            self.pause_btn.setIcon(FIF.PAUSE)
        else:
            self.start_btn.setText("■  停止录制    F9")
            self.pause_btn.setEnabled(True)
            if s is RecorderState.PAUSED:
                self.pause_btn.setText("继续  F10")
                self.pause_btn.setIcon(FIF.PLAY)
            else:
                self.pause_btn.setText("暂停  F10")
                self.pause_btn.setIcon(FIF.PAUSE)
        self._apply_record_btn_style(recording_now)

    def _apply_record_btn_style(self, recording: bool):
        """Per-instance QSS — Fluent PushButton's painter respects bg/color via QSS only when applied locally."""
        if recording:
            qss = """
                QPushButton {
                    background-color: #3a3a3a; color: #ffffff;
                    border: 1px solid #3a3a3a; border-radius: 6px;
                    font-weight: 600; font-size: 13px; padding: 0 12px;
                }
                QPushButton:hover { background-color: #4a4a4a; border-color: #4a4a4a; }
                QPushButton:pressed { background-color: #2a2a2a; border-color: #2a2a2a; }
            """
        else:
            qss = """
                QPushButton {
                    background-color: #e63946; color: #ffffff;
                    border: 1px solid #e63946; border-radius: 6px;
                    font-weight: 600; font-size: 13px; padding: 0 12px;
                }
                QPushButton:hover { background-color: #f04757; border-color: #f04757; }
                QPushButton:pressed { background-color: #c92e3a; border-color: #c92e3a; }
            """
        self.start_btn.setStyleSheet(qss)

    def _tick_elapsed(self):
        if self.recorder.state is RecorderState.RECORDING:
            self._elapsed += 1
            txt = f"录制中  {self._format_elapsed()}"
            self.header_status.setText(txt)
            self.status_label.setText(txt)

    def _format_elapsed(self) -> str:
        m, s = divmod(self._elapsed, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    # ---------- Settings ----------

    def _toggle_always_on_top(self, on: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()  # Re-show is required after changing window flags

    def open_output_dir(self):
        """Open output dir in Explorer; highlight last recorded file if any."""
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
                self.preset_combo.setCurrentIndex(self._preset_values.index(self.cfg.quality_preset))
            except ValueError:
                pass
            cfg_mod.save(self.cfg)
            InfoBar.success(
                title="已保存", content="设置已生效", orient=Qt.Horizontal,
                isClosable=True, position=InfoBarPosition.TOP, duration=2000, parent=self,
            )

    # ---------- Hotkeys ----------

    def _register_hotkeys(self):
        # Thread-safe: keyboard callbacks run on a worker thread; marshal via signal
        self.hotkeys.register(self.cfg.hotkey_toggle, lambda: self.bridge.state_changed.emit("__toggle__"))
        self.hotkeys.register(self.cfg.hotkey_pause, lambda: self.bridge.state_changed.emit("__pause__"))
        # Override bridge handler to also catch hotkey tokens
        self.bridge.state_changed.connect(self._on_hotkey_token)

    @Slot(object)
    def _on_hotkey_token(self, token):
        if token == "__toggle__":
            self.toggle_record()
        elif token == "__pause__":
            self.toggle_pause()

    # ---------- Lifecycle ----------

    def closeEvent(self, ev):
        cfg_mod.save(self.cfg)
        if self.recorder.state is not RecorderState.IDLE:
            self.recorder.stop()
        self.hotkeys.unregister_all()
        self.overlay.destroy()
        super().closeEvent(ev)
