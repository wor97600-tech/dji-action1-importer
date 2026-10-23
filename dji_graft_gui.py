#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dji_graft.py / batch_dji_graft.py 的图形界面版本。

只依赖 Python 标准库 tkinter，ffmpeg / ffprobe 由 ffmpeg_env 自动定位或安装。
"""

import sys
import traceback
from pathlib import Path

import tkinter as tk

from dji_graft import (
    configure_ffmpeg,
    get_ref_targets,
    transcode,
    graft,
    get_input_video_bitrate,
)
from ffmpeg_env import ensure_ffmpeg, find_ffmpeg, ffmpeg_version
from utils import find_input_videos
from desktop_ui import DesktopUI, VERSION


APP_VERSION = VERSION


def _enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run_selftest():
    """非 GUI 自检：把 ffmpeg 检测结果写到 selftest_result.txt 后退出。"""
    out_file = Path.cwd() / "selftest_result.txt"
    ffmpeg_path, ffprobe_path = find_ffmpeg()
    if ffmpeg_path and ffprobe_path:
        version = ffmpeg_version(ffmpeg_path) or "unknown"
        out_file.write_text(
            f"OK\nffmpeg={ffmpeg_path}\nffprobe={ffprobe_path}\nversion={version}\n",
            encoding="utf-8",
        )
    else:
        out_file.write_text("MISSING\n", encoding="utf-8")
    sys.exit(0)


class App(DesktopUI, tk.Tk):
    def _worker(self, mode, ref, inp, out, start_num, crf, max_br, prefix, acceleration='cpu'):
        try:
            self.msg_queue.put(("log", "检查 ffmpeg 环境 ..."))
            ffmpeg_path, ffprobe_path = ensure_ffmpeg(
                progress_callback=lambda pct, msg: self.msg_queue.put(("ffmpeg", (pct, msg)))
            )
            configure_ffmpeg(ffmpeg_path, ffprobe_path)
            self.msg_queue.put(("ffmpeg_ready", (str(ffmpeg_path), str(ffprobe_path))))
        except Exception as exc:
            self.msg_queue.put(("error", f"ffmpeg 环境准备失败：{exc}"))
            self.msg_queue.put(("done", None))
            return

        try:
            self.msg_queue.put(("log", f"读取参考文件编码参数: {ref}"))
            targets = get_ref_targets(Path(ref))

            if mode == "single":
                input_vb = get_input_video_bitrate(Path(inp))
                if input_vb > 0 and targets["video_bitrate"] > input_vb * 3 and crf is None:
                    self.msg_queue.put(
                        (
                            "log",
                            f"提示：参考码率 {targets['video_bitrate']//1000}kbps "
                            f"远高于输入 {input_vb//1000}kbps，建议启用 CRF 以减小体积",
                        )
                    )

            self.msg_queue.put(
                (
                    "log",
                    f"目标规格: {targets['width']}x{targets['height']} @ {targets['fps']}fps, "
                    f"音频 {targets['sample_rate']}Hz/{targets['channels']}ch",
                )
            )

            if mode == "single":
                self._run_single(ref, Path(inp), Path(out), targets, crf, max_br, acceleration)
            else:
                self._run_batch(ref, Path(inp), Path(out), targets, start_num, crf, max_br, prefix, acceleration)

            self.msg_queue.put(("log", "\n处理结束。"))
        except Exception as exc:
            self.msg_queue.put(("error", f"{exc}\n\n{traceback.format_exc()}"))
        finally:
            self.msg_queue.put(("done", None))

    def _run_single(self, ref, inp, out, targets, crf, max_br, acceleration='cpu'):
        tmp_path = out.with_suffix(".reencoded_tmp.mp4")
        self.msg_queue.put(
            (
                "log",
                f"转码中: {inp.name} (CRF={crf if crf is not None else '固定码率'}, "
                f"峰值上限={max_br//1000 if max_br else '参考文件'}kbps)",
            )
        )
        transcode(
            inp,
            tmp_path,
            targets,
            progress_callback=lambda p: self.msg_queue.put(("progress", (inp.name, p))),
            crf=crf,
            max_video_bitrate=max_br,
            acceleration=acceleration,
            status_callback=lambda msg: self.msg_queue.put(('log', msg)),
        )
        self.msg_queue.put(("log", "容器移植并生成输入视频封面（原位置、原长度替换）..."))
        graft(Path(ref), tmp_path, out)
        tmp_path.unlink(missing_ok=True)
        out_size = out.stat().st_size
        in_size = inp.stat().st_size
        ratio = out_size / in_size if in_size > 0 else 0
        self.msg_queue.put(
            ("log", f"完成 -> {out} ({out_size/1024/1024:.1f} MB, 体积比 {ratio:.2f}x)")
        )
        self.msg_queue.put(("openable", str(out.parent)))

    def _run_batch(self, ref, input_dir, output_dir, targets, start_num, crf, max_br, prefix, acceleration='cpu'):
        output_dir.mkdir(parents=True, exist_ok=True)
        videos = find_input_videos(input_dir)
        if not videos:
            self.msg_queue.put(("log", "文件夹里没有找到支持的视频文件"))
            self.msg_queue.put(("openable", str(output_dir)))
            return

        self.msg_queue.put(
            ("log", f"共发现 {len(videos)} 个文件（已按文件名自然排序），从编号 {start_num} 开始命名")
        )
        number = start_num
        ok_count, fail_count = 0, 0

        for idx, video in enumerate(videos, 1):
            out_name = f"{prefix}{number:04d}.MP4"
            out_path = output_dir / out_name
            tmp_path = out_path.with_suffix(".reencoded_tmp.mp4")
            self.msg_queue.put(("log", f"\n[{idx}/{len(videos)}] {video.name} -> {out_name}"))
            try:
                transcode(
                    video,
                    tmp_path,
                    targets,
                    progress_callback=lambda p, n=video.name, i=idx, t=len(videos): (
                        self.msg_queue.put(("progress", (n, p, i, t)))
                    ),
                    crf=crf,
                    max_video_bitrate=max_br,
                    acceleration=acceleration,
                    status_callback=lambda msg: self.msg_queue.put(('log', msg)),
                )
                self.msg_queue.put(("log", "生成本视频封面（原位置、原长度替换）..."))
                graft(Path(ref), tmp_path, out_path)
                out_size = out_path.stat().st_size
                in_size = video.stat().st_size
                ratio = out_size / in_size if in_size > 0 else 0
                self.msg_queue.put(("log", f"  完成 ✅ ({out_size/1024/1024:.1f} MB, 比 {ratio:.2f}x)"))
                ok_count += 1
            except Exception as exc:
                self.msg_queue.put(("log", f"  失败 ❌ {exc}"))
                fail_count += 1
            finally:
                tmp_path.unlink(missing_ok=True)
            number += 1

        self.msg_queue.put(("log", f"\n批量转换完成：成功 {ok_count} 个，失败 {fail_count} 个"))
        self.msg_queue.put(("openable", str(output_dir)))

def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return
    _enable_dpi_awareness()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DJIGraft.Desktop.5.0")
        except (OSError, AttributeError):
            pass
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
