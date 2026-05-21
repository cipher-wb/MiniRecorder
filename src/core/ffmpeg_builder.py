"""Build ffmpeg command lines for screen + system audio recording."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .paths import ffmpeg_path


@dataclass
class CaptureRegion:
    """Region in screen pixels. None for fullscreen."""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    fullscreen: bool = False

    def even(self) -> "CaptureRegion":
        """libx264 requires even dimensions when using yuv420p."""
        return CaptureRegion(self.x, self.y, self.w - (self.w % 2), self.h - (self.h % 2), self.fullscreen)


_CREATE_NO_WINDOW = 0x08000000


def list_dshow_audio_devices() -> list[str]:
    """Return names of available DirectShow audio capture devices."""
    try:
        proc = subprocess.run(
            [str(ffmpeg_path()), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    out = (proc.stderr or "") + (proc.stdout or "")
    devices: list[str] = []
    in_audio = False
    for line in out.splitlines():
        if "DirectShow audio devices" in line:
            in_audio = True
            continue
        if "DirectShow video devices" in line:
            in_audio = False
            continue
        if in_audio and '"' in line:
            start = line.find('"')
            end = line.find('"', start + 1)
            if end > start:
                devices.append(line[start + 1:end])
    return devices


_audio_device_cache: Optional[str] = None
_audio_device_probed: bool = False


def pick_audio_device(force_refresh: bool = False) -> Optional[str]:
    """Pick best-effort system-audio capture device. Cached after first probe."""
    global _audio_device_cache, _audio_device_probed
    if _audio_device_probed and not force_refresh:
        return _audio_device_cache
    devices = list_dshow_audio_devices()
    priorities = ["virtual-audio-capturer", "Stereo Mix", "立体声混音", "What U Hear"]
    lowered = {d.lower(): d for d in devices}
    picked: Optional[str] = None
    for p in priorities:
        for k, original in lowered.items():
            if p.lower() in k:
                picked = original
                break
        if picked:
            break
    _audio_device_cache = picked
    _audio_device_probed = True
    return picked


def build_command(
    region: CaptureRegion,
    fps: int,
    bitrate_mbps: float,
    draw_mouse: bool,
    output_path: Path,
    audio_device: Optional[str],
) -> list[str]:
    ff = str(ffmpeg_path())
    cmd: list[str] = [
        ff, "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "gdigrab",
        "-framerate", str(fps),
        "-draw_mouse", "1" if draw_mouse else "0",
    ]
    if not region.fullscreen:
        r = region.even()
        cmd += [
            "-offset_x", str(r.x),
            "-offset_y", str(r.y),
            "-video_size", f"{r.w}x{r.h}",
        ]
    cmd += ["-i", "desktop"]

    if audio_device:
        cmd += ["-f", "dshow", "-i", f"audio={audio_device}"]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-b:v", f"{bitrate_mbps}M",
        "-maxrate", f"{bitrate_mbps * 1.5}M",
        "-bufsize", f"{bitrate_mbps * 2}M",
    ]
    if audio_device:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    return cmd
