$ErrorActionPreference = "Stop"

# setup-python places the requested interpreter on PATH as `python`.  The
# Windows `py` launcher may still resolve to a different system version
# (for example 3.15), which can break PyInstaller's Tcl/Tk discovery.
if (Get-Command python -ErrorAction SilentlyContinue) {
    $Py = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Py = "py"
} else {
    throw "未找到 Python。请安装 Python 或运行 GitHub Actions 的 setup-python。"
}

& $Py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip 安装 PyInstaller 失败" }

& $Py -m PyInstaller --noconfirm --clean --onefile --windowed --additional-hooks-dir hooks --name DJIGraft-5.1-Windows-x64 --version-file windows-version.txt --icon assets/app-icon.ico --add-data "assets;assets" dji_graft_gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

Write-Host ""
Write-Host "打包完成：dist\DJIGraft-5.1-Windows-x64.exe"
