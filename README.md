# DJI Action 第三方视频移植工具

当前版本：**v3.1**

把第三方拍摄的视频（手机、运动相机、屏幕录像等）转码并“移植”进大疆 Action 系列
相机的原生 MP4 容器结构，让相机能像播放自己拍摄的文件一样正常回放。

本项目主要针对 DJI Osmo Action 1（也适用于结构相同的机型），核心思路是：

1. 读取一个“相机自己拍的、能正常播放”的参考文件，提取它的分辨率、帧率、音频参数等；
2. 用 ffmpeg 把要导入的视频转码成匹配的参数（H.264 + AAC + faststart）；
3. 不重新封装，而是直接把转码后的音视频分块“移植”进参考文件的容器结构，
   尽量保持相机固件对文件的兼容性；
4. 按相机命名规则输出 `DJI_0900.MP4` 这样的文件。

## 功能

- 单个文件 / 整个文件夹批量转换
- 批量模式下按**文件名自然排序**（`video2` 会排在 `video10` 前面），
  输出文件顺序与输入顺序一致
- 可自定义输出文件名前缀和起始编号
- CRF / 峰值码率两种体积控制方式
- **自动检测并自动安装 ffmpeg**：程序会先在配置目录、
  程序目录和系统 PATH 中查找 `ffmpeg.exe` / `ffprobe.exe`，找不到时自动下载安装
- 图形界面（tkinter，无需安装第三方 Python 库）

## 下载与使用

### 方式一：直接使用打包好的 exe（推荐）

1. 从 [Releases](../../releases) 下载 `DJIGraft.exe`；
2. 双击运行即可，不需要单独安装 Python 或 ffmpeg。
   首次转换时如果检测不到 ffmpeg，程序会提示并自动下载安装
   （需要联网，之后会缓存在 `%LOCALAPPDATA%\DJIGraft\bin`）。

### 方式二：从源码运行

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

> 提示：不同固件版本的兼容性可能有差异，建议先用一小段视频验证。

## 打包 exe

```powershell
.\build.ps1
```

输出文件在 `dist\DJIGraft.exe`。生成的 exe 默认**不内置** ffmpeg，
首次使用时会自动下载，因此安装包体积很小。

## 项目结构

```
dji_graft.py        核心移植逻辑（CLI 单文件）
batch_dji_graft.py  CLI 批量版本
dji_graft_gui.py    tkinter 图形界面
box_tools.py        MP4/MOV box 解析与构建
ffmpeg_env.py       ffmpeg 定位 / 校验 / 自动安装
utils.py            自然排序等通用工具
```

## 许可证

[MIT](./LICENSE)
