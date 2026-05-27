@echo off
REM ============================================================
REM  毕设项目 - Windows 一键装环境（5060 Ti / Blackwell 适配版）
REM
REM  关键事实：
REM    - 5060 Ti 是 sm_120（Blackwell）
REM    - 唯一稳定可用的组合：PyTorch 2.7.1 + CUDA 12.8（cu128 wheel）
REM    - cu121 / cu124 都会跑炸 "no kernel image"
REM
REM  全部装到 E 盘：
REM    E:\conda_envs\yolo      虚拟环境
REM    E:\pip_cache            pip 缓存
REM    E:\torch_cache          PyTorch / ultralytics 模型缓存
REM    E:\hf_cache             HuggingFace 缓存
REM
REM  双击运行即可。重跑安全（幂等）。
REM ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   毕设项目环境一键安装
echo   目标 GPU: NVIDIA RTX 5060 Ti 16G ^(Blackwell sm_120^)
echo   组合:     PyTorch 2.7.1 + CUDA 12.8
echo   位置:     E 盘
echo ============================================================
echo.

REM 1. 检查项目目录
if not exist "setup\verify_gpu.py" (
    echo [错误] 没有找到 setup\verify_gpu.py
    echo 请把这个 .bat 放到 graduation_project\code 目录下双击
    pause
    exit /b 1
)

REM 2. 准备 E 盘目录
set "ENV_ROOT=E:\conda_envs"
set "PIP_CACHE=E:\pip_cache"
set "TORCH_CACHE=E:\torch_cache"
set "HF_CACHE=E:\hf_cache"

if not exist "%ENV_ROOT%"   mkdir "%ENV_ROOT%"
if not exist "%PIP_CACHE%"  mkdir "%PIP_CACHE%"
if not exist "%TORCH_CACHE%" mkdir "%TORCH_CACHE%"
if not exist "%HF_CACHE%"   mkdir "%HF_CACHE%"

set "PIP_CACHE_DIR=%PIP_CACHE%"
set "TORCH_HOME=%TORCH_CACHE%"
set "HF_HOME=%HF_CACHE%"
set "HUGGINGFACE_HUB_CACHE=%HF_CACHE%"
set "ULTRALYTICS_DIR=%TORCH_CACHE%\ultralytics"

echo [INFO] 缓存目录:
echo    pip       -^> %PIP_CACHE%
echo    torch     -^> %TORCH_CACHE%
echo    hf        -^> %HF_CACHE%
echo    conda env -^> %ENV_ROOT%\yolo
echo.

REM 3. 找 conda
where conda >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 conda 命令
    echo.
    echo 请先安装 Miniconda3 ^(强烈建议装到 E 盘^):
    echo   1^) 下载: https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
    echo   2^) 安装时点 Customize Install
    echo   3^) 安装路径选 E:\Miniconda3
    echo   4^) 勾选 "Add Miniconda3 to my PATH"
    echo   5^) 装完重启电脑
    echo   6^) 重新双击本文件
    echo.
    pause
    exit /b 1
)
echo [OK] conda 已安装

REM 4. 检查 nvidia-smi
where nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 nvidia-smi
    echo 请安装最新 NVIDIA 驱动: https://www.nvidia.com/Download/index.aspx
    echo 5060 Ti 需要驱动版本 ^>= 570.x
    pause
    exit /b 1
)
echo [OK] 检测显卡:
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
echo.

REM 5. 创建 conda 环境
set "ENV_PATH=%ENV_ROOT%\yolo"
echo ==^> 创建 conda 环境到 %ENV_PATH%
if exist "%ENV_PATH%\python.exe" (
    echo    环境已存在,跳过创建
) else (
    call conda create --prefix "%ENV_PATH%" python=3.11 pip -y
    if errorlevel 1 (
        echo [错误] 创建环境失败
        pause
        exit /b 1
    )
)

REM 6. 装 PyTorch 2.7.1 + CUDA 12.8（5060 Ti 唯一稳定组合）
echo.
echo ==^> 升级 pip
call conda run -p "%ENV_PATH%" python -m pip install --upgrade pip --cache-dir "%PIP_CACHE%"

echo.
echo ==^> 安装 PyTorch 2.7.1 + torchvision 0.22.1 ^(CUDA 12.8 / cu128^)
call conda run -p "%ENV_PATH%" pip install ^
    torch==2.7.1 torchvision==0.22.1 ^
    --index-url https://download.pytorch.org/whl/cu128 ^
    --cache-dir "%PIP_CACHE%"

if errorlevel 1 (
    echo.
    echo [警告] 2.7.1+cu128 装失败,尝试 nightly cu128 兜底
    call conda run -p "%ENV_PATH%" pip install --pre torch torchvision ^
        --index-url https://download.pytorch.org/whl/nightly/cu128 ^
        --cache-dir "%PIP_CACHE%"
    if errorlevel 1 (
        echo [错误] PyTorch 安装彻底失败,请检查网络后重跑
        pause
        exit /b 1
    )
)

REM 7. 装 ultralytics 等其他依赖
echo.
echo ==^> 安装 ultralytics 与其他依赖
call conda run -p "%ENV_PATH%" pip install -r requirements.txt --cache-dir "%PIP_CACHE%"
if errorlevel 1 (
    echo [警告] 部分依赖安装失败,看上面输出
)

REM 8. 持久化环境变量
echo.
echo ==^> 持久化缓存路径到用户环境变量
setx PIP_CACHE_DIR         "%PIP_CACHE%"   >nul
setx TORCH_HOME            "%TORCH_CACHE%" >nul
setx HF_HOME               "%HF_CACHE%"    >nul
setx HUGGINGFACE_HUB_CACHE "%HF_CACHE%"    >nul
setx ULTRALYTICS_DIR       "%TORCH_CACHE%\ultralytics" >nul
echo    已写入用户级环境变量

REM 9. 写一个 _activate.bat 给后续脚本用
(
echo @echo off
echo set "PIP_CACHE_DIR=%PIP_CACHE%"
echo set "TORCH_HOME=%TORCH_CACHE%"
echo set "HF_HOME=%HF_CACHE%"
echo set "ULTRALYTICS_DIR=%TORCH_CACHE%\ultralytics"
echo call conda activate "%ENV_PATH%"
) > _activate.bat
echo    已生成 _activate.bat

REM 10. GPU 验证（含实跑卷积）
echo.
echo ==^> 运行环境验证脚本
call conda run -p "%ENV_PATH%" python setup\verify_gpu.py
set "VERIFY_RC=!ERRORLEVEL!"

REM 11. 5060 Ti 兼容性诊断
echo.
echo ==^> 运行 5060 Ti 兼容性诊断
call conda run -p "%ENV_PATH%" python setup\diagnose_5060ti.py

echo.
echo ============================================================
if "!VERIFY_RC!"=="0" (
    echo   ^| [OK] 装环境流程结束,验证通过
) else (
    echo   ^| [!!] 装环境结束,但验证有问题,看上面输出
)
echo   ^|
echo   ^| conda 环境位置: %ENV_PATH%
echo   ^| 所有缓存都在 E 盘
echo   ^|
echo   ^| 下一步:
echo   ^|   1^) 把上面所有输出截图发给 Kiro
echo   ^|   2^) 看 setup\dataset_layout.md 准备数据集
echo   ^|   3^) 数据集到位后双击 01_一键跑实验.bat
echo ============================================================
pause
exit /b !VERIFY_RC!
