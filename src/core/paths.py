"""Resource path resolution (works in dev and PyInstaller --onefile)."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Optional


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


BASE_DIR = _base_dir()


def resource(*parts: str) -> Path:
    return BASE_DIR.joinpath(*parts)


def ffmpeg_path() -> Path:
    p = resource("ffmpeg", "ffmpeg.exe")
    if p.exists():
        return p
    from shutil import which
    found = which("ffmpeg")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "ffmpeg.exe not found. Expected bundled at ffmpeg/ffmpeg.exe or on PATH."
    )


def ffprobe_path() -> Optional[Path]:
    """Best-effort locate ffprobe next to bundled ffmpeg, or on PATH. May be None."""
    from shutil import which
    cand = resource("ffmpeg", "ffprobe.exe")
    if cand.exists():
        return cand
    # Same folder as resolved ffmpeg
    try:
        sibling = ffmpeg_path().with_name("ffprobe.exe")
        if sibling.exists():
            return sibling
    except FileNotFoundError:
        pass
    found = which("ffprobe")
    return Path(found) if found else None


def assets_dir() -> Path:
    return resource("src", "assets") if not getattr(sys, "frozen", False) else resource("assets")


def config_dir() -> Path:
    d = Path(os.environ.get("APPDATA", str(Path.home()))) / "MiniRecorder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_output_dir() -> Path:
    d = Path.home() / "Videos" / "MiniRecorder"
    d.mkdir(parents=True, exist_ok=True)
    return d
