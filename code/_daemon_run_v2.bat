@echo off
REM v2 daemon - 由 schtasks 启动，独立 svchost 进程
REM 跑 run_pipeline_v2.py（E1+E2+E3+E4+eval）
chcp 65001 >nul

set "PROJECT=E:\Users\Administrator\Desktop\gp\graduation_project\code"
set "PYEXE=E:\conda_envs\yolo\python.exe"
set "TORCH_HOME=E:\torch_cache"
set "ULTRALYTICS_DIR=E:\torch_cache\ultralytics"
set "PYTHONIOENCODING=utf-8"

cd /d "%PROJECT%"

if not exist runs\v2 mkdir runs\v2

echo === daemon_v2 started %date% %time% === >> runs\v2\daemon_v2.log

"%PYEXE%" run_pipeline_v2.py >> runs\v2\daemon_v2.log 2>&1

echo === daemon_v2 finished %date% %time% (exit %ERRORLEVEL%) === >> runs\v2\daemon_v2.log
