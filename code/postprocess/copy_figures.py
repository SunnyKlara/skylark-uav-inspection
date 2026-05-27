"""
copy_figures.py
===============
把 ``code/paper/figures/*.png`` 拷贝到论文目录：
  - paper/tex/figures/      (LaTeX 引用)
  - paper/figures/          (中文 markdown 引用)

不存在的图就跳过；占位 PNG 不覆盖（除非 --force）。

用法:
  python postprocess/copy_figures.py
  python postprocess/copy_figures.py --force      # 覆盖所有
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "paper" / "figures"
DST_TEX = PROJECT_ROOT.parent / "paper" / "tex" / "figures"
DST_MD = PROJECT_ROOT.parent / "paper" / "figures"


def copy_dir(src: Path, dst: Path, force: bool) -> tuple[int, int]:
    """返回 (拷贝数, 跳过数)"""
    if not src.exists():
        print(f"[warn] 源目录不存在: {src}")
        return 0, 0
    dst.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for src_file in src.iterdir():
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
            continue
        dst_file = dst / src_file.name
        if dst_file.exists() and not force:
            # 比较大小判断是否需要覆盖；占位图通常 <30KB
            src_size = src_file.stat().st_size
            dst_size = dst_file.stat().st_size
            if dst_size < 30_000 < src_size:
                shutil.copy2(src_file, dst_file)
                copied += 1
                print(f"  [overwrite small placeholder] {src_file.name}  "
                      f"{dst_size} -> {src_size} bytes")
                continue
            if src_size == dst_size:
                skipped += 1
                continue
            shutil.copy2(src_file, dst_file)
            copied += 1
            print(f"  [update] {src_file.name}  {dst_size} -> {src_size} bytes")
        else:
            shutil.copy2(src_file, dst_file)
            copied += 1
            print(f"  [copy]   {src_file.name}  ({src_file.stat().st_size} bytes)")
    return copied, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="无条件覆盖目标")
    args = ap.parse_args()

    print(f"[1/2] -> {DST_TEX}")
    c1, s1 = copy_dir(SRC, DST_TEX, args.force)
    print(f"     拷贝 {c1}，跳过 {s1}")

    print(f"[2/2] -> {DST_MD}")
    c2, s2 = copy_dir(SRC, DST_MD, args.force)
    print(f"     拷贝 {c2}，跳过 {s2}")

    print(f"\n[OK] 共拷贝 {c1 + c2} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
