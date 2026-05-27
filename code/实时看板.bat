@echo off
chcp 65001 >nul
title 实验进度看板 - 每 10 秒自动刷新 - Ctrl+C 退出
"E:\conda_envs\yolo\python.exe" "%~dp0setup\watch_progress.py" --watch --interval 10
