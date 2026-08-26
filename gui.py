#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DJI 视频批量转换工具 - 图形界面
依赖 tkinter（内置）和 queue、threading 等标准库。
"""

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import threading
import queue
import sys
import os

# 导入转换核心模块（必须与这三个 .py 文件在同一目录）
import batch_dji_graft


class StreamRedirector:
    """将写入 stdout/stderr 的内容放入队列，供 UI 线程消费"""
    def __init__(self, queue_obj):
        self.queue = queue_obj

    def write(self, msg):
        if msg:
            self.queue.put(msg)

    def flush(self):
        pass


class ConversionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DJI 视频批量转换工具")
        self.root.geometry("700x600")
        self.queue = queue.Queue()
        self.running = False
        self.build_ui()
        self.process_queue()

    def build_ui(self):
        row = 0

        # ---- 参考文件 ----
        tk.Label(self.root, text="参考文件:").grid(row=row, column=0, sticky='e', padx=5, pady=5)
        self.ref_entry = tk.Entry(self.root, width=50)
        self.ref_entry.grid(row=row, column=1, padx=5, pady=5)
        tk.Button(self.root, text="浏览...", command=self.browse_ref).grid(row=row, column=2, padx=5, pady=5)
        row += 1

        # ---- 输入文件夹 ----
        tk.Label(self.root, text="输入文件夹:").grid(row=row, column=0, sticky='e', padx=5, pady=5)
        self.input_entry = tk.Entry(self.root, width=50)
        self.input_entry.grid(row=row, column=1, padx=5, pady=5)
        tk.Button(self.root, text="浏览...", command=self.browse_input_dir).grid(row=row, column=2, padx=5, pady=5)
        row += 1

        # ---- 输出文件夹 ----
        tk.Label(self.root, text="输出文件夹:").grid(row=row, column=0, sticky='e', padx=5, pady=5)
        self.output_entry = tk.Entry(self.root, width=50)
        self.output_entry.grid(row=row, column=1, padx=5, pady=5)
        tk.Button(self.root, text="浏览...", command=self.browse_output_dir).grid(row=row, column=2, padx=5, pady=5)
        row += 1

        # ---- 起始编号 ----
        tk.Label(self.root, text="起始编号:").grid(row=row, column=0, sticky='e', padx=5, pady=5)
        self.start_spin = tk.Spinbox(self.root, from_=1, to=9999, width=10)
        self.start_spin.delete(0, tk.END)
        self.start_spin.insert(0, "900")
        self.start_spin.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1

        # ---- 前缀 ----
        tk.Label(self.root, text="前缀:").grid(row=row, column=0, sticky='e', padx=5, pady=5)
        self.prefix_entry = tk.Entry(self.root, width=10)
        self.prefix_entry.insert(0, "DJI_")
        self.prefix_entry.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1

        # ---- 选项：保留临时文件 ----
        self.keep_temp_var = tk.IntVar()
        tk.Checkbutton(self.root, text="保留临时文件", variable=self.keep_temp_var).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=5, pady=5
        )
        row += 1

        # ---- 开始按钮 ----
        self.start_button = tk.Button(self.root, text="开始转换", command=self.start_conversion, bg="lightblue")
        self.start_button.grid(row=row, column=0, columnspan=3, pady=10)
        row += 1

        # ---- 日志区域 ----
        self.log_text = scrolledtext.ScrolledText(self.root, width=80, height=20, state='normal')
        self.log_text.grid(row=row, column=0, columnspan=3, padx=5, pady=5)
        row += 1

        # ---- 状态栏 ----
        self.status_label = tk.Label(self.root, text="就绪", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.grid(row=row, column=0, columnspan=3, sticky='we')

    # -------- 文件/文件夹浏览 --------
    def browse_ref(self):
        f = filedialog.askopenfilename(title="选择参考文件", filetypes=[("MP4 文件", "*.mp4"), ("所有文件", "*.*")])
        if f:
            self.ref_entry.delete(0, tk.END)
            self.ref_entry.insert(0, f)

    def browse_input_dir(self):
        d = filedialog.askdirectory(title="选择输入文件夹")
        if d:
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, d)

    def browse_output_dir(self):
        d = filedialog.askdirectory(title="选择输出文件夹")
        if d:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, d)

    # -------- 启动转换（在子线程中执行） --------
    def start_conversion(self):
        if self.running:
            return

        # 获取参数
        ref = self.ref_entry.get().strip()
        input_dir = self.input_entry.get().strip()
        output_dir = self.output_entry.get().strip()
        start_str = self.start_spin.get().strip()
        prefix = self.prefix_entry.get().strip()
        keep_temp = bool(self.keep_temp_var.get())

        # 校验
        if not ref:
            messagebox.showerror("错误", "请选择参考文件")
            return
        if not input_dir:
            messagebox.showerror("错误", "请选择输入文件夹")
            return
        if not output_dir:
            messagebox.showerror("错误", "请选择输出文件夹")
            return
        try:
            start_num = int(start_str)
        except ValueError:
            messagebox.showerror("错误", "起始编号必须为整数")
            return
        if not prefix:
            prefix = "DJI_"

        # 禁用按钮，清空日志
        self.start_button.config(state=tk.DISABLED)
        self.status_label.config(text="转换中...")
        self.log_text.delete(1.0, tk.END)

        self.running = True
        # 启动子线程
        thread = threading.Thread(
            target=self.run_conversion,
            args=(ref, input_dir, output_dir, start_num, prefix, keep_temp),
            daemon=True
        )
        thread.start()

    def run_conversion(self, ref, input_dir, output_dir, start, prefix, keep_temp):
        """子线程中执行实际转换"""
        # 备份原 sys.argv，并构造虚拟命令行参数
        old_argv = sys.argv
        sys.argv = [
            'batch_dji_graft.py',
            '--ref', ref,
            '--input-dir', input_dir,
            '--output-dir', output_dir,
            '--start', str(start),
            '--prefix', prefix
        ]
        if keep_temp:
            sys.argv.append('--keep-temp')

        # 重定向 stdout / stderr 到队列
        redirector = StreamRedirector(self.queue)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = redirector
        sys.stderr = redirector

        try:
            # 调用核心主函数
            batch_dji_graft.main()
        except SystemExit as e:
            # 脚本中调用 sys.exit() 会抛出此异常
            if e.code != 0:
                self.queue.put(f"程序退出，代码 {e.code}\n")
        except Exception as e:
            self.queue.put(f"发生异常: {e}\n")
            import traceback
            self.queue.put(traceback.format_exc())
        finally:
            # 恢复
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.running = False
            # 通知主线程更新 UI
            self.root.after(0, self.conversion_finished)

    def conversion_finished(self):
        """转换结束（无论成功失败）恢复按钮状态"""
        self.start_button.config(state=tk.NORMAL)
        self.status_label.config(text="就绪")
        self.queue.put("\n===== 转换处理结束 =====\n")

    # -------- 定时从队列取日志并显示 --------
    def process_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                self.log_text.insert(tk.END, msg)
                self.log_text.see(tk.END)   # 自动滚动到底部
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)


# -------- 启动 GUI --------
if __name__ == "__main__":
    root = tk.Tk()
    app = ConversionApp(root)
    root.mainloop()