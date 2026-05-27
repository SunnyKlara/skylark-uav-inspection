"""
train_v2.py
===========

v2 协议下的统一训练脚本，覆盖 E1（baseline）/ E2（主消融）/ E3（CBAM 位置）/ E4（预算扫描）。

v2 协议（与所有配置同等施加，确保公平）：
  - epochs    = 200（默认；E4 可改）
  - cos_lr    = True
  - lrf       = 0.01
  - close_mosaic = 20
  - patience  = 50
  - batch     = 8
  - workers   = 2
  - imgsz     = 640
  - optimizer = SGD（默认）
  - lr0       = 0.01
  - momentum  = 0.937
  - weight_decay = 5e-4
  - seed      = 42
  - AMP       = True
  - 都用对应预训练权重（v8n.pt / v10n.pt / yolo11n.pt）

输出位置：runs/v2/<group>/<name>/
  - group ∈ {baseline, ablation, cbam_pos, budget}
  - name 取配置名

用法:
  # E1 baseline 横评
  python train/train_v2.py --group baseline --name yolov8n
  python train/train_v2.py --group baseline --name yolov10n
  python train/train_v2.py --group baseline --name yolo11n

  # E2 主消融
  python train/train_v2.py --group ablation --name yolo11n           # A0
  python train/train_v2.py --group ablation --name yolo11n_cbam      # A1
  python train/train_v2.py --group ablation --name yolo11n_ema       # A2
  python train/train_v2.py --group ablation --name yolo11n_p2        # A3
  python train/train_v2.py --group ablation --name yolo11n_full      # A4

  # E3 CBAM 位置消融
  python train/train_v2.py --group cbam_pos --name yolo11n_cbam_p3only
  python train/train_v2.py --group cbam_pos --name yolo11n_cbam_p3p4
  python train/train_v2.py --group cbam_pos --name yolo11n_cbam_p5only

  # E4 预算扫描（同 ours，不同 epoch）
  python train/train_v2.py --group budget --name yolo11n_full --epochs 100 --tag _ep100
  python train/train_v2.py --group budget --name yolo11n_full --epochs 300 --tag _ep300
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
RUNS_ROOT = PROJECT_ROOT / "runs" / "v2"


# 配置注册表：name -> (yaml_path or None, pretrained_pt)
# yaml_path = None 表示直接用预训练权重（baseline，纯 ultralytics）
REGISTRY: dict[str, tuple[str | None, str]] = {
    # E1 baseline 横评
    "yolov8n":               (None,                                   "yolov8n.pt"),
    "yolov10n":              (None,                                   "yolov10n.pt"),
    "yolo11n":               (None,                                   "yolo11n.pt"),
    # E2 主消融（除 yolo11n 外都改了结构）
    "yolo11n_cbam":          ("configs/yolo11n_cbam.yaml",            "yolo11n.pt"),
    "yolo11n_ema":           ("configs/yolo11n_ema.yaml",             "yolo11n.pt"),
    "yolo11n_p2":            ("configs/yolo11n_p2.yaml",              "yolo11n.pt"),
    "yolo11n_full":          ("configs/yolo11n_full.yaml",            "yolo11n.pt"),
    # E3 CBAM 位置消融
    "yolo11n_cbam_p3only":   ("configs/yolo11n_cbam_p3only.yaml",     "yolo11n.pt"),
    "yolo11n_cbam_p3p4":     ("configs/yolo11n_cbam_p3p4.yaml",       "yolo11n.pt"),
    "yolo11n_cbam_p5only":   ("configs/yolo11n_cbam_p5only.yaml",     "yolo11n.pt"),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--group", required=True,
                   choices=["baseline", "ablation", "cbam_pos", "budget"])
    p.add_argument("--name", required=True, choices=list(REGISTRY.keys()))
    p.add_argument("--tag", default="",
                   help="run 名后缀（如 _ep100），用于区分同一 name 不同 epoch 的实验")
    p.add_argument("--epochs", type=int, default=200)
    p.add_argument("--patience", type=int, default=50)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--device", type=str, default="0")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--resume", action="store_true",
                   help="如果 last.pt 存在则续训")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    register()

    if not DATA_YAML.exists():
        raise FileNotFoundError(f"找不到 {DATA_YAML}")

    cfg, pretrained = REGISTRY[args.name]
    cfg_path = None
    if cfg:
        cfg_path = str((PROJECT_ROOT / cfg).resolve())
        if not Path(cfg_path).exists():
            raise FileNotFoundError(f"找不到模型 yaml: {cfg_path}")

    pretrained_path = (PROJECT_ROOT / pretrained).resolve()
    if not pretrained_path.exists():
        raise FileNotFoundError(f"找不到预训练权重: {pretrained_path}")

    run_name = args.name + args.tag
    out_dir = RUNS_ROOT / args.group / run_name

    print("=" * 60)
    print(f"  v2 训练: {args.group} / {run_name}")
    print(f"  cfg:        {cfg_path or '(use pretrained directly)'}")
    print(f"  pretrained: {pretrained_path}")
    print(f"  epochs:     {args.epochs}")
    print(f"  out_dir:    {out_dir}")
    print(f"  patience:   {args.patience}")
    print(f"  cos_lr:     True")
    print(f"  close_mosaic: 20")
    print(f"  seed:       {args.seed}")
    print("=" * 60)

    from ultralytics import YOLO

    # 续训处理
    last_pt = out_dir / "weights" / "last.pt"
    if args.resume and last_pt.exists():
        print(f"  [resume] from {last_pt}")
        model = YOLO(str(last_pt))
        train_kwargs = {"resume": True}
    elif cfg_path:
        # cfg 决定结构 + load 预训练（非匹配层会被忽略）
        model = YOLO(cfg_path).load(str(pretrained_path))
        train_kwargs = {}
    else:
        # 纯预训练（标准结构）
        model = YOLO(str(pretrained_path))
        train_kwargs = {}

    t0 = time.time()
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        device=args.device,
        project=str(out_dir.parent),
        name=run_name,
        exist_ok=True,
        verbose=True,
        plots=True,
        # ---- v2 协议 ----
        cos_lr=True,
        lr0=0.01,
        lrf=0.01,
        momentum=0.937,
        weight_decay=5e-4,
        warmup_epochs=3.0,
        close_mosaic=20,
        patience=args.patience,
        seed=args.seed,
        amp=True,
        **train_kwargs,
    )
    elapsed = time.time() - t0

    n_params = sum(p.numel() for p in model.model.parameters())
    metrics = {
        "name":      run_name,
        "group":     args.group,
        "cfg":       cfg or "",
        "pretrained": pretrained,
        "epochs":    args.epochs,
        "actual_epochs": getattr(results, "results_dict", {}).get("fitness_epoch", args.epochs)
                         if hasattr(results, "results_dict") else args.epochs,
        "mAP_50":    float(results.box.map50) if hasattr(results, "box") else None,
        "mAP_50_95": float(results.box.map)   if hasattr(results, "box") else None,
        "precision": float(results.box.mp)    if hasattr(results, "box") else None,
        "recall":    float(results.box.mr)    if hasattr(results, "box") else None,
        "params_M":  n_params / 1e6,
        "train_time_s": elapsed,
        "protocol":  "v2_cos_lr",
    }
    metrics_file = out_dir.parent / f"{run_name}_metrics.json"
    metrics_file.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print()
    print("=" * 60)
    print(f"  完成: {run_name}")
    print(f"  mAP@0.5     = {metrics['mAP_50']:.4f}" if metrics.get('mAP_50') else "")
    print(f"  mAP@0.5:.95 = {metrics['mAP_50_95']:.4f}" if metrics.get('mAP_50_95') else "")
    print(f"  耗时: {elapsed/3600:.2f} h")
    print(f"  metrics -> {metrics_file}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
