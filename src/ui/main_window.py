"""Main control panel: start/pause/stop + mode/preset + status."""
from __future__ import annotations
from pathlib import Path
import os
import subprocess
import threading
from PySide6.QtCore import Qt, QRect, QTimer, Signal, QObject, Slot, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QMessageBox, QSystemTrayIcon, QMenu, QFrame,
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
        self.setWindowTitle("MiniRecorder")
        self.resize(420, 200)
        self.setMinimumSize(380, 180)

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
        if self.cfg.last_region:
            x, y, w, h = self.cfg.last_region
            self.overlay.set_region_rect(QRect(x, y, w, h))

        self._window_choices: list[WindowInfo] = []
        self._window_follow_timer = QTimer(self)
        self._window_follow_timer.setInterval(500)
        self._window_follow_timer.timeout.connect(self._refresh_window_rect)
        self._selected_hwnd: int | None = None

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

    # ---------- UI ----------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 10, 18, 14)
        root.setSpacing(8)

        # Top row: pin (always-on-top) button on the right
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch(1)
        self.pin_btn = QPushButton("📌")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFixedSize(28, 24)
        self.pin_btn.setObjectName("pinBtn")
        self.pin_btn.setToolTip("置顶窗口")
        self.pin_btn.toggled.connect(self._toggle_always_on_top)
        top_row.addWidget(self.pin_btn)
        root.addLayout(top_row)

        # Row: mode + preset
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("模式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("全屏", "fullscreen")
        self.mode_combo.addItem("窗口", "window")
        self.mode_combo.addItem("自定义区域", "custom")
        idx = self.mode_combo.findData(self.cfg.region_mode)
        if idx >= 0: self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        row.addWidget(self.mode_combo, 1)

        row.addSpacing(6)
        row.addWidget(QLabel("质量"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("高 (10Mbps/60fps)", "high")
        self.preset_combo.addItem("中 (6Mbps/30fps)", "medium")
        self.preset_combo.addItem("低 (3Mbps/30fps)", "low")
        self.preset_combo.addItem("自定义", "custom")
        idx = self.preset_combo.findData(self.cfg.quality_preset)
        if idx >= 0: self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        row.addWidget(self.preset_combo, 1)
        root.addLayout(row)

        # Row: window picker (visible only in window mode)
        self.window_row = QHBoxLayout()
        self.window_label = QLabel("窗口")
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(220)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._refresh_window_list)
        self.window_combo.currentIndexChanged.connect(self._on_window_selected)
        self.window_row.addWidget(self.window_label)
        self.window_row.addWidget(self.window_combo, 1)
        self.window_row.addWidget(self.refresh_btn)
        root.addLayout(self.window_row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setObjectName("sep")
        root.addWidget(sep)

        # Row: buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.start_btn = QPushButton("● 开始 (F9)")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self.toggle_record)
        self.pause_btn = QPushButton("⏸ 暂停 (F10)")
        self.pause_btn.setObjectName("pauseBtn")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.open_dir_btn = QPushButton("📂")
        self.open_dir_btn.setFixedWidth(40)
        self.open_dir_btn.setObjectName("settingsBtn")
        self.open_dir_btn.setToolTip("打开输出目录")
        self.open_dir_btn.clicked.connect(self.open_output_dir)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedWidth(40)
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.clicked.connect(self.open_settings)
        btn_row.addWidget(self.start_btn, 2)
        btn_row.addWidget(self.pause_btn, 1)
        btn_row.addWidget(self.open_dir_btn)
        btn_row.addWidget(self.settings_btn)
        root.addLayout(btn_row)

        # Status
        self.status_label = QLabel("待机")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status_label)

    def _apply_theme(self, qss: str):
        base = """
        QMainWindow { background: #1f2230; }
        QWidget { color: #e8eaf2; font-family: 'Segoe UI', 'Microsoft YaHei UI', sans-serif; font-size: 13px; }
        QLabel { color: #c4c8d6; }
        QLabel#status { font-size: 13px; padding: 4px; color: #8a90a4; }
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
            background: #2a2e3f; border: 1px solid #383c4e; border-radius: 6px;
            padding: 4px 8px; min-height: 22px; color: #e8eaf2;
        }
        QComboBox:hover, QLineEdit:hover { border-color: #5566ff; }
        QComboBox QAbstractItemView { background: #2a2e3f; border: 1px solid #383c4e; selection-background-color: #5566ff; }
        QPushButton {
            background: #2a2e3f; border: 1px solid #383c4e; border-radius: 6px;
            padding: 8px 12px; color: #e8eaf2; font-weight: 500;
        }
        QPushButton:hover { background: #353a4e; border-color: #5566ff; }
        QPushButton:pressed { background: #232636; }
        QPushButton:disabled { color: #5a5e70; }
        QPushButton#startBtn { background: #d04545; border-color: #d04545; color: white; font-weight: 600; }
        QPushButton#startBtn:hover { background: #e05555; border-color: #e05555; }
        QPushButton#startBtn[recording="true"] { background: #4a4e60; border-color: #4a4e60; }
        QPushButton#pauseBtn { background: transparent; }
        QPushButton#settingsBtn { background: transparent; font-size: 16px; }
        QPushButton#pinBtn { background: transparent; border: 1px solid transparent; font-size: 14px; padding: 2px; }
        QPushButton#pinBtn:hover { background: #2a2e3f; border-color: #383c4e; }
        QPushButton#pinBtn:checked { background: #5566ff; border-color: #5566ff; color: white; }
        QFrame#sep { color: #2a2e3f; background: #2a2e3f; max-height: 1px; }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid #4a4e60; background: #2a2e3f; }
        QCheckBox::indicator:checked { background: #5566ff; border-color: #5566ff; }
        QDialog { background: #1f2230; }
        """
        self.setStyleSheet(base + "\n" + qss)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        a_show = QAction("显示主窗口", self); a_show.triggered.connect(self._show_from_tray)
        a_toggle = QAction("开始/停止录制", self); a_toggle.triggered.connect(self.toggle_record)
        a_quit = QAction("退出", self); a_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(a_show); menu.addAction(a_toggle); menu.addSeparator(); menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("MiniRecorder")
        self.tray.activated.connect(lambda r: self._show_from_tray() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    # ---------- Mode / region ----------

    def _on_mode_changed(self):
        self.cfg.region_mode = self.mode_combo.currentData()
        self._update_mode_ui()

    def _update_mode_ui(self):
        mode = self.cfg.region_mode
        is_window = mode == "window"
        self.window_label.setVisible(is_window)
        self.window_combo.setVisible(is_window)
        self.refresh_btn.setVisible(is_window)

        if mode == "custom":
            self.overlay.show()
            self.overlay.set_recording(False)
        else:
            self.overlay.hide()

        if is_window:
            self._refresh_window_list()
        else:
            self._window_follow_timer.stop()
            self._selected_hwnd = None

    def _refresh_window_list(self):
        self._window_choices = list_windows()
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        for w in self._window_choices:
            self.window_combo.addItem(f"{w.title}  ({w.rect[2]}x{w.rect[3]})", w.hwnd)
        self.window_combo.blockSignals(False)
        if self._window_choices:
            self._on_window_selected()

    def _on_window_selected(self):
        hwnd = self.window_combo.currentData()
        if hwnd is None: return
        self._selected_hwnd = int(hwnd)
        self._window_follow_timer.start()
        self._refresh_window_rect()

    def _refresh_window_rect(self):
        if self._selected_hwnd is None: return
        r = get_window_rect(self._selected_hwnd)
        if r is None: return
        # nothing to display visually for window mode; just store implicitly via hwnd

    def _on_region_changed(self, r: QRect):
        self.cfg.last_region = [r.x(), r.y(), r.width(), r.height()]

    def _on_preset_changed(self):
        self.cfg.quality_preset = self.preset_combo.currentData()

    # ---------- Recorder ----------

    def _current_region(self) -> CaptureRegion | None:
        mode = self.cfg.region_mode
        if mode == "fullscreen":
            return CaptureRegion(fullscreen=True)
        if mode == "window":
            if self._selected_hwnd is None:
                QMessageBox.warning(self, "提示", "请先选择一个窗口")
                return None
            r = get_window_rect(self._selected_hwnd)
            if r is None:
                QMessageBox.warning(self, "提示", "无法获取窗口位置，可能已关闭")
                return None
            x, y, w, h = r
            return CaptureRegion(x, y, w, h, fullscreen=False)
        # custom
        r = self.overlay.region_rect()
        return CaptureRegion(r.x(), r.y(), r.width(), r.height(), fullscreen=False)

    def toggle_record(self):
        if self.recorder.state is RecorderState.IDLE:
            self.start_record()
        else:
            self.stop_record()

    def start_record(self):
        region = self._current_region()
        if region is None:
            return
        # Switch overlay to recording look: red blink + handles hidden
        if self.cfg.region_mode == "custom":
            self.overlay.set_recording(True)
        try:
            self.recorder.start(self.cfg, region)
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))
            if self.cfg.region_mode == "custom":
                self.overlay.set_recording(False)
            return
        self._elapsed = 0
        self._elapsed_timer.start()
        cfg_mod.save(self.cfg)

    def stop_record(self):
        out = self.recorder.stop()
        self._elapsed_timer.stop()
        if self.cfg.region_mode == "custom":
            self.overlay.set_recording(False)
        if out and out.exists():
            size_mb = out.stat().st_size / (1024 * 1024)
            self.status_label.setText(f"✔ 已保存：{out.name}  ({size_mb:.1f} MB)")
            self.tray.showMessage(
                "录制完成",
                f"{out.name}  ({size_mb:.1f} MB)\n位置：{out.parent}",
                QSystemTrayIcon.Information, 5000,
            )
            self._last_output = out
        else:
            self.status_label.setText("⚠ 录制失败 — 查看输出目录或重试")

    def toggle_pause(self):
        if self.recorder.state is RecorderState.RECORDING:
            self.recorder.pause()
        elif self.recorder.state is RecorderState.PAUSED:
            self.recorder.resume()

    @Slot(object)
    def _on_state(self, state):
        self._update_buttons()
        if state is RecorderState.RECORDING:
            self.status_label.setText(f"● 录制中  {self._format_elapsed()}")
        elif state is RecorderState.PAUSED:
            self.status_label.setText(f"⏸ 已暂停  {self._format_elapsed()}")
        else:
            self.status_label.setText("待机")

    @Slot(str)
    def _on_error(self, msg: str):
        QMessageBox.critical(self, "录制错误", msg)

    def _update_buttons(self):
        s = self.recorder.state
        if s is RecorderState.IDLE:
            self.start_btn.setText("● 开始 (F9)")
            self.start_btn.setProperty("recording", "false")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("⏸ 暂停 (F10)")
        else:
            self.start_btn.setText("■ 停止 (F9)")
            self.start_btn.setProperty("recording", "true")
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("▶ 继续 (F10)" if s is RecorderState.PAUSED else "⏸ 暂停 (F10)")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

    def _tick_elapsed(self):
        if self.recorder.state is RecorderState.RECORDING:
            self._elapsed += 1
            self.status_label.setText(f"● 录制中  {self._format_elapsed()}")

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
            # Reflect changed preset back into combo
            idx = self.preset_combo.findData(self.cfg.quality_preset)
            if idx >= 0: self.preset_combo.setCurrentIndex(idx)
            cfg_mod.save(self.cfg)

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
