"""Persistent JSON config."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from .paths import config_dir, default_output_dir

CONFIG_FILE = config_dir() / "config.json"


@dataclass
class AppConfig:
    quality_preset: str = "medium"          # high | medium | low | custom
    custom_bitrate_mbps: float = 6.0
    custom_fps: int = 30
    draw_mouse: bool = True
    record_audio: bool = True
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    region_mode: str = "fullscreen"         # fullscreen | window | custom
    last_region: Optional[list] = None      # [x, y, w, h]
    hotkey_toggle: str = "f9"
    hotkey_pause: str = "f10"
    theme: str = "default"

    def preset_params(self) -> tuple[float, int]:
        """Return (bitrate_mbps, fps) for current preset."""
        table = {
            "high": (10.0, 60),
            "medium": (6.0, 30),
            "low": (3.0, 30),
        }
        if self.quality_preset in table:
            return table[self.quality_preset]
        return (self.custom_bitrate_mbps, self.custom_fps)


def load() -> AppConfig:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return AppConfig(**{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__})
        except Exception:
            pass
    return AppConfig()


def save(cfg: AppConfig) -> None:
    CONFIG_FILE.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
