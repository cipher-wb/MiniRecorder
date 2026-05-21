"""Settings dialog — top-level QDialog (not MessageBoxBase) so it's not clipped by the parent window."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QFileDialog, QDialogButtonBox
from qfluentwidgets import (
    BodyLabel, StrongBodyLabel, CaptionLabel, ComboBox, DoubleSpinBox, SpinBox,
    SwitchButton, LineEdit, PushButton, ToolButton, PrimaryPushButton,
    FluentIcon as FIF, setTheme, Theme,
)

from ..core.config import AppConfig
from ..core.ffmpeg_builder import detect_capabilities


_LABEL_W = 90
_FIELD_H = 34


def _row(label_text: str, *widgets, stretch_first: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.setContentsMargins(0, 0, 0, 0)
    lbl = BodyLabel(label_text)
    lbl.setFixedWidth(_LABEL_W)
    row.addWidget(lbl)
    for i, w in enumerate(widgets):
        if hasattr(w, "setMinimumHeight"):
            w.setMinimumHeight(_FIELD_H)
        row.addWidget(w, 1 if (stretch_first and i == 0) else 0)
    return row


class SettingsDialog(QDialog):
    """Top-level settings dialog with Fluent components."""

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("设置")
        self.setMinimumSize(540, 480)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog { background-color: #1c1c1c; }
            QDialog QLabel { color: #d8d8d8; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        title = StrongBodyLabel("设置")
        title.setStyleSheet("font-size:17px;")
        root.addWidget(title)

        # Quality preset
        self.preset = ComboBox()
        self.preset.addItems(["超高清 30Mbps/60fps", "高清 12Mbps/60fps",
                              "标清 6Mbps/30fps", "流畅 3Mbps/30fps",
                              "自定义"])
        preset_map = {"ultra": 0, "high": 1, "medium": 2, "low": 3, "custom": 4}
        self.preset.setCurrentIndex(preset_map.get(cfg.quality_preset, 2))
        root.addLayout(_row("质量预设", self.preset))

        # Custom bitrate
        self.bitrate = DoubleSpinBox()
        self.bitrate.setRange(0.5, 100.0)
        self.bitrate.setSingleStep(0.5)
        self.bitrate.setValue(cfg.custom_bitrate_mbps)
        self.bitrate.setSuffix(" Mbps")
        root.addLayout(_row("自定义码率", self.bitrate))

        # Custom fps
        self.fps = SpinBox()
        self.fps.setRange(10, 120)
        self.fps.setValue(cfg.custom_fps)
        self.fps.setSuffix(" fps")
        root.addLayout(_row("自定义帧率", self.fps))

        # Toggles
        self.draw_mouse = SwitchButton()
        self.draw_mouse.setOnText("开"); self.draw_mouse.setOffText("关")
        self.draw_mouse.setChecked(cfg.draw_mouse)
        root.addLayout(_row("录入鼠标指针", self.draw_mouse, stretch_first=False))

        self.record_audio = SwitchButton()
        self.record_audio.setOnText("开"); self.record_audio.setOffText("关")
        self.record_audio.setChecked(cfg.record_audio)
        root.addLayout(_row("录入系统声音", self.record_audio, stretch_first=False))

        # Performance toggles + capability info
        caps = detect_capabilities()
        self.use_hw = SwitchButton()
        self.use_hw.setOnText("开"); self.use_hw.setOffText("关")
        self.use_hw.setChecked(cfg.use_hw_encoder)
        hw_name = {"h264_nvenc": "NVIDIA NVENC", "h264_qsv": "Intel QSV",
                   "h264_amf": "AMD AMF"}.get(caps.hw_encoder, "未检测到（用CPU软编码）")
        root.addLayout(_row(f"硬件编码 ({hw_name})", self.use_hw, stretch_first=False))
        if not caps.hw_encoder:
            self.use_hw.setEnabled(False)

        self.use_dxgi = SwitchButton()
        self.use_dxgi.setOnText("开"); self.use_dxgi.setOffText("关")
        self.use_dxgi.setChecked(cfg.use_dxgi_capture)
        dxgi_name = "可用（推荐，适合DX游戏）" if caps.has_ddagrab else "不可用（用GDI抓屏）"
        root.addLayout(_row(f"DXGI抓屏 ({dxgi_name})", self.use_dxgi, stretch_first=False))
        if not caps.has_ddagrab:
            self.use_dxgi.setEnabled(False)

        # Output dir
        out_row = QHBoxLayout()
        out_row.setSpacing(10)
        out_lbl = BodyLabel("输出目录"); out_lbl.setFixedWidth(_LABEL_W)
        out_row.addWidget(out_lbl)
        self.out_dir = LineEdit()
        self.out_dir.setText(cfg.output_dir)
        self.out_dir.setMinimumHeight(_FIELD_H)
        out_row.addWidget(self.out_dir, 1)
        browse = ToolButton(FIF.FOLDER)
        browse.setFixedSize(_FIELD_H, _FIELD_H)
        browse.setToolTip("浏览")
        browse.clicked.connect(self._pick_dir)
        out_row.addWidget(browse)
        root.addLayout(out_row)

        # Hotkey hint
        hint = CaptionLabel("快捷键：F9 开始/停止    F10 暂停")
        hint.setStyleSheet("color:#888; padding-top:2px;")
        root.addWidget(hint)

        root.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = PushButton("取消")
        cancel.setMinimumSize(96, 36)
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("保存")
        save.setMinimumSize(96, 36)
        save.clicked.connect(self.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        root.addLayout(btn_row)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def apply_to(self, cfg: AppConfig) -> AppConfig:
        preset_keys = ["ultra", "high", "medium", "low", "custom"]
        cfg.quality_preset = preset_keys[self.preset.currentIndex()]
        cfg.custom_bitrate_mbps = float(self.bitrate.value())
        cfg.custom_fps = int(self.fps.value())
        cfg.draw_mouse = self.draw_mouse.isChecked()
        cfg.record_audio = self.record_audio.isChecked()
        cfg.use_hw_encoder = self.use_hw.isChecked()
        cfg.use_dxgi_capture = self.use_dxgi.isChecked()
        d = self.out_dir.text().strip()
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
            cfg.output_dir = d
        return cfg
