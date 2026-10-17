# 第三方组件与许可证

桌面版的 Python 源码使用仓库根目录的 MIT 许可证。

Android APK 内置了 **FFmpegKitNext 9.0.0** 的 GPL 构建，其中包含：

- FFmpeg / FFprobe
- libx264（GPL）
- FFmpegKitNext 的 JNI 封装

该二进制来自公开的社区构建：

- 源码：https://github.com/arthenica/ffmpeg-kit-next
- Android 构建与 Maven 包：https://github.com/XiaoHao560/ffmpeg-kit-next

FFmpegKitNext 以 GPL v3.0 发布，libx264 以 GPL v2.0 发布。由于 APK
把上述 GPL 组件与应用程序一起分发，**包含该 APK 的整体分发需要遵守
GPL 的相应条款**。本仓库公开了完整的应用源码、构建脚本和 FFmpeg 获取方式，
以满足源码提供义务；如果你重新发布 APK，请保留本说明、相关许可证和源码链接。

FFmpegKitNext 的 AAR 内还包含 `res/raw/license.txt`、
`res/raw/license_cpu_features.txt` 和 `res/raw/source.txt`，这些文件会随
APK 一起打包。

如果你希望发布闭源版本，需要替换为符合 LGPL/商业许可的 FFmpeg 构建，并自行
评估 libx264 的 GPL 影响。
