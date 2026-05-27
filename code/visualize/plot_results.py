"""
画训练曲线 - 论文 5.2 节用
============================
读取 runs/baseline/* 和 runs/ours/* 下的 results.csv,
画多个模型的 mAP@0.5 / loss 训练曲线对比图。

输出:paper/figures/fig_training_curves.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RUNS_ROOT = PROJECT_ROOT / "runs"
FIG_DIR = PROJECT_ROOT / "paper" / "figures"

CANDIDATES = [
    ("YOLOv8n",     RUNS_ROOT / "baseline" / "yolov8n"),
    ("YOLOv10n",    RUNS_ROOT / "baseline" / "yolov10n"),
    ("YOLOv11n",    RUNS_ROOT / "baseline" / "yolo11n"),
    ("Ours (Full)", RUNS_ROOT / "ours" / "yolo11n_full"),
]


def find_results_csv(run_dir: Path) -> Path | None:
    if not run_dir.exists():
        return None
    csv = run_dir / "results.csv"
    if csv.exists():
        return csv
    # ultralytics 有时会把 csv 放到子目录
    for sub in run_dir.glob("**/results.csv"):
        return sub
    return None


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    for name, run_dir in CANDIDATES:
        csv = find_results_csv(run_dir)
        if not csv:
            print(f"⚠️  跳过 {name},找不到 results.csv")
            continue
        df = pd.read_csv(csv)
        df.columns = [c.strip() for c in df.columns]

        # 取 mAP@0.5
        map_col = next((c for c in df.columns
                        if "metrics/mAP50(B)" == c
                        or c.endswith("mAP50") or c.endswith("mAP_0.5")),
                       None)
        loss_col = next((c for c in df.columns
                         if "train/box_loss" in c or "train/loss" in c),
                        None)

        epochs = df["epoch"] if "epoch" in df.columns else range(len(df))

        if map_col:
            ax1.plot(epochs, df[map_col], label=name)
        if loss_col:
            ax2.plot(epochs, df[loss_col], label=name)

    ax1.set_title("mAP@0.5 vs Epoch")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("mAP@0.5")
    ax1.grid(alpha=0.3)
    ax1.legend()

    ax2.set_title("Box Loss vs Epoch")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Loss")
    ax2.grid(alpha=0.3)
    ax2.legend()

    fig.tight_layout()
    out = FIG_DIR / "fig_training_curves.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"✅ 训练曲线写入 {out}")


if __name__ == "__main__":
    main()
