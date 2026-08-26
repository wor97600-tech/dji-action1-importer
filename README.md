dji-action1-importer
一个关于把第三方视频改成大疆action1可以识别视频的程序
DJI Action 1 反向导入工具

> 把电脑上的视频导入到大疆 Action 1 相机里，在相机屏幕上直接播放

---

背景

官方没有提供反向导入功能，这个工具填补了这个空白。

我自己有一台 Action 1，想把剪好的视频导回相机里播放，但全网都找不到工具。折腾了一天，用 Claude AI 写了一个，居然跑通了，分享出来给大家用。

---

使用方法

## 快速开始（给普通用户）

1. 下载本仓库的 `dji_graft_gui.exe`
2. 去 [ffmpeg 下载页](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-full.7z`，解压后把 `ffmpeg.exe` 和 `ffprobe.exe` 放到 **和 exe 同一个文件夹**里
3. 双击 `dji_graft_gui.exe` 运行

## 首次使用步骤

1. 从你的 Action 1 相机里拷贝一个原生 MP4 文件作为“参考文件”
2. 打开工具，选择参考文件
3. 选择你要导入的第三方视频所在的文件夹
4. 点击“开始转换”


依赖安装

需要安装 ffmpeg
下载地址：https://www.gyan.dev/ffmpeg/builds/

---

声明

本工具仅供学习研究使用，使用前请备份 SD 卡数据，作者不承担数据丢失风险。

---

致谢

本项目由 Claude AI 辅助开发，实际测试可用。

有问题请提 Issue，欢迎 PR！
