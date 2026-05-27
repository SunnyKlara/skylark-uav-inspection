@echo off
chcp 65001 >nul
cls
"E:\conda_envs\yolo\python.exe" "%~dp0setup\watch_progress.py" %*
echo.
pause
