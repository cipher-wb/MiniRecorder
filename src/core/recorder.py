"""Recorder: manages the ffmpeg subprocess lifecycle (start/pause/resume/stop)."""
from __future__ import annotations
import ctypes
import datetime as _dt
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import ffmpeg_builder as fb
from .config import AppConfig

_ntdll = ctypes.windll.ntdll
_kernel32 = ctypes.windll.kernel32
PROCESS_SUSPEND_RESUME = 0x0800


class RecorderState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"


class Recorder:
    def __init__(self, on_state_change: Optional[Callable[[RecorderState], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self._proc: Optional[subprocess.Popen] = None
        self._state: RecorderState = RecorderState.IDLE
        self._on_state_change = on_state_change
        self._on_error = on_error
        self._output_path: Optional[Path] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_buf: list[str] = []

    @property
    def state(self) -> RecorderState:
        return self._state

    @property
    def output_path(self) -> Optional[Path]:
        return self._output_path

    def _set_state(self, s: RecorderState) -> None:
        self._state = s
        if self._on_state_change:
            self._on_state_change(s)

    def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        try:
            for line in self._proc.stderr:
                if line:
                    self._stderr_buf.append(line.decode("utf-8", errors="replace"))
                    if len(self._stderr_buf) > 200:
                        self._stderr_buf.pop(0)
        except Exception:
            pass

    def start(self, cfg: AppConfig, region: fb.CaptureRegion,
              screens: list[tuple[int, int, int, int]] | None = None) -> Path:
        if self._state is not RecorderState.IDLE:
            raise RuntimeError("Recorder already active")

        bitrate, fps = cfg.preset_params()
        out_dir = Path(cfg.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = out_dir / f"record_{ts}.mp4"

        caps = fb.detect_capabilities()
        audio_device = caps.audio_device if cfg.record_audio else None

        cmd = fb.build_command(
            region=region,
            fps=fps,
            bitrate_mbps=bitrate,
            draw_mouse=cfg.draw_mouse,
            output_path=output,
            audio_device=audio_device,
            capabilities=caps,
            screens=tuple(screens or ()),
            use_hw_encoder=cfg.use_hw_encoder,
            use_dxgi_capture=cfg.use_dxgi_capture,
        )

        creationflags = 0x08000000  # CREATE_NO_WINDOW
        self._stderr_buf = []
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        self._output_path = output
        self._set_state(RecorderState.RECORDING)
        return output

    def pause(self) -> None:
        if self._state is not RecorderState.RECORDING or not self._proc:
            return
        h = _kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, self._proc.pid)
        if h:
            try:
                _ntdll.NtSuspendProcess(h)
            finally:
                _kernel32.CloseHandle(h)
            self._set_state(RecorderState.PAUSED)

    def resume(self) -> None:
        if self._state is not RecorderState.PAUSED or not self._proc:
            return
        h = _kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, self._proc.pid)
        if h:
            try:
                _ntdll.NtResumeProcess(h)
            finally:
                _kernel32.CloseHandle(h)
            self._set_state(RecorderState.RECORDING)

    def stop(self) -> Optional[Path]:
        if self._state is RecorderState.IDLE or not self._proc:
            return None
        if self._state is RecorderState.PAUSED:
            self.resume()
        try:
            if self._proc.stdin:
                try:
                    self._proc.stdin.write(b"q")
                    self._proc.stdin.flush()
                except Exception:
                    pass
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        finally:
            rc = self._proc.returncode
            self._proc = None
            self._set_state(RecorderState.IDLE)
            if rc not in (0, None) and self._on_error:
                self._on_error("ffmpeg exited with code %s\n%s" % (rc, "".join(self._stderr_buf[-30:])))
        return self._output_path

    def stderr_tail(self) -> str:
        return "".join(self._stderr_buf[-40:])
