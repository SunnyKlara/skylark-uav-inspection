"""
鲁棒性实验:在 val 集上施加 6 种扰动,看 mAP 跌多少
====================================================

扰动类型:
  - brightness_dim       亮度暗化
  - brightness_bright    亮度亮化
  - gaussian_noise       高斯噪声
  - motion_blur          运动模糊
  - jpeg_compression     压缩伪影
  - rotation             旋转扰动

输出:
  - paper/tables/robustness_table.md
  - paper/figures/fig_robustness.png  曲线图
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import yaml
import matplotlib.pyplot as plt
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

DATA_YAML = PROJECT_ROOT / "data" / "processed" / "pvel_yolo" / "data.yaml"
RUNS_ROOT = PROJECT_ROOT / "runs"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"
FIG_DIR = PROJECT_ROOT / "paper" / "figures"

CANDIDATES = [
    ("YOLOv11n",    RUNS_ROOT / "baseline" / "yolo11n"),
    ("Ours (Full)", RUNS_ROOT / "ours" / "yolo11n_full"),
]

PERTURBATIONS = [
    "brightness_dim",
    "brightness_bright",
    "gaussian_noise",
    "motion_blur",
    "jpeg_compression",
    "rotation",
]


def perturb(img: np.ndarray, kind: str, strength: float) -> np.ndarray:
    """根据扰动类型 + 强度返回扰动图."""
    if kind == "brightness_dim":
        return np.clip(img.astype(np.float32) * (1 - 0.6 * strength), 0, 255).astype(np.uint8)
    if kind == "brightness_bright":
        return np.clip(img.astype(np.float32) * (1 + 0.6 * strength), 0, 255).astype(np.uint8)
    if kind == "gaussian_noise":
        sigma = 25 * strength
        noise = np.random.normal(0, sigma, img.shape)
        return np.clip(img + noise, 0, 255).astype(np.uint8)
    if kind == "motion_blur":
        ksize = max(3, int(15 * strength) | 1)
        kernel = np.zeros((ksize, ksize))
        kernel[ksize // 2, :] = 1.0 / ksize
        return cv2.filter2D(img, -1, kernel)
    if kind == "jpeg_compression":
        quality = max(10, int(95 - 80 * strength))
        _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return cv2.imdecode(enc, cv2.IMREAD_COLOR)
    if kind == "rotation":
        angle = 15 * strength
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(img, M, (w, h))
    return img


def build_perturbed_dataset(kind: str, strength: float) -> Path:
    """生成一个临时数据集目录,只替换 val 图片."""
    src_root = DATA_YAML.parent
    tmp = Path(tempfile.mkdtemp(prefix=f"robust_{kind}_"))

    # 软链 train / test,只改 val 图片
    (tmp / "images").mkdir(parents=True)
    (tmp / "labels").mkdir(parents=True)
    for sub in ["train", "test"]:
        if (src_root / "images" / sub).exists():
            shutil.copytree(src_root / "images" / sub, tmp / "images" / sub,
                            symlinks=True)
        if (src_root / "labels" / sub).exists():
            shutil.copytree(src_root / "labels" / sub, tmp / "labels" / sub,
                            symlinks=True)
    # val labels 直接拷
    if (src_root / "labels" / "val").exists():
        shutil.copytree(src_root / "labels" / "val", tmp / "labels" / "val")

    # val images 重新生成扰动
    src_val_img = src_root / "images" / "val"
    dst_val_img = tmp / "images" / "val"
    dst_val_img.mkdir(parents=True, exist_ok=True)
    for img_path in src_val_img.glob("*"):
        if not img_path.is_file():
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        out = perturb(img, kind, strength)
        cv2.imwrite(str(dst_val_img / img_path.name), out)

    # 写一个新 data.yaml
    cfg = yaml.safe_load(DATA_YAML.read_text())
    cfg["path"] = str(tmp.resolve())
    new_yaml = tmp / "data.yaml"
    new_yaml.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return new_yaml


def evaluate(weights: Path, data_yaml: Path) -> float:
    from ultralytics import YOLO
    model = YOLO(str(weights))
    res = model.val(data=str(data_yaml), verbose=False)
    return float(res.box.map50)


def run_one_model(name: str, run_dir: Path,
                  strengths: list[float]) -> dict:
    weights = run_dir / "weights" / "best.pt"
    if not weights.exists():
        return {"name": name, "error": f"找不到 {weights}"}

    print(f"==> 评估 {name}")
    out = {"name": name}

    # 干净 baseline
    res = evaluate(weights, DATA_YAML)
    out["clean"] = res
    print(f"   clean mAP50 = {res:.3f}")

    for kind in PERTURBATIONS:
        out[kind] = []
        for s in strengths:
            data_yaml = build_perturbed_dataset(kind, s)
            try:
                m = evaluate(weights, data_yaml)
            finally:
                shutil.rmtree(data_yaml.parent, ignore_errors=True)
            out[kind].append(m)
            print(f"   {kind} s={s:.1f} -> mAP50 = {m:.3f}")
    return out


def write_outputs(all_results: list[dict],
                  strengths: list[float]) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    md = TABLE_DIR / "robustness_table.md"
    with md.open("w", encoding="utf-8") as f:
        f.write("# 鲁棒性实验:mAP@0.5 在 6 种扰动下的退化\n\n")
        for s in strengths:
            f.write(f"## strength = {s:.1f}\n\n")
            f.write("| Model | clean | "
                    + " | ".join(PERTURBATIONS)
                    + " |\n")
            f.write("|" + "-------|" * (2 + len(PERTURBATIONS)) + "\n")
            for r in all_results:
                if "error" in r:
                    continue
                row = f"| {r['name']} | {r['clean']:.3f} |"
                idx = strengths.index(s)
                for k in PERTURBATIONS:
                    row += f" {r[k][idx]:.3f} |"
                f.write(row + "\n")
            f.write("\n")
    print(f"✅ 鲁棒性表写入 {md}")

    # 出曲线图(每个 perturbation 一个 subplot)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    axes = axes.flatten()
    for i, kind in enumerate(PERTURBATIONS):
        ax = axes[i]
        for r in all_results:
            if "error" in r:
                continue
            ax.plot(strengths, r[kind], marker="o", label=r["name"])
        ax.set_title(kind)
        ax.set_xlabel("Perturbation strength")
        ax.set_ylabel("mAP@0.5")
        ax.legend()
        ax.grid(alpha=0.3)
    fig.tight_layout()
    out_fig = FIG_DIR / "fig_robustness.png"
    fig.savefig(out_fig, dpi=300)
    plt.close(fig)
    print(f"✅ 鲁棒性图写入 {out_fig}")


def main() -> None:
    register()
    if not DATA_YAML.exists():
        raise FileNotFoundError(f"找不到 {DATA_YAML}")

    strengths = [0.3, 0.6, 0.9]
    all_results = []
    for name, run_dir in CANDIDATES:
        all_results.append(run_one_model(name, run_dir, strengths))

    write_outputs(all_results, strengths)


if __name__ == "__main__":
    main()
