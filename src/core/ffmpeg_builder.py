"""Build ffmpeg command lines for screen + system audio recording.

Capability auto-detection:
- Hardware H.264 encoder: probes NVENC / QSV / AMF; falls back to libx264 (CPU).
- Capture backend: prefers DXGI Desktop Duplication (`ddagrab`, ~10x faster than
  gdigrab and able to grab DirectX exclusive-fullscreen) when the region fits a
  single monitor; falls back to gdigrab otherwise (multi-monitor span, etc).
"""
from __future__ import annotations
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .paths import ffmpeg_path

_CREATE_NO_WINDOW = 0x08000000


@dataclass
class CaptureRegion:
    """Region in screen pixels. `fullscreen=True` = entire virtual desktop."""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    fullscreen: bool = False

    def even(self) -> "CaptureRegion":
        return CaptureRegion(self.x, self.y, self.w - (self.w % 2),
                             self.h - (self.h % 2), self.fullscreen)


@dataclass
class CaptureCapabilities:
    hw_encoder: str = ""           # "h264_nvenc" | "h264_qsv" | "h264_amf" | "" (none)
    has_ddagrab: bool = False
    audio_device: Optional[str] = None


_caps_cache: Optional[CaptureCapabilities] = None
_caps_lock = threading.Lock()


