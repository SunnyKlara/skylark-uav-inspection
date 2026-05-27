"""
sanity_check_configs.py
========================

只 build model（不训练），验证：
  1. 所有 yaml 能被 ultralytics 解析
  2. 能加载 yolo11n.pt 预训练权重
  3. 报告每个配置的：参数量、FLOPs（粗略）、迁移率（matched / total state_dict）

不占 GPU 时间（CPU 上 build 即可）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.register_modules import register

CONFIGS = [
    ("yolo11n (baseline)", None,                                "yolo11n.pt"),
    ("yolo11n_cbam (P3+P4+P5)", "configs/yolo11n_cbam.yaml",    "yolo11n.pt"),
    ("yolo11n_cbam_p3only",     "configs/yolo11n_cbam_p3only.yaml", "yolo11n.pt"),
    ("yolo11n_cbam_p3p4",       "configs/yolo11n_cbam_p3p4.yaml",   "yolo11n.pt"),
    ("yolo11n_cbam_p5only",     "configs/yolo11n_cbam_p5only.yaml", "yolo11n.pt"),
    ("yolo11n_ema",             "configs/yolo11n_ema.yaml",         "yolo11n.pt"),
    ("yolo11n_p2",              "configs/yolo11n_p2.yaml",          "yolo11n.pt"),
    ("yolo11n_full (ours)",     "configs/yolo11n_full.yaml",        "yolo11n.pt"),
]


def count_state_dict_match(model, pretrained_pt: str) -> tuple[int, int, int]:
    """加载预训练权重，统计匹配率"""
    if not Path(pretrained_pt).exists():
        return -1, -1, -1
    ckpt = torch.load(pretrained_pt, map_location="cpu", weights_only=False)
    if "model" in ckpt:
        pre_state = ckpt["model"].state_dict() if hasattr(ckpt["model"], "state_dict") else ckpt["model"]
    else:
        pre_state = ckpt

    cur_state = model.state_dict()
    matched = sum(1 for k, v in pre_state.items()
                  if k in cur_state and cur_state[k].shape == v.shape)
    total_pre = len(pre_state)
    total_cur = len(cur_state)
    return matched, total_pre, total_cur


def check_one(label: str, cfg: str | None, pretrained: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  cfg: {cfg or '(use weights only)'}")
    print(f"{'=' * 60}")
    try:
        from ultralytics import YOLO
        if cfg:
            cfg_path = str((PROJECT_ROOT / cfg).resolve())
            model = YOLO(cfg_path).load(pretrained)
        else:
            model = YOLO(pretrained)

        n_params = sum(p.numel() for p in model.model.parameters())
        print(f"  参数量: {n_params/1e6:.3f} M")

        matched, total_pre, total_cur = count_state_dict_match(
            model.model, pretrained
        )
        if matched >= 0:
            pct = matched / max(total_cur, 1) * 100
            print(f"  权重匹配: {matched} / {total_cur} ({pct:.1f}%)  pre={total_pre}")
        print(f"  [OK]")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  [FAIL] {e}")


def main() -> int:
    register()
    for label, cfg, pre in CONFIGS:
        check_one(label, cfg, pre)
    return 0


if __name__ == "__main__":
    sys.exit(main())
