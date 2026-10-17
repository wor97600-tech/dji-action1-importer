"""覆盖 PyInstaller 内置 hook，避免在受限环境中误删 tkinter。

内置 hook 会在无法创建 Tk 窗口（例如无显示/沙箱拦截 Tcl 文件读取）时把 tkinter
整个排除。这里改为空操作，让 tkinter 正常参与分析；真正的 Tcl/Tk 数据由
``hooks/hook-_tkinter.py`` 负责收集。
"""


def pre_find_module_path(hook_api):
    return
