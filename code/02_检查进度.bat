@echo off
chcp 65001 >nul
set "ENV_PATH=E:\conda_envs\yolo"

if not exist "%ENV_PATH%\python.exe" (
    echo [错误] 没找到 yolo 环境,请先跑 00_一键装环境.bat
    pause
    exit /b 1
)

call conda run -p "%ENV_PATH%" python setup\check_progress.py
echo.
pause
