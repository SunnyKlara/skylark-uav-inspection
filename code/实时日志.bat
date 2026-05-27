@echo off
chcp 65001 >nul
title 训练实时日志 - Ctrl+C 退出
cls
echo ============================================================
echo   实时跟踪当前训练子进程的输出 (runs\current.log)
echo   你会看到 ultralytics 每个 batch 的 loss / 进度条 / mAP
echo   切换到下一个阶段时,这个文件会被清空重写
echo   Ctrl+C 退出
echo ============================================================
echo.
powershell -NoProfile -Command "while ($true) { if (Test-Path 'E:\Users\Administrator\Desktop\gp\graduation_project\code\runs\current.log') { Get-Content 'E:\Users\Administrator\Desktop\gp\graduation_project\code\runs\current.log' -Wait -Tail 60 } else { Write-Host 'waiting for current.log...'; Start-Sleep -Seconds 3 } }"
