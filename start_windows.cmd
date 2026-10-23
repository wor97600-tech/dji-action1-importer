@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0dji_graft_gui.py"
) else (
    start "" pythonw "%~dp0dji_graft_gui.py"
)
