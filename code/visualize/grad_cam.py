"""
Grad-CAM 可视化 - 论文必备图
=============================
对最终模型在若干测试样本上做注意力可视化,
证明你的 CBAM 注意力模块"看对了地方"。

输出:paper/figures/fig_grad_cam.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

RUNS_ROOT = PROJECT_ROOT / "runs"
FIG_DIR = PROJECT_ROOT / "paper" / "figures"
DATA_ROOT = PROJECT_ROOT / "data" / "processed" / "pvel_yolo"

OURS_WEIGHTS = RUNS_ROOT / "ours" / "yolo11n_full" / "weights" / "best.pt"
BASELINE_WEIGHTS = RUNS_ROOT / "baseline" / "yolo11n" / "weights" / "best.pt"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def get_target_layer(model: torch.nn.Module) -> torch.nn.Module:
    """选 backbone 最深的 conv 层做 Grad-CAM."""
    target = None
    for m in model.modules():
        if isinstance(m, torch.nn.Conv2d):
            target = m
    if target is None:
        raise RuntimeError("找不到 Conv2d 层")
    return target


def cam_for_image(weights_path: Path, img_path: Path,
                  imgsz: int = 640) -> np.ndarray:
    from ultralytics import YOLO
    from pytorch_grad_cam import EigenCAM
    from pytorch_grad_cam.utils.image import show_cam_on_image

    yolo = YOLO(str(weights_path))
    model = yolo.model.to(DEVICE).eval()

    img_bgr = cv2.imread(str(img_path))
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    img_resized = cv2.resize(img_rgb, (imgsz, imgsz))
    img_norm = img_resized.astype(np.float32) / 255.0

    tensor = torch.from_numpy(img_norm).permute(2, 0, 1).unsqueeze(0).to(DEVICE)

    target_layer = get_target_layer(model)
    cam = EigenCAM(model=model, target_layers=[target_layer])
    grayscale_cam = cam(input_tensor=tensor)[0]

    visualization = show_cam_on_image(img_norm, grayscale_cam, use_rgb=True)
    return visualization


def main() -> None:
    register()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # 选 4 张代表性图(优先 val 里第一批)
    val_dir = DATA_ROOT / "images" / "val"
    if not val_dir.exists():
        raise FileNotFoundError(f"找不到 {val_dir}")
    imgs = sorted([p for p in val_dir.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")])[:4]
    if not imgs:
        raise RuntimeError("val 集为空")

    fig, axes = plt.subplots(len(imgs), 3, figsize=(12, 3 * len(imgs)))
    if len(imgs) == 1:
        axes = axes[np.newaxis, :]

    for i, img_path in enumerate(imgs):
        orig = cv2.cvtColor(cv2.imread(str(img_path)), cv2.COLOR_BGR2RGB)
        orig_resized = cv2.resize(orig, (640, 640))
        axes[i, 0].imshow(orig_resized)
        axes[i, 0].set_title("Input" if i == 0 else "")
        axes[i, 0].axis("off")

        if BASELINE_WEIGHTS.exists():
            try:
                cam_b = cam_for_image(BASELINE_WEIGHTS, img_path)
                axes[i, 1].imshow(cam_b)
            except Exception as e:
                axes[i, 1].text(0.5, 0.5, f"baseline failed:\n{e}",
                                ha="center", va="center")
            axes[i, 1].set_title("Baseline (YOLOv11n)" if i == 0 else "")
            axes[i, 1].axis("off")
        else:
            axes[i, 1].axis("off")

        if OURS_WEIGHTS.exists():
            try:
                cam_o = cam_for_image(OURS_WEIGHTS, img_path)
                axes[i, 2].imshow(cam_o)
            except Exception as e:
                axes[i, 2].text(0.5, 0.5, f"ours failed:\n{e}",
                                ha="center", va="center")
            axes[i, 2].set_title("Ours (Full)" if i == 0 else "")
            axes[i, 2].axis("off")
        else:
            axes[i, 2].axis("off")

    fig.tight_layout()
    out = FIG_DIR / "fig_grad_cam.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"✅ Grad-CAM 写入 {out}")


if __name__ == "__main__":
    main()
