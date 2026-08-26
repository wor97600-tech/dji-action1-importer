#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_dji_graft.py — dji_graft.py 的批量版本。
指定一个参考原生文件 + 一个装满第三方视频的文件夹，一次性把里面所有视频都
转换成大疆相机能识别播放的格式，自动按顺序编号命名，方便直接整批拷进卡里。

用法：
    python3 batch_dji_graft.py --ref DJI_0819.MP4 --input-dir ./to_import \
        --output-dir ./output --start 900

    --ref          参考原生文件（拍摄自你要用的那台相机）
    --input-dir    存放待转换第三方视频的文件夹
    --output-dir   转换结果输出的文件夹（不存在会自动创建）
    --start        起始编号，默认 900，即从 DJI_0900.MP4 开始往后编号
                   （编号请接着卡里已有文件的最大编号来取，避免相机识别混乱）
    --prefix       文件名前缀，默认 DJI_，一般不用改
    --keep-temp    保留每个文件的中间转码结果，方便排查某个文件失败的原因
    --continue-on-error  某个文件转换失败时跳过继续处理下一个（默认行为）

支持的第三方视频后缀：.mp4 .mov .mkv .avi .m4v .ts .wmv .flv
（只要 ffmpeg 能读的格式基本都行，这个列表只是用来筛选文件夹里哪些文件当作待处理项）
"""
import argparse
import sys
import traceback
from pathlib import Path

# 复用 dji_graft.py 里已经写好、测试过的核心函数
from dji_graft import check_tools, get_ref_targets, transcode, graft

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".wmv", ".flv"}


def format_batch_bar(done, total, width=30):
    percent = (done / total * 100) if total else 0
    filled = int(width * percent / 100)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {done}/{total}"


def find_input_videos(input_dir):
    files = sorted(
        p for p in Path(input_dir).iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )
    return files


def main():
    ap = argparse.ArgumentParser(description="批量把第三方视频移植进大疆 Action 原生 MP4 容器结构")
    ap.add_argument("--ref", required=True, help="参考原生 MP4 文件")
    ap.add_argument("--input-dir", required=True, help="待转换视频所在文件夹")
    ap.add_argument("--output-dir", required=True, help="输出文件夹")
    ap.add_argument("--start", type=int, default=900, help="输出文件起始编号（默认 900）")
    ap.add_argument("--prefix", default="DJI_", help="输出文件名前缀（默认 DJI_）")
    ap.add_argument("--keep-temp", action="store_true", help="保留每个文件的中间转码结果")
    args = ap.parse_args()

    check_tools()

    ref_path = Path(args.ref)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not ref_path.is_file():
        print(f"错误：参考文件不存在: {ref_path}", file=sys.stderr)
        sys.exit(1)
    if not input_dir.is_dir():
        print(f"错误：输入文件夹不存在: {input_dir}", file=sys.stderr)
        sys.exit(1)

    videos = find_input_videos(input_dir)
    if not videos:
        print(f"在 {input_dir} 里没找到支持的视频文件（支持后缀: {', '.join(sorted(VIDEO_EXTS))}）")
        sys.exit(0)

    print(f"读取参考文件编码参数: {ref_path}")
    targets = get_ref_targets(ref_path)
    print(f"目标规格: {targets['width']}x{targets['height']} @ {targets['fps']}fps, "
          f"音频 {targets['sample_rate']}Hz/{targets['channels']}ch")
    print(f"共发现 {len(videos)} 个待转换文件，从编号 {args.start} 开始命名\n")

    results = []  # (input_path, output_path_or_None, error_or_None)
    number = args.start

    for idx, video in enumerate(videos, 1):
        out_name = f"{args.prefix}{number:04d}.MP4"
        out_path = output_dir / out_name
        tmp_path = out_path.with_suffix(".reencoded_tmp.mp4")

        print(f"总进度 [{idx}/{len(videos)}] {format_batch_bar(idx - 1, len(videos))}")
        print(f"  {video.name}  ->  {out_name}")
        try:
            transcode(video, tmp_path, targets, show_progress=True, label="转码中")
            print("  容器移植中...", end="", flush=True)
            graft(ref_path, tmp_path, out_path)
            print("\r  完成 ✅                    ")
            results.append((video, out_path, None))
        except Exception as e:
            print(f"    失败 ❌ {e}", file=sys.stderr)
            if args.keep_temp:
                pass  # 转码中间文件保留供排查
            results.append((video, None, str(e)))
            traceback.print_exc(file=sys.stderr)
        finally:
            if not args.keep_temp:
                tmp_path.unlink(missing_ok=True)

        number += 1
        print()

    print(f"总进度 [{len(videos)}/{len(videos)}] {format_batch_bar(len(videos), len(videos))}\n")

    ok = [r for r in results if r[1] is not None]
    failed = [r for r in results if r[1] is None]

    print("=" * 50)
    print(f"批量转换完成：成功 {len(ok)} 个，失败 {len(failed)} 个")
    if failed:
        print("\n以下文件转换失败，请检查：")
        for src, _out, err in failed:
            print(f"  - {src.name}: {err}")
    print(f"\n成功的文件已输出到: {output_dir}")
    print("下一步：把这些文件复制到相机 microSD 卡的 DCIM/DJI_XXX 目录下，装卡上机测试播放。")


if __name__ == "__main__":
    main()
