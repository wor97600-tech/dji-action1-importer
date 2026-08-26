#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dji_graft_gui.py — dji_graft.py / batch_dji_graft.py 的图形界面版本。
只用标准库 tkinter，不依赖任何第三方 GUI 库。
"""
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from dji_graft import check_tools, get_ref_targets, transcode, graft, get_input_video_bitrate

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".wmv", ".flv"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("第三方视频导入运动相机工具")
        self.geometry("640x620")
        self.resizable(False, False)

        self.ref_path = tk.StringVar()
        self.mode = tk.StringVar(value="single")
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.start_number = tk.StringVar(value="900")
        self.crf = tk.StringVar(value="23")
        self.max_bitrate = tk.StringVar(value="")

        self.msg_queue = queue.Queue()
        self.worker_thread = None

        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        frm_ref = ttk.LabelFrame(self, text="① 参考原生文件（相机自己拍的、能正常播放的一个文件）")
        frm_ref.pack(fill="x", **pad)
        ttk.Entry(frm_ref, textvariable=self.ref_path).pack(side="left", fill="x", expand=True, padx=(10, 5), pady=8)
        ttk.Button(frm_ref, text="选择文件...", command=self._pick_ref).pack(side="left", padx=(0, 10))

        frm_mode = ttk.LabelFrame(self, text="② 选择模式")
        frm_mode.pack(fill="x", **pad)
        ttk.Radiobutton(frm_mode, text="单个文件", variable=self.mode, value="single",
                         command=self._on_mode_change).pack(side="left", padx=10, pady=6)
        ttk.Radiobutton(frm_mode, text="批量（整个文件夹）", variable=self.mode, value="batch",
                         command=self._on_mode_change).pack(side="left", padx=10, pady=6)

        self.frm_input = ttk.LabelFrame(self, text="③ 输入")
        self.frm_input.pack(fill="x", **pad)
        self.input_entry = ttk.Entry(self.frm_input, textvariable=self.input_path)
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=8)
        self.input_btn = ttk.Button(self.frm_input, text="选择文件...", command=self._pick_input)
        self.input_btn.pack(side="left", padx=(0, 10))

        self.frm_output = ttk.LabelFrame(self, text="④ 输出")
        self.frm_output.pack(fill="x", **pad)
        self.output_entry = ttk.Entry(self.frm_output, textvariable=self.output_path)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=8)
        self.output_btn = ttk.Button(self.frm_output, text="另存为...", command=self._pick_output)
        self.output_btn.pack(side="left", padx=(0, 10))

        self.frm_start = ttk.Frame(self.frm_output)
        ttk.Label(self.frm_start, text="起始编号：").pack(side="left")
        ttk.Entry(self.frm_start, textvariable=self.start_number, width=8).pack(side="left")
        ttk.Label(self.frm_start, text="（比 SD 卡里现有文件最大编号大即可）").pack(side="left", padx=(4, 0))

        frm_quality = ttk.LabelFrame(self, text="⑤ 体积控制（可选）")
        frm_quality.pack(fill="x", **pad)
        
        frm_crf = ttk.Frame(frm_quality)
        frm_crf.pack(fill="x", padx=10, pady=(6, 2))
        ttk.Label(frm_crf, text="CRF 质量值：").pack(side="left")
        ttk.Entry(frm_crf, textvariable=self.crf, width=6).pack(side="left", padx=(4, 0))
        ttk.Label(frm_crf, text="（越小画质越好，推荐 23~28，留空则使用固定码率）").pack(side="left", padx=(6, 0))

        frm_br = ttk.Frame(frm_quality)
        frm_br.pack(fill="x", padx=10, pady=(2, 6))
        ttk.Label(frm_br, text="峰值码率上限(kbps)：").pack(side="left")
        ttk.Entry(frm_br, textvariable=self.max_bitrate, width=10).pack(side="left", padx=(4, 0))
        ttk.Label(frm_br, text="（例如 20000 = 20Mbps，留空则跟随参考文件）").pack(side="left", padx=(6, 0))

        self.start_btn = ttk.Button(self, text="开始转换", command=self._start)
        self.start_btn.pack(pady=(4, 4))

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(0, 6))
        self.progress_label = ttk.Label(self, text="")
        self.progress_label.pack()

        frm_log = ttk.LabelFrame(self, text="日志")
        frm_log.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self.log_text = tk.Text(frm_log, height=12, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

        self._on_mode_change()

    def _on_mode_change(self):
        if self.mode.get() == "single":
            self.frm_input.config(text="③ 输入：要导入的第三方视频")
            self.input_btn.config(text="选择文件...")
            self.frm_output.config(text="④ 输出：转换后的文件名")
            self.output_btn.config(text="另存为...")
            self.frm_start.pack_forget()
        else:
            self.frm_input.config(text="③ 输入：存放待转换视频的文件夹")
            self.input_btn.config(text="选择文件夹...")
            self.frm_output.config(text="④ 输出：转换结果存放的文件夹")
            self.output_btn.config(text="选择文件夹...")
            self.frm_start.pack(fill="x", padx=10, pady=(0, 8))

    def _pick_ref(self):
        p = filedialog.askopenfilename(title="选择参考原生文件",
                                        filetypes=[("视频文件", "*.mp4 *.MP4 *.mov *.MOV"), ("所有文件", "*.*")])
        if p:
            self.ref_path.set(p)

    def _pick_input(self):
        if self.mode.get() == "single":
            p = filedialog.askopenfilename(title="选择要导入的第三方视频", filetypes=[("视频文件", "*.*")])
        else:
            p = filedialog.askdirectory(title="选择存放待转换视频的文件夹")
        if p:
            self.input_path.set(p)
            if self.mode.get() == "single" and not self.output_path.get():
                default_out = str(Path(p).with_name("DJI_0900.MP4"))
                self.output_path.set(default_out)

    def _pick_output(self):
        if self.mode.get() == "single":
            p = filedialog.asksaveasfilename(title="另存为", defaultextension=".MP4",
                                              filetypes=[("MP4 文件", "*.MP4")])
        else:
            p = filedialog.askdirectory(title="选择转换结果存放的文件夹")
        if p:
            self.output_path.set(p)

    def _log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        for w in (self.input_entry, self.input_btn, self.output_entry, self.output_btn):
            w.config(state=state)

    def _start(self):
        if self.worker_thread and self.worker_thread.is_alive():
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

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.progress["value"] = 0
        self.progress_label.config(text="")
        self._set_running(True)

        mode = self.mode.get()
        start_num_str = self.start_number.get().strip()
        try:
            start_num = int(start_num_str) if start_num_str else 900
        except ValueError:
            start_num = 900

        self.worker_thread = threading.Thread(
            target=self._worker, args=(mode, ref, inp, out, start_num, crf, max_br), daemon=True)
        self.worker_thread.start()

    def _worker(self, mode, ref, inp, out, start_num, crf, max_br):
        try:
            check_tools()
        except SystemExit:
            self.msg_queue.put(("error", "没有找到 ffmpeg/ffprobe，请确认它们和本程序在同一个文件夹里，"
                                          "或已加入系统 PATH。"))
            self.msg_queue.put(("done", None))
            return

        try:
            self.msg_queue.put(("log", f"读取参考文件编码参数: {ref}"))
            targets = get_ref_targets(Path(ref))
            
            if mode == "single":
                input_vb = get_input_video_bitrate(Path(inp))
                if input_vb > 0 and targets["video_bitrate"] > input_vb * 3 and crf is None:
                    self.msg_queue.put(("log", f"提示：参考码率 {targets['video_bitrate']//1000}kbps "
                                                f"远高于输入 {input_vb//1000}kbps，建议启用 CRF 以减小体积"))

            self.msg_queue.put(("log", f"目标规格: {targets['width']}x{targets['height']} "
                                        f"@ {targets['fps']}fps, 音频 {targets['sample_rate']}Hz/"
                                        f"{targets['channels']}ch"))

            if mode == "single":
                self._run_single(ref, Path(inp), Path(out), targets, crf, max_br)
            else:
                self._run_batch(ref, Path(inp), Path(out), targets, start_num, crf, max_br)

            self.msg_queue.put(("log", "\n处理结束。"))
        except Exception as e:
            self.msg_queue.put(("error", f"{e}\n\n{traceback.format_exc()}"))
        finally:
            self.msg_queue.put(("done", None))

    def _run_single(self, ref, inp, out, targets, crf, max_br):
        tmp_path = out.with_suffix(".reencoded_tmp.mp4")
        self.msg_queue.put(("log", f"转码中: {inp.name} (CRF={crf if crf is not None else '固定码率'}, "
                                    f"峰值上限={max_br//1000 if max_br else '参考文件'}kbps)"))
        transcode(inp, tmp_path, targets, progress_callback=lambda p: self.msg_queue.put(("progress", (inp.name, p))),
                  crf=crf, max_video_bitrate=max_br)
        self.msg_queue.put(("log", "容器移植中..."))
        graft(Path(ref), tmp_path, out)
        tmp_path.unlink(missing_ok=True)
        out_size = out.stat().st_size
        in_size = inp.stat().st_size
        ratio = out_size / in_size if in_size > 0 else 0
        self.msg_queue.put(("log", f"完成 -> {out} ({out_size/1024/1024:.1f} MB, 体积比 {ratio:.2f}x)"))

    def _run_batch(self, ref, input_dir, output_dir, targets, start_num, crf, max_br):
        output_dir.mkdir(parents=True, exist_ok=True)
        videos = sorted(p for p in input_dir.iterdir()
                         if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
        if not videos:
            self.msg_queue.put(("log", "文件夹里没有找到支持的视频文件"))
            return

        self.msg_queue.put(("log", f"共发现 {len(videos)} 个文件，从编号 {start_num} 开始命名"))
        number = start_num
        ok_count, fail_count = 0, 0

        for idx, video in enumerate(videos, 1):
            out_name = f"DJI_{number:04d}.MP4"
            out_path = output_dir / out_name
            tmp_path = out_path.with_suffix(".reencoded_tmp.mp4")
            self.msg_queue.put(("log", f"\n[{idx}/{len(videos)}] {video.name} -> {out_name}"))
            try:
                transcode(video, tmp_path, targets,
                          progress_callback=lambda p, n=video.name: self.msg_queue.put(("progress", (n, p))),
                          crf=crf, max_video_bitrate=max_br)
                graft(Path(ref), tmp_path, out_path)
                out_size = out_path.stat().st_size
                in_size = video.stat().st_size
                ratio = out_size / in_size if in_size > 0 else 0
                self.msg_queue.put(("log", f"  完成 ✅ ({out_size/1024/1024:.1f} MB, 比 {ratio:.2f}x)"))
                ok_count += 1
            except Exception as e:
                self.msg_queue.put(("log", f"  失败 ❌ {e}"))
                fail_count += 1
            finally:
                tmp_path.unlink(missing_ok=True)
            number += 1

        self.msg_queue.put(("log", f"\n批量转换完成：成功 {ok_count} 个，失败 {fail_count} 个"))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    name, percent = payload
                    self.progress["value"] = percent
                    self.progress_label.config(text=f"{name}  {percent:5.1f}%")
                elif kind == "error":
                    self._log(f"错误: {payload}")
                    messagebox.showerror("出错了", str(payload).split("\n\n")[0])
                elif kind == "done":
                    self._set_running(False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
