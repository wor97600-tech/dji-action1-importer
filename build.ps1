$ErrorActionPreference = "Stop"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $Py = "py"
} else {
    $Py = "python"
}

& $Py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip 安装 PyInstaller 失败" }

& $Py -m PyInstaller --noconfirm --clean --onefile --windowed --additional-hooks-dir hooks --name DJIGraft-5.1-Windows-x64 --version-file windows-version.txt --icon assets/app-icon.ico --add-data "assets;assets" dji_graft_gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

Write-Host ""
Write-Host "打包完成：dist\DJIGraft-5.1-Windows-x64.exe"
