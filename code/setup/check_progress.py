"""
实验进度检查
================
扫描 runs/ 和 paper/ 目录,告诉用户哪些步骤完成了。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS = PROJECT_ROOT / "runs"
PAPER = PROJECT_ROOT / "paper"
DATA = PROJECT_ROOT / "data" / "processed" / "pvel_yolo"


def check(condition: bool, ok_msg: str, fail_msg: str) -> None:
    marker = "[OK]" if condition else "[  ]"
    print(f"  {marker}  {ok_msg if condition else fail_msg}")


def main() -> None:
    print()
    print("=" * 60)
    print("  数据集准备")
    print("=" * 60)
    check((DATA / "data.yaml").exists(),
          f"data.yaml 已生成 -> {DATA / 'data.yaml'}",
          "数据集未准备 - 跑 prepare_pvel_ad.py")
    check((DATA / "images" / "train").exists(),
          "train 集存在",
          "train 集缺失")
    check((DATA / "images" / "val").exists(),
          "val 集存在",
          "val 集缺失")

    print()
    print("=" * 60)
    print("  Baseline 训练")
    print("=" * 60)
    for name in ["yolov8n", "yolov10n", "yolo11n", "rtdetr"]:
        weights = RUNS / "baseline" / name / "weights" / "best.pt"
        check(weights.exists(),
              f"{name} 已训完 -> {weights.name}",
              f"{name} 还没训")

    print()
    print("=" * 60)
    print("  Ours 训练")
    print("=" * 60)
    ours = RUNS / "ours" / "yolo11n_full" / "weights" / "best.pt"
    check(ours.exists(),
          "ours (yolo11n_full) 已训完",
          "ours 还没训 - 跑 train/train_ours.py")

    print()
    print("=" * 60)
    print("  消融实验")
    print("=" * 60)
    for name in ["yolo11n", "yolo11n_cbam", "yolo11n_ema",
                 "yolo11n_p2", "yolo11n_full"]:
        weights = RUNS / "ablation" / name / "weights" / "best.pt"
        check(weights.exists(),
              f"{name} 消融已完",
              f"{name} 消融未完")

    print()
    print("=" * 60)
    print("  评估表格")
    print("=" * 60)
    for fname in ["baseline_table.md", "main_comparison.md",
                  "ablation_table.md", "complexity_table.md",
                  "robustness_table.md", "deployment_table.md",
                  "dataset_stats.md"]:
        f = PAPER / "tables" / fname
        check(f.exists(),
              f"{fname} 已生成",
              f"{fname} 未生成")

    print()
    print("=" * 60)
    print("  论文图片")
    print("=" * 60)
    for fname in ["fig_dataset_dist.png", "fig_box_size.png",
                  "fig_training_curves.png", "fig_grad_cam.png",
                  "fig_qualitative.png", "fig_robustness.png"]:
        f = PAPER / "figures" / fname
        check(f.exists(),
              f"{fname} 已生成",
              f"{fname} 未生成")

    print()


if __name__ == "__main__":
    main()
