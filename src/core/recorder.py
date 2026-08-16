"""Recorder: manages the ffmpeg subprocess lifecycle (start/pause/resume/stop).

Stop path is designed so long recordings do not lose the MP4 moov atom:
- write to a temporary ``*.tmp.mp4`` file
- never apply +faststart during live capture
- wait long enough for graceful 'q' finalize (timeout scales with file size)
- optional crash-safe fragmented MP4 remuxed to progressive after stop
- validate that the finished file contains a moov atom
"""
from __future__ import annotations
import ctypes
import datetime as _dt
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import ffmpeg_builder as fb
from .config import AppConfig

_ntdll = ctypes.windll.ntdll
_kernel32 = ctypes.windll.kernel32
PROCESS_SUSPEND_RESUME = 0x0800
_CREATE_NO_WINDOW = 0x08000000

# Graceful stop: base wait + size-based extra, hard cap
_STOP_BASE_SEC = 45.0
_STOP_SEC_PER_GB = 25.0
_STOP_MAX_SEC = 300.0
_REMUX_MAX_SEC = 600.0


class RecorderState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    FINALIZING = "finalizing"  # stop/remux/validate in progress


@dataclass
class StopResult:
    """Outcome of a stop() call."""
    path: Optional[Path] = None
    ok: bool = False
    message: str = ""
    bytes_written: int = 0


def mp4_has_moov(path: Path) -> bool:
    """Return True if an MP4-like file has a top-level or nested 'moov' box.

    Pure Python — does not require ffprobe. Scans top-level boxes and, for
    fragmented files, also accepts 'moof' (moov may be empty_moov at start).
    """
    try:
        size = path.stat().st_size
        if size < 32:
            return False
        with path.open("rb") as f:
            # Quick full-file scan for moov/moof tags in first 8MB + last 8MB
            # (covers empty_moov at head and classic moov-at-end).
            head_n = min(size, 8 * 1024 * 1024)
            head = f.read(head_n)
            if b"moov" in head or b"moof" in head:
                # verify it looks like a box type (4 bytes before could be size)
                if _find_box_type(head, b"moov") or _find_box_type(head, b"moof"):
                    return True
            if size > head_n:
                f.seek(max(0, size - 8 * 1024 * 1024))
                tail = f.read()
                if _find_box_type(tail, b"moov") or _find_box_type(tail, b"moof"):
                    return True
            # Sequential top-level walk (authoritative)
            return _walk_top_level_has_moov(path, size)
    except OSError:
        return False


def _find_box_type(buf: bytes, name: bytes) -> bool:
    idx = 0
    while True:
        i = buf.find(name, idx)
        if i < 0:
            return False
        # box type is at offset+4 of a box header; size is 4 bytes before type
        if i >= 4:
            return True
        idx = i + 1


def _walk_top_level_has_moov(path: Path, size: int) -> bool:
    with path.open("rb") as f:
        pos = 0
        for _ in range(64):
            if pos + 8 > size:
                break
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            box_size = struct.unpack(">I", hdr[:4])[0]
            box_type = hdr[4:8]
            if box_type in (b"moov", b"moof"):
                return True
            if box_size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    break
                box_size = struct.unpack(">Q", ext)[0]
                next_pos = pos + box_size
            elif box_size == 0:
                # extends to EOF — no moov after this
                break
            else:
                next_pos = pos + box_size
            if next_pos <= pos or next_pos > size:
                break
            pos = next_pos
    return False


def _stop_timeout_sec(part_path: Optional[Path]) -> float:
    gb = 0.0
    if part_path and part_path.exists():
        try:
            gb = part_path.stat().st_size / (1024 ** 3)
        except OSError:
            pass
    return min(_STOP_MAX_SEC, _STOP_BASE_SEC + gb * _STOP_SEC_PER_GB)


