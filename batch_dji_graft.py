#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_dji_graft.py — 批量版本 + 体积控制
"""
import argparse
import sys
import traceback
from pathlib import Path

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
    ap.add_argument("--crf", type=int, default=None,
                    help="使用 CRF 质量模式（推荐 23~28），体积通常比固定码率小 30%%-60%%")
    ap.add_argument("--max-bitrate", type=int, default=None,
                    help="手动限制视频峰值码率（kbps），例如 20000 表示 20Mbps")
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
    
    max_br = args.max_bitrate * 1000 if args.max_bitrate else None
    crf_info = f"CRF={args.crf}" if args.crf is not None else "固定码率"
    br_info = f"{args.max_bitrate}kbps" if args.max_bitrate else "参考文件码率"
    print(f"体积控制: {crf_info}, 峰值上限={br_info}")
    print(f"共发现 {len(videos)} 个待转换文件，从编号 {args.start} 开始命名\n")

    results = []
    number = args.start

    for idx, video in enumerate(videos, 1):
        out_name = f"{args.prefix}{number:04d}.MP4"
        out_path = output_dir / out_name
        tmp_path = out_path.with_suffix(".reencoded_tmp.mp4")

        print(f"总进度 [{idx}/{len(videos)}] {format_batch_bar(idx - 1, len(videos))}")
        print(f"  {video.name}  ->  {out_name}")
        try:
            transcode(video, tmp_path, targets, show_progress=True, label="转码中",
                      crf=args.crf, max_video_bitrate=max_br)
            print("  容器移植中...", end="", flush=True)
            graft(ref_path, tmp_path, out_path)
            out_size = out_path.stat().st_size
            in_size = video.stat().st_size
            ratio = out_size / in_size if in_size > 0 else 0
            print(f"\r  完成 ✅ ({out_size/1024/1024:.1f} MB, 比 {ratio:.2f}x)        ")
            results.append((video, out_path, None))
        except Exception as e:
            print(f"    失败 ❌ {e}", file=sys.stderr)
            if args.keep_temp:
                pass
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
