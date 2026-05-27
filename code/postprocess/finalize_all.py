"""
finalize_all.py
===============
daemon 跑完后的一键化收尾。

按顺序：
  1. collect_metrics.py    汇总实验数字
  2. fill_paper.py         回填 LaTeX/Markdown
  3. copy_figures.py       搬图
  4. build_pdfs.py         重编中英 PDF
  5. prepare_defense.py    生成答辩材料

每一步独立 try/except，某步失败不阻塞后续。
最终在 runs/finalize_status.md 出一份摘要报告。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYEXE = sys.executable
RUNS_ROOT = PROJECT_ROOT / "runs"
STATUS_FILE = RUNS_ROOT / "finalize_status.md"


STEPS = [
    ("collect",  "collect_metrics.py",   []),
    ("fill",     "fill_paper.py",        []),
    ("figures",  "copy_figures.py",      []),
    ("pdfs",     "build_pdfs.py",        []),
    ("defense",  "prepare_defense.py",   []),
]


def run(step_id: str, script: str, args: list[str]) -> tuple[int, str]:
    cmd = [PYEXE, f"postprocess/{script}"] + args
    print(f"\n{'=' * 60}")
    print(f"  STEP [{step_id}] {script}")
    print(f"{'=' * 60}")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout or ""
    # 防止 Windows GBK 终端炸 -- 强制 ASCII-safe 打印
    try:
        sys.stdout.write(out)
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        sys.stdout.flush()
    return proc.returncode, out


def main() -> int:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    started = datetime.now()

    results: list[tuple[str, str, int]] = []
    for sid, script, args in STEPS:
        rc, _ = run(sid, script, args)
        results.append((sid, script, rc))

    # 写状态文件
    lines = [
        "# Finalize 状态报告",
        f"- 开始: {started.isoformat(timespec='seconds')}",
        f"- 结束: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 每一步状态",
    ]
    for sid, script, rc in results:
        mark = "✓" if rc == 0 else "✗"
        lines.append(f"- {mark} `{script}`  (exit={rc})")

    failed = [r for r in results if r[2] != 0]
    if failed:
        lines.append("")
        lines.append("## ⚠️ 失败步骤")
        for sid, script, rc in failed:
            lines.append(f"- {script}  exit={rc}")

    lines.append("")
    lines.append("## 产出文件")
    for p in [
        "runs/collected_metrics.json",
        "runs/fill_report.md",
        "paper/tex/main.pdf",
        "paper/tex/main_zh.pdf",
        "paper/defense/答辩PPT大纲.md",
        "paper/defense/常见问题与回答.md",
    ]:
        full = PROJECT_ROOT.parent / p if p.startswith("paper/") else PROJECT_ROOT / p
        if full.exists():
            kb = full.stat().st_size // 1024
            lines.append(f"- ✓ {p}  ({kb} KB)")
        else:
            lines.append(f"- ✗ {p}  缺失")

    STATUS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[OK] 状态报告 -> {STATUS_FILE}")

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
