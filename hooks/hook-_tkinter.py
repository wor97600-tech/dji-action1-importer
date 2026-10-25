"""收集 tkinter 运行所需的 Tcl/Tk 脚本与动态库。

正常情况下直接复用 PyInstaller 的检测结果；在受限环境（无法实例化 Tk）中，
改为根据当前 Python 前缀手动定位并收集，保证打包产物始终包含可用的 tkinter。
"""

from pathlib import Path
import tempfile

from PyInstaller.utils.hooks.tcl_tk import tcltk_info


def _collect_manually(hook_api):
    import tkinter

    prefix = Path(tkinter.__file__).resolve().parents[2]
    datas = []
    patched_dir = Path(tempfile.mkdtemp(prefix='djigraft-tcl-'))

    for ver in ("8.6", "8.5"):
        tcl_dir = prefix / "tcl" / f"tcl{ver}"
        tk_dir = prefix / "tcl" / f"tk{ver}"
        if tcl_dir.is_dir():
            for path in tcl_dir.rglob('*'):
                if path.is_file() and path.name not in {'tclConfig.sh'} and 'demos' not in path.parts:
                    dest = patched_dir / 'tcl' / path.relative_to(tcl_dir)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    data = path.read_bytes()
                    if path.name == 'init.tcl': data = data.replace(b'package require -exact Tcl 8.6.12', b'package require Tcl 8.6')
                    dest.write_bytes(data)
                    datas.append((str(dest), str(Path('_tcl_data') / path.relative_to(tcl_dir).parent)))
        if tk_dir.is_dir():
            for path in tk_dir.rglob('*'):
                if path.is_file() and path.name not in {'tkConfig.sh'} and 'demos' not in path.parts:
                    dest = patched_dir / 'tk' / path.relative_to(tk_dir)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    data = path.read_bytes()
                    if path.name == 'tk.tcl': data = data.replace(b'package require -exact Tk  8.6.12', b'package require Tk 8.6')
                    dest.write_bytes(data)
                    datas.append((str(dest), str(Path('_tk_data') / path.relative_to(tk_dir).parent)))
        if datas:
            break

    if not datas:
        raise SystemExit("无法定位 Tcl/Tk 数据目录，无法打包 tkinter")

    hook_api.add_datas(datas)

    binaries = []
    dll_dir = prefix / "DLLs"
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "tcl85.dll", "tk85.dll"):
        path = dll_dir / name
        if path.is_file():
            binaries.append((str(path), "."))
    if binaries:
        hook_api.add_binaries(binaries)


def hook(hook_api):
    # The bundled workspace Python reports Tcl as available but its runtime
    # layout is nonstandard. Collect the scripts explicitly at the locations
    # expected by PyInstaller's tkinter runtime hook.
    _collect_manually(hook_api)
