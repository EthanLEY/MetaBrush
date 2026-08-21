@echo off
rem MetaBrush 一键打包：Python 3.10+ -> 单 EXE + 桌面快捷方式
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
if errorlevel 1 (
    echo.
    echo [MetaBrush] 打包失败，请查看上方错误信息。
    pause
    exit /b 1
)
pause
