# DJI Action 第三方视频移植工具

桌面版：**v3.1** · Android 版：**v4.0.0**

把第三方拍摄的视频（手机、运动相机、屏幕录像等）转码并“移植”进大疆
Action 系列相机的原生 MP4 容器结构，让相机能像播放自己拍摄的文件一样正常回放。

核心思路：

1. 读取一个“相机自己拍的、能正常播放”的参考文件，提取分辨率、帧率、音频参数；
2. 用 FFmpeg 把要导入的视频转码成匹配的参数（H.264 + AAC + faststart）；
3. 不重新封装，而是把转码后的音视频分块“移植”进参考文件的容器结构，
   尽量保持相机固件对文件的兼容性；
4. 按相机命名规则输出 `DJI_0900.MP4` 这样的文件。

## 手机版（Android）

### 下载安装

1. 打开仓库的 [Releases](../../releases) 页面；
2. 下载最新的 `DJIGraft-Android-*.apk`；
3. 在手机上允许“安装未知来源应用”，安装后即可使用。

APK 已内置 FFmpeg（含 libx264），不需要 Root，也不需要额外安装 Termux。

### 使用步骤

1. **选择参考文件**：一段相机自己拍摄、带声音、能正常回放的 MP4；
2. **添加视频**：可以一次选择多个文件，列表会按文件名自然排序；
3. **设置输出**：文件名前缀默认 `DJI_`，起始编号默认 `0900`；
   画质 CRF 默认 23，数值越小越清晰、体积越大；
4. **选择输出位置**（可选）：
   - 默认保存到 `Downloads/DJIGraft`；
   - 如果手机插了相机 SD 卡，可以直接选择卡里的 `DCIM/DJI_XXX` 文件夹，
     转换完成后直接写入卡里；
5. 点击**开始转换**。转换在前台服务中运行，锁屏或切到后台也能继续，
   通知栏会显示进度和“取消”按钮；
6. 完成后可以直接“打开”预览或“分享”，也可以把文件复制到相机 SD 卡。

> 建议先用一条 10 秒左右的短片在相机上验证回放，再批量导入。
> 不同固件版本的兼容性可能有差异；文件名编号要大于卡里已有的最大编号。

### 手机版特性

- 单文件 / 多文件批量转换
- 自然排序，`video2` 会排在 `video10` 前面
- 自动读取参考文件的分辨率、帧率、音频参数
- CRF 画质控制 + 可选峰值码率
- 没有音轨的输入会自动补静音音轨，避免移植时缺音轨
- 输出文件重名时自动递增编号
- 前台服务 + 通知栏进度，支持取消
- 输出到系统下载目录，或通过 SAF 直接写入 SD 卡文件夹

### 从源码构建 Android APK

要求：JDK 17、Android SDK Platform 35 / Build-Tools 35、Gradle 8.9。

```bash
cd android
gradle prepareFfmpegKit    # 首次运行会下载并校验 FFmpegKitNext Maven 包
gradle :app:testDebugUnitTest
gradle :app:assembleDebug
```

APK 输出在 `android/app/build/outputs/apk/debug/app-debug.apk`。

也可以直接把代码推到 GitHub，`android` workflow 会自动：

1. 下载并校验 FFmpegKitNext；
2. 运行容器移植单元测试（与桌面版 `dji_graft.py` 输出逐字节对比）；
3. 构建 APK 并上传 artifact；
4. 推送 `v*` 标签时，自动把 APK 附加到 GitHub Release。

例如：

```bash
git tag v4.0.0
git push origin v4.0.0
```

## 桌面版

### 直接使用打包好的 exe（推荐）

从 [Releases](../../releases) 下载 `DJIGraft.exe`，双击运行即可，不需要单独安装
Python 或 ffmpeg。首次转换时如果检测不到 ffmpeg，程序会提示并自动下载安装
（需要联网，之后会缓存在 `%LOCALAPPDATA%\DJIGraft\bin`）。

### 从源码运行

要求：Python 3.9+，系统已安装 ffmpeg/ffprobe（或在程序目录放置这两个 exe）。

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

## 输出后要做什么

1. 把生成的 `DJI_XXXX.MP4` 复制到相机 microSD 卡的 `DCIM/DJI_XXX` 目录下
   （和相机自己生成的文件放一起）；
2. 文件编号要大于卡里已有的最大编号，避免和已有文件冲突；
3. 装卡上机测试播放，确认可以正常回放后再批量导入。

## 项目结构

```
dji_graft.py        桌面版核心移植逻辑（CLI 单文件）
batch_dji_graft.py  桌面版 CLI 批量版本
dji_graft_gui.py    桌面版 tkinter 图形界面
box_tools.py        MP4/MOV box 解析与构建
ffmpeg_env.py       桌面版 ffmpeg 定位 / 校验 / 自动安装
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
```

## 许可证

桌面版源码：[MIT](./LICENSE)。

Android APK 内置 GPL 版 FFmpeg/FFmpegKitNext 与 libx264，分发时请遵守相应
GPL 条款。详见 [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md)。
