"""收集 tkinter 运行所需的 Tcl/Tk 脚本与动态库。

正常情况下直接复用 PyInstaller 的检测结果；在受限环境（无法实例化 Tk）中，
改为根据当前 Python 前缀手动定位并收集，保证打包产物始终包含可用的 tkinter。
"""

from pathlib import Path

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks.tcl_tk import tcltk_info


def _collect_manually(hook_api):
    import tkinter

    prefix = Path(tkinter.__file__).resolve().parents[2]
    datas = []

    for ver in ("8.6", "8.5"):
        tcl_dir = prefix / "tcl" / f"tcl{ver}"
        tk_dir = prefix / "tcl" / f"tk{ver}"
        if tcl_dir.is_dir():
            datas += Tree(
                str(tcl_dir),
                prefix="_tcl_data",
                excludes=["demos", "*.lib", "tclConfig.sh"],
            )
        if tk_dir.is_dir():
            datas += Tree(
                str(tk_dir),
                prefix="_tk_data",
                excludes=["demos", "*.lib", "tkConfig.sh"],
            )
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
    if tcltk_info.available:
        if tcltk_info.tcl_data_missing:
            raise SystemExit(
                f"ERROR: Tcl data/library directory ({tcltk_info.tcl_data_dir!r}) could not be collected!"
            )
        if tcltk_info.tk_data_missing:
            raise SystemExit(
                f"ERROR: Tk data/library directory ({tcltk_info.tk_data_dir!r}) could not be collected!"
            )
        hook_api.add_datas(tcltk_info.data_files)
    else:
        _collect_manually(hook_api)