def list_dshow_audio_devices() -> list[str]:
    try:
        proc = subprocess.run(
            [str(ffmpeg_path()), "-hide_banner", "-list_devices", "true",
             "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    out = (proc.stderr or "") + (proc.stdout or "")
    devices: list[str] = []
    in_audio = False
    for line in out.splitlines():
        if "DirectShow audio devices" in line:
            in_audio = True; continue
        if "DirectShow video devices" in line:
            in_audio = False; continue
        if in_audio and '"' in line:
            start = line.find('"')
            end = line.find('"', start + 1)
            if end > start:
                devices.append(line[start + 1:end])
    return devices


def pick_audio_device() -> Optional[str]:
    devices = list_dshow_audio_devices()
    priorities = ["virtual-audio-capturer", "Stereo Mix", "立体声混音", "What U Hear"]
    lowered = {d.lower(): d for d in devices}
    for p in priorities:
        for k, original in lowered.items():
            if p.lower() in k:
                return original
    return None


def _probe_encoder(name: str) -> bool:
    """Try a tiny encode with the encoder; success means hardware is available."""
    try:
        r = subprocess.run(
            [str(ffmpeg_path()), "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=size=64x64:rate=1:duration=0.1",
             "-c:v", name, "-f", "null", "-"],
            capture_output=True, timeout=12,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def _probe_ddagrab() -> bool:
    try:
        r = subprocess.run(
            [str(ffmpeg_path()), "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "ddagrab=video_size=64x64:framerate=1",
             "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_capabilities(force: bool = False) -> CaptureCapabilities:
    """Probe ffmpeg + system for hardware encoders, ddagrab, audio device. Cached."""
    global _caps_cache
    with _caps_lock:
        if _caps_cache and not force:
            return _caps_cache
        hw = ""
        for cand in ("h264_nvenc", "h264_qsv", "h264_amf"):
            if _probe_encoder(cand):
                hw = cand
                break
        caps = CaptureCapabilities(
            hw_encoder=hw,
            has_ddagrab=_probe_ddagrab() if sys.platform == "win32" else False,
            audio_device=pick_audio_device(),
        )
        _caps_cache = caps
        return caps


def _which_monitor(rect: CaptureRegion, screens: Sequence[tuple[int, int, int, int]]) -> int:
    """Return monitor index that fully contains the rect, or -1 if it spans / no fit."""
    if rect.fullscreen:
        return -1
    cx, cy = rect.x + rect.w // 2, rect.y + rect.h // 2
    fits = -1
    for i, (sx, sy, sw, sh) in enumerate(screens):
        if sx <= cx < sx + sw and sy <= cy < sy + sh:
            # Make sure the whole rect is inside this monitor
            if (rect.x >= sx and rect.y >= sy and
                rect.x + rect.w <= sx + sw and
                rect.y + rect.h <= sy + sh):
                fits = i
            break
    return fits


def build_command(
    region: CaptureRegion,
    fps: int,
    bitrate_mbps: float,
    draw_mouse: bool,
    output_path: Path,
    audio_device: Optional[str],
    capabilities: Optional[CaptureCapabilities] = None,
    screens: Sequence[tuple[int, int, int, int]] = (),
    use_hw_encoder: bool = True,
    use_dxgi_capture: bool = True,
) -> list[str]:
    """Build the ffmpeg argv. Auto-selects hw encoder + capture backend based on caps."""
    caps = capabilities or detect_capabilities()
    ff = str(ffmpeg_path())
    cmd: list[str] = [ff, "-hide_banner", "-loglevel", "warning", "-y"]

    # ---- Capture input ----
    monitor_idx = _which_monitor(region, screens) if screens else -1
    can_use_dda = (use_dxgi_capture and caps.has_ddagrab and
                   (region.fullscreen and len(screens) == 1) or
                   (not region.fullscreen and monitor_idx >= 0))
    # NOTE: ddagrab can't span multiple monitors. fullscreen=True with multiple
    # screens (= "all screens" virtual desktop) must fall back to gdigrab.

    if can_use_dda and not region.fullscreen:
        # Region within monitor N: convert virtual-desktop coords to monitor-local.
        sx, sy, sw, sh = screens[monitor_idx]
        r = region.even()
        local_x = r.x - sx
        local_y = r.y - sy
        opts = [
            f"output_idx={monitor_idx}",
            f"framerate={fps}",
            f"draw_mouse={1 if draw_mouse else 0}",
            f"video_size={r.w}x{r.h}",
            f"offset_x={local_x}",
            f"offset_y={local_y}",
        ]
        # ddagrab outputs D3D11 frames — hwdownload to CPU + bgra for libx264/NVENC compat
        cmd += ["-f", "lavfi", "-i", f"ddagrab={':'.join(opts)},hwdownload,format=bgra"]
    elif can_use_dda and region.fullscreen and len(screens) == 1:
        opts = [
            f"output_idx=0",
            f"framerate={fps}",
            f"draw_mouse={1 if draw_mouse else 0}",
        ]
        cmd += ["-f", "lavfi", "-i", f"ddagrab={':'.join(opts)},hwdownload,format=bgra"]
    else:
        # gdigrab fallback (multi-monitor span, all-screens fullscreen, or ddagrab unavailable)
        cmd += ["-f", "gdigrab", "-framerate", str(fps),
                "-draw_mouse", "1" if draw_mouse else "0"]
        if not region.fullscreen:
            r = region.even()
            cmd += ["-offset_x", str(r.x), "-offset_y", str(r.y),
                    "-video_size", f"{r.w}x{r.h}"]
        cmd += ["-i", "desktop"]

    # ---- Audio input ----
    if audio_device:
        cmd += ["-f", "dshow", "-i", f"audio={audio_device}"]

    # ---- Encoder ----
    codec = caps.hw_encoder if (use_hw_encoder and caps.hw_encoder) else "libx264"
    cmd += ["-c:v", codec]
    if codec == "libx264":
        cmd += ["-preset", "veryfast", "-tune", "zerolatency"]
    elif codec == "h264_nvenc":
        cmd += ["-preset", "p5", "-tune", "hq", "-rc", "vbr"]
    elif codec == "h264_qsv":
        cmd += ["-preset", "medium"]
    elif codec == "h264_amf":
        cmd += ["-quality", "balanced", "-usage", "transcoding"]

    cmd += ["-pix_fmt", "yuv420p",
            "-b:v", f"{bitrate_mbps}M",
            "-maxrate", f"{bitrate_mbps * 1.5}M",
            "-bufsize", f"{bitrate_mbps * 2}M"]
    if audio_device:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    return cmd
