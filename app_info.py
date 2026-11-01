"""Desktop first-run notice and independent About / sponsorship window."""
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from ui_theme import COLORS as C


DISCLAIMER = (
    '本项目仅作学习交流与技术讨论，不开展商业运营。\n\n'
    '视频转换及相机回放存在兼容性风险。请自行评估使用风险，并在使用前备份原始视频及相机存储卡中的重要数据。\n\n'
    '因使用本软件转换的视频而导致的相机损坏、设备异常、数据丢失或其他损失，'
    '由使用者自行承担风险，开发者不承担相关责任（法律另有规定的除外）。\n\n'
    '本软件按现状提供，不保证转换结果适用于所有相机、固件或视频。'
)


def _notice_path():
    appdata = os.environ.get('APPDATA')
    root = Path(appdata) / 'DJI Graft' if appdata else Path.home() / '.djigraft'
    return root / 'disclaimer-acknowledged.txt'


def disclaimer_acknowledged(path=None):
    try:
        return Path(path or _notice_path()).read_text(encoding='utf-8').strip() == 'acknowledged'
    except (OSError, UnicodeError):
        return False


def acknowledge_disclaimer(path=None):
    path = Path(path or _notice_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('acknowledged\n', encoding='utf-8')


def _window(parent, title):
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(title)
    win.configure(bg=C['surface'])
    win.transient(parent)
    win.u = parent.u
    win.ui_scale = parent.ui_scale
    return win


def _show_centered(win, size=None):
    win.update_idletasks()
    width, height = size or (win.winfo_reqwidth(), win.winfo_reqheight())
    x = max(0, (win.winfo_screenwidth() - width) // 2)
    y = max(0, (win.winfo_screenheight() - height) // 2)
    win.geometry(f'{width}x{height}+{x}+{y}')
    win.deiconify()
    win.lift()


def _dim_owner(parent, dialog):
    """Dim only the owning app window; remove the shade with the dialog."""
    previous_grab = parent.grab_current()
    was_disabled = parent.attributes('-disabled') if sys.platform == 'win32' else None
    parent.update_idletasks()
    shade = tk.Toplevel(parent)
    shade.withdraw()
    shade.overrideredirect(True)
    shade.transient(parent)
    shade.configure(bg='black', borderwidth=0)
    shade.attributes('-alpha', 0.28)

    def sync(event=None):
        if event is None or event.widget is parent:
            shade.geometry(f'{parent.winfo_width()}x{parent.winfo_height()}'
                           f'{parent.winfo_rootx():+d}{parent.winfo_rooty():+d}')

    sync()
    binding = parent.bind('<Configure>', sync, add='+')
    shade.deiconify()
    shade.lift(parent)
    dialog._shade = shade
    if sys.platform == 'win32':
        parent.attributes('-disabled', True)

    def cleanup(event):
        if event.widget is dialog:
            try:
                parent.unbind('<Configure>', binding)
                shade.destroy()
                if sys.platform == 'win32':
                    parent.attributes('-disabled', was_disabled)
                if previous_grab is not None and previous_grab.winfo_exists():
                    previous_grab.grab_set()
                parent.focus_set()
            except tk.TclError:
                pass

    dialog.bind('<Destroy>', cleanup, add='+')


def show_disclaimer(parent, first_run=False):
    from desktop_ui import RoundedActionButton
    win = _window(parent, '使用前请阅读 · 免责声明')
    win.resizable(False, False)
    content = ttk.Frame(win, padding=parent.u(24))
    content.pack(fill='both', expand=True)
    ttk.Label(content, text='免责声明', style='Title.TLabel').pack(anchor='w')
    ttk.Label(content, text=DISCLAIMER, wraplength=parent.u(500), justify='left').pack(
        fill='x', pady=(parent.u(16), parent.u(20)))
    error = tk.StringVar()
    ttk.Label(content, textvariable=error, foreground=C['error'],
              wraplength=parent.u(500)).pack(anchor='w')
    actions = ttk.Frame(content)
    actions.pack(fill='x')

    def accept():
        if first_run:
            try:
                acknowledge_disclaimer()
            except OSError:
                error.set('无法保存确认记录，请检查用户配置目录的写入权限后重试。')
                return
            parent._notice_pending = False
        win.destroy()

    def decline():
        win.destroy()
        if first_run:
            parent.destroy()

    if first_run:
        ttk.Button(actions, text='退出软件', command=decline).pack(side='left')
    RoundedActionButton(actions, text='我已阅读并知悉，进入软件' if first_run else '知道了',
                        primary=True, scale=parent.ui_scale, command=accept).pack(side='right')
    win.protocol('WM_DELETE_WINDOW', decline)
    _dim_owner(parent, win)
    _show_centered(win)
    win.grab_set()
    win.focus_set()
    return win


def show_about(parent, version):
    from desktop_ui import RoundedActionButton
    existing = getattr(parent, '_about_window', None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    win = parent._about_window = _window(parent, '关于我们 · DJI Graft')
    win.geometry(f'{parent.u(700)}x{parent.u(650)}')
    win.minsize(parent.u(620), parent.u(570))
    outer = ttk.Frame(win, padding=parent.u(20))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='DJI Graft', style='Title.TLabel').pack(anchor='w')
    ttk.Label(outer, text=f'{version} · Windows · 视频导入工具', style='Muted.TLabel').pack(anchor='w', pady=(0,parent.u(16)))
    tabs = ttk.Notebook(outer)
    tabs.pack(fill='both', expand=True)
    about = ttk.Frame(tabs, padding=parent.u(20))
    support = ttk.Frame(tabs, padding=parent.u(12))
    tabs.add(about, text='关于我们')
    tabs.add(support, text='赞助支持')
    ttk.Label(about, text='让你的视频，在相机里播放', style='Section.TLabel').pack(anchor='w')
    ttk.Label(about, text='本项目仅作学习交流与技术讨论，不开展商业运营。',
              wraplength=parent.u(550)).pack(anchor='w', pady=(parent.u(8),parent.u(24)))
    ttk.Label(about, text='联系我们', style='Section.TLabel').pack(anchor='w')
    for title, value in [('邮箱', '137167923@qq.com'), ('微信', 's444444444b123')]:
        row = ttk.Frame(about)
        row.pack(fill='x', pady=parent.u(8))
        ttk.Label(row, text=f'{title}  {value}').pack(side='left')
        def copy(text=value):
            win.clipboard_clear()
            win.clipboard_append(text)
            copied.set('已复制到剪贴板')
        ttk.Button(row, text='复制', command=copy).pack(side='right')
    copied = tk.StringVar()
    ttk.Label(about, textvariable=copied, style='Muted.TLabel').pack(anchor='w')
    ttk.Label(about, text='特别感谢', style='Section.TLabel').pack(anchor='w', pady=(parent.u(20),parent.u(8)))
    ttk.Label(about, text='感谢鸢尾鸟的赞助与支持。').pack(anchor='w')
    ttk.Button(about, text='查看免责声明', style='Quiet.TButton',
               command=lambda: show_disclaimer(win, False)).pack(anchor='w', pady=parent.u(20))
    ttk.Label(support, text='自愿赞助 · 感谢支持', style='Section.TLabel').pack(anchor='w')
    ttk.Label(support, text='赞助不影响软件功能，请自行核对收款信息。', style='Muted.TLabel').pack(anchor='w', pady=(parent.u(4),parent.u(8)))
    codes = ttk.Frame(support)
    codes.pack(fill='both', expand=True)
    codes.columnconfigure((0,1), weight=1)
    assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'
    win._payment_images = []
    for column, (label, stem) in enumerate([('微信支付','support-wechat'), ('支付宝','support-alipay')]):
        panel = ttk.Frame(codes)
        panel.grid(row=0,column=column,sticky='n',padx=parent.u(6))
        ttk.Label(panel, text=label, style='Section.TLabel').pack(pady=parent.u(6))
        try:
            photo = tk.PhotoImage(master=win, file=str(assets / f'{stem}-preview.png'))
            if parent.ui_scale < 0.8:
                photo = photo.zoom(3).subsample(4)
            win._payment_images.append(photo)
            ttk.Label(panel, image=photo).pack()
        except tk.TclError:
            ttk.Label(panel, text='图片加载失败，请查看原图。').pack()
        def open_image(filename=assets / f'{stem}.png'):
            try:
                os.startfile(str(filename))
            except OSError as exc:
                messagebox.showerror('无法打开图片', str(exc), parent=win)
        ttk.Button(panel, text='查看收款码原图', command=open_image).pack(pady=parent.u(8))
    RoundedActionButton(outer, text='返回主界面', command=win.destroy,
                        scale=parent.ui_scale).pack(anchor='e',pady=(parent.u(12),0))
    _dim_owner(parent, win)
    _show_centered(win, (parent.u(700), parent.u(650)))
    win.grab_set()
    win.focus_set()
    return win
