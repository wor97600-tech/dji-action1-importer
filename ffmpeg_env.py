#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位、校验并在缺失时自动安装 ffmpeg / ffprobe。

查找顺序：
1. 用户配置目录（%LOCALAPPDATA%\\DJIGraft\\bin），即自动安装/手动放置的位置；
2. 与 exe 同目录（便携模式）；
3. PyInstaller 解包目录（如果把 ffmpeg 一起打包进 exe）；
4. 系统 PATH。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


APP_NAME = "DJIGraft"
FFMPEG_EXE = "ffmpeg.exe"
FFPROBE_EXE = "ffprobe.exe"

# gyan.dev 的 essentials 包只包含常用的 ffmpeg / ffprobe，体积比 full 包小很多。
DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _app_dir():
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def bin_dir():
    return _app_dir() / "bin"


def _is_frozen():
    return bool(getattr(sys, "frozen", False))


def _candidate_root_dirs():
    dirs = []
    dirs.append(bin_dir())
    if _is_frozen():
        dirs.append(Path(sys.executable).resolve().parent)
    else:
        dirs.append(Path(__file__).resolve().parent)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))
    return dirs


def _find_tool(exe_name):
    for d in _candidate_root_dirs():
        p = d / exe_name
        if p.is_file():
            return p
    which = shutil.which(exe_name)
    if which:
        return Path(which)
    return None


def find_ffmpeg():
    """返回 (ffmpeg 路径, ffprobe 路径)，找不到的为 None。"""
    return _find_tool(FFMPEG_EXE), _find_tool(FFPROBE_EXE)


def is_available():
    ffmpeg_path, ffprobe_path = find_ffmpeg()
    return bool(ffmpeg_path and ffprobe_path)


def ffmpeg_version(ffmpeg_path):
    """读取 ffmpeg 版本字符串，失败返回 None。"""
    try:
        r = subprocess.run(
            [str(ffmpeg_path), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if r.returncode == 0:
            return r.stdout.splitlines()[0].strip()
    except Exception:
        return None
    return None


def _download(url, dest, progress_callback=None):
    def report(percent, msg):
        if progress_callback:
            progress_callback(percent, msg)

    report(0, "正在下载 ffmpeg，请稍候 ...")
    req = urllib.request.Request(url, headers={"User-Agent": "DJIGraft/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = min(99, done * 100 // total)
                    report(
                        pct,
                        f"正在下载 ffmpeg ... {done // (1024 * 1024)} MB / "
                        f"{total // (1024 * 1024)} MB",
                    )
    report(100, "ffmpeg 下载完成")


def install_ffmpeg(progress_callback=None, dest_dir=None):
    """下载并解压 ffmpeg / ffprobe 到配置目录，返回两个文件的路径。"""
    dest_dir = Path(dest_dir) if dest_dir else bin_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = Path(tempfile.gettempdir()) / "dji_graft_ffmpeg.zip"

    try:
        _download(DOWNLOAD_URL, zip_path, progress_callback)
        if progress_callback:
            progress_callback(100, "正在解压 ffmpeg ...")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            ffmpeg_name = next(
                (n for n in names if n.replace("\\", "/").endswith("/bin/ffmpeg.exe")),
                None,
            )
            ffprobe_name = next(
                (n for n in names if n.replace("\\", "/").endswith("/bin/ffprobe.exe")),
                None,
            )
            if not ffmpeg_name or not ffprobe_name:
                raise RuntimeError("下载的压缩包里没有找到 ffmpeg.exe / ffprobe.exe")

            for src_name, dst_name in (
                (ffmpeg_name, FFMPEG_EXE),
                (ffprobe_name, FFPROBE_EXE),
            ):
                with zf.open(src_name) as src, open(dest_dir / dst_name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass

    ffmpeg_path = dest_dir / FFMPEG_EXE
    ffprobe_path = dest_dir / FFPROBE_EXE
    if not ffmpeg_path.is_file() or not ffprobe_path.is_file():
        raise RuntimeError("ffmpeg 安装后文件缺失")
    return ffmpeg_path, ffprobe_path


def ensure_ffmpeg(progress_callback=None):
    """确保 ffmpeg / ffprobe 可用；缺失时自动下载安装。"""
    ffmpeg_path, ffprobe_path = find_ffmpeg()
    if ffmpeg_path and ffprobe_path:
        return ffmpeg_path, ffprobe_path

    if progress_callback:
        progress_callback(0, "未找到 ffmpeg，准备自动安装 ...")
    try:
        return install_ffmpeg(progress_callback)
    except Exception as exc:
        raise RuntimeError(
            "未找到 ffmpeg/ffprobe，自动安装失败。\n"
            "请手动下载 ffmpeg，把 ffmpeg.exe 和 ffprobe.exe 放到本程序目录，"
            "或加入系统 PATH。\n"
            f"下载地址：{DOWNLOAD_URL}\n原因：{exc}"
        ) from exc
