"""
环境验证脚本（5060 Ti / Blackwell 强化版）

普通 import 检查不够，因为 PyTorch 装错版本时 import 不报错，
但跑到第一次 kernel 调用才会炸 "no kernel image available"。
所以这里实跑一次卷积，确认 sm_120 真能用。
"""
from __future__ import annotations

import sys


def check_python() -> bool:
    v = sys.version_info
    if v.major == 3 and v.minor >= 10:
        print(f"✅ Python 版本：{v.major}.{v.minor}.{v.micro}")
        return True
    print(f"❌ Python 版本：{v.major}.{v.minor}.{v.micro}（需要 3.10+）")
    return False


def check_torch_smoke() -> bool:
    """
    重点：不仅看 cuda.is_available，还要实跑一次卷积。
    Blackwell (sm_120) 在旧版 PyTorch 上 is_available()=True，
    但 conv2d 会炸 "CUDA error: no kernel image available for execution"。
    """
    try:
        import torch
    except ImportError:
        print("❌ PyTorch 未安装")
        return False

    print(f"✅ PyTorch 版本：{torch.__version__}")
    print(f"✅ PyTorch 编译时 CUDA 版本：{torch.version.cuda}")

    if not torch.cuda.is_available():
        print("❌ CUDA 不可用 —— 检查驱动 / cu128 wheel 是否装对")
        return False

    dev = torch.cuda.get_device_properties(0)
    cap = torch.cuda.get_device_capability(0)
    sm  = f"sm_{cap[0]}{cap[1]}"
    mem = dev.total_memory / 1024 / 1024
    print(f"✅ GPU 名称：{dev.name}")
    print(f"✅ GPU 显存：{mem:.0f} MiB")
    print(f"✅ Compute Capability：{sm}")

    if mem < 7000:
        print("⚠️  显存 < 7G，可能不是 5060 Ti，请确认")

    # 真实 kernel 测试 ----------------------------------------
    try:
        x = torch.randn(8, 3, 224, 224, device="cuda")
        conv = torch.nn.Conv2d(3, 16, 3, padding=1).cuda()
        y = conv(x)
        torch.cuda.synchronize()
        _ = y.sum().item()
        print(f"✅ CUDA kernel 测试通过（卷积 {tuple(y.shape)}）")
    except RuntimeError as e:
        msg = str(e)
        print(f"❌ CUDA kernel 失败：{msg.splitlines()[0]}")
        if "no kernel image" in msg or "not compatible" in msg:
            print("   → 你的 PyTorch wheel 不支持当前 GPU 架构。")
            print("     Blackwell (sm_120) 需要 PyTorch ≥ 2.7.1 + cu128:")
            print("     pip install torch==2.7.1 torchvision==0.22.1 \\")
            print("         --index-url https://download.pytorch.org/whl/cu128")
        return False
    except Exception as e:
        print(f"❌ CUDA 测试出错：{e}")
        return False

    # 半精度也跑一下，YOLO 训练默认用 AMP --------------------
    try:
        with torch.autocast("cuda", dtype=torch.float16):
            _ = conv(x).sum().item()
        print("✅ 半精度 (FP16 / AMP) 测试通过")
    except Exception as e:
        print(f"⚠️  FP16 测试失败：{e}（不致命，但训练 AMP 可能要关）")

    return True


def check_ultralytics() -> bool:
    try:
        import ultralytics
        print(f"✅ ultralytics 版本：{ultralytics.__version__}")
        return True
    except ImportError:
        print("❌ ultralytics 未安装")
        return False


def check_others() -> bool:
    pkgs = ["cv2", "numpy", "pandas", "matplotlib", "yaml", "tqdm",
            "thop", "onnx", "onnxruntime"]
    missing = []
    for p in pkgs:
        try:
            __import__(p)
        except ImportError:
            missing.append(p)
    if missing:
        print(f"❌ 缺失依赖：{', '.join(missing)}")
        return False
    print("✅ 其他依赖：opencv / numpy / pandas / matplotlib / pyyaml / "
          "tqdm / thop / onnx / onnxruntime")
    return True


def main() -> int:
    print("=" * 60)
    print("  毕设项目环境验证（5060 Ti / Blackwell 强化版）")
    print("=" * 60)

    results = [
        check_python(),
        check_torch_smoke(),
        check_ultralytics(),
        check_others(),
    ]

    print()
    print("=" * 60)
    if all(results):
        print("  ==> 环境就绪，可以开始训练")
        print("=" * 60)
        return 0
    print("  ==> 有 ❌，把上面输出截图发我")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
