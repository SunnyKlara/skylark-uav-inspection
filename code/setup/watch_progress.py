"""
Live progress dashboard for the experiment pipeline.

Shows:
  - Pipeline stage status (done / failed / pending)
  - Current training run live: epoch / batch / loss / mAP
  - GPU utilization / memory / temperature
  - Generated paper artifacts

Usage:
  Double-click 进度.bat                   # one-shot
  python setup/watch_progress.py --watch  # auto-refresh every 10s
  python setup/watch_progress.py --tail   # just show pipeline log tail
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = PROJECT_ROOT / "runs"
PAPER_ROOT = PROJECT_ROOT / "paper"
STATUS_FILE = RUNS_ROOT / "pipeline_status.json"
LOG_FILE = RUNS_ROOT / "pipeline.log"

ALL_STAGES = [
    ("baseline_yolov8n",   "Baseline 1/4: YOLOv8n"),
    ("baseline_yolov10n",  "Baseline 2/4: YOLOv10n"),
    ("baseline_yolo11n",   "Baseline 3/4: YOLOv11n"),
    ("baseline_rtdetr",    "Baseline 4/4: RT-DETR-l"),
    ("ours",               "Ours: YOLOv11n + CBAM + P2"),
    ("ablation",           "Ablation: 5 configs"),
    ("dataset_stats",      "Dataset stats + figures"),
    ("eval_complexity",    "Eval: complexity"),
    ("eval_robustness",    "Eval: robustness"),
    ("eval_deployment",    "Eval: deployment"),
    ("viz_curves",         "Viz: training curves"),
    ("viz_gradcam",        "Viz: Grad-CAM"),
    ("viz_qualitative",    "Viz: qualitative"),
]


def color(s: str, code: str) -> str:
    if os.environ.get("NO_COLOR"):
        return s
    return f"\033[{code}m{s}\033[0m"


GREEN = lambda s: color(s, "32")
RED = lambda s: color(s, "31")
YELLOW = lambda s: color(s, "33")
CYAN = lambda s: color(s, "36")
GRAY = lambda s: color(s, "90")
BOLD = lambda s: color(s, "1")


def load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def gpu_stats() -> dict | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            text=True, encoding="utf-8", errors="ignore",
        ).strip().splitlines()[0]
        u, used, total, temp, power = [x.strip() for x in out.split(",")]
        return {
            "util": int(u),
            "mem_used": int(used),
            "mem_total": int(total),
            "temp": int(temp),
            "power": float(power) if power else 0.0,
        }
    except Exception:
        return None


def find_running_csv() -> Path | None:
    """Most-recently-modified results.csv (probably the active training)."""
    candidates = list(RUNS_ROOT.glob("**/results.csv"))
    if not candidates:
        return None
    now = time.time()
    fresh = [(p, p.stat().st_mtime) for p in candidates
             if now - p.stat().st_mtime < 600]
    if not fresh:
        return None
    fresh.sort(key=lambda x: x[1], reverse=True)
    return fresh[0][0]


def parse_results_csv(csv_path: Path) -> dict | None:
    try:
        with csv_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return None
            last = {k.strip(): v.strip() for k, v in rows[-1].items()}

            def num(*keys):
                for k in keys:
                    if k in last and last[k]:
                        try:
                            return float(last[k])
                        except ValueError:
                            return None
                return None

            return {
                "n_rows": len(rows),
                "epoch": int(num("epoch") or 0),
                "box_loss": num("train/box_loss"),
                "cls_loss": num("train/cls_loss"),
                "map50": num("metrics/mAP50(B)", "metrics/mAP50"),
                "map50_95": num("metrics/mAP50-95(B)", "metrics/mAP50-95"),
                "precision": num("metrics/precision(B)", "metrics/precision"),
                "recall": num("metrics/recall(B)", "metrics/recall"),
            }
    except Exception:
        return None


def parse_log_tail(n: int = 80) -> list[str]:
    if not LOG_FILE.exists():
        return []
    try:
        return LOG_FILE.read_text(encoding="utf-8").splitlines()[-n:]
    except Exception:
        return []


# ultralytics 训练进度行: " 1/50  1.16G  2.453  12.62  2.012  8  640: 22% ..."
ULT_PROGRESS_RE = re.compile(
    r"\s+(\d+)/(\d+)\s+[\d.]+G\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+\d+\s+\d+:\s*(\d+)%"
)


def parse_ult_progress(lines: list[str]) -> dict | None:
    text = "\n".join(lines)
    m_last = None
    for m in ULT_PROGRESS_RE.finditer(text):
        m_last = m
    if not m_last:
        return None
    return {
        "epoch": int(m_last.group(1)),
        "total_epochs": int(m_last.group(2)),
        "box_loss": float(m_last.group(3)),
        "cls_loss": float(m_last.group(4)),
        "dfl_loss": float(m_last.group(5)),
        "batch_pct": int(m_last.group(6)),
    }


def fmt_seconds(s: int | float) -> str:
    return str(timedelta(seconds=int(s)))


def progress_bar(pct: float, width: int = 30,
                 filled: str = "#", empty: str = ".") -> str:
    pct = max(0, min(100, pct))
    n = int(width * pct / 100)
    return filled * n + empty * (width - n)


def render_once() -> None:
    status = load_status()
    steps = status.get("steps", {})

    # Header
    print(BOLD(CYAN("=" * 70)))
    print(BOLD(CYAN("  Graduation project | Live experiment dashboard")))
    started = status.get("started_at")
    epochs_per_stage = status.get("epochs", "?")
    if started:
        try:
            t0 = datetime.fromisoformat(started)
            running = datetime.now() - t0
            print(f"  Started: {started}    Elapsed: {fmt_seconds(running.total_seconds())}")
        except Exception:
            print(f"  Started: {started}")
    print(f"  Epochs per stage: {epochs_per_stage}")
    print(BOLD(CYAN("=" * 70)))
    print()

    # GPU
    g = gpu_stats()
    if g:
        bar_u = progress_bar(g["util"], 20)
        mem_pct = g["mem_used"] * 100 / max(g["mem_total"], 1)
        bar_m = progress_bar(mem_pct, 20)
        print(f"  GPU util  [{bar_u}] {g['util']:>3}%   "
              f"temp {g['temp']}C   power {g['power']:.0f}W")
        print(f"  GPU mem   [{bar_m}] {g['mem_used']:>5}/{g['mem_total']} MiB "
              f"({mem_pct:.1f}%)")
    else:
        print("  GPU:  " + RED("(nvidia-smi failed)"))
    print()

    # Stages
    print(BOLD("Pipeline stages"))
    print("-" * 70)
    n_done = 0
    n_failed = 0
    started_seen = False
    for sid, label in ALL_STAGES:
        info = steps.get(sid)
        if info is None:
            if not started_seen:
                # 第一个未跑的 = 当前在跑
                marker = YELLOW("[*]")
                tail = "  " + YELLOW("running / pending")
                started_seen = True
            else:
                marker = GRAY("[ ]")
                tail = ""
        else:
            ec = info.get("exit")
            secs = info.get("seconds", 0)
            if ec == 0:
                marker = GREEN("[v]")
                n_done += 1
                tail = f"  {fmt_seconds(secs)}"
            else:
                marker = RED("[x]")
                n_failed += 1
                tail = "  " + RED(f"exit={ec}") + f"  {fmt_seconds(secs)}"
        print(f"  {marker}  {label:<40}{tail}")

    n_total = len(ALL_STAGES)
    overall_pct = n_done * 100 / n_total
    print("-" * 70)
    print(f"  done: {GREEN(str(n_done))}/{n_total}    "
          f"failed: {RED(str(n_failed)) if n_failed else '0'}    "
          f"overall: [{progress_bar(overall_pct, 30)}] {overall_pct:.1f}%")
    print()

    # Active run details
    csv_path = find_running_csv()
    if csv_path:
        rel_parent = csv_path.parent.name
        m = parse_results_csv(csv_path)
        print(BOLD(f"Active run: {rel_parent}"))
        print("-" * 70)
        if m:
            print(f"  completed epochs: {m['n_rows']} / {epochs_per_stage}")
            map50 = m.get("map50")
            if map50 is not None:
                print(f"  mAP@0.5     : {GREEN(f'{map50:.4f}')}")
            map50_95 = m.get("map50_95")
            if map50_95 is not None:
                print(f"  mAP@0.5:.95 : {GREEN(f'{map50_95:.4f}')}")
            p_ = m.get("precision")
            r_ = m.get("recall")
            if p_ is not None and r_ is not None:
                print(f"  precision   : {p_:.4f}    recall: {r_:.4f}")
            if m.get("box_loss") is not None:
                print(f"  loss        : box={m['box_loss']:.3f}  "
                      f"cls={m.get('cls_loss', 0):.3f}")

        # In-epoch live progress (从 pipeline.log 抽 ultralytics 进度行)
        rt = parse_ult_progress(parse_log_tail(120))
        if rt:
            print()
            print(f"  Epoch {rt['epoch']}/{rt['total_epochs']}  "
                  f"batch [{progress_bar(rt['batch_pct'], 25)}] {rt['batch_pct']}%")
            print(f"  live loss: box={rt['box_loss']:.3f}  "
                  f"cls={rt['cls_loss']:.3f}  dfl={rt['dfl_loss']:.3f}")
        print()
    else:
        print(GRAY("(no active training run detected yet)"))
        print()

    # Paper outputs
    print(BOLD("Paper artifacts"))
    print("-" * 70)
    tables_dir = PAPER_ROOT / "tables"
    figs_dir = PAPER_ROOT / "figures"
    n_tables = len(list(tables_dir.glob("*.md"))) if tables_dir.exists() else 0
    n_figs = len(list(figs_dir.glob("*.png"))) if figs_dir.exists() else 0
    print(f"  tables: {n_tables} files in paper/tables/")
    if tables_dir.exists():
        for p in sorted(tables_dir.glob("*.md"))[:8]:
            print(f"      {p.name}")
    print(f"  figures: {n_figs} files in paper/figures/")
    if figs_dir.exists():
        for p in sorted(figs_dir.glob("*.png"))[:8]:
            print(f"      {p.name}")
    print()
    print(GRAY("  details:  type runs\\pipeline.log     |  status: runs\\pipeline_status.json"))
    print()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--watch", action="store_true",
                   help="auto-refresh every N seconds")
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--tail", action="store_true",
                   help="just print last 40 lines of pipeline.log")
    args = p.parse_args()

    if args.tail:
        for line in parse_log_tail(40):
            print(line)
        return 0

    # Enable ANSI on Windows
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

    if args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")
                render_once()
                print(GRAY(f"(refreshing every {args.interval}s, Ctrl+C to quit)"))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped")
            return 0
    else:
        render_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
