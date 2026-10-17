#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dji_graft.py / batch_dji_graft.py 的图形界面版本。

只依赖 Python 标准库 tkinter，ffmpeg / ffprobe 由 ffmpeg_env 自动定位或安装。
"""

import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from dji_graft import (
    configure_ffmpeg,
    get_ref_targets,
    transcode,
    graft,
    get_input_video_bitrate,
)
from ffmpeg_env import ensure_ffmpeg, find_ffmpeg, ffmpeg_version
from utils import find_input_videos


APP_VERSION = "v3.1"


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"DJI Action 第三方视频移植工具 {APP_VERSION}")
        self.geometry("840x760")
        self.minsize(720, 680)

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.ref_path = tk.StringVar()
        self.mode = tk.StringVar(value="single")
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.prefix = tk.StringVar(value="DJI_")
        self.start_number = tk.StringVar(value="0900")
        self.crf = tk.StringVar(value="23")
        self.max_bitrate = tk.StringVar(value="")
        self.ffmpeg_status_var = tk.StringVar()

        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self.install_thread = None
        self._open_dir = None

        self._build_ui()
        self._bind_name_preview()
        self.after(100, self._poll_queue)
        self._refresh_ffmpeg_status()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        status_frm = ttk.Frame(self)
        status_frm.pack(fill="x", padx=10, pady=(8, 0))
        self.status_label = tk.Label(
            status_frm,
            textvariable=self.ffmpeg_status_var,
            anchor="w",
            fg="#0a7d33",
        )
        self.status_label.pack(side="left", fill="x", expand=True)
        self.install_btn = ttk.Button(
            status_frm, text="安装 / 修复 ffmpeg", command=self._install_ffmpeg
        )
        self.install_btn.pack(side="right")

        frm_ref = ttk.LabelFrame(self, text="① 参考原生文件")
        frm_ref.pack(fill="x", **pad)
        frm_ref.columnconfigure(0, weight=1)
        ttk.Entry(frm_ref, textvariable=self.ref_path).grid(
            row=0, column=0, sticky="ew", padx=(10, 5), pady=(8, 2)
        )
        ttk.Button(frm_ref, text="选择文件...", command=self._pick_ref).grid(
            row=0, column=1, padx=(0, 10), pady=(8, 2)
        )
        ttk.Label(
            frm_ref,
            text="选一个相机自己拍的、能正常播放的 MP4，用于读取分辨率 / 帧率 / 音频等参数。",
            foreground="#666666",
            wraplength=620,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))

        frm_mode = ttk.LabelFrame(self, text="② 选择模式")
        frm_mode.pack(fill="x", **pad)
        ttk.Radiobutton(
            frm_mode, text="单个文件", variable=self.mode, value="single",
            command=self._on_mode_change,
        ).grid(row=0, column=0, padx=(10, 20), pady=6)
        ttk.Radiobutton(
            frm_mode, text="批量（整个文件夹）", variable=self.mode, value="batch",
            command=self._on_mode_change,
        ).grid(row=0, column=1, padx=(0, 10), pady=6)

        self.frm_input = ttk.LabelFrame(self, text="③ 输入")
        self.frm_input.pack(fill="x", **pad)
        self.frm_input.columnconfigure(0, weight=1)
        self.input_entry = ttk.Entry(self.frm_input, textvariable=self.input_path)
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=8)
        self.input_btn = ttk.Button(self.frm_input, text="选择文件...", command=self._pick_input)
        self.input_btn.grid(row=0, column=1, padx=(0, 10), pady=8)

        self.frm_output = ttk.LabelFrame(self, text="④ 输出")
        self.frm_output.pack(fill="x", **pad)
        self.frm_output.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(self.frm_output, textvariable=self.output_path)
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=(8, 2))
        self.output_btn = ttk.Button(self.frm_output, text="另存为...", command=self._pick_output)
        self.output_btn.grid(row=0, column=1, padx=(0, 10), pady=(8, 2))

        self.frm_naming = ttk.Frame(self.frm_output)
        self.frm_naming.columnconfigure(3, weight=1)
        ttk.Label(self.frm_naming, text="文件名前缀：").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.frm_naming, textvariable=self.prefix, width=10).grid(
            row=0, column=1, sticky="w", padx=(2, 12)
        )
        ttk.Label(self.frm_naming, text="起始编号：").grid(row=0, column=2, sticky="w")
        ttk.Entry(self.frm_naming, textvariable=self.start_number, width=8).grid(
            row=0, column=3, sticky="w", padx=(2, 0)
        )
        self.name_preview_label = ttk.Label(self.frm_naming, text="", foreground="#0a7d33")
        self.name_preview_label.grid(row=0, column=4, sticky="w", padx=(12, 0))
        ttk.Label(
            self.frm_naming,
            text="4 位编号，按文件顺序依次命名；请设为比卡里现有最大编号大的值。",
            foreground="#666666",
            wraplength=620,
            justify="left",
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))

        frm_quality = ttk.LabelFrame(self, text="⑤ 体积控制（可选）")
        frm_quality.pack(fill="x", **pad)
        frm_quality.columnconfigure(1, weight=1)
        ttk.Label(frm_quality, text="CRF 质量值：").grid(
            row=0, column=0, sticky="w", padx=(10, 2), pady=(6, 0)
        )
        ttk.Entry(frm_quality, textvariable=self.crf, width=6).grid(
            row=0, column=1, sticky="w", pady=(6, 0)
        )
        ttk.Label(
            frm_quality,
            text="数值越小画质越好，推荐 23~28；留空则使用固定码率。",
            foreground="#666666",
            wraplength=620,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 4))

        ttk.Label(frm_quality, text="峰值码率上限(kbps)：").grid(
            row=2, column=0, sticky="w", padx=(10, 2), pady=(4, 0)
        )
        ttk.Entry(frm_quality, textvariable=self.max_bitrate, width=10).grid(
            row=2, column=1, sticky="w", pady=(4, 0)
        )
        ttk.Label(
            frm_quality,
            text="例如 20000 = 20Mbps；留空则跟随参考文件。",
            foreground="#666666",
            wraplength=620,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 6))

        btn_row = ttk.Frame(self)
        btn_row.pack(pady=(4, 4))
        self.start_btn = ttk.Button(btn_row, text="开始转换", command=self._start)
        self.start_btn.pack(side="left", padx=5)
        self.open_btn = ttk.Button(
            btn_row, text="打开输出位置", command=self._open_output, state="disabled"
        )
        self.open_btn.pack(side="left", padx=5)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 6))
        self.progress_label = ttk.Label(self, text="")
        self.progress_label.pack()

        frm_log = ttk.LabelFrame(self, text="日志")
        frm_log.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        frm_log.columnconfigure(0, weight=1)
        frm_log.rowconfigure(0, weight=1)
        self.log_text = tk.Text(frm_log, wrap="word", state="disabled", height=10)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        scroll = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.log_text.configure(yscrollcommand=scroll.set)

        self._on_mode_change()

    def _on_mode_change(self):
        if self.mode.get() == "single":
            self.frm_input.config(text="③ 输入：要导入的视频")
            self.input_btn.config(text="选择文件...")
            self.frm_output.config(text="④ 输出：转换后的文件名")
            self.output_btn.config(text="另存为...")
            self.frm_naming.grid_remove()
            self.name_preview_label.config(text="")
        else:
            self.frm_input.config(text="③ 输入：待转换视频所在文件夹")
            self.input_btn.config(text="选择文件夹...")
            self.frm_output.config(text="④ 输出：转换结果存放文件夹")
            self.output_btn.config(text="选择文件夹...")
            self.frm_naming.grid(
                row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8)
            )
            self._update_name_preview()

    def _bind_name_preview(self):
        for var in (self.prefix, self.start_number):
            var.trace_add("write", lambda *_: self._update_name_preview())

    def _update_name_preview(self):
        if self.mode.get() != "batch":
            self.name_preview_label.config(text="")
            return
        prefix = self.prefix.get().strip() or "DJI_"
        start_str = self.start_number.get().strip()
        try:
            start = int(start_str) if start_str else 900
        except ValueError:
            self.name_preview_label.config(text="起始编号无效", foreground="#b3261e")
            return
        self.name_preview_label.config(
            text=f"示例：{prefix}{start:04d}.MP4", foreground="#0a7d33"
        )

    # ------------------------------------------------------------ 文件选择
    def _pick_ref(self):
        p = filedialog.askopenfilename(
            title="选择参考原生文件",
            filetypes=[("视频文件", "*.mp4 *.MP4 *.mov *.MOV"), ("所有文件", "*.*")],
        )
        if p:
            self.ref_path.set(p)

    def _pick_input(self):
        if self.mode.get() == "single":
            p = filedialog.askopenfilename(
                title="选择要导入的第三方视频", filetypes=[("视频文件", "*.*")]
            )
        else:
            p = filedialog.askdirectory(title="选择存放待转换视频的文件夹")
        if p:
            self.input_path.set(p)
            if self.mode.get() == "single" and not self.output_path.get():
                self.output_path.set(str(Path(p).with_name("DJI_0900.MP4")))

    def _pick_output(self):
        if self.mode.get() == "single":
            p = filedialog.asksaveasfilename(
                title="另存为", defaultextension=".MP4", filetypes=[("MP4 文件", "*.MP4")]
            )
        else:
            p = filedialog.askdirectory(title="选择转换结果存放的文件夹")
        if p:
            self.output_path.set(p)

    def _open_output(self):
        target = getattr(self, "_open_dir", None)
        if target is None:
            out = self.output_path.get().strip()
            if out:
                p = Path(out)
                target = p if p.is_dir() else p.parent
        if target and Path(target).exists():
            os.startfile(str(target))
        else:
            messagebox.showinfo("提示", "还没有可打开的目录")

    # ------------------------------------------------------------ 日志/状态
    def _log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _refresh_ffmpeg_status(self):
        ffmpeg_path, ffprobe_path = find_ffmpeg()
        if ffmpeg_path and ffprobe_path:
            version = ffmpeg_version(ffmpeg_path) or str(ffmpeg_path)
            self.ffmpeg_status_var.set("ffmpeg 已就绪")
            self.status_label.config(fg="#0a7d33")
            self._log(f"ffmpeg 环境：{version}")
        else:
            self.ffmpeg_status_var.set("未检测到 ffmpeg，开始转换时会自动安装")
            self.status_label.config(fg="#b3261e")

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        self.install_btn.config(state=state)
        for w in (self.input_entry, self.input_btn, self.output_entry, self.output_btn):
            w.config(state=state)
        if running:
            self.open_btn.config(state="disabled")
        elif getattr(self, "_open_dir", None):
            self.open_btn.config(state="normal")

    # ------------------------------------------------------------ 安装 ffmpeg
    def _install_ffmpeg(self):
        if self.install_thread and self.install_thread.is_alive():
            return
        self.progress["value"] = 0
        self.progress_label.config(text="")
        self._set_running(True)
        self.install_thread = threading.Thread(target=self._install_worker, daemon=True)
        self.install_thread.start()

    def _install_worker(self):
        try:
            ffmpeg_path, ffprobe_path = ensure_ffmpeg(
                progress_callback=lambda pct, msg: self.msg_queue.put(("ffmpeg", (pct, msg)))
            )
            configure_ffmpeg(ffmpeg_path, ffprobe_path)
            self.msg_queue.put(("ffmpeg_ready", (str(ffmpeg_path), str(ffprobe_path))))
            self.msg_queue.put(("log", f"ffmpeg 环境就绪：{ffmpeg_path}"))
        except Exception as exc:
            self.msg_queue.put(("error", f"ffmpeg 安装失败：{exc}"))
        finally:
            self.msg_queue.put(("done", None))

    # ------------------------------------------------------------ 开始转换
    def _start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        if self.install_thread and self.install_thread.is_alive():
            messagebox.showinfo("提示", "正在准备 ffmpeg 环境，请稍候")
            return

        ref = self.ref_path.get().strip()
        inp = self.input_path.get().strip()
        out = self.output_path.get().strip()

        if not ref or not Path(ref).is_file():
            messagebox.showerror("错误", "请先选择一个有效的参考原生文件")
            return
        if not inp:
            messagebox.showerror("错误", "请选择输入")
            return
        if not out:
            messagebox.showerror("错误", "请选择输出位置")
            return

        crf_str = self.crf.get().strip()
        crf = int(crf_str) if crf_str else None
        if crf is not None and not (0 <= crf <= 51):
            messagebox.showerror("错误", "CRF 值必须在 0~51 之间")
            return

        max_br_str = self.max_bitrate.get().strip()
        max_br = int(max_br_str) * 1000 if max_br_str else None
        if max_br is not None and max_br < 1000:
            messagebox.showerror("错误", "码率上限至少为 1000 kbps")
            return

        prefix = self.prefix.get().strip() or "DJI_"
        start_num_str = self.start_number.get().strip()
        try:
            start_num = int(start_num_str) if start_num_str else 900
        except ValueError:
            messagebox.showerror("错误", "起始编号必须是数字")
            return

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.progress["value"] = 0
        self.progress_label.config(text="")
        self._open_dir = None
        self._set_running(True)

        mode = self.mode.get()
        self.worker_thread = threading.Thread(
            target=self._worker,
            args=(mode, ref, inp, out, start_num, crf, max_br, prefix),
            daemon=True,
        )
        self.worker_thread.start()

    def _worker(self, mode, ref, inp, out, start_num, crf, max_br, prefix):
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
                self._run_single(ref, Path(inp), Path(out), targets, crf, max_br)
            else:
                self._run_batch(ref, Path(inp), Path(out), targets, start_num, crf, max_br, prefix)

            self.msg_queue.put(("log", "\n处理结束。"))
        except Exception as exc:
            self.msg_queue.put(("error", f"{exc}\n\n{traceback.format_exc()}"))
        finally:
            self.msg_queue.put(("done", None))

    def _run_single(self, ref, inp, out, targets, crf, max_br):
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
        )
        self.msg_queue.put(("log", "容器移植中..."))
        graft(Path(ref), tmp_path, out)
        tmp_path.unlink(missing_ok=True)
        out_size = out.stat().st_size
        in_size = inp.stat().st_size
        ratio = out_size / in_size if in_size > 0 else 0
        self.msg_queue.put(
            ("log", f"完成 -> {out} ({out_size/1024/1024:.1f} MB, 体积比 {ratio:.2f}x)")
        )
        self.msg_queue.put(("openable", str(out.parent)))

    def _run_batch(self, ref, input_dir, output_dir, targets, start_num, crf, max_br, prefix):
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
                )
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

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    if len(payload) == 4:
                        name, percent, idx, total = payload
                        overall = ((idx - 1) + percent / 100.0) / total * 100
                        self.progress["value"] = overall
                        self.progress_label.config(text=f"[{idx}/{total}] {name}  {percent:5.1f}%")
                    else:
                        name, percent = payload
                        self.progress["value"] = percent
                        self.progress_label.config(text=f"{name}  {percent:5.1f}%")
                elif kind == "ffmpeg":
                    percent, msg = payload
                    self.progress["value"] = percent
                    self.progress_label.config(text=msg)
                    self.ffmpeg_status_var.set("正在准备 ffmpeg ...")
                    self.status_label.config(fg="#8a6d00")
                elif kind == "ffmpeg_ready":
                    self.ffmpeg_status_var.set("ffmpeg 已就绪")
                    self.status_label.config(fg="#0a7d33")
                elif kind == "openable":
                    self._open_dir = Path(payload)
                elif kind == "error":
                    self._log(f"错误: {payload}")
                    messagebox.showerror("出错了", str(payload).split("\n\n")[0])
                elif kind == "done":
                    self._set_running(False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return
    _enable_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
