"""
定性对比图:Baseline vs Ours 在同一批样本上的检测结果
======================================================

输出:paper/figures/fig_qualitative.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

RUNS_ROOT = PROJECT_ROOT / "runs"
FIG_DIR = PROJECT_ROOT / "paper" / "figures"
DATA_ROOT = PROJECT_ROOT / "data" / "processed" / "pvel_yolo"

BASELINE = RUNS_ROOT / "baseline" / "yolo11n" / "weights" / "best.pt"
OURS = RUNS_ROOT / "ours" / "yolo11n_full" / "weights" / "best.pt"


def predict_and_render(weights: Path, img_path: Path) -> np.ndarray:
    from ultralytics import YOLO
    model = YOLO(str(weights))
    res = model.predict(source=str(img_path), verbose=False, conf=0.25)
    annotated = res[0].plot()  # BGR
    return cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)


def main() -> None:
    register()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    val_dir = DATA_ROOT / "images" / "val"
    imgs = sorted([p for p in val_dir.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")])[:6]
    if not imgs:
        raise RuntimeError("val 集为空")

    fig, axes = plt.subplots(len(imgs), 2, figsize=(10, 3 * len(imgs)))

    for i, img_path in enumerate(imgs):
        if BASELINE.exists():
            axes[i, 0].imshow(predict_and_render(BASELINE, img_path))
        axes[i, 0].set_title("Baseline" if i == 0 else "")
        axes[i, 0].axis("off")

        if OURS.exists():
            axes[i, 1].imshow(predict_and_render(OURS, img_path))
        axes[i, 1].set_title("Ours (Full)" if i == 0 else "")
        axes[i, 1].axis("off")

    fig.tight_layout()
    out = FIG_DIR / "fig_qualitative.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"✅ 定性对比图写入 {out}")


if __name__ == "__main__":
    main()
