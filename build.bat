@echo off
setlocal

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --additional-hooks-dir hooks --name DJIGraft dji_graft_gui.py
if errorlevel 1 goto :fail

echo.
echo 打包完成：dist\DJIGraft.exe
goto :end

:fail
echo.
echo 打包失败，请检查上方的错误信息。

:end
pause
