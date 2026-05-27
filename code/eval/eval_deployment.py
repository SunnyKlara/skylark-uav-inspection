"""
部署可行性测试
=================
对最终模型做:
  - PyTorch FP32 / FP16 推理
  - ONNX 导出 + onnxruntime 推理
  - (可选) TensorRT FP16

输出:paper/tables/deployment_table.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

RUNS_ROOT = PROJECT_ROOT / "runs"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"

OURS_RUN = RUNS_ROOT / "ours" / "yolo11n_full"
WEIGHTS = OURS_RUN / "weights" / "best.pt"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IMG_SIZE = 640
WARMUP = 20
RUNS = 100


def benchmark_pytorch_fp32() -> dict:
    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))
    model.fuse()
    arr = np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)

    for _ in range(WARMUP):
        model.predict(source=arr, verbose=False)

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(RUNS):
        model.predict(source=arr, verbose=False)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.time() - t0

    return {
        "engine": "PyTorch FP32",
        "fps":    RUNS / elapsed,
        "ms":     elapsed / RUNS * 1000,
    }


def benchmark_pytorch_fp16() -> dict:
    if not torch.cuda.is_available():
        return {"engine": "PyTorch FP16", "skipped": "no cuda"}
    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))
    model.fuse()
    model.to("cuda").half()
    arr = np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)

    for _ in range(WARMUP):
        model.predict(source=arr, verbose=False, half=True)

    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(RUNS):
        model.predict(source=arr, verbose=False, half=True)
    torch.cuda.synchronize()
    elapsed = time.time() - t0

    return {
        "engine": "PyTorch FP16",
        "fps":    RUNS / elapsed,
        "ms":     elapsed / RUNS * 1000,
    }


def benchmark_onnx() -> dict:
    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))
    onnx_path = model.export(format="onnx", imgsz=IMG_SIZE,
                             opset=17, simplify=True)
    onnx_path = Path(onnx_path)
    if not onnx_path.exists():
        return {"engine": "ONNX", "skipped": "export failed"}

    try:
        import onnxruntime as ort
    except ImportError:
        return {"engine": "ONNX",
                "skipped": "onnxruntime 未装"}

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] \
        if torch.cuda.is_available() else ["CPUExecutionProvider"]
    sess = ort.InferenceSession(str(onnx_path), providers=providers)
    input_name = sess.get_inputs()[0].name

    arr = np.zeros((1, 3, IMG_SIZE, IMG_SIZE), dtype=np.float32)
    for _ in range(WARMUP):
        sess.run(None, {input_name: arr})
    t0 = time.time()
    for _ in range(RUNS):
        sess.run(None, {input_name: arr})
    elapsed = time.time() - t0

    size_mb = onnx_path.stat().st_size / 1024 / 1024
    return {
        "engine":  "ONNX (onnxruntime)",
        "fps":     RUNS / elapsed,
        "ms":      elapsed / RUNS * 1000,
        "size_MB": size_mb,
    }


def write_table(rows: list[dict]) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    md = TABLE_DIR / "deployment_table.md"
    with md.open("w", encoding="utf-8") as f:
        f.write("# 部署可行性测试(Ours - yolo11n_full)\n\n")
        f.write("| Engine | FPS | Latency (ms) | Size (MB) |\n")
        f.write("|--------|-----|--------------|-----------|\n")
        for r in rows:
            if "skipped" in r:
                f.write(f"| {r['engine']} | - | - | - |  *{r['skipped']}*\n")
                continue
            size = r.get("size_MB", "-")
            size_str = f"{size:.2f}" if isinstance(size, float) else str(size)
            f.write(
                f"| {r['engine']} | "
                f"{r['fps']:.1f} | "
                f"{r['ms']:.2f} | "
                f"{size_str} |\n"
            )
    print(f"✅ 部署对比表写入 {md}")


def main() -> None:
    register()

    if not WEIGHTS.exists():
        raise FileNotFoundError(f"找不到 {WEIGHTS},先训完 ours 再来")

    print("=" * 60)
    print("  部署可行性测试")
    print("=" * 60)

    rows = [
        benchmark_pytorch_fp32(),
        benchmark_pytorch_fp16(),
        benchmark_onnx(),
    ]
    for r in rows:
        print(r)

    write_table(rows)


if __name__ == "__main__":
    main()
