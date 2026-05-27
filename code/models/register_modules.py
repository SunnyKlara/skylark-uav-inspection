"""
把自定义模块注入 ultralytics
================================

ultralytics 的 yaml 解析(parse_model)对自带模块会按 width_multiple 自动缩放通道。
我们的 CBAM / EMA / BiFPNAdd 不在 base_modules 集合里,所以 yaml 里写的通道数会被字面使用。

为了让自定义模块也享受 width 缩放(yaml 里写 base 通道,nano/s/m 自适应),
我们 monkey-patch parse_model:在它处理 yaml 之前,预先把自定义模块的
args[0] 按当前 scale 的 width 缩放并对齐到 8 的倍数。

用法:在所有训练 / 推理脚本入口最早处:
    from models.register_modules import register
    register()
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# 标记是否已 patch,避免重复 wrap
_PATCHED = False


def _make_divisible(x: float, divisor: int = 8) -> int:
    """Round x up to nearest multiple of divisor (matches ultralytics)."""
    return int(((x + divisor / 2) // divisor) * divisor)


def register() -> None:
    """把自定义 nn.Module 注册到 ultralytics 命名空间, 并 patch parse_model."""
    global _PATCHED

    try:
        ul_modules = importlib.import_module("ultralytics.nn.modules")
        tasks_mod = importlib.import_module("ultralytics.nn.tasks")
    except ImportError as e:
        raise RuntimeError("先 pip install ultralytics") from e

    from models.modules import CBAM, EMA, BiFPNAdd

    custom_classes = {"CBAM": CBAM, "EMA": EMA, "BiFPNAdd": BiFPNAdd}

    # ---- 1. 注入到命名空间 ----
    for name, cls in custom_classes.items():
        setattr(ul_modules, name, cls)
        setattr(tasks_mod, name, cls)

    # __all__ 可能是 tuple,需先转成 list
    if hasattr(ul_modules, "__all__"):
        try:
            existing = list(ul_modules.__all__)
            for name in custom_classes:
                if name not in existing:
                    existing.append(name)
            ul_modules.__all__ = existing
        except (TypeError, AttributeError):
            pass

    # ---- 2. monkey-patch parse_model: 让 CBAM/EMA/BiFPNAdd 也按 width 缩放 ----
    if not _PATCHED:
        original_parse_model = tasks_mod.parse_model

        def patched_parse_model(d, ch, verbose=True):
            import copy
            # 深拷贝 d,避免就地修改污染原始 yaml dict (会被多次解析)
            d = copy.deepcopy(d)

            # 解析当前 scale 的 width 和 max_channels
            scales = d.get("scales") or {}
            scale = d.get("scale") or (next(iter(scales.keys())) if scales else None)
            if scale and scale in scales:
                _, width, max_channels = scales[scale]
            else:
                width = float(d.get("width_multiple", 1.0))
                max_channels = float("inf")

            # 对 yaml 里的自定义模块 args[0] 做和 ultralytics 一样的缩放
            for section in ("backbone", "head"):
                for entry in d.get(section, []):
                    if len(entry) < 4:
                        continue
                    m = entry[2]
                    args = entry[3]
                    if isinstance(m, str) and m in custom_classes:
                        if args and isinstance(args[0], (int, float)):
                            scaled = _make_divisible(
                                min(args[0], max_channels) * width
                            )
                            args[0] = scaled

            return original_parse_model(d, ch, verbose)

        tasks_mod.parse_model = patched_parse_model
        _PATCHED = True

    print("[register_modules] CBAM / EMA / BiFPNAdd 已注册并加入 width 缩放")
