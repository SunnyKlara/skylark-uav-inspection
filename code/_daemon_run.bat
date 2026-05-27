@echo off
REM 独立守护批处理：被 schtasks 调起，与任何交互式窗口完全脱离
REM 标准输出/错误重定向到 runs\daemon.log，进程树挂在 svchost (taskeng) 下，
REM 关闭任何 PowerShell / Kiro / 桌面会话都不会影响它。
chcp 65001 >nul

set "PROJECT=E:\Users\Administrator\Desktop\gp\graduation_project\code"
set "PYEXE=E:\conda_envs\yolo\python.exe"
set "TORCH_HOME=E:\torch_cache"
set "ULTRALYTICS_DIR=E:\torch_cache\ultralytics"
set "PYTHONIOENCODING=utf-8"

cd /d "%PROJECT%"

echo === daemon started %date% %time% === >> runs\daemon.log

"%PYEXE%" run_full_pipeline.py --epochs 80 >> runs\daemon.log 2>&1

echo === daemon finished %date% %time% (exit %ERRORLEVEL%) === >> runs\daemon.log
