"""
build_pdfs.py
=============
重编中英 PDF：
  - main.tex        : pdflatex + bibtex + pdflatex x2
  - main_zh.tex     : xelatex + bibtex + xelatex x2

依赖 TeX Live 2024：``E:\\Program Files\\texlive\\2024\\bin\\windows\\``

用法:
  python postprocess/build_pdfs.py
  python postprocess/build_pdfs.py --only en
  python postprocess/build_pdfs.py --only zh
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEX_DIR = PROJECT_ROOT.parent / "paper" / "tex"

TEXLIVE_BIN = Path(r"E:\Program Files\texlive\2024\bin\windows")
PDFLATEX = TEXLIVE_BIN / "pdflatex.exe"
XELATEX = TEXLIVE_BIN / "xelatex.exe"
BIBTEX = TEXLIVE_BIN / "bibtex.exe"


def find_tool(name: str, fallback: Path) -> str:
    """优先用 PATH 中的，否则用绝对路径"""
    p = shutil.which(name)
    if p:
        return p
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError(f"找不到 {name}（既不在 PATH，也不在 {fallback}）")


def run(cmd: list[str], cwd: Path, log_prefix: str) -> int:
    print(f"[run] {log_prefix}: {' '.join(Path(c).name if Path(c).exists() else c for c in cmd)}")
    env = os.environ.copy()
    # 让 kpathsea 找到 IEEEtran.cls 等 — 把 TeX Live bin 加到 PATH
    if TEXLIVE_BIN.exists():
        env["PATH"] = str(TEXLIVE_BIN) + os.pathsep + env.get("PATH", "")
    # 注意：不要设 TEXINPUTS=.,会屏蔽 TeX Live 的 system tree
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # 只把最后 30 行打出来，避免淹没
    lines = (proc.stdout or "").splitlines()
    if proc.returncode != 0:
        print("---- 末尾输出 ----")
        for ln in lines[-40:]:
            print(ln)
    else:
        # 抓 ! 错误 / Warning（出汇总）
        flag_lines = [ln for ln in lines
                      if ln.startswith("!") or "Error" in ln or "Warning" in ln]
        if flag_lines:
            print(f"  ({len(flag_lines)} warning/error lines, 前 5)")
            for ln in flag_lines[:5]:
                print("  ", ln)
    return proc.returncode


def build_en(stop_on_err: bool) -> bool:
    pdflatex = find_tool("pdflatex", PDFLATEX)
    bibtex = find_tool("bibtex", BIBTEX)

    print(f"\n=== 构建英文 main.pdf ===")
    cwd = TEX_DIR
    pdf = cwd / "main.pdf"
    # 删旧 PDF，避免假阳性 OK
    if pdf.exists():
        pdf.unlink()

    base_args = [pdflatex, "-interaction=nonstopmode",
                 "-halt-on-error", "main.tex"]

    rc = run(base_args, cwd, "pdflatex 1/3")
    if rc != 0 and stop_on_err:
        return False

    rc = run([bibtex, "main"], cwd, "bibtex")
    # bibtex 警告很常见，不当失败
    if rc != 0:
        print("  [bibtex] 退出码非 0，但通常可继续")

    run(base_args, cwd, "pdflatex 2/3")
    run(base_args, cwd, "pdflatex 3/3")

    if pdf.exists():
        print(f"[OK] {pdf} ({pdf.stat().st_size // 1024} KB)")
        return True
    print(f"[FAIL] 没生成 {pdf}")
    return False


def build_zh(stop_on_err: bool) -> bool:
    xelatex = find_tool("xelatex", XELATEX)
    bibtex = find_tool("bibtex", BIBTEX)

    print(f"\n=== 构建中文 main_zh.pdf ===")
    cwd = TEX_DIR
    pdf = cwd / "main_zh.pdf"
    if pdf.exists():
        pdf.unlink()

    base_args = [xelatex, "-interaction=nonstopmode",
                 "-halt-on-error", "main_zh.tex"]

    rc = run(base_args, cwd, "xelatex 1/3")
    if rc != 0 and stop_on_err:
        return False

    rc = run([bibtex, "main_zh"], cwd, "bibtex")
    if rc != 0:
        print("  [bibtex] 退出码非 0，但通常可继续")

    run(base_args, cwd, "xelatex 2/3")
    run(base_args, cwd, "xelatex 3/3")

    if pdf.exists():
        print(f"[OK] {pdf} ({pdf.stat().st_size // 1024} KB)")
        return True
    print(f"[FAIL] 没生成 {pdf}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["en", "zh"], default=None)
    ap.add_argument("--stop-on-err", action="store_true",
                    help="第一次 pdflatex 失败就退出（默认：继续往下跑）")
    args = ap.parse_args()

    if not TEX_DIR.exists():
        print(f"[err] 找不到 {TEX_DIR}", file=sys.stderr)
        return 1

    ok = True
    if args.only != "zh":
        ok = build_en(args.stop_on_err) and ok
    if args.only != "en":
        ok = build_zh(args.stop_on_err) and ok

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
