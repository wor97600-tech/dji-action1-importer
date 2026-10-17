# DJI Action 第三方视频移植工具

> 把手机、运动相机、屏幕录像等第三方视频，转码并“移植”进 DJI Action 系列相机的原生 MP4 容器结构，让相机能像播放自己拍摄的文件一样正常回放。

**最新版本：v4.0.0** · Windows 桌面版 + Android 手机版

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

两个平台的文件放在同一个 GitHub Release 中：

| 平台 | 文件 | 体积 | 说明 |
|---|---|---|---|
| Windows 10/11 | `DJIGraft.exe` | 约 12 MB | 首次转换时自动下载 FFmpeg |
| Android 8.0+ | `DJIGraft-Android-v4.0.0.apk` | 约 111 MB | 已内置 FFmpeg，离线可用 |

前往 [Releases](../../releases) 下载最新版本。当前 v4.0.0 的校验值：

- Windows：`C5D5C46FC9BC78EB22C56BAE7D737948A98335E05B547AD8167CD4B67139558E`
- Android：`2FBF4D5AB739902E046046F6F878DAD656A35F2EA36BB93C330C561E4EC228C4`

> Windows exe 和 Android APK 使用不同的打包方式，体积差异是正常的。原因见下方“为什么 APK 比 exe 大这么多”。

## Windows 桌面版

### 直接运行

1. 下载 `DJIGraft.exe`；
2. 双击运行，不需要单独安装 Python；
3. 首次转换时如果系统里没有 FFmpeg，程序会提示并自动下载，
   之后缓存在 `%LOCALAPPDATA%\DJIGraft\bin`；
4. 选择参考文件、输入视频和输出目录，点击开始转换。

Windows 可能提示“未知发布者”，这是因为 exe 没有购买代码签名证书；确认来源可信后选择“仍要运行”。

### 从源码运行

要求：Python 3.9+，系统已安装 `ffmpeg` / `ffprobe`，或者把这两个 exe 放在程序目录。

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

输出文件在 `dist\DJIGraft.exe`。生成的 exe 默认不内置 FFmpeg，
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

### 一次性发布 Windows + Android

推送 `v*` 标签会触发 `release` workflow：

1. 在 Windows runner 上构建 `DJIGraft.exe`；
2. 下载并校验 FFmpegKitNext；
3. 运行 Android 容器移植单元测试；
4. 构建 APK；
5. 等两端都成功后，把 `DJIGraft.exe` 和 `DJIGraft-Android-*.apk`
   一起附加到同一个 GitHub Release。

```bash
git tag v4.0.0
git push origin v4.0.0
```

## 项目结构

```text
dji_graft.py        桌面版核心移植逻辑（CLI 单文件）
batch_dji_graft.py  桌面版 CLI 批量版本
dji_graft_gui.py    桌面版 tkinter 图形界面
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
  release.yml               标签发布：同时构建 Windows 和 Android
  android.yml               Android 分支 CI
  build.yml                 Windows 手动构建
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
