# DJI Action 第三方视频移植工具

> 把手机、运动相机、屏幕录像等第三方视频，转码并“移植”进 DJI Action 系列相机的原生 MP4 容器结构，让相机能像播放自己拍摄的文件一样正常回放。

**Windows 正式版：v5.0** · Android 手机版：v4.0.0（本次不更新）

[下载 Windows 版](#windows-桌面版) · [下载 Android 版](#android-手机版) · [查看 Releases](../../releases)

## 这个工具解决什么问题

大疆 Action 相机对 MP4 容器、编码参数和文件命名有比较严格的要求。普通视频即使能转换成 H.264 + AAC，直接复制到相机 SD 卡里也经常无法播放、无法预览，或者拖动进度条时出问题。

本工具不会只做一次普通转码，而是：

1. 读取一段相机自己拍摄、能正常回放的 MP4 作为“参考文件”；
2. 提取参考文件的分辨率、帧率、音频参数和容器结构；
3. 用 FFmpeg 把待导入视频转码成匹配的参数；
4. 把转码后的音视频分块移植进参考文件的原生容器结构，并重新计算 chunk offset、时长和轨道信息；
5. 按相机命名规则输出 `DJI_0900.MP4` 这样的文件。

整个过程在本地完成，不上传视频，也不需要刷机或修改相机固件。

## 下载

Windows v5.0 已独立发布；Android 继续使用 v4.0.0，本次不发布 APK。

| 平台 | 文件 | 体积 | 说明 |
|---|---|---|---|
| Windows 10/11 x64 | [DJIGraft-5.0-Windows-x64.exe](../../releases/download/v5.0/DJIGraft-5.0-Windows-x64.exe) | 约 14 MB | 不内置 FFmpeg，可使用已有环境 |
| Android 8.0+ | `DJIGraft-Android-v4.0.0.apk` | 约 111 MB | 已内置 FFmpeg，离线可用 |

前往 [Windows v5.0](../../releases/tag/v5.0) 或 [Android v4.0.0](../../releases/tag/v4.0.0) 下载对应版本。Windows 校验值见 v5.0 附件 `SHA256SUMS.txt`。

- Android：`2FBF4D5AB739902E046046F6F878DAD656A35F2EA36BB93C330C561E4EC228C4`

> Windows exe 和 Android APK 使用不同的打包方式，体积差异是正常的。原因见下方“为什么 APK 比 exe 大这么多”。

## Windows 桌面版

### v5.0 更新亮点

- **全新扁平界面**：左侧文件与批量命名，右侧编码设置和日志；开始转换固定在底部。修复批量模式画质和码率说明被裁切的问题。
- **默认显卡加速**：自动检测 NVIDIA NVENC → Intel Quick Sync → AMD AMF；检测、编码或校验失败时尝试后续编码器，全部失败回退 CPU。也可手动选择编码器。
- **默认码率上限 2000 kbps（2 Mbps）**：不是 2000 KB/s。留空跟随参考视频；CRF 仅用于 CPU 编码及回退，显卡按码率控制。
- **封面与播放修复**：使用待转换视频生成相机预览，修复封面颜色异常、错误识别为照片等问题；完善 AMD / NVIDIA 码流兼容性处理。
- **转换无黑色弹窗**：环境检测、转码、封面等子进程在 Windows 下隐藏控制台。
- **更清楚的交互**：统一应用图标，加强按钮辨识；输入校验、覆盖确认、运行锁定、日志复制/保存及打开输出位置。

完整记录见 [更新日志](CHANGELOG.md)。显卡加速需要对应硬件、驱动和 FFmpeg 支持 H.264 编码；解码和缩放仍由 CPU 完成。建议先用短片确认相机回放。

### 直接运行

1. 下载 [DJIGraft-5.0-Windows-x64.exe](../../releases/download/v5.0/DJIGraft-5.0-Windows-x64.exe)；
2. 双击运行，不需要单独安装 Python；
3. 首次转换时如果系统里没有 FFmpeg，程序会提示并自动下载，
   之后缓存在 `%LOCALAPPDATA%\DJIGraft\bin`；
4. 选择参考文件、输入视频和输出目录，点击开始转换。

Windows 可能提示“未知发布者”，这是因为 exe 没有购买代码签名证书；确认来源可信后选择“仍要运行”。

### 从源码运行

要求：Python 3.10+（推荐 3.12，需包含 Tk），系统已安装 `ffmpeg` / `ffprobe`，或者把这两个 exe 放在程序目录。

```powershell
python dji_graft_gui.py
```

命令行批量版本：

```powershell
python batch_dji_graft.py --ref 参考原生文件.MP4 --input-dir 待转换文件夹 --output-dir 输出文件夹 --start 900 --prefix DJI_
```

命令行单文件版本：

```powershell
python dji_graft.py --ref 参考原生文件.MP4 --input 输入视频.mp4 --output DJI_0900.MP4 --crf 23
```

## Android 手机版

### 安装

1. 下载 `DJIGraft-Android-v4.0.0.apk`；
2. 在手机上允许“安装未知来源应用”；
3. 安装后打开即可使用，不需要 Root，也不需要 Termux。

### 使用步骤

1. **选择参考文件**：一段相机自己拍摄、带声音、能正常回放的 MP4；
2. **添加视频**：可以一次选择多个文件，列表会按文件名自然排序，
   `video2` 会排在 `video10` 前面；
3. **设置输出**：文件名前缀默认 `DJI_`，起始编号默认 `0900`；
   画质 CRF 默认 23，数值越小越清晰、体积越大；
4. **选择输出位置**（可选）：
   - 默认保存到 `Downloads/DJIGraft`；
   - 如果手机插了相机 SD 卡，可以直接选择卡里的 `DCIM/DJI_XXX` 文件夹，
     转换完成后直接写入卡里；
5. 点击**开始转换**。转换在前台服务中运行，锁屏或切到后台也能继续，
   通知栏会显示进度和“取消”按钮；
6. 完成后可以直接“打开”预览或“分享”，也可以把文件复制到相机 SD 卡。

### 手机版特性

- 单文件 / 多文件批量转换
- 文件名自然排序，输出顺序与输入顺序一致
- 自动读取参考文件的分辨率、帧率、音频参数
- CRF 画质控制 + 可选峰值码率
- 没有音轨的输入自动补静音音轨
- 输出文件重名时自动递增编号
- 前台服务 + 通知栏进度，支持取消
- 输出到系统下载目录，或通过 SAF 直接写入 SD 卡文件夹
- 完全本地处理，不上传视频

## Windows 和 Android 有什么区别

| 项目 | Windows 桌面版 | Android 手机版 |
|---|---|---|
| 使用场景 | 电脑上批量整理、输出到本地目录 | 直接在手机上处理并写入 SD 卡 |
| 包体 | exe 约 12 MB，首次运行下载 FFmpeg | APK 约 111 MB，内置 FFmpeg |
| 离线使用 | 首次下载 FFmpeg 后可离线 | 安装后即可离线 |
| 后台运行 | 桌面窗口 | 前台服务，切后台/锁屏可继续 |
| 文件选择 | 系统文件对话框 | 系统文件选择器 + SAF 文件夹 |

两端共享同一套“参考文件容器移植”思路；Android 端的容器移植逻辑用 Kotlin 重写，
并有单元测试与桌面版 `dji_graft.py` 的输出做逐字节对比。

## 兼容性与注意事项

- 主要针对 DJI Osmo Action 1，也适用于容器结构相同的 Action 机型；
- 不同相机固件对容器的要求可能有差异，**建议先用一条 10 秒左右的短片测试回放**；
- 输出文件编号要大于 SD 卡里已有的最大编号，避免和相机已有文件冲突；
- 参考文件必须是相机自己拍摄、能正常回放、带音轨的 MP4；
- 输入视频可以没有音轨，手机版会自动补静音音轨；
- 转换会占用较多临时空间，视频越大、时长越长，耗时越久。

## 从源码构建

### Windows exe

```powershell
.\build.ps1
```

输出文件在 `dist\DJIGraft-5.0-Windows-x64.exe`。生成的 exe 默认不内置 FFmpeg，
首次使用时会自动下载，因此安装包体积很小。

### Android APK

要求：JDK 17、Android SDK Platform 35 / Build-Tools 35、Gradle 8.9。

```bash
cd android
gradle prepareFfmpegKit    # 首次运行会下载并校验 FFmpegKitNext Maven 包
gradle :app:testDebugUnitTest
gradle :app:assembleDebug
```

APK 输出在 `android/app/build/outputs/apk/debug/app-debug.apk`。

### 发布 Windows 正式版

推送 `v5.0` 标签触发 Windows 发布流程：运行自动测试、构建轻量 EXE、生成 SHA-256 校验文件，并使用 `docs/releases/v5.0.md` 发布说明。此流程不构建、不上传 Android APK，手机端保留 v4.0.0。

### 桌面测试

```powershell
python -m unittest discover -v
python scripts/check_ui_layout.py
```

普通测试需要 FFmpeg/ffprobe；布局检查需要 Windows 桌面及 Tk。真实视频及显卡测试的配置见 [开发说明](docs/DEVELOPMENT.md)。

## 项目结构

```text
dji_graft.py        桌面版核心移植逻辑（CLI 单文件）
batch_dji_graft.py  桌面版 CLI 批量版本
dji_graft_gui.py    桌面入口与单文件/批量任务
desktop_ui.py       tkinter 窗口、布局与交互
ui_model.py         输入校验与任务参数
ui_theme.py         界面颜色与字体
hardware_accel.py   硬件编码检测、回退和兼容性校验
dji_preview.py      相机预览等长替换
process_utils.py    Windows 子进程无控制台启动
assets/             统一应用图标
tests/              桌面回归测试
scripts/            窗口布局检查
CHANGELOG.md        Windows 更新日志
box_tools.py        MP4/MOV box 解析与构建
ffmpeg_env.py       桌面版 FFmpeg 定位 / 校验 / 自动安装
utils.py            自然排序等通用工具

android/            Android 工程（Kotlin + Material 3）
  app/src/main/java/com/djigraft/mobile/
    MainActivity.kt          手机界面
    ConversionManager.kt     批量转换流程与进度
    ConversionService.kt     前台服务与通知
    FfmpegCommand.kt         FFmpeg 转码命令
    MediaProbe.kt            FFprobe 参数读取
    OutputTarget.kt          下载目录 / SAF 输出
    graft/Mp4Graft.kt        Kotlin 版容器移植
  app/src/test/...          与桌面版输出逐字节对比的单元测试

.github/workflows/
  release.yml               Windows 标签发布 / 手动构建（不发布 APK）
  android.yml               Android 分支 CI
```

## 常见问题

### 为什么 APK 比 exe 大这么多？

Windows exe 没有内置 FFmpeg，首次转换时才下载；Android APK 为了离线可用，
内置了 FFmpegKitNext，并且同时包含 `arm64-v8a` 和 `armeabi-v7a` 两套原生库。
APK 里约 105 MB 都是 FFmpeg 的 `.so` 文件。

如果想减小体积，可以只保留 `arm64-v8a`（APK 约 60 MB），或者拆成两个 ABI 独立 APK。

### 手机版需要 Root 吗？

不需要。APK 使用 Android 标准的文件选择器和 SAF 权限，不修改系统分区。

### 会上传视频吗？

不会。转码和容器移植都在本地完成，不依赖服务器。

### 为什么一定要参考文件？

相机固件不只看编码参数，还会检查 MP4 的容器结构、轨道信息和 chunk 布局。
参考文件提供一个“相机认可”的容器模板，工具把新视频的数据移植进去，
比单纯重新封装更接近相机自己拍摄的文件。

### 支持哪些机型？

目前主要面向 DJI Osmo Action 1。其他 Action 机型如果容器结构相同，也可以尝试；
建议每次先用短片验证。

## 许可证

桌面版源码使用 [MIT](./LICENSE)。

Android APK 内置 GPL 版 FFmpeg/FFmpegKitNext 与 libx264，分发时请遵守相应
GPL 条款。详见 [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md)。
