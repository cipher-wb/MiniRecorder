# MiniRecorder — 极简录屏

Bandicam 风格的轻量录屏工具，给游戏开发团队录素材用。

## 功能

- **三种录制模式**：全屏 / 窗口 / 自定义区域（自定义区域可拖拽、可 resize）
- **质量预设**：高 (10Mbps/60fps) / 中 (6Mbps/30fps) / 低 (3Mbps/30fps) + 自定义
- **系统声音录制**（需安装 virtual-audio-capturer，见下）
- **全局快捷键**：F9 开始/停止、F10 暂停/继续
- **鼠标指针**可选录入
- **系统托盘**最小化运行
- **记忆**上次输出目录、区域、预设

## 团队使用（SVN）

只需把 `dist\MiniRecorder.exe` 拉下来双击运行——无需安装 Python / FFmpeg / .NET。

## 开发环境

需要 Windows + Python 3.10+（推荐 3.12，但 3.14 也可，PySide6 用 abi3 wheel 兼容）。

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe run.py
```

### 准备 FFmpeg

仓库不带 `ffmpeg.exe`（GitHub 单文件上限 100MB，FFmpeg full build 213MB）。需要手动放一份：

1. 到 https://www.gyan.dev/ffmpeg/builds/ 下载 **release essentials build**（~80MB）或 full build
2. 解压后把 `bin\ffmpeg.exe` 复制到本仓库的 `ffmpeg\` 目录下

打包时 `build.spec` 会自动把它嵌进 exe。

## 打包单 exe

```powershell
.\venv\Scripts\pyinstaller.exe build.spec
# 输出：dist\MiniRecorder.exe
```

## 制作 Windows 安装包

需要先用 winget 安装 Inno Setup：

```powershell
winget install --id JRSoftware.InnoSetup
```

然后编译安装包：

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
# 输出：installer_dist\轻录_Setup_1.0.0.exe
```

`ChineseSimplified.isl` 是中文界面语言包，已附在仓库内（Inno Setup 官方不默认带）。

安装包会引导用户安装到 `Program Files\MiniRecorder`，生成开始菜单和（可选）桌面快捷方式，附带卸载器。

注意：`ffmpeg\ffmpeg.exe` 必须存在于工程根目录的 `ffmpeg\` 下，会被打进 exe。当前内置的是 Gyan 的 full build（约 213MB）；如果要减小 exe 体积，可以替换为 [essentials build](https://www.gyan.dev/ffmpeg/builds/)（约 80MB），功能（gdigrab + dshow + libx264 + aac）完全够用。

## 系统声音录制

FFmpeg 在 Windows 上录系统声音需要一个虚拟音频设备。推荐两种：

1. **Stereo Mix（立体声混音）** — Windows 自带，在「声音设置 → 录制」里启用即可。
2. **screen-capture-recorder-virtual-audio-capturer** — 第三方虚拟驱动，GitHub 上能下到 MSI 安装包；适用于声卡不支持立体声混音的笔记本。

启动后程序会自动检测可用的虚拟音频设备；如果一个都没有，会自动录无声视频。

## 皮肤化

UI 主题完全由 `src/assets/theme.qss` 控制，图标在 `src/assets/icons/` 里。换主题不需要改代码——直接编辑 QSS 和替换图片即可（比如做一个"猫猫主题"）。

## 工程结构

```
src/
  main.py              # 入口
  core/
    recorder.py        # FFmpeg 子进程生命周期 + NtSuspendProcess 暂停
    ffmpeg_builder.py  # 命令行组装、设备枚举
    config.py          # JSON 配置持久化
    hotkey.py          # 全局快捷键
    paths.py           # 资源路径解析（兼容 PyInstaller _MEIPASS）
  ui/
    main_window.py     # 主控制面板
    region_overlay.py  # 可拖拽边框
    window_picker.py   # 顶层窗口枚举
    settings_dialog.py # 设置对话框
  assets/
    theme.qss          # 主题
    icons/             # 图标
ffmpeg/ffmpeg.exe      # 内置（不入 SVN 也行，打包脚本会嵌入）
build.spec             # PyInstaller 配置
```

## 已知问题 / 后续

- 当前打包后单 exe 约 250–280MB（FFmpeg full build 占大头）。换 essentials 可降到 ~120MB。
- 高分辨率 60fps 用 libx264 CPU 占用偏高；后续可接 NVENC 硬编码（仅需在 `ffmpeg_builder.py` 替换 `-c:v` 参数）。
- 窗口模式跟随是 500ms 轮询；如果游戏窗口在录制中移动，画面坐标会滞后半秒——一般录游戏全屏化运行不会触发。
