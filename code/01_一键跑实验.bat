@echo off
REM ============================================================
REM  毕设 - 一键跑全套实验(挂机过夜)
REM
REM  跑这个之前需要先:
REM     1) 跑过 00_一键装环境.bat 且看到 [OK]
REM     2) 把数据集 zip 放到 data\raw\pvel_ad.zip
REM ============================================================
chcp 65001 >nul
setlocal

set "ENV_PATH=E:\conda_envs\yolo"

REM 缓存全部走 E 盘
set "PIP_CACHE_DIR=E:\pip_cache"
set "TORCH_HOME=E:\torch_cache"
set "HF_HOME=E:\hf_cache"
set "ULTRALYTICS_DIR=E:\torch_cache\ultralytics"

echo ============================================================
echo   一键跑全套实验
echo   conda 环境: %ENV_PATH%
echo   预计耗时:  24-36 小时(可挂机过夜)
echo ============================================================
echo.

REM 1. 进入项目目录
if not exist "train\train_baseline.py" (
    echo [错误] 请把这个 .bat 放到 graduation_project\code 目录下
    pause
    exit /b 1
)

REM 2. 检查 conda 环境
if not exist "%ENV_PATH%\python.exe" (
    echo [错误] 没有找到 yolo 环境 ^(%ENV_PATH%^)
    echo 请先双击运行 00_一键装环境.bat
    pause
    exit /b 1
)

REM ============================================================
REM Step 1: 数据集准备
REM ============================================================
echo.
echo [Step 1/6] 准备数据集
echo ------------------------------------------------------------
call conda run -p "%ENV_PATH%" python data\prepare_pvel_ad.py
if errorlevel 1 (
    echo.
    echo [警告] 数据集脚本退出.
    echo 通常意味着你还没下载数据集.脚本应该已经打印了下载链接.
    echo 下完后把 zip 放到 data\raw\pvel_ad.zip 重跑这个 .bat
    pause
    exit /b 1
)

REM ============================================================
REM Step 2: 数据集统计
REM ============================================================
echo.
echo [Step 2/6] 数据集统计 + 图
echo ------------------------------------------------------------
call conda run -p "%ENV_PATH%" python data\dataset_stats.py

REM ============================================================
REM Step 3: 4 baseline (耗时 6-10 小时)
REM ============================================================
echo.
echo [Step 3/6] 训练 4 个 baseline (会跑 6-10 小时,可挂机过夜)
echo ------------------------------------------------------------
call conda run -p "%ENV_PATH%" python train\train_baseline.py

REM ============================================================
REM Step 4: 训练我的方法 (3-4 小时)
REM ============================================================
echo.
echo [Step 4/6] 训练 ours (CBAM + P2)
echo ------------------------------------------------------------
call conda run -p "%ENV_PATH%" python train\train_ours.py

REM ============================================================
REM Step 5: 消融 (耗时 7-10 小时)
REM ============================================================
echo.
echo [Step 5/6] 消融实验 5 组
echo ------------------------------------------------------------
call conda run -p "%ENV_PATH%" python train\train_ablation.py

REM ============================================================
REM Step 6: 评估 + 出图
REM ============================================================
echo.
echo [Step 6/6] 评估 + 出图
echo ------------------------------------------------------------
call conda run -p "%ENV_PATH%" python eval\eval_complexity.py
call conda run -p "%ENV_PATH%" python eval\eval_robustness.py
call conda run -p "%ENV_PATH%" python eval\eval_deployment.py
call conda run -p "%ENV_PATH%" python visualize\plot_results.py
call conda run -p "%ENV_PATH%" python visualize\grad_cam.py
call conda run -p "%ENV_PATH%" python visualize\make_qualitative.py

echo.
echo ============================================================
echo   ^| 全部完成
echo   ^|
echo   ^| 论文表格在: paper\tables\
echo   ^| 论文图片在: paper\figures\
echo   ^|
echo   ^| 把这些文件夹发给 Kiro,进入"写论文"阶段
echo ============================================================
pause
