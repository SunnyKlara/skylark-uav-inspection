"""
消融实验
================
跑 7 组配置:

  1. yolo11n              baseline
  2. yolo11n_cbam         + CBAM only
  3. yolo11n_ema          + EMA only
  4. yolo11n_p2           + P2 head only
  5. yolo11n_cbam_p2      + CBAM + P2
  6. yolo11n_ema_p2       + EMA + P2
  7. yolo11n_full         CBAM + P2(我们的最终方法)

把每组的 mAP / 参数量 / FPS 写到 paper/tables/ablation_table.md

# Tip:这玩意会跑很久(7 组 x 100 epochs 大约 7-10 小时)。
# 推荐挂机过夜。如果时间紧:
#   python train/train_ablation.py --epochs 50  # 快速版
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
RUNS_ROOT = PROJECT_ROOT / "runs" / "ablation"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"

ABLATION_CONFIGS = [
    # 名称              cfg path                      pretrained     描述
    ("yolo11n",         "yolo11n.yaml",              "yolo11n.pt",  "Baseline (YOLOv11n)"),
    ("yolo11n_cbam",    "configs/yolo11n_cbam.yaml", "yolo11n.pt",  "+ CBAM"),
    ("yolo11n_ema",     "configs/yolo11n_ema.yaml",  "yolo11n.pt",  "+ EMA"),
    ("yolo11n_p2",      "configs/yolo11n_p2.yaml",   "yolo11n.pt",  "+ P2 head"),
    ("yolo11n_full",    "configs/yolo11n_full.yaml", "yolo11n.pt",  "+ CBAM + P2 (Ours)"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--device", type=str, default="0")
    p.add_argument("--skip", nargs="*", default=[],
                   help="跳过哪些 config(名字)")
    return p.parse_args()


def train_one(name: str, cfg: str, pretrained: str,
              args: argparse.Namespace) -> dict:
    from ultralytics import YOLO

    cfg_path = cfg if cfg.endswith(".yaml") and "/" not in cfg \
        else str((PROJECT_ROOT / cfg).resolve())

    print()
    print("=" * 60)
    print(f"  Ablation: {name}")
    print(f"  cfg = {cfg_path}")
    print(f"  pretrained = {pretrained}")
    print("=" * 60)

    if pretrained:
        try:
            model = YOLO(cfg_path).load(pretrained)
        except Exception:
            # baseline yaml 是 ultralytics 自带的,可以直接用 weights 起手
            model = YOLO(pretrained)
    else:
        model = YOLO(cfg_path)

    t0 = time.time()
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        device=args.device,
        project=str(RUNS_ROOT),
        name=name,
        exist_ok=True,
        verbose=True,
        plots=True,
    )
    elapsed = time.time() - t0

    # 参数量(基于 PyTorch model)
    n_params = sum(p.numel() for p in model.model.parameters())

    metrics = {
        "name":       name,
        "mAP_50":     float(results.box.map50) if hasattr(results, "box") else None,
        "mAP_50_95":  float(results.box.map)   if hasattr(results, "box") else None,
        "precision":  float(results.box.mp)    if hasattr(results, "box") else None,
        "recall":     float(results.box.mr)    if hasattr(results, "box") else None,
        "params_M":   n_params / 1e6,
        "train_time": elapsed,
    }
    return metrics


def write_table(all_metrics: list[dict]) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    md = TABLE_DIR / "ablation_table.md"
    csv_path = TABLE_DIR / "ablation_table.csv"

    with md.open("w", encoding="utf-8") as f:
        f.write("# 消融实验对比表\n\n")
        f.write("| Config | mAP@0.5 | mAP@0.5:0.95 | Precision | Recall | "
                "Params (M) | Train (h) |\n")
        f.write("|--------|---------|--------------|-----------|--------|"
                "------------|-----------|\n")
        for m in all_metrics:
            f.write(
                f"| {m['name']} | "
                f"{m.get('mAP_50', 0):.3f} | "
                f"{m.get('mAP_50_95', 0):.3f} | "
                f"{m.get('precision', 0):.3f} | "
                f"{m.get('recall', 0):.3f} | "
                f"{m.get('params_M', 0):.2f} | "
                f"{m.get('train_time', 0)/3600:.2f} |\n"
            )

    with csv_path.open("w", encoding="utf-8") as f:
        keys = ["name", "mAP_50", "mAP_50_95", "precision", "recall",
                "params_M", "train_time"]
        f.write(",".join(keys) + "\n")
        for m in all_metrics:
            f.write(",".join(str(m.get(k, "")) for k in keys) + "\n")

    print()
    print("=" * 60)
    print(" 消融实验完成")
    print("=" * 60)
    print(f" 表格: {md}")
    print(f" CSV : {csv_path}")


def main() -> None:
    args = parse_args()
    register()

    all_metrics = []
    for name, cfg, pretrained, _desc in ABLATION_CONFIGS:
        if name in args.skip:
            print(f"==> 跳过 {name}")
            continue
        try:
            m = train_one(name, cfg, pretrained, args)
            all_metrics.append(m)
            (RUNS_ROOT / f"{name}_metrics.json").write_text(
                json.dumps(m, indent=2)
            )
        except Exception as e:
            print(f"❌ {name} 失败: {e}")
            all_metrics.append({"name": name, "error": str(e)})

    write_table(all_metrics)


if __name__ == "__main__":
    main()
