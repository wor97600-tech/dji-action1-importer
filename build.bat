@echo off
setlocal

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --additional-hooks-dir hooks --name DJIGraft-5.0-Windows-x64 --version-file windows-version.txt --icon assets/app-icon.ico --add-data "assets;assets" dji_graft_gui.py
if errorlevel 1 goto :fail

echo.
echo 打包完成：dist\DJIGraft-5.0-Windows-x64.exe
goto :end

:fail
echo.
echo 打包失败，请检查上方的错误信息。

:end
pause
