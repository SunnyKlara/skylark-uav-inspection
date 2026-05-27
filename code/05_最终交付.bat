@echo off
REM 一键化论文收尾。daemon 跑完后或任何时候都可以重复执行。
chcp 65001 >nul

set "PROJECT=E:\Users\Administrator\Desktop\gp\graduation_project\code"
set "PYEXE=E:\conda_envs\yolo\python.exe"
set "TORCH_HOME=E:\torch_cache"
set "PYTHONIOENCODING=utf-8"

cd /d "%PROJECT%"

echo ============================================================
echo   最终交付 finalize_all
echo   时间: %date% %time%
echo ============================================================

"%PYEXE%" postprocess\finalize_all.py

echo.
echo ============================================================
echo   完成。查看：
echo     - runs\finalize_status.md         状态报告
echo     - runs\collected_metrics.json     汇总数字
echo     - runs\fill_report.md             回填报告
echo     - ..\paper\tex\main.pdf           英文 PDF
echo     - ..\paper\tex\main_zh.pdf        中文 PDF
echo     - ..\paper\defense\               答辩材料
echo ============================================================
pause
