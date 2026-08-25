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

下载ffmpeg
打开解压后的文件夹，找到 bin 子文件夹，里面应该有三个文件：ffmpeg.exe、ffprobe.exe、ffplay.exe。把这两个（ffmpeg.exe 和 ffprobe.exe）直接复制到文件夹里。这样就不用折腾环境变量了，命令行在那个文件夹里能直接调用到。把你要转换的视频放入文件中，我已经把一个大疆原生拍摄的视频放入项目中了，无需再次导入，你只需要再导入你要转换的视频以及ffmpeg的两个文件
确认文件夹里现在有哪些东西
这时候那个文件夹里应该有：dji_graft.py、box_tools.py、ffmpeg.exe、ffprobe.exe，加上你的参考视频和要导入的第三方视频，一共六个文件都在同一层。
测试 ffmpeg 能不能跑
在这个文件夹的地址栏里输入 cmd 回车，会弹出一个已经定位到这里的命令行窗口。先输入 ffmpeg -version 回车测试一下，能看到版本号输出就说明这个文件夹里的 ffmpeg.exe 可以正常调用了。
运行转换脚本
确认没问题后，输入： python3 dji_graft.py --ref DJI_0819.MP4 --input 你的第三方视频.mp4 --output DJI_0900.MP4 （如果提示 python3 不是内部命令，换成 python 重试）。把文件名换成你自己的实际文件名就行。
---

依赖安装

需要安装 Python 3.8+
下载地址：https://python.org

需要安装 ffmpeg
下载地址：https://www.gyan.dev/ffmpeg/builds/

下载后把 ffmpeg.exe 放到项目文件夹里的 ffmpeg/bin/ 目录下

---

声明

本工具仅供学习研究使用，使用前请备份 SD 卡数据，作者不承担数据丢失风险。

---

致谢

本项目由 Claude AI 辅助开发，实际测试可用。

有问题请提 Issue，欢迎 PR！
