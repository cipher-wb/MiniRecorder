# 轻录 (MiniRecorder)

Windows 屏幕录制小工具。PySide6 + qfluentwidgets 界面，底层用打包进来的 ffmpeg 抓屏。
入口 `src/main.py`（开发期：`python run.py`）。

## ⚠️ 构建与发布：两个产物必须同步

本项目对外有**两个分发产物，内容必须始终一致**。**任何代码改动后，都要把这两个一起重新构建**，
否则会出现「绿色版是新代码、安装包还是旧代码」（或反之）的不一致，这是禁止的：

1. **绿色免安装版** → `dist/MiniRecorder/`
   - onedir 结构：`MiniRecorder.exe` + `_internal/`，**整个文件夹是一个整体，缺一不可**（单独拷 exe 会无法启动）。
   - 构建命令：`venv\Scripts\python.exe -m PyInstaller build.spec --noconfirm --clean`
   - ⚠️ 本机的 `venv\Scripts\pyinstaller.exe` 启动器已损坏（直接运行会静默退出码 1），**必须用上面的 `python -m PyInstaller` 形式**。

2. **安装包** → `installer_dist/轻录_Setup_<版本>.exe`
   - Inno Setup 把上面的 `dist/MiniRecorder/*` 整包压缩而成（见 `installer.iss` 第 46 行）。
   - 构建命令：`& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss`

**发布顺序不能乱（安装包依赖绿色版的产物）：**

1. 改代码
2. 重建绿色版：`python -m PyInstaller build.spec --noconfirm --clean` → 生成 `dist/MiniRecorder/`
3. 重建安装包：`ISCC.exe installer.iss` → 读取第 2 步的输出，生成 `installer_dist/轻录_Setup_*.exe`
4. 两个产物都更新后，再对外分发

> - 改版本号：编辑 `installer.iss` 顶部的 `#define AppVersion`，安装包文件名会随之变化。
> - **只重建其中一个 = 两边不一致，禁止。** 要么两个都重建，要么都不动。

## 关键路径与约定

- 资源路径解析：`src/core/paths.py`（冻结后走 `sys._MEIPASS`，即 `_internal/`；开发期走源码目录）。
- 配置文件：`%APPDATA%\MiniRecorder\config.json`（不在程序目录，所以绿色版整包搬动不影响配置）。
- 录像默认输出：`~/Videos/MiniRecorder`。
- ffmpeg：打包在 `_internal/ffmpeg/ffmpeg.exe`，源码里在 `ffmpeg/ffmpeg.exe`。
- UI 设计稿：`轻录-prototype/`（Claude Code 终端面板风格，HTML/JSX 高保真原型 + 设计 token）。
