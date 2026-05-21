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
    hiddenimports=['qfluentwidgets'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'PIL', 'pandas', 'scipy',
        'PyQt5', 'PyQt6', 'PySide2',
        # Qt modules we don't use — saves ~15-25MB
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DAnimation',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtHelp',
        'PySide6.QtPositioning', 'PySide6.QtLocation',
        'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSerialPort',
        'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors',
        'PySide6.QtTextToSpeech', 'PySide6.QtQuick', 'PySide6.QtQml',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

# --onedir layout: small exe stub + collected files. Lets Inno Setup do one
# solid LZMA pass instead of (PyInstaller LZMA) + (Inno LZMA) double-compression.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MiniRecorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / 'src' / 'assets' / 'icons' / 'app.ico') if (ROOT / 'src' / 'assets' / 'icons' / 'app.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MiniRecorder',
)
