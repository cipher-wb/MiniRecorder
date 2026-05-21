"""Settings dialog: custom bitrate/fps, output dir, mouse toggle, audio toggle."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSpinBox,
    QCheckBox, QPushButton, QFileDialog, QLineEdit, QComboBox, QFrame,
)

from ..core.config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(440)
        self.cfg = cfg

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 20)

        # 质量预设
        row = QHBoxLayout()
        row.addWidget(QLabel("质量预设"))
        self.preset = QComboBox()
        self.preset.addItems(["high", "medium", "low", "custom"])
        self.preset.setCurrentText(cfg.quality_preset)
        row.addWidget(self.preset, 1)
        root.addLayout(row)

        # 自定义码率
        row = QHBoxLayout()
        row.addWidget(QLabel("码率 (Mbps)"))
        self.bitrate = QDoubleSpinBox()
        self.bitrate.setRange(0.5, 100.0)
        self.bitrate.setSingleStep(0.5)
        self.bitrate.setValue(cfg.custom_bitrate_mbps)
        row.addWidget(self.bitrate, 1)
        root.addLayout(row)

        # 自定义帧率
        row = QHBoxLayout()
        row.addWidget(QLabel("帧率"))
        self.fps = QSpinBox()
        self.fps.setRange(10, 120)
        self.fps.setValue(cfg.custom_fps)
        row.addWidget(self.fps, 1)
        root.addLayout(row)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        # 选项
        self.draw_mouse = QCheckBox("录入鼠标指针")
        self.draw_mouse.setChecked(cfg.draw_mouse)
        root.addWidget(self.draw_mouse)

        self.record_audio = QCheckBox("录入系统声音")
        self.record_audio.setChecked(cfg.record_audio)
        root.addWidget(self.record_audio)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        # 输出目录
        row = QHBoxLayout()
        row.addWidget(QLabel("输出目录"))
        self.out_dir = QLineEdit(cfg.output_dir)
        row.addWidget(self.out_dir, 1)
        btn = QPushButton("浏览…")
        btn.clicked.connect(self._pick_dir)
        row.addWidget(btn)
        root.addLayout(row)

        # 快捷键展示
        row = QHBoxLayout()
        row.addWidget(QLabel("快捷键"))
        row.addWidget(QLabel(f"F9 开始/停止   F10 暂停"))
        row.addStretch(1)
        root.addLayout(row)

        root.addStretch(1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton("确定")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(ok)
        btn_row.addWidget(cancel)
        root.addLayout(btn_row)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def apply_to(self, cfg: AppConfig) -> AppConfig:
        cfg.quality_preset = self.preset.currentText()
        cfg.custom_bitrate_mbps = float(self.bitrate.value())
        cfg.custom_fps = int(self.fps.value())
        cfg.draw_mouse = self.draw_mouse.isChecked()
        cfg.record_audio = self.record_audio.isChecked()
        d = self.out_dir.text().strip()
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
            cfg.output_dir = d
        return cfg
