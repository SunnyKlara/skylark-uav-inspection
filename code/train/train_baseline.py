"""
一键训练 4 个 baseline
========================
- YOLOv8n
- YOLOv10n
- YOLOv11n
- RT-DETR-l

训练完会自动:
  - 把每个模型的最终 mAP / Precision / Recall / FPS 写到 paper/tables/baseline_table.md
  - 把权重保存到 runs/baseline/<model>/

用法:
  conda activate yolo
  python train/train_baseline.py
  # 想只跑某一个: python train/train_baseline.py --only yolo11n
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = PROJECT_ROOT / "data" / "processed" / "pvel_yolo" / "data.yaml"
RUNS_ROOT = PROJECT_ROOT / "runs" / "baseline"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"

BASELINES = [
    {"name": "yolov8n",  "weights": "yolov8n.pt",  "task": "detect", "framework": "yolo"},
    {"name": "yolov10n", "weights": "yolov10n.pt", "task": "detect", "framework": "yolo"},
    {"name": "yolo11n",  "weights": "yolo11n.pt",  "task": "detect", "framework": "yolo"},
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=100,
                   help="训练 epochs(默认 100)")
    p.add_argument("--imgsz", type=int, default=640,
                   help="输入分辨率(默认 640)")
    p.add_argument("--batch", type=int, default=8,
                   help="batch size(5060 Ti 16G 在 PVEL-AD 上 8 稳定;16 会触发 bad allocation)")
    p.add_argument("--workers", type=int, default=2,
                   help="dataloader 进程数(Windows 多进程兼容性问题,2 比默认 8 稳)")
    p.add_argument("--only", type=str, default=None,
                   help="只跑某个模型(yolo11n / yolov8n / rtdetr 等)")
    p.add_argument("--device", type=str, default="0", help="GPU 编号")
    return p.parse_args()


def train_one(cfg: dict, args: argparse.Namespace) -> dict:
    from ultralytics import YOLO, RTDETR

    model_cls = RTDETR if cfg["framework"] == "rtdetr" else YOLO
    model = model_cls(cfg["weights"])

    print()
    print("=" * 60)
    print(f"  开始训练 {cfg['name']}")
    print("=" * 60)

    out_dir = RUNS_ROOT / cfg["name"]
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        device=args.device,
        project=str(RUNS_ROOT),
        name=cfg["name"],
        exist_ok=True,
        verbose=True,
        plots=True,
    )
    elapsed = time.time() - t0

    # 取出关键指标(ultralytics 8.3+)
    metrics = {
        "model": cfg["name"],
        "mAP_50":     float(results.box.map50) if hasattr(results, "box") else None,
        "mAP_50_95":  float(results.box.map)   if hasattr(results, "box") else None,
        "precision":  float(results.box.mp)    if hasattr(results, "box") else None,
        "recall":     float(results.box.mr)    if hasattr(results, "box") else None,
        "train_time": elapsed,
    }

    # 跑一次 val 拿 FPS
    val_t0 = time.time()
    _ = model.val(data=str(DATA_YAML), imgsz=args.imgsz,
                  batch=args.batch, workers=args.workers,
                  device=args.device, verbose=False)
    val_elapsed = time.time() - val_t0

    val_lbl_dir = (PROJECT_ROOT / "data" / "processed"
                   / "pvel_yolo" / "labels" / "val")
    n_val = sum(1 for _ in val_lbl_dir.glob("*.txt")) if val_lbl_dir.exists() else 1
    metrics["fps_val"] = n_val / max(val_elapsed, 1e-3)

    # 模型大小
    weights_path = out_dir / "weights" / "best.pt"
    if weights_path.exists():
        size_mb = weights_path.stat().st_size / 1024 / 1024
        metrics["weights_size_mb"] = size_mb

    return metrics


def write_table(all_metrics: list[dict]) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    md_path = TABLE_DIR / "baseline_table.md"
    csv_path = TABLE_DIR / "baseline_table.csv"

    cols = ["model", "mAP_50", "mAP_50_95", "precision", "recall",
            "fps_val", "weights_size_mb", "train_time"]

    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Baseline 对比表\n\n")
        f.write("| Model | mAP@0.5 | mAP@0.5:0.95 | Precision | Recall | "
                "FPS | Weight (MB) | Train (h) |\n")
        f.write("|-------|---------|--------------|-----------|--------|-----|"
                "-------------|-----------|\n")
        for m in all_metrics:
            row = (
                f"| {m['model']} | "
                f"{m.get('mAP_50', 0):.3f} | "
                f"{m.get('mAP_50_95', 0):.3f} | "
                f"{m.get('precision', 0):.3f} | "
                f"{m.get('recall', 0):.3f} | "
                f"{m.get('fps_val', 0):.1f} | "
                f"{m.get('weights_size_mb', 0):.2f} | "
                f"{m.get('train_time', 0)/3600:.2f} |"
            )
            f.write(row + "\n")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for m in all_metrics:
            writer.writerow({k: m.get(k, "") for k in cols})

    print()
    print("=" * 60)
    print(" 全部 baseline 训练完成")
    print("=" * 60)
    print(f" 论文表格: {md_path}")
    print(f" 原始 CSV: {csv_path}")


def main() -> None:
    args = parse_args()

    if not DATA_YAML.exists():
        raise FileNotFoundError(
            f"数据集未准备 - 找不到 {DATA_YAML}\n"
            "先跑 `python data/prepare_pvel_ad.py`"
        )

    if args.only:
        models = [b for b in BASELINES if b["name"] == args.only]
        if not models:
            raise ValueError(f"--only 参数不在候选里: {args.only}")
    else:
        models = BASELINES

    all_metrics = []
    for cfg in models:
        try:
            m = train_one(cfg, args)
            all_metrics.append(m)
            (RUNS_ROOT / f"{cfg['name']}_metrics.json").write_text(
                json.dumps(m, indent=2)
            )
        except Exception as e:
            print(f"❌ {cfg['name']} 失败: {e}")
            all_metrics.append({"model": cfg["name"], "error": str(e)})

    write_table(all_metrics)


if __name__ == "__main__":
    main()
