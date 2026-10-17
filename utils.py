#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用工具函数。"""

import re
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".wmv", ".flv"}


def natural_sort_key(path):
    """按文件名做自然排序，让 video2.mp4 排在 video10.mp4 前面。

    例如 ["DJI_0900.MP4", "DJI_0902.MP4", "DJI_0901.MP4"] 会被排成
    ["DJI_0900.MP4", "DJI_0901.MP4", "DJI_0902.MP4"]。
    """
    name = path.name if isinstance(path, Path) else str(path)
    parts = re.split(r"(\d+)", name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def find_input_videos(input_dir):
    """返回按文件名自然排序的视频文件列表。"""
    input_dir = Path(input_dir)
    return sorted(
        (
            p
            for p in input_dir.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        ),
        key=natural_sort_key,
    )
