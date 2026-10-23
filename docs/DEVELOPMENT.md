# Windows 开发说明

Python 3.10+（推荐 3.12，含 tkinter）。运行时仅依赖标准库及外部 FFmpeg/ffprobe；PyInstaller 仅用于打包。

## 运行与构建

运行 python dji_graft_gui.py，或双击 start_windows.cmd。执行 build.ps1 / build.bat 打包，输出 dist/DJIGraft-5.0-Windows-x64.exe，包含图标及版本资源，不包含 FFmpeg。

## 模块职责

- desktop_ui.py：布局、交互和线程消息；ui_model.py：输入校验和任务参数；ui_theme.py：颜色字体。
- dji_graft_gui.py：入口及单文件/批量任务；dji_graft.py：CPU 转码和容器移植。
- hardware_accel.py：硬件编码及兼容校验；dji_preview.py：预览原位等长替换。
- process_utils.py：隐藏 Windows 子进程控制台；ffmpeg_env.py：环境定位与准备。

## 测试

安装 FFmpeg/ffprobe 后执行 python -m unittest discover -v。历史兼容测试读取固定 v4.0.0 标签，先运行 git fetch --tags。Windows 桌面执行 python scripts/check_ui_layout.py，检查默认值、单视频/批量窗口控件以及逐级父容器裁切。

真实视频与硬件测试的环境变量（未提供时相关测试跳过）：

- DJI_TEST_REFERENCE：相机参考 MP4。
- DJI_TEST_GPU：可用编码器，如 h264_amf、h264_nvenc、h264_qsv。
- DJI_TEST_BAD_NVENC：旧 NVIDIA 问题样片，用于码流头回归。
- DJI_TEST_OUTPUT、DJI_TEST_CONFIRMED：转码中间文件、已由相机确认的输出；同时提供参考文件。

私人样片、构建缓存和日志放在被忽略的 _smoke/，不提交仓库。发布说明位于 docs/releases/v5.0.md。本次只发布 Windows，手机端留待后续更新。