class Recorder:
    def __init__(
        self,
        on_state_change: Optional[Callable[[RecorderState], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self._proc: Optional[subprocess.Popen] = None
        self._state: RecorderState = RecorderState.IDLE
        self._on_state_change = on_state_change
        self._on_error = on_error
        self._on_status = on_status
        self._output_path: Optional[Path] = None   # final .mp4 path
        self._part_path: Optional[Path] = None     # temp .tmp.mp4 while recording
        self._crash_safe: bool = True
        self._apply_faststart: bool = True
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_buf: list[str] = []
        self._stop_lock = threading.Lock()

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

    def _status(self, msg: str) -> None:
        if self._on_status:
            self._on_status(msg)

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
        # Sanitize prefix — strip filesystem-unsafe chars and empty fallback
        raw = (cfg.filename_prefix or "record").strip()
        safe = "".join(c for c in raw if c not in '<>:"/\\|?*\x00') or "record"
        final = out_dir / f"{safe}_{ts}.mp4"
        # Keep a real .mp4 suffix so ffmpeg can sniff the muxer; force -f mp4 as well.
        part = out_dir / f"{safe}_{ts}.tmp.mp4"

        # Clean stale part if any
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass

        caps = fb.detect_capabilities()
        audio_device = caps.audio_device if cfg.record_audio else None
        self._crash_safe = bool(getattr(cfg, "crash_safe_recording", True))
        self._apply_faststart = bool(getattr(cfg, "apply_faststart_after", True))

        cmd = fb.build_command(
            region=region,
            fps=fps,
            bitrate_mbps=bitrate,
            draw_mouse=cfg.draw_mouse,
            output_path=part,  # write temp until finalize succeeds
            audio_device=audio_device,
            capabilities=caps,
            screens=tuple(screens or ()),
            use_hw_encoder=cfg.use_hw_encoder,
            use_dxgi_capture=cfg.use_dxgi_capture,
            crash_safe=self._crash_safe,
        )

        creationflags = _CREATE_NO_WINDOW
        self._stderr_buf = []
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        self._output_path = final
        self._part_path = part
        self._set_state(RecorderState.RECORDING)
        return final

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

    def stop(self) -> StopResult:
        """Gracefully stop ffmpeg, remux if needed, validate, rename to final path.

        Safe to call from a worker thread (UI should dispatch status via signals).
        """
        with self._stop_lock:
            return self._stop_locked()

    def _stop_locked(self) -> StopResult:
        if self._state is RecorderState.IDLE or not self._proc:
            # Already idle — return last path if it looks valid
            if self._output_path and self._output_path.exists() and mp4_has_moov(self._output_path):
                return StopResult(path=self._output_path, ok=True,
                                  message="already stopped",
                                  bytes_written=self._output_path.stat().st_size)
            return StopResult(ok=False, message="not recording")

        if self._state is RecorderState.PAUSED:
            self.resume()

        self._set_state(RecorderState.FINALIZING)
        self._status("正在结束录制，请勿关闭…")

        part = self._part_path
        final = self._output_path
        proc = self._proc
        timeout = _stop_timeout_sec(part)

        # 1) Ask ffmpeg to finalize (writes moov / closes fragments)
        try:
            if proc.stdin:
                try:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                except Exception:
                    pass

            deadline = time.monotonic() + timeout
            rc = None
            while time.monotonic() < deadline:
                rc = proc.poll()
                if rc is not None:
                    break
                # keep UI informed every ~2s
                remaining = int(deadline - time.monotonic())
                self._status(f"正在封装视频…（最多还可等 {remaining}s）")
                time.sleep(0.4)
            else:
                # Still running: escalate gently
                self._status("封装较慢，正在尝试结束编码进程…")
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=15)
                    rc = proc.returncode
                except subprocess.TimeoutExpired:
                    self._status("强制结束编码进程…")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    rc = proc.returncode
        finally:
            self._proc = None

        # 2) Finalize file on disk
        result = self._finalize_file(part, final, ffmpeg_rc=rc)

        self._part_path = None
        self._set_state(RecorderState.IDLE)

        if not result.ok and self._on_error:
            self._on_error(result.message)
        return result

    def _finalize_file(
        self,
        part: Optional[Path],
        final: Optional[Path],
        ffmpeg_rc: Optional[int],
    ) -> StopResult:
        if not part or not final:
            return StopResult(ok=False, message="内部错误：缺少输出路径")

        if not part.exists():
            tail = "".join(self._stderr_buf[-20:])
            return StopResult(
                ok=False,
                message=f"录制文件未生成（ffmpeg code={ffmpeg_rc}）\n{tail}",
            )

        size = part.stat().st_size
        if size < 1024:
            try:
                part.unlink()
            except OSError:
                pass
            return StopResult(
                ok=False,
                message="录制文件过小，可能未写入有效数据",
                bytes_written=size,
            )

        # Crash-safe path: remux fragmented → progressive MP4
        if self._crash_safe:
            self._status("正在转换为标准 MP4…")
            tmp_out = final.with_suffix(".mp4.tmp")
            if tmp_out.exists():
                try:
                    tmp_out.unlink()
                except OSError:
                    pass
            ok_remux, remux_msg = self._remux(part, tmp_out, faststart=self._apply_faststart)
            if ok_remux and tmp_out.exists() and mp4_has_moov(tmp_out):
                try:
                    if final.exists():
                        final.unlink()
                except OSError:
                    pass
                try:
                    tmp_out.replace(final)
                except OSError:
                    # fallback copy
                    import shutil
                    shutil.copy2(tmp_out, final)
                    try:
                        tmp_out.unlink()
                    except OSError:
                        pass
                try:
                    part.unlink()
                except OSError:
                    pass
                return StopResult(
                    path=final,
                    ok=True,
                    message="ok",
                    bytes_written=final.stat().st_size,
                )
            # Remux failed — fall through and try to salvage the .part
            self._status(f"标准封装失败，尝试保留原始片段…（{remux_msg}）")

        # Progressive (or remux failed): require moov on the part file
        if not mp4_has_moov(part):
            # Keep the .part so the user can try external repair tools
            return StopResult(
                path=part,
                ok=False,
                message=(
                    f"文件可能已损坏（缺少 moov，ffmpeg code={ffmpeg_rc}）。\n"
                    f"临时文件已保留：{part.name}\n"
                    "可用 untrunc 等工具尝试修复，或检查是否在封装完成前强制结束了进程。"
                ),
                bytes_written=size,
            )

        # Optional faststart for progressive recordings (post-stop only)
        if self._apply_faststart and not self._crash_safe:
            self._status("正在优化 MP4 以便拖动进度条…")
            tmp_out = final.with_suffix(".mp4.tmp")
            ok_remux, _ = self._remux(part, tmp_out, faststart=True)
            if ok_remux and tmp_out.exists() and mp4_has_moov(tmp_out):
                try:
                    if final.exists():
                        final.unlink()
                except OSError:
                    pass
                tmp_out.replace(final)
                try:
                    part.unlink()
                except OSError:
                    pass
                return StopResult(
                    path=final, ok=True, message="ok",
                    bytes_written=final.stat().st_size,
                )

        # Plain rename part → final
        try:
            if final.exists():
                final.unlink()
        except OSError:
            pass
        try:
            part.replace(final)
        except OSError as e:
            return StopResult(
                path=part, ok=False,
                message=f"重命名失败：{e}（文件仍在 {part.name}）",
                bytes_written=size,
            )

        if not mp4_has_moov(final):
            return StopResult(
                path=final, ok=False,
                message="封装后校验失败：文件仍缺少 moov",
                bytes_written=final.stat().st_size,
            )

        return StopResult(
            path=final, ok=True, message="ok",
            bytes_written=final.stat().st_size,
        )

    def _remux(self, src: Path, dst: Path, faststart: bool) -> tuple[bool, str]:
        try:
            cmd = fb.build_remux_command(src, dst, faststart=faststart)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_REMUX_MAX_SEC,
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
                return False, f"remux exit {proc.returncode}: {err}"
            return True, "ok"
        except subprocess.TimeoutExpired:
            return False, "remux timeout"
        except Exception as e:
            return False, str(e)

    def stderr_tail(self) -> str:
        return "".join(self._stderr_buf[-40:])
