"""
训练你的"最终方法":YOLOv11n + CBAM + P2 小目标头
=====================================================

用法:
  conda activate yolo
  python train/train_ours.py

会自动:
  1. 用 configs/yolo11n_full.yaml 这个网络结构
  2. 加载 yolo11n 预训练权重做迁移
  3. 训完写 paper/tables/main_comparison.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

DATA_YAML = PROJECT_ROOT / "data" / "processed" / "pvel_yolo" / "data.yaml"
RUNS_ROOT = PROJECT_ROOT / "runs" / "ours"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--cfg", default="configs/yolo11n_full.yaml")
    p.add_argument("--name", default="yolo11n_full")
    p.add_argument("--pretrained", default="yolo11n.pt",
                   help="预训练权重(传 '' 则从头训)")
    p.add_argument("--epochs", type=int, default=150)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--device", type=str, default="0")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # 必须在 import YOLO 之前注册自定义模块
    register()
    from ultralytics import YOLO

    if not DATA_YAML.exists():
        raise FileNotFoundError(f"找不到 {DATA_YAML},先跑数据准备脚本")

    cfg_path = (PROJECT_ROOT / args.cfg).resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到模型 yaml: {cfg_path}")

    print("=" * 60)
    print(f"  训练 ours: {args.name}")
    print(f"  配置: {cfg_path}")
    print(f"  预训练: {args.pretrained or '从头训'}")
    print("=" * 60)

    if args.pretrained:
        # cfg 决定结构,pretrained 决定权重(非匹配层会被忽略)
        model = YOLO(str(cfg_path)).load(args.pretrained)
    else:
        model = YOLO(str(cfg_path))

    t0 = time.time()
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        device=args.device,
        project=str(RUNS_ROOT),
        name=args.name,
        exist_ok=True,
        verbose=True,
        plots=True,
    )
    elapsed = time.time() - t0

    metrics = {
        "model": args.name,
        "mAP_50":     float(results.box.map50) if hasattr(results, "box") else None,
        "mAP_50_95":  float(results.box.map)   if hasattr(results, "box") else None,
        "precision":  float(results.box.mp)    if hasattr(results, "box") else None,
        "recall":     float(results.box.mr)    if hasattr(results, "box") else None,
        "train_time": elapsed,
    }

    out_dir = RUNS_ROOT / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir.parent / f"{args.name}_metrics.json").write_text(
        json.dumps(metrics, indent=2)
    )

    # 把结果合并进 main_comparison.md
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    md_path = TABLE_DIR / "main_comparison.md"

    baseline_md = TABLE_DIR / "baseline_table.md"
    md_path.write_text((baseline_md.read_text(encoding="utf-8") if baseline_md.exists() else "")
                       + f"\n\n## Ours\n\n"
                       f"| Model | mAP@0.5 | mAP@0.5:0.95 | Precision | Recall | Train (h) |\n"
                       f"|-------|---------|--------------|-----------|--------|-----------|\n"
                       f"| **{args.name} (Ours)** | "
                       f"{metrics['mAP_50']:.3f} | {metrics['mAP_50_95']:.3f} | "
                       f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | "
                       f"{metrics['train_time']/3600:.2f} |\n",
                       encoding="utf-8")

    print()
    print("=" * 60)
    print(f"  训练完成: {args.name}")
    print(f"  mAP@0.5    = {metrics['mAP_50']:.4f}")
    print(f"  mAP@0.5:.95 = {metrics['mAP_50_95']:.4f}")
    print(f"  权重:      {out_dir / 'weights' / 'best.pt'}")
    print(f"  对比表:    {md_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
