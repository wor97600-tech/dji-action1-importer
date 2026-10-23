"""Flat desktop shell. Encoding and container work remain in dji_graft_gui.App.

Constraint brief (§2.1/§2.8/§3.6): primary = file selection + Start;
secondary = encoding + progress; tertiary = help + logs. One primary action.
Grayscale structure: two columns above a non-scrolling action footer.
Tokens: generated neutral/brand ramps; spacing 4/8/12/16/24/32/48;
two weights; three neutral text tiers; no shadows or decorative borders.
"""
import ctypes
import os
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ffmpeg_env import ensure_ffmpeg, find_ffmpeg, ffmpeg_version
from dji_graft import configure_ffmpeg
from utils import find_input_videos
from ui_model import validate_form
from ui_theme import COLORS as C, FONT

VERSION = 'v5.0'
MODES = {'CPU · 原版': 'cpu', '自动选择 · 显卡优先': 'auto',
         'NVIDIA NVENC': 'h264_nvenc', 'Intel Quick Sync': 'h264_qsv', 'AMD AMF': 'h264_amf'}


class DesktopUI:
    def __init__(self):
        super().__init__()
        self.title('DJI Graft · 视频导入工具 ' + VERSION)
        self.configure(bg=C['bg'])
        area = (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        if sys.platform == 'win32':
            try:
                from ctypes import wintypes
                rect = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                    area = (rect.left, rect.top, rect.right, rect.bottom)
            except (OSError, AttributeError): pass
        aw, ah = area[2]-area[0], area[3]-area[1]
        self.ui_scale = min(1.0, (aw-32)/1080, (ah-56)/700)
        self.u = lambda x: max(1, round(x*self.ui_scale))
        w, h = self.u(1080), self.u(700)
        self.geometry(f'{w}x{h}+{area[0]+max(0,(aw-w)//2)}+{area[1]+max(0,(ah-h)//2)}')
        self.minsize(self.u(920), self.u(630))
        self._running = False
        self._had_error = False
        self._task_kind = 'conversion'
        self._mode_active = 'single'
        self._mode_paths = {'single': ('',''), 'batch': ('','')}
        self._open_dir = None
        self.worker_thread = self.install_thread = None
        self.msg_queue = queue.Queue()
        self.ref_path = tk.StringVar()
        self.mode = tk.StringVar(value='single')
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.prefix = tk.StringVar(value='DJI_')
        self.start_number = tk.StringVar(value='0900')
        self.crf = tk.StringVar(value='23')
        self.max_bitrate = tk.StringVar(value='2000')
        self.acceleration = tk.StringVar(value='自动选择 · 显卡优先')
        self.ffmpeg_status_var = tk.StringVar(value='正在检查环境…')
        self.hint_var = tk.StringVar(value='准备就绪后，点击右下角开始转换。')
        self._controls = []
        self._set_theme()
        self._set_icon()
        self._build_ui()
        for var in (self.prefix,self.start_number):
            var.trace_add('write',lambda *_: self._update_name_preview())
        self.acceleration.trace_add('write', lambda *_: self._update_encoder_hint())
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.bind('<Control-Return>', lambda e: self._start())
        self._poll_id = self.after(100,self._poll_queue)
        self.after(80,self._refresh_ffmpeg_status)

    def _set_theme(self):
        u=self.u
        style=ttk.Style(self); style.theme_use('clam')
        self.option_add('*Font',(FONT,-u(14)))
        style.configure('.',font=(FONT,-u(14)),background=C['surface'],foreground=C['text'])
        style.configure('TFrame',background=C['surface'])
        style.configure('Page.TFrame',background=C['bg'])
        style.configure('TLabel',background=C['surface'],foreground=C['text'])
        style.configure('Muted.TLabel',foreground=C['muted'],font=(FONT,-u(12)))
        style.configure('Title.TLabel',font=(FONT,-u(20),'bold'))
        style.configure('Section.TLabel',font=(FONT,-u(14),'bold'))
        style.configure('TButton',padding=(u(12),u(7)),borderwidth=1,relief='solid',background=C['tint'],foreground=C['action'],bordercolor=C['action'],lightcolor=C['action'],darkcolor=C['action'],font=(FONT,-u(14),'bold'))
        style.map('TButton',background=[('disabled',C['bg']),('pressed',C['border']),('active',C['border'])],foreground=[('disabled',C['muted'])],bordercolor=[('disabled',C['border']),('!disabled',C['action'])])
        style.configure('Primary.TButton',background=C['action'],foreground=C['surface'],font=(FONT,-u(16),'bold'),padding=(u(24),u(12)))
        style.map('Primary.TButton',background=[('disabled',C['border']),('active',C['hover'])],foreground=[('disabled',C['secondary']),('!disabled',C['surface'])])
        style.configure('TEntry',padding=(u(8),u(7)),fieldbackground=C['bg'],bordercolor=C['border'],lightcolor=C['border'],darkcolor=C['border'])
        style.configure('TCombobox',padding=(u(8),u(6)),fieldbackground=C['bg'],arrowsize=u(12))
        style.map('TCombobox',fieldbackground=[('readonly',C['bg'])],foreground=[('readonly',C['text'])])
        style.configure('Mode.TRadiobutton',padding=(u(12),u(8)),background=C['bg'])
        style.map('Mode.TRadiobutton',background=[('selected',C['tint'])],foreground=[('selected',C['action'])])
        style.configure('Horizontal.TProgressbar',background=C['action'],troughcolor=C['bg'],borderwidth=0,thickness=u(6))

    def _set_icon(self):
        assets=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'
        try:
            self._icon_image=tk.PhotoImage(file=str(assets/'app-icon.png'))
            self.iconphoto(True,self._icon_image)
            if sys.platform=='win32':self.iconbitmap(str(assets/'app-icon.ico'))
            self._mark=tk.PhotoImage(file=str(assets/'app-mark.png'))
        except tk.TclError:
            self._mark=None

    def _entry(self,parent,var,width=16):
        e=ttk.Entry(parent,textvariable=var,width=width);self._controls.append(e);return e

    def _button(self,parent,text,command):
        b=ttk.Button(parent,text=text,command=command);self._controls.append(b);return b

    def _build_ui(self):
        u=self.u
        self.columnconfigure(0,weight=1);self.rowconfigure(1,weight=1)
        header=ttk.Frame(self,padding=(u(24),u(12)))
        header.grid(row=0,column=0,sticky='ew');header.columnconfigure(1,weight=1)
        if self._mark:ttk.Label(header,image=self._mark).grid(row=0,column=0,rowspan=2,padx=(0,u(12)))
        ttk.Label(header,text='DJI Graft',style='Title.TLabel').grid(row=0,column=1,sticky='w')
        ttk.Label(header,text='让你的视频，在相机里播放',style='Muted.TLabel').grid(row=1,column=1,sticky='w')
        ttk.Label(header,text=VERSION+'  ·  Windows',style='Muted.TLabel').grid(row=0,column=2,rowspan=2)

        body=ttk.Frame(self,style='Page.TFrame',padding=(u(16),u(12)))
        body.grid(row=1,column=0,sticky='nsew');body.rowconfigure(0,weight=1)
        body.columnconfigure(0,weight=3,uniform='body');body.columnconfigure(1,weight=2,uniform='body')
        left=ttk.Frame(body,padding=u(16));left.grid(row=0,column=0,sticky='nsew',padx=(0,u(12)));left.columnconfigure(0,weight=1)
        right=ttk.Frame(body,padding=u(16));right.grid(row=0,column=1,sticky='nsew');right.columnconfigure(0,weight=1);right.rowconfigure(4,weight=1)
        modebar=ttk.Frame(left);modebar.grid(row=0,column=0,sticky='ew',pady=(0,u(12)))
        for col,(title,value) in enumerate((('单个视频','single'),('批量转换','batch'))):
            b=ttk.Radiobutton(modebar,text=title,variable=self.mode,value=value,command=self._on_mode_change,style='Mode.TRadiobutton')
            b.grid(row=0,column=col,sticky='ew',padx=(0,u(8)));self._controls.append(b)

        def path_group(row,title,var,command,button):
            f=ttk.Frame(left);f.grid(row=row,column=0,sticky='ew',pady=(0,u(12)));f.columnconfigure(0,weight=1)
            title_label=ttk.Label(f,text=title,style='Section.TLabel');title_label.grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,u(4)))
            e=self._entry(f,var);e.grid(row=1,column=0,sticky='ew',padx=(0,u(8)))
            b=self._button(f,button,command);b.grid(row=1,column=1)
            return f,title_label,e,b
        self.frm_ref,_,self.ref_entry,self.ref_btn=path_group(1,'01  相机参考视频',self.ref_path,self._pick_ref,'选择参考')
        ttk.Label(self.frm_ref,text='选择相机拍摄的原生 MP4，沿用其格式参数。',style='Muted.TLabel').grid(row=2,column=0,columnspan=2,sticky='w',pady=(u(4),0))
        self.frm_input,self.input_title,self.input_entry,self.input_btn=path_group(2,'02  待转换视频',self.input_path,self._pick_input,'选择视频')
        self.frm_output,self.output_title,self.output_entry,self.output_btn=path_group(3,'03  输出文件',self.output_path,self._pick_output,'保存到')
        self.frm_naming=ttk.Frame(left);self.frm_naming.grid(row=4,column=0,sticky='ew',pady=(0,u(12)))
        ttk.Label(self.frm_naming,text='前缀',style='Muted.TLabel').grid(row=0,column=0,padx=(0,u(4)))
        self._entry(self.frm_naming,self.prefix,8).grid(row=0,column=1,padx=(0,u(12)))
        ttk.Label(self.frm_naming,text='起始编号',style='Muted.TLabel').grid(row=0,column=2,padx=(0,u(4)))
        self._entry(self.frm_naming,self.start_number,6).grid(row=0,column=3)
        self.name_preview_label=ttk.Label(self.frm_naming,text='',style='Muted.TLabel');self.name_preview_label.grid(row=0,column=4,padx=(u(8),0))
        self.frm_naming.grid_remove()

        quality=ttk.Frame(right);quality.grid(row=0,column=0,sticky='ew',pady=(0,u(12)));quality.columnconfigure(0,weight=1);quality.columnconfigure(1,weight=1)
        ttk.Label(quality,text='04  编码与画质',style='Section.TLabel').grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,u(8)))
        self.acceleration_box=ttk.Combobox(quality,textvariable=self.acceleration,values=list(MODES),state='readonly',width=24)
        self.acceleration_box.grid(row=1,column=0,columnspan=2,sticky='ew')
        ttk.Label(quality,text='CRF · CPU 画质',style='Muted.TLabel').grid(row=2,column=0,sticky='w',pady=(u(8),u(4)))
        ttk.Label(quality,text='码率上限 · kbps',style='Muted.TLabel').grid(row=2,column=1,sticky='w',pady=(u(8),u(4)))
        self.crf_entry=self._entry(quality,self.crf,8);self.crf_entry.grid(row=3,column=0,sticky='ew',padx=(0,u(12)))
        self.bitrate_entry=self._entry(quality,self.max_bitrate,10);self.bitrate_entry.grid(row=3,column=1,sticky='ew')
        self.encoder_hint=ttk.Label(quality,style='Muted.TLabel',wraplength=u(320),justify='left')
        self.encoder_hint.grid(row=4,column=0,columnspan=2,sticky='w',pady=(u(8),0));self._update_encoder_hint()

        self.status_label=tk.Label(right,textvariable=self.ffmpeg_status_var,bg=C['tint'],fg=C['action'],anchor='w',padx=u(8),pady=u(6),font=(FONT,-u(12)))
        self.status_label.grid(row=1,column=0,sticky='ew',pady=(0,u(8)))
        self.install_btn=ttk.Button(right,text='检查 / 准备 FFmpeg',command=self._install_ffmpeg);self.install_btn.grid(row=2,column=0,sticky='ew',pady=(0,u(12)))
        tools=ttk.Frame(right);tools.grid(row=3,column=0,sticky='ew',pady=(0,u(8)));tools.columnconfigure(0,weight=1)
        ttk.Label(tools,text='运行日志',style='Section.TLabel').grid(row=0,column=0,sticky='w')
        self.copy_btn=ttk.Button(tools,text='复制日志',command=self._copy_log);self.copy_btn.grid(row=0,column=1)
        self.save_btn=ttk.Button(tools,text='保存日志',command=self._save_log);self.save_btn.grid(row=0,column=2,padx=(u(8),0))
        logframe=ttk.Frame(right);logframe.grid(row=4,column=0,sticky='nsew');logframe.rowconfigure(0,weight=1);logframe.columnconfigure(0,weight=1)
        self.log_text=tk.Text(logframe,wrap='word',state='disabled',height=4,width=1,bg=C['bg'],fg=C['secondary'],relief='flat',borderwidth=0,padx=u(12),pady=u(12),font=(FONT,-u(12)),spacing3=u(4))
        self.log_text.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(logframe,command=self.log_text.yview);scroll.grid(row=0,column=1,sticky='ns');self.log_text.config(yscrollcommand=scroll.set)

        self.footer=ttk.Frame(self,padding=(u(24),u(12)))
        self.footer.grid(row=2,column=0,sticky='ew');self.footer.columnconfigure(0,weight=1)
        self.progress_label=ttk.Label(self.footer,text='等待开始',style='Section.TLabel');self.progress_label.grid(row=0,column=0,sticky='w')
        self.progress=ttk.Progressbar(self.footer,mode='determinate',maximum=100);self.progress.grid(row=1,column=0,sticky='ew',pady=(u(8),u(4)),padx=(0,u(24)))
        self.hint_label=ttk.Label(self.footer,textvariable=self.hint_var,style='Muted.TLabel',wraplength=u(600));self.hint_label.grid(row=2,column=0,sticky='w')
        self.open_btn=ttk.Button(self.footer,text='打开输出位置',command=self._open_output,state='disabled');self.open_btn.grid(row=0,column=1,rowspan=3,padx=(0,u(12)))
        self.start_btn=ttk.Button(self.footer,text='开始转换  →',style='Primary.TButton',command=self._start);self.start_btn.grid(row=0,column=2,rowspan=3)
        self._log('欢迎使用 DJI Graft。选择参考视频和输入内容后即可开始。')

    def _update_encoder_hint(self):
        if not hasattr(self,'encoder_hint'):return
        cpu=MODES.get(self.acceleration.get())=='cpu'
        self.encoder_hint.config(text='CRF 越小画质越高，仅 CPU 使用。\n默认码率上限 2000 kbps（2 Mbps）。\n码率留空跟随参考视频。' if cpu else '显卡优先，失败自动回退 CPU。\n默认码率上限 2000 kbps（2 Mbps）。\nCRF 仅用于 CPU；码率留空跟随参考。')

    def _on_mode_change(self):
        new=self.mode.get()
        if self._running:return
        if new!=self._mode_active:
            self._mode_paths[self._mode_active]=(self.input_path.get(),self.output_path.get())
            self.input_path.set(self._mode_paths[new][0]);self.output_path.set(self._mode_paths[new][1]);self._mode_active=new
        batch=new=='batch'
        self.input_title.config(text='02  输入文件夹' if batch else '02  待转换视频')
        self.output_title.config(text='03  输出文件夹' if batch else '03  输出文件')
        self.input_btn.config(text='选择文件夹' if batch else '选择视频')
        self.output_btn.config(text='选择文件夹' if batch else '保存到')
        if batch:self.frm_naming.grid()
        else:self.frm_naming.grid_remove()
        self._update_name_preview()

    def _update_name_preview(self):
        try:
            n=int(self.start_number.get() or '900')
            text=f'{self.prefix.get() or "DJI_"}{n:04d}.MP4' if 0<=n<=9999 else '编号 0–9999'
        except ValueError:text='编号须为整数'
        self.name_preview_label.config(text=text)

    def _pick_ref(self):
        p=filedialog.askopenfilename(parent=self,title='选择相机原生参考视频',filetypes=[('MP4 视频','*.mp4 *.MP4'),('所有文件','*.*')])
        if p:self.ref_path.set(p)

    def _pick_input(self):
        p=filedialog.askopenfilename(parent=self,title='选择待转换视频') if self.mode.get()=='single' else filedialog.askdirectory(parent=self,title='选择输入文件夹')
        if p:
            self.input_path.set(p)
            if not self.output_path.get():
                self.output_path.set(str(Path(p).with_name('DJI_0900.MP4')) if self.mode.get()=='single' else str(Path(p)/'DJI_Output'))

    def _pick_output(self):
        p=filedialog.asksaveasfilename(parent=self,title='保存转换后视频',initialfile='DJI_0900.MP4',defaultextension='.MP4',filetypes=[('MP4 视频','*.MP4')]) if self.mode.get()=='single' else filedialog.askdirectory(parent=self,title='选择输出文件夹')
        if p:self.output_path.set(p)

    def _open_output(self):
        if self._open_dir and Path(self._open_dir).exists():os.startfile(str(self._open_dir))

    def _log(self,text):
        self.log_text.config(state='normal');self.log_text.insert('end',text+'\n');self.log_text.see('end');self.log_text.config(state='disabled')

    def _copy_log(self):
        self.clipboard_clear();self.clipboard_append(self.log_text.get('1.0','end-1c'));self.hint_var.set('日志已复制。')

    def _save_log(self):
        p=filedialog.asksaveasfilename(parent=self,title='保存日志',initialfile='DJIGraft-log.txt',defaultextension='.txt')
        if p:
            try:Path(p).write_text(self.log_text.get('1.0','end-1c'),encoding='utf-8');self.hint_var.set('日志已保存。')
            except OSError as exc:self._show_error(str(exc))

    def _show_error(self,text):
        self._had_error=True;self.hint_var.set(text.split('\n')[0]);self.hint_label.config(foreground=C['error']);self._log('错误：'+text)

    def _refresh_ffmpeg_status(self):
        def check():
            a,b=find_ffmpeg()
            version=ffmpeg_version(a) if a and b else None
            self.msg_queue.put(('env_checked',(bool(version),version)))
        threading.Thread(target=check,daemon=True).start()

    def _set_running(self,running):
        self._running=running
        for w in self._controls:w.config(state='disabled' if running else 'normal')
        self.acceleration_box.config(state='disabled' if running else 'readonly')
        self.start_btn.config(state='disabled' if running else 'normal',text='正在处理…' if running else '开始转换  →')
        self.install_btn.config(state='disabled' if running else 'normal')
        self.open_btn.config(state='normal' if not running and self._open_dir else 'disabled')

    def _install_ffmpeg(self):
        if self._running:return
        self._task_kind='install';self._had_error=False;self._set_running(True)
        self.progress_label.config(text='准备转换环境');self.hint_label.config(foreground=C['muted'])
        self.install_thread=threading.Thread(target=self._install_worker,daemon=True);self.install_thread.start()

    def _install_worker(self):
        try:
            a,b=ensure_ffmpeg(progress_callback=lambda p,m:self.msg_queue.put(('ffmpeg',(p,m))))
            configure_ffmpeg(a,b);self.msg_queue.put(('ffmpeg_ready',(str(a),str(b))));self.msg_queue.put(('log',f'环境就绪：{a}'))
        except Exception as exc:self.msg_queue.put(('error',str(exc)))
        finally:self.msg_queue.put(('done',None))

    def _start(self):
        if self._running:return
        try:
            job=validate_form(dict(mode=self.mode.get(),ref=self.ref_path.get(),inp=self.input_path.get(),out=self.output_path.get(),crf=self.crf.get(),max_bitrate=self.max_bitrate.get(),prefix=self.prefix.get(),start_number=self.start_number.get(),acceleration=MODES.get(self.acceleration.get(),'')))
            if job.mode=='batch':
                videos=find_input_videos(Path(job.inp))
                if not videos:raise ValueError('输入文件夹中没有支持的视频。')
                if job.start_number+len(videos)-1>9999:raise ValueError('批量编号将超过 9999，请调低起始编号。')
                conflicts=[Path(job.out)/f'{job.prefix}{job.start_number+i:04d}.MP4' for i in range(len(videos))]
                if Path(job.ref).resolve() in [p.resolve() for p in conflicts]:raise ValueError('批量输出不能覆盖参考视频。')
                overwrite=any(p.exists() for p in conflicts)
            else:overwrite=Path(job.out).exists()
            if overwrite and not messagebox.askyesno('确认覆盖','输出位置已有同名文件。是否覆盖？',parent=self):return
            (Path(job.out).parent if job.mode=='single' else Path(job.out)).mkdir(parents=True,exist_ok=True)
        except (ValueError,OSError) as exc:self._show_error(str(exc));return
        self._had_error=False;self._task_kind='conversion';self._open_dir=None
        self.hint_label.config(foreground=C['muted']);self.hint_var.set('转换后将继续生成封面并移植容器，请等待全部完成。')
        self.progress['value']=0;self.progress_label.config(text='正在准备转换')
        self._log('\n— 新任务 —');self._set_running(True)
        self.worker_thread=threading.Thread(target=self._worker,args=(job.mode,job.ref,job.inp,job.out,job.start_number,job.crf,job.max_bitrate,job.prefix,job.acceleration),daemon=True)
        self.worker_thread.start()

    def _poll_queue(self):
        try:
            while True:
                kind,payload=self.msg_queue.get_nowait()
                if kind=='log':
                    self._log(payload)
                    if '失败 ❌' in payload:self._had_error=True
                    if '封面' in payload and ('生成' in payload or '移植' in payload):self.progress_label.config(text='正在生成封面 / 移植容器')
                elif kind=='progress':
                    if len(payload)==4:
                        name,pct,idx,total=payload;self.progress['value']=((idx-1)+pct/100)/total*100
                        self.progress_label.config(text=f'转换 {idx}/{total} · {pct:.0f}%')
                    else:
                        name,pct=payload;self.progress['value']=pct;self.progress_label.config(text=f'正在转码 · {pct:.0f}%')
                elif kind=='ffmpeg':
                    pct,msg=payload;self.progress['value']=pct;self.progress_label.config(text='准备转换环境');self.hint_var.set(msg)
                elif kind=='env_checked':
                    good,version=payload
                    self.ffmpeg_status_var.set('● FFmpeg 已就绪' if good else '○ 缺少 FFmpeg · 开始时自动安装')
                    if version:self._log(version)
                elif kind=='ffmpeg_ready':self.ffmpeg_status_var.set('● FFmpeg 已就绪')
                elif kind=='openable':self._open_dir=Path(payload)
                elif kind=='error':self._show_error(payload)
                elif kind=='done':
                    self._set_running(False)
                    if self._had_error:self.progress_label.config(text='处理结束 · 请检查错误日志')
                    else:
                        self.progress['value']=100;self.progress_label.config(text='环境已就绪' if self._task_kind=='install' else '转换完成')
                        self.hint_var.set('可以开始转换。' if self._task_kind=='install' else '视频已保存，点击“打开输出位置”查看。')
        except queue.Empty:pass
        self._poll_id=self.after(100,self._poll_queue)

    def _close(self):
        if self._running:
            messagebox.showinfo('任务正在进行','请等待当前任务完成后再关闭窗口，避免留下不完整视频。',parent=self);return
        self.after_cancel(self._poll_id);self.destroy()
