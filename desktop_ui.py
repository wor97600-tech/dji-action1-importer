"""Flat desktop shell. Encoding and container work remain in dji_graft_gui.App.

Constraint brief (§2.1/§2.8/§3.6): primary = file selection + Start;
secondary = encoding + progress; tertiary = help + logs. One primary action.
Grayscale structure: two columns above a non-scrolling action footer.
Tokens: generated neutral/brand ramps; spacing 4/8/12/16/24/32/48;
two weights; three neutral text tiers; no shadows or decorative borders.
"""
import ctypes
import math
import os
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk, filedialog, messagebox

from ffmpeg_env import ensure_ffmpeg, find_ffmpeg, ffmpeg_version
from dji_graft import configure_ffmpeg
from utils import find_input_videos
from ui_model import validate_form, build_batch_queue, validate_queue_names, pending_batch_items
from ui_theme import COLORS as C, FONT

VERSION = 'v5.1'
MODES = {'CPU · 原版': 'cpu', '自动选择 · 显卡优先': 'auto',
         'NVIDIA NVENC': 'h264_nvenc', 'Intel Quick Sync': 'h264_qsv', 'AMD AMF': 'h264_amf'}


class RoundedActionButton(tk.Canvas):
    """Canvas-backed rounded button for the app's existing green actions."""

    def __init__(self, parent, text, command, *, primary=False, scale=1, state='normal'):
        self._text = text
        self._command = command
        self._primary = primary
        self._scale = scale
        self._state = state
        self._font = tkfont.Font(family=FONT, size=-round(14 * scale), weight='bold')
        self._pad_x = round((18 if primary else 12) * scale)
        self._pad_y = round((10 if primary else 7) * scale)
        self._normal_bg = C['action'] if primary else C['tint']
        self._normal_fg = C['surface'] if primary else C['action']
        self._hover_bg = C['text'] if primary else C['hover']
        self._hover_fg = C['surface']
        self._current_bg = self._normal_bg
        self._current_fg = self._normal_fg
        self._anim_id = None
        width = self._font.measure(text) + 2 * self._pad_x
        height = self._font.metrics('linespace') + 2 * self._pad_y
        super().__init__(parent, width=width, height=height, bg=C['surface'],
                         highlightthickness=0, borderwidth=0, takefocus=1, cursor='hand2')
        self._shape = self.create_polygon(0, 0, 0, 0, smooth=False, outline='', tags=('button-shape',))
        self._label = self.create_text(width / 2, height / 2, text=text, font=self._font,
                                       fill=self._normal_fg, tags=('button-label',))
        self._draw_shape(self._normal_bg)
        self.bind('<Enter>', lambda _e: self._animate(True), add='+')
        self.bind('<Leave>', lambda _e: self._animate(False), add='+')
        self.bind('<ButtonPress-1>', self._press, add='+')
        self.bind('<ButtonRelease-1>', self._release, add='+')
        self.bind('<Return>', self._invoke, add='+')
        self.bind('<space>', self._invoke, add='+')

    def _draw_shape(self, color):
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        r = min(h / 2, w / 2)
        points = []
        for cx, cy, start in ((w-r, r, -90), (w-r, h-r, 0), (r, h-r, 90), (r, r, 180)):
            for angle in range(start, start + 91, 15):
                rad = angle * 3.141592653589793 / 180
                points.extend((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        self.coords(self._shape, *points)
        self.itemconfigure(self._shape, fill=color)
        self.tag_raise(self._label)

    def _paint(self, bg, fg):
        self._current_bg, self._current_fg = bg, fg
        self._draw_shape(bg)
        self.itemconfigure(self._label, fill=fg)

    @staticmethod
    def _mix(start, end, amount):
        a = tuple(int(start[i:i+2], 16) for i in (1, 3, 5))
        b = tuple(int(end[i:i+2], 16) for i in (1, 3, 5))
        return '#' + ''.join(f'{round(x + (y - x) * amount):02x}' for x, y in zip(a, b))

    def _animate(self, hovering, pressed=False):
        if self._state == 'disabled':
            return
        if self._anim_id:
            try: self.after_cancel(self._anim_id)
            except tk.TclError: pass
            self._anim_id = None
        bg = self._hover_bg if hovering else self._normal_bg
        fg = self._hover_fg if hovering else self._normal_fg
        if pressed:
            bg = C['text']
            fg = C['surface']
        start_bg, start_fg = self._current_bg, self._current_fg
        def frame(index=1):
            amount = index / 3
            self._paint(self._mix(start_bg, bg, amount), self._mix(start_fg, fg, amount))
            if index < 3:
                self._anim_id = self.after(7, lambda: frame(index + 1))
            else:
                self._anim_id = None
        frame()

    def _press(self, _event):
        self.focus_set()
        self._animate(True, pressed=True)

    def _release(self, event):
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._animate(inside)
        if inside and self._state != 'disabled':
            self._invoke()

    def _invoke(self, _event=None):
        if self._state != 'disabled':
            self._command()
        return 'break'

    def configure(self, cnf=None, **kwargs):
        if cnf and isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        text = kwargs.pop('text', None)
        state = kwargs.pop('state', None)
        if text is not None:
            self._text = text
            self.itemconfigure(self._label, text=text)
            width = self._font.measure(text) + 2 * self._pad_x
            self.configure(width=width)
        if state is not None:
            self._state = state
            if state == 'disabled':
                self._paint(C['border'], C['secondary'])
                self.configure(cursor='arrow')
            else:
                self.configure(cursor='hand2')
                self._paint(self._normal_bg, self._normal_fg)
        if kwargs:
            super().configure(**kwargs)

    config = configure

    def cget(self, key):
        if key == 'text': return self._text
        if key == 'state': return self._state
        return super().cget(key)


class HelpHint(tk.Canvas):
    """Small circular question mark with a hover-only explanatory tooltip."""

    def __init__(self, parent, text, scale=1):
        self._hint = text
        self._scale = scale
        size = max(16, round(18 * scale))
        super().__init__(parent, width=size, height=size, bg=C['surface'],
                         highlightthickness=0, borderwidth=0, takefocus=0, cursor='question_arrow')
        self.create_oval(1, 1, size-1, size-1, fill=C['tint'], outline=C['border'])
        self.create_text(size/2, size/2, text='?', fill=C['action'],
                         font=(FONT, -round(11*scale), 'bold'))
        self.bind('<Enter>', self._show, add='+')
        self.bind('<Leave>', self._hide, add='+')
        self._tooltip = None

    def _show(self, event):
        self._hide()
        tip = self._tooltip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.configure(bg=C['text'])
        label = tk.Label(tip, text=self._hint, justify='left', wraplength=round(260*self._scale),
                         bg=C['text'], fg=C['surface'], padx=10, pady=7,
                         font=(FONT, -round(12*self._scale)))
        label.pack()
        tip.geometry(f'+{event.x_root+12}+{event.y_root+14}')

    def _hide(self, _event=None):
        if self._tooltip is not None:
            try: self._tooltip.destroy()
            except tk.TclError: pass
            self._tooltip = None


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
        self._batch_queue = []
        self._failed_queue = []
        self.worker_thread = self.install_thread = None
        self.msg_queue = queue.Queue()
        self.ref_path = tk.StringVar()
        self.mode = tk.StringVar(value='single')
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.prefix = tk.StringVar(value='DJI_')
        self.start_number = tk.StringVar(value='0000')
        self.crf = tk.StringVar(value='23')
        self.max_bitrate = tk.StringVar(value='2000')
        self.acceleration = tk.StringVar(value='自动选择 · 显卡优先')
        self.ffmpeg_status_var = tk.StringVar(value='正在检查环境…')
        self.hint_var = tk.StringVar(value='准备就绪后，点击右下角开始转换。')
        self._controls = []
        self._set_theme()
        self._set_icon()
        self._build_ui()
        for var in (self.prefix, self.start_number):
            var.trace_add('write',lambda *_: (self._update_name_preview(), self._apply_queue_naming()))
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
        b=RoundedActionButton(parent,text,command,scale=self.ui_scale)
        self._controls.append(b)
        return b

    @staticmethod
    def _mix_color(start, end, amount):
        a = tuple(int(start[i:i+2], 16) for i in (1, 3, 5))
        b = tuple(int(end[i:i+2], 16) for i in (1, 3, 5))
        return '#' + ''.join(f'{round(x + (y - x) * amount):02x}' for x, y in zip(a, b))

    def _enable_button_hover(self, button, hover_color=None):
        style = ttk.Style(self)
        original = button.cget('style') or 'TButton'
        base = style.lookup(original, 'background') or C['surface']
        foreground = style.lookup(original, 'foreground') or C['text']
        custom = f'Hover{abs(hash(str(button)))}.{original}'
        configured = style.configure(original) or {}
        style.layout(custom, style.layout(original))
        style.configure(custom, **configured)
        maps = style.map(original) or {}
        maps.pop('background', None)
        if maps:
            style.map(custom, **maps)
        style.configure(custom, background=base, foreground=foreground)
        button.configure(style=custom)
        state = {'style': custom, 'base': base, 'current': base,
                 'hover': hover_color or C['hover'], 'after': None}
        button.bind('<Enter>', lambda _event, w=button: self._animate_button_color(w, True), add='+')
        button.bind('<Leave>', lambda _event, w=button: self._animate_button_color(w, False), add='+')
        button.bind('<ButtonPress-1>', lambda _event, w=button: self._animate_button_color(w, True, pressed=True), add='+')
        button.bind('<ButtonRelease-1>', lambda _event, w=button: self._animate_button_color(w, bool(w.winfo_containing(*w.winfo_pointerxy()) == w)), add='+')
        button._djigraft_hover_state = state

    def _animate_button_color(self, button, hovering, pressed=False):
        state = getattr(button, '_djigraft_hover_state', None)
        if not state or not button.winfo_exists():
            return
        if state['after'] is not None:
            try: button.after_cancel(state['after'])
            except tk.TclError: pass
        start = state['current']
        target = C['text'] if pressed else (state['hover'] if hovering else state['base'])
        steps = 6
        def frame(index=1):
            if not button.winfo_exists(): return
            color = self._mix_color(start, target, index / steps)
            ttk.Style(self).configure(state['style'], background=color)
            state['current'] = color
            if index < steps:
                state['after'] = button.after(16, lambda: frame(index + 1))
            else:
                state['after'] = None
        frame()

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
        left=ttk.Frame(body,padding=u(16));left.grid(row=0,column=0,sticky='nsew',padx=(0,u(12)));left.columnconfigure(0,weight=1);left.rowconfigure(5,weight=1)
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

        self.queue_frame = ttk.Frame(left)
        self.queue_frame.grid(row=5, column=0, sticky='nsew', pady=(0, u(8)))
        self.queue_frame.columnconfigure(0, weight=1); self.queue_frame.rowconfigure(1, weight=1)
        ttk.Label(self.queue_frame, text='批量队列（双击可编辑输出文件名）', style='Section.TLabel').grid(row=0, column=0, sticky='w', pady=(0, u(6)))
        tree_wrap = ttk.Frame(self.queue_frame); tree_wrap.grid(row=1, column=0, sticky='nsew'); tree_wrap.columnconfigure(0, weight=1); tree_wrap.rowconfigure(0, weight=1)
        self.queue_tree = ttk.Treeview(tree_wrap, columns=('source', 'output', 'status', 'action'), show='headings', height=7)
        for col, title, width in (('source', '原视频', 180), ('output', '输出文件名', 220), ('status', '状态', 90), ('action', '操作', 110)):
            self.queue_tree.heading(col, text=title)
            self.queue_tree.column(col, width=u(width), minwidth=u(width), anchor='w', stretch=(col in ('source', 'output')))
        self.queue_tree.grid(row=0, column=0, sticky='nsew')
        self.queue_tree.tag_configure('waiting', foreground=C['text'])
        self.queue_tree.tag_configure('running', foreground=C['action'])
        self.queue_tree.tag_configure('success', foreground='#168f4b')
        self.queue_tree.tag_configure('failed', foreground=C['error'])
        self.queue_tree.tag_configure('action_hover', background=C['surface'], foreground=C['text'])
        self._queue_hover_anim_id = None
        self._queue_hover_color = C['surface']
        queue_scroll = ttk.Scrollbar(tree_wrap, orient='vertical', command=self.queue_tree.yview)
        queue_scroll.grid(row=0, column=1, sticky='ns')
        self.queue_tree.configure(yscrollcommand=queue_scroll.set)
        self.queue_tree.bind('<Double-1>', self._edit_queue_name)
        self.queue_tree.bind('<Button-1>', self._queue_action_click)
        self.queue_tree.bind('<Motion>', self._queue_hover_motion)
        self.queue_tree.bind('<Leave>', lambda _event: self._set_queue_hover(None))
        self.queue_frame.grid_remove()

        quality=ttk.Frame(right);quality.grid(row=0,column=0,sticky='ew',pady=(0,u(12)));quality.columnconfigure(0,weight=1);quality.columnconfigure(1,weight=1)
        quality_head=ttk.Frame(quality);quality_head.grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,u(8)))
        ttk.Label(quality_head,text='04  编码与画质',style='Section.TLabel').grid(row=0,column=0,sticky='w')
        HelpHint(quality_head,'选择编码方式，并设置画质或输出码率上限。显卡模式会优先使用可用硬件编码。',self.ui_scale).grid(row=0,column=1,padx=(u(6),0))
        self.acceleration_box=ttk.Combobox(quality,textvariable=self.acceleration,values=list(MODES),state='readonly',width=24)
        self.acceleration_box.grid(row=1,column=0,columnspan=2,sticky='ew')
        crf_head=ttk.Frame(quality);crf_head.grid(row=2,column=0,sticky='w',pady=(u(8),u(4)))
        ttk.Label(crf_head,text='CRF · CPU 画质',style='Muted.TLabel').grid(row=0,column=0,sticky='w')
        HelpHint(crf_head,'CRF 仅用于 CPU 编码。数值越小，画质越高、文件通常也越大；显卡编码时此项不生效。',self.ui_scale).grid(row=0,column=1,padx=(u(5),0))
        bitrate_head=ttk.Frame(quality);bitrate_head.grid(row=2,column=1,sticky='w',pady=(u(8),u(4)))
        ttk.Label(bitrate_head,text='码率上限 · kbps',style='Muted.TLabel').grid(row=0,column=0,sticky='w')
        HelpHint(bitrate_head,'限制视频的峰值码率，单位为 kbps。默认 2000 kbps（约 2 Mbps）；留空则跟随参考视频。',self.ui_scale).grid(row=0,column=1,padx=(u(5),0))
        self.crf_entry=self._entry(quality,self.crf,8);self.crf_entry.grid(row=3,column=0,sticky='ew',padx=(0,u(12)))
        self.bitrate_entry=self._entry(quality,self.max_bitrate,10);self.bitrate_entry.grid(row=3,column=1,sticky='ew')
        self.encoder_hint=ttk.Label(quality,style='Muted.TLabel',wraplength=u(320),justify='left')
        self.encoder_hint.grid(row=4,column=0,columnspan=2,sticky='w',pady=(u(8),0));self._update_encoder_hint()

        self.status_label=tk.Label(right,textvariable=self.ffmpeg_status_var,bg=C['tint'],fg=C['action'],anchor='w',padx=u(8),pady=u(6),font=(FONT,-u(12)))
        self.status_label.grid(row=1,column=0,sticky='ew',pady=(0,u(8)))
        self.install_btn=RoundedActionButton(right,'检查 / 准备 FFmpeg',self._install_ffmpeg,scale=self.ui_scale);self.install_btn.grid(row=2,column=0,sticky='ew',pady=(0,u(12)));self._controls.append(self.install_btn)
        tools=ttk.Frame(right);tools.grid(row=3,column=0,sticky='ew',pady=(0,u(8)));tools.columnconfigure(0,weight=1)
        ttk.Label(tools,text='运行日志',style='Section.TLabel').grid(row=0,column=0,sticky='w')
        self.copy_btn=RoundedActionButton(tools,'复制日志',self._copy_log,scale=self.ui_scale);self.copy_btn.grid(row=0,column=1);self._controls.append(self.copy_btn)
        self.save_btn=RoundedActionButton(tools,'保存日志',self._save_log,scale=self.ui_scale);self.save_btn.grid(row=0,column=2,padx=(u(8),0));self._controls.append(self.save_btn)
        logframe=ttk.Frame(right);logframe.grid(row=4,column=0,sticky='nsew');logframe.rowconfigure(0,weight=1);logframe.columnconfigure(0,weight=1)
        self.log_text=tk.Text(logframe,wrap='word',state='disabled',height=4,width=1,bg=C['bg'],fg=C['secondary'],relief='flat',borderwidth=0,padx=u(12),pady=u(12),font=(FONT,-u(12)),spacing3=u(4))
        self.log_text.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(logframe,command=self.log_text.yview);scroll.grid(row=0,column=1,sticky='ns');self.log_text.config(yscrollcommand=scroll.set)

        self.footer=ttk.Frame(self,padding=(u(24),u(12)))
        self.footer.grid(row=2,column=0,sticky='ew');self.footer.columnconfigure(0,weight=1)
        self.progress_label=ttk.Label(self.footer,text='等待开始',style='Section.TLabel');self.progress_label.grid(row=0,column=0,sticky='w')
        self.progress=ttk.Progressbar(self.footer,mode='determinate',maximum=100);self.progress.grid(row=1,column=0,sticky='ew',pady=(u(8),u(4)),padx=(0,u(24)))
        self.hint_label=ttk.Label(self.footer,textvariable=self.hint_var,style='Muted.TLabel',wraplength=u(600));self.hint_label.grid(row=2,column=0,sticky='w')
        self.open_btn=RoundedActionButton(self.footer,'打开输出位置',self._open_output,scale=self.ui_scale,state='disabled');self.open_btn.grid(row=0,column=1,rowspan=3,padx=(0,u(12)));self._controls.append(self.open_btn)
        self.start_btn=RoundedActionButton(self.footer,'开始转换  →',self._start,primary=True,scale=self.ui_scale);self.start_btn.grid(row=0,column=2,rowspan=3);self._controls.append(self.start_btn)
        self.retry_btn=RoundedActionButton(self.footer,'重试失败视频',self._retry_failed,scale=self.ui_scale,state='disabled');self.retry_btn.grid(row=0,column=3,rowspan=3,padx=(u(12),0));self._controls.append(self.retry_btn)
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
        if batch:
            self.queue_frame.grid()
            self._refresh_batch_queue()
        else:
            self.queue_frame.grid_remove()
        self._update_name_preview()

    def _update_name_preview(self):
        try:
            n=int(self.start_number.get() or '0')
            text=f'{self.prefix.get() or "DJI_"}{n:04d}.MP4' if 0<=n<=9999 else '编号 0–9999'
        except ValueError:text='编号须为整数'
        self.name_preview_label.config(text=text)

    def _pick_ref(self):
        p=filedialog.askopenfilename(parent=self,title='选择相机原生参考视频',filetypes=[('MP4 视频','*.mp4 *.MP4'),('所有文件','*.*')])
        if p:self.ref_path.set(p)

    def _pick_input(self):
        p = filedialog.askopenfilename(parent=self, title='选择待转换视频') if self.mode.get() == 'single' else filedialog.askdirectory(parent=self, title='选择输入文件夹')
        if p:
            self.input_path.set(p)
            if not self.output_path.get():
                self.output_path.set(str(Path(p).with_name('DJI_0000.MP4')) if self.mode.get()=='single' else str(Path(p)/'DJI_Output'))
            if self.mode.get() == 'batch': self._refresh_batch_queue()

    def _refresh_batch_queue(self):
        if not hasattr(self, 'queue_tree') or self.mode.get() != 'batch': return
        try:
            videos = find_input_videos(Path(self.input_path.get())) if Path(self.input_path.get()).is_dir() else []
            previous = {str(item.source): item for item in self._batch_queue}
            defaults = build_batch_queue(videos, self.prefix.get() or 'DJI_', int(self.start_number.get() or '0'))
            for item in defaults:
                old = previous.get(str(item.source))
                if old:
                    if old.custom_name:
                        item.output_name = old.output_name
                        item.custom_name = True
                    if item.output_name == old.output_name:
                        item.status, item.error = old.status, old.error
            self._batch_queue = defaults
        except (OSError, ValueError):
            self._batch_queue = []
        self._failed_queue = []
        for row in self.queue_tree.get_children(): self.queue_tree.delete(row)
        for item in self._batch_queue:
            self.queue_tree.insert('', 'end', iid=str(item.source), values=(item.source.name, item.output_name, item.status, self._queue_action_text(item.status)), tags=(self._queue_status_tag(item.status),))

    @staticmethod
    def _queue_action_text(status):
        return {'转换中': '转换中…', '已完成': '再次转换 ↻', '失败': '重试转换 ↻'}.get(status, '单独转换 ▶')

    @staticmethod
    def _queue_status_tag(status):
        return {'已完成': 'success', '失败': 'failed', '转换中': 'running'}.get(status, 'waiting')

    def _update_queue_row(self, item):
        row = str(item.source)
        if self.queue_tree.exists(row):
            self.queue_tree.set(row, 'status', item.status)
            self.queue_tree.set(row, 'action', self._queue_action_text(item.status))
            self.queue_tree.item(row, tags=(self._queue_status_tag(item.status),))

    def _apply_queue_naming(self):
        """Prefix/number edits intentionally rename every queued output."""
        self._update_name_preview()
        if self.mode.get() != 'batch' or not self._batch_queue:
            return
        try:
            start = int(self.start_number.get() or '0')
        except ValueError:
            return
        prefix = self.prefix.get() or 'DJI_'
        for index, item in enumerate(self._batch_queue):
            item.output_name = f'{prefix}{start + index:04d}.MP4'
            item.custom_name = False
        self._refresh_batch_queue()

    def _edit_queue_name(self, event):
        row = self.queue_tree.identify_row(event.y)
        col = self.queue_tree.identify_column(event.x)
        if not row or col != '#2' or self._running: return
        item = next((x for x in self._batch_queue if str(x.source) == row), None)
        if item is None: return
        x, y, w, h = self.queue_tree.bbox(row, col)
        editor = ttk.Entry(self.queue_tree)
        editor.insert(0, item.output_name); editor.select_range(0, 'end'); editor.place(x=x, y=y, width=w, height=h)
        def save(_event=None):
            value = editor.get().strip()
            if not value:
                index = self._batch_queue.index(item)
                value = f'{self.prefix.get() or "DJI_"}{int(self.start_number.get() or "0") + index:04d}.MP4'
                item.custom_name = False
            else:
                item.custom_name = True
            item.output_name = value
            self.queue_tree.set(row, 'output', value)
            editor.destroy()
        editor.bind('<Return>', save); editor.bind('<FocusOut>', save); editor.focus_set()

    def _queue_action_click(self, event):
        row = self.queue_tree.identify_row(event.y)
        col = self.queue_tree.identify_column(event.x)
        if row and col == '#4':
            item = next((x for x in self._batch_queue if str(x.source) == row), None)
            if item:
                self._convert_single_queue_item(item)
            return 'break'

    def _queue_hover_motion(self, event):
        row = self.queue_tree.identify_row(event.y)
        col = self.queue_tree.identify_column(event.x)
        self._set_queue_hover(row if row and col == '#4' else None)

    def _set_queue_hover(self, row):
        if getattr(self, '_queue_hover_row', None) == row:
            return
        previous = getattr(self, '_queue_hover_row', None)
        if self._queue_hover_anim_id is not None:
            try: self.after_cancel(self._queue_hover_anim_id)
            except tk.TclError: pass
            self._queue_hover_anim_id = None
        if previous and self.queue_tree.exists(previous):
            item = next((x for x in self._batch_queue if str(x.source) == previous), None)
            tags = [self._queue_status_tag(item.status)] if item else []
            self.queue_tree.item(previous, tags=tags)
        self._queue_hover_row = row
        if row and self.queue_tree.exists(row):
            item = next((x for x in self._batch_queue if str(x.source) == row), None)
            tags = [self._queue_status_tag(item.status)] if item else []
            tags.append('action_hover')
            self.queue_tree.item(row, tags=tags)
            self._animate_queue_hover(C['surface'], C['tint'])
        else:
            self._queue_hover_color = C['surface']

    def _animate_queue_hover(self, start, target, frame=1):
        color = self._mix_color(start, target, frame / 4)
        self.queue_tree.tag_configure('action_hover', background=color, foreground=C['text'])
        self._queue_hover_color = color
        if frame < 4:
            self._queue_hover_anim_id = self.after(8, lambda: self._animate_queue_hover(start, target, frame + 1))
        else:
            self._queue_hover_anim_id = None

    def _convert_single_queue_item(self, item):
        if self._running or self.mode.get() != 'batch':
            return
        try:
            job = validate_form(dict(mode='batch', ref=self.ref_path.get(), inp=self.input_path.get(), out=self.output_path.get(),
                                     crf=self.crf.get(), max_bitrate=self.max_bitrate.get(), prefix=self.prefix.get(),
                                     start_number=self.start_number.get(),
                                     acceleration=MODES.get(self.acceleration.get(), '')))
            validate_queue_names(self._batch_queue)
            out_path = Path(job.out) / item.output_name
            if out_path.exists() and not messagebox.askyesno('确认覆盖', f'{item.output_name} 已存在。是否覆盖？', parent=self):
                return
            Path(job.out).mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError) as exc:
            self._show_error(str(exc)); return
        self._had_error = False; self._task_kind = 'single_item'; self._open_dir = None
        self._skipped_count = 0
        item.status, item.error = '转换中', ''
        self._update_queue_row(item)
        self.progress['value'] = 0; self.progress_label.config(text='正在转换选中视频')
        self.hint_var.set(f'正在转换：{item.output_name}')
        self._log(f'\n— 单独转换：{item.source.name} → {item.output_name} —'); self._set_running(True)
        self.worker_thread = threading.Thread(target=self._worker,
            args=('batch', job.ref, job.inp, job.out, job.start_number, job.crf, job.max_bitrate, job.prefix,
                  job.acceleration, [(str(item.source), item.output_name)]), daemon=True)
        self.worker_thread.start()

    def _queue_snapshot(self, items=None):
        return [(str(item.source), item.output_name) for item in (items if items is not None else self._batch_queue)]

    def _pick_output(self):
        p=filedialog.asksaveasfilename(parent=self,title='保存转换后视频',initialfile='DJI_0000.MP4',defaultextension='.MP4',filetypes=[('MP4 视频','*.MP4')]) if self.mode.get()=='single' else filedialog.askdirectory(parent=self,title='选择输出文件夹')
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
        self.retry_btn.config(state='disabled' if running else ('normal' if self._failed_queue else 'disabled'))

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
        skipped_items = []
        queue_items = None
        try:
            job=validate_form(dict(mode=self.mode.get(),ref=self.ref_path.get(),inp=self.input_path.get(),out=self.output_path.get(),crf=self.crf.get(),max_bitrate=self.max_bitrate.get(),prefix=self.prefix.get(),start_number=self.start_number.get(),acceleration=MODES.get(self.acceleration.get(),'')))
            if job.mode=='batch':
                if not self._batch_queue: self._refresh_batch_queue()
                if not self._batch_queue:raise ValueError('输入文件夹中没有支持的视频。')
                validate_queue_names(self._batch_queue)
                pending_items, skipped_items = pending_batch_items(self._batch_queue, job.out)
                if not pending_items:
                    self.hint_var.set(f'队列中的视频都已完成，已跳过 {len(skipped_items)} 个任务。')
                    self.progress_label.config(text='无需转换 · 任务均已完成')
                    self._log(f'所有任务均已完成，自动跳过 {len(skipped_items)} 个视频。')
                    messagebox.showinfo('无需转换', f'队列中的 {len(skipped_items)} 个视频都已转换完成，本次无需重复转换。', parent=self)
                    return
                if job.start_number+len(self._batch_queue)-1>9999:raise ValueError('批量编号将超过 9999，请调低起始编号。')
                conflicts=[Path(job.out)/item.output_name for item in pending_items]
                if Path(job.ref).resolve() in [p.resolve() for p in conflicts]:raise ValueError('批量输出不能覆盖参考视频。')
                overwrite=any(p.exists() for p in conflicts)
            else:overwrite=Path(job.out).exists()
            if overwrite and not messagebox.askyesno('确认覆盖','输出位置已有同名文件。是否覆盖？',parent=self):return
            (Path(job.out).parent if job.mode=='single' else Path(job.out)).mkdir(parents=True,exist_ok=True)
        except (ValueError,OSError) as exc:self._show_error(str(exc));return
        self._had_error=False;self._task_kind='conversion';self._open_dir=None;self._failed_queue=[]
        self._skipped_count = len(skipped_items)
        if self._skipped_count:
            self._log(f'自动跳过 {self._skipped_count} 个已完成且输出文件存在的视频。')
        for item in (pending_items if job.mode == 'batch' else []):
            item.status, item.error = '等待转换', ''
            self._update_queue_row(item)
        self.hint_label.config(foreground=C['muted']);self.hint_var.set('转换后将继续生成封面并移植容器，请等待全部完成。')
        self.progress['value']=0;self.progress_label.config(text='正在准备转换')
        self._log('\n— 新任务 —');self._set_running(True)
        queue_items = self._queue_snapshot(pending_items) if job.mode == 'batch' else None
        self.worker_thread=threading.Thread(target=self._worker,args=(job.mode,job.ref,job.inp,job.out,job.start_number,job.crf,job.max_bitrate,job.prefix,job.acceleration,queue_items),daemon=True)
        self.worker_thread.start()

    def _retry_failed(self):
        if self._running or not self._failed_queue: return
        try:
            job = validate_form(dict(mode='batch', ref=self.ref_path.get(), inp=self.input_path.get(), out=self.output_path.get(), crf=self.crf.get(), max_bitrate=self.max_bitrate.get(), prefix=self.prefix.get(), start_number=self.start_number.get(), acceleration=MODES.get(self.acceleration.get(), '')))
            validate_queue_names(self._failed_queue)
        except (ValueError, OSError) as exc:
            self._show_error(str(exc)); return
        self._had_error = False; self._task_kind = 'retry'; self._open_dir = None
        self._skipped_count = 0
        self.progress['value'] = 0; self.progress_label.config(text='正在重试失败视频')
        self.hint_var.set('正在重试失败项目，输出名称沿用队列设置。')
        self._log('\n— 重试失败视频 —'); self._set_running(True)
        items = list(self._failed_queue)
        for item in items:
            item.status, item.error = '等待重试', ''
            self._update_queue_row(item)
        self.worker_thread = threading.Thread(target=self._worker, args=(job.mode, job.ref, job.inp, job.out, job.start_number, job.crf, job.max_bitrate, job.prefix, job.acceleration, self._queue_snapshot(items)), daemon=True)
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
                elif kind=='queue_status':
                    source, status, error = payload
                    item = next((x for x in self._batch_queue if str(x.source) == source), None)
                    if item:
                        item.status, item.error = status, error
                        if status == '失败' and item not in self._failed_queue: self._failed_queue.append(item)
                        if status == '已完成' and item in self._failed_queue: self._failed_queue.remove(item)
                        self._update_queue_row(item)
                elif kind=='error':self._show_error(payload)
                elif kind=='done':
                    self._set_running(False)
                    self.retry_btn.config(state='normal' if self._failed_queue else 'disabled')
                    if self._had_error or self._failed_queue:
                        self.progress_label.config(text='处理结束 · 可重试失败视频')
                        if self._skipped_count:
                            self.hint_var.set(f'处理结束，自动跳过 {self._skipped_count} 个已完成视频；失败视频可点击“重试失败视频”。')
                    else:
                        self.progress['value']=100;self.progress_label.config(text='环境已就绪' if self._task_kind=='install' else '转换完成')
                        if self._task_kind == 'install':
                            self.hint_var.set('可以开始转换。')
                        elif self._skipped_count:
                            self.hint_var.set(f'转换完成，自动跳过 {self._skipped_count} 个已完成视频。')
                        else:
                            self.hint_var.set('视频已保存，点击“打开输出位置”查看。')
        except queue.Empty:pass
        self._poll_id=self.after(100,self._poll_queue)

    def _close(self):
        if self._running:
            messagebox.showinfo('任务正在进行','请等待当前任务完成后再关闭窗口，避免留下不完整视频。',parent=self);return
        self.after_cancel(self._poll_id);self.destroy()
