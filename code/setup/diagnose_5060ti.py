"""
RTX 5060 Ti (Blackwell) 兼容性诊断脚本
=========================================

5060 Ti 是 2025 年发布的 Blackwell 架构 (Compute Capability 12.0, sm_120)。
旧版 PyTorch / CUDA 不识别它，跑训练时第一次 kernel 调用会炸：
   "no kernel image is available for execution on the device"

唯一稳定可用的组合：
   PyTorch 2.7.1 + CUDA 12.8 wheel (cu128 索引)

本脚本检查 5 个常见兼容性问题，并给出修复指令。

跑法:
   conda activate <env>
   python setup/diagnose_5060ti.py
"""
from __future__ import annotations

import subprocess
import sys

CU128_INSTALL = (
    "pip install torch==2.7.1 torchvision==0.22.1 "
    "--index-url https://download.pytorch.org/whl/cu128"
)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_driver_version() -> tuple[bool, str]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            text=True,
        ).strip().splitlines()[0]
        print(f"驱动版本:           {out}")
        major = int(out.split(".")[0])
        # Blackwell desktop 驱动从 570 开始正式支持
        if major < 570:
            return False, (
                f"驱动 {out} 太旧，5060 Ti 建议 ≥ 570。"
                "去 https://www.nvidia.com/Download/index.aspx 装最新驱动后重启。"
            )
        return True, "驱动版本足够新"
    except Exception as e:
        return False, f"读取驱动版本失败: {e}"


def check_pytorch_version() -> tuple[bool, str]:
    try:
        import torch
    except ImportError:
        return False, "PyTorch 未安装。装：" + CU128_INSTALL

    version = torch.__version__
    cuda_version = torch.version.cuda or "none"
    print(f"PyTorch 版本:       {version}")
    print(f"内置 CUDA 版本:     {cuda_version}")

    # 解析 X.Y
    base = version.split("+")[0]
    parts = base.split(".")
    major = int(parts[0])
    minor = int(parts[1])
    if (major, minor) < (2, 7):
        return False, (
            f"PyTorch {version} 不支持 sm_120。\n"
            f"   解决：{CU128_INSTALL}"
        )

    if cuda_version and not cuda_version.startswith("12.8") and not cuda_version.startswith("12.9"):
        return False, (
            f"PyTorch 内置 CUDA 是 {cuda_version}，5060 Ti 需要 12.8+。\n"
            f"   解决：{CU128_INSTALL}"
        )
    return True, "PyTorch 版本和 CUDA 适配 5060 Ti"


def check_cuda_capability() -> tuple[bool, str]:
    try:
        import torch
    except ImportError:
        return False, "PyTorch 未安装"

    if not torch.cuda.is_available():
        return False, "CUDA 不可用（驱动 / 显卡 / WSL 设置问题）"

    cap = torch.cuda.get_device_capability(0)
    name = torch.cuda.get_device_name(0)
    print(f"GPU:                 {name}")
    print(f"Compute capability:  sm_{cap[0]}{cap[1]}")

    supported = torch.cuda.get_arch_list()
    print(f"PyTorch 支持架构:    {supported}")

    if cap[0] >= 12:
        if not any("120" in s for s in supported):
            return False, (
                "PyTorch 没有 sm_120 kernel，跑训练会炸 'no kernel image'。\n"
                f"   解决：{CU128_INSTALL}"
            )
    return True, "GPU 架构匹配"


def check_compute_runtime() -> tuple[bool, str]:
    try:
        import torch
        if not torch.cuda.is_available():
            return False, "CUDA 不可用"

        # 真跑一次卷积，比 matmul 更接近实际训练负载
        x = torch.randn(8, 3, 224, 224, device="cuda")
        conv = torch.nn.Conv2d(3, 16, 3, padding=1).cuda()
        y = conv(x)
        torch.cuda.synchronize()
        _ = y.sum().item()
        return True, f"GPU 卷积 OK (输出 {tuple(y.shape)})"
    except RuntimeError as e:
        msg = str(e).splitlines()[0]
        if "no kernel image" in str(e):
            return False, (
                f"{msg}\n"
                f"   → PyTorch wheel 不支持当前 GPU 架构。\n"
                f"   解决：{CU128_INSTALL}"
            )
        return False, msg
    except Exception as e:
        return False, str(e)


def check_ultralytics() -> tuple[bool, str]:
    try:
        import ultralytics
        print(f"ultralytics 版本:   {ultralytics.__version__}")
        return True, "ultralytics OK"
    except ImportError:
        return False, "ultralytics 未安装：pip install ultralytics"


def main() -> int:
    section("RTX 5060 Ti 兼容性诊断")

    checks = [
        ("驱动版本",     check_driver_version),
        ("PyTorch 版本", check_pytorch_version),
        ("GPU 架构支持", check_cuda_capability),
        ("ultralytics",  check_ultralytics),
        ("GPU 真实计算", check_compute_runtime),
    ]

    results = []
    for name, fn in checks:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, str(e)
        results.append((name, ok, msg))

    section("诊断报告")
    for name, ok, msg in results:
        marker = "[OK]  " if ok else "[!!]  "
        print(f"{marker}{name}: {msg}")

    failed = [r for r in results if not r[1]]

    print()
    if not failed:
        print("=" * 60)
        print("  ==> 全部通过,环境就绪")
        print("=" * 60)
        return 0

    print("=" * 60)
    print(f"  ==> 有 {len(failed)} 项需要修复")
    print("  ==> 把上面 [!!] 行截图发给 Kiro，我会给具体修复步骤")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
