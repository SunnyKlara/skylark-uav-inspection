@echo off
chcp 65001 >nul
set "ENV_PATH=E:\conda_envs\yolo"
set "TORCH_HOME=E:\torch_cache"
set "ULTRALYTICS_DIR=E:\torch_cache\ultralytics"

if not exist "%ENV_PATH%\python.exe" (
    echo [错误] 没找到 yolo 环境,请先跑 00_一键装环境.bat
    pause
    exit /b 1
)

echo [Eval] 复杂度对比
call conda run -p "%ENV_PATH%" python eval\eval_complexity.py

echo.
echo [Eval] 鲁棒性
call conda run -p "%ENV_PATH%" python eval\eval_robustness.py

echo.
echo [Eval] 部署
call conda run -p "%ENV_PATH%" python eval\eval_deployment.py

echo.
echo [Vis] 训练曲线
call conda run -p "%ENV_PATH%" python visualize\plot_results.py

echo.
echo [Vis] Grad-CAM
call conda run -p "%ENV_PATH%" python visualize\grad_cam.py

echo.
echo [Vis] 检测结果对比
call conda run -p "%ENV_PATH%" python visualize\make_qualitative.py

echo.
echo ============================================================
echo   评估 + 出图完成
echo   产物在 paper\tables\ 和 paper\figures\
echo ============================================================
pause
