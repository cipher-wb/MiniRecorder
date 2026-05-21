# PyInstaller spec — produce a single-file MiniRecorder.exe with bundled ffmpeg.
# Build:  venv\Scripts\pyinstaller.exe build.spec
# Output: dist\MiniRecorder.exe
from pathlib import Path

ROOT = Path('.').resolve()

a = Analysis(
    [str(ROOT / 'launcher.py')],
    pathex=[str(ROOT)],
    binaries=[(str(ROOT / 'ffmpeg' / 'ffmpeg.exe'), 'ffmpeg')],
    datas=[(str(ROOT / 'src' / 'assets'), 'assets')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MiniRecorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / 'src' / 'assets' / 'icons' / 'app.ico') if (ROOT / 'src' / 'assets' / 'icons' / 'app.ico').exists() else None,
)
