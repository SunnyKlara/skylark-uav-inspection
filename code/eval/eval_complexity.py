"""
模型复杂度对比:Params / FLOPs / FPS / 模型大小
================================================

对比 baseline 和你的方法的:
  - 参数量(Params, M)
  - 计算量(FLOPs, G)
  - 推理速度(FPS)
  - 权重文件大小(MB)

输出:paper/tables/complexity_table.md
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

RUNS_ROOT = PROJECT_ROOT / "runs"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"

CANDIDATES = [
    # (展示名, 训练 run 路径)
    ("YOLOv8n",    RUNS_ROOT / "baseline" / "yolov8n"),
    ("YOLOv10n",   RUNS_ROOT / "baseline" / "yolov10n"),
    ("YOLOv11n",   RUNS_ROOT / "baseline" / "yolo11n"),
    ("Ours (Full)", RUNS_ROOT / "ours" / "yolo11n_full"),
]

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def measure_one(name: str, run_dir: Path, imgsz: int = 640,
                warmup: int = 20, runs: int = 100) -> dict:
    weights = run_dir / "weights" / "best.pt"
    if not weights.exists():
        return {"name": name, "error": f"找不到权重 {weights}"}

    from ultralytics import YOLO
    model = YOLO(str(weights))
    model.fuse()

    # 参数量
    n_params = sum(p.numel() for p in model.model.parameters())

    # 计算量 — 用 thop
    try:
        from thop import profile
        dummy = torch.zeros(1, 3, imgsz, imgsz, device=DEVICE)
        model.model.to(DEVICE).eval()
        flops, _ = profile(model.model, inputs=(dummy,), verbose=False)
    except Exception as e:
        flops = None
        print(f"  ⚠️  {name} 计算 FLOPs 失败: {e}")

    # FPS - 用真实图片走推理(更接近实际)
    model.predict(source=torch.zeros(3, imgsz, imgsz).numpy(), verbose=False)
    dummy_np = torch.zeros(3, imgsz, imgsz).numpy()
    for _ in range(warmup):
        model.predict(source=dummy_np, verbose=False)

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(runs):
        model.predict(source=dummy_np, verbose=False)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    fps = runs / (time.time() - t0)

    return {
        "name":         name,
        "params_M":     n_params / 1e6,
        "flops_G":      flops / 1e9 if flops else None,
        "fps":          fps,
        "size_MB":      weights.stat().st_size / 1024 / 1024,
    }


def write_table(all_metrics: list[dict]) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    md = TABLE_DIR / "complexity_table.md"
    with md.open("w", encoding="utf-8") as f:
        f.write("# 模型复杂度对比\n\n")
        f.write("| Model | Params (M) | FLOPs (G) | FPS | Size (MB) |\n")
        f.write("|-------|------------|-----------|-----|-----------|\n")
        for m in all_metrics:
            if "error" in m:
                f.write(f"| {m['name']} | - | - | - | - |  *{m['error']}*\n")
                continue
            flops_str = f"{m['flops_G']:.2f}" if m.get("flops_G") else "-"
            f.write(
                f"| {m['name']} | "
                f"{m['params_M']:.2f} | "
                f"{flops_str} | "
                f"{m['fps']:.1f} | "
                f"{m['size_MB']:.2f} |\n"
            )

    print()
    print(f"✅ 复杂度表写入 {md}")


def main() -> None:
    register()
    all_metrics = []
    for name, run_dir in CANDIDATES:
        print(f"==> 评估 {name}")
        m = measure_one(name, run_dir)
        print(f"   {m}")
        all_metrics.append(m)

    (TABLE_DIR.parent.parent / "runs" / "complexity.json").write_text(
        json.dumps(all_metrics, indent=2)
    )
    write_table(all_metrics)


if __name__ == "__main__":
    main()
