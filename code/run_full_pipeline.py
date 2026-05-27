"""
一键跑全套实验的串行流水线
=========================================

按顺序跑:
  1. 4 个 baseline (yolov8n / yolov10n / yolo11n / rtdetr) - 各 50 epochs
  2. ours (yolo11n_full = CBAM + P2)        - 50 epochs
  3. 5 组消融 (yolo11n / cbam / ema / p2 / full) - 各 50 epochs
  4. 数据集统计图 (dataset_stats.py)
  5. eval: complexity / robustness / deployment
  6. visualize: plot_results / grad_cam / make_qualitative

特性:
  - 每一步独立 try/except,某步失败不阻塞后续
  - 状态写入 runs/pipeline_status.json (检查进度用)
  - 已有产物自动跳过(支持中断后续跑)
  - 全部输出叠到 runs/pipeline.log

跑法:
  python run_full_pipeline.py            # 默认 50 epochs
  python run_full_pipeline.py --epochs 100   # 改轮数
  python run_full_pipeline.py --skip baseline ablation   # 跳过某些大块
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PYEXE = sys.executable
RUNS_ROOT = PROJECT_ROOT / "runs"
PAPER_ROOT = PROJECT_ROOT / "paper"
STATUS_FILE = RUNS_ROOT / "pipeline_status.json"
LOG_FILE = RUNS_ROOT / "pipeline.log"

# ---- 各阶段产物路径(用来判断"已经做过") ----
BASELINE_NAMES = ["yolov8n", "yolov10n", "yolo11n", "rtdetr"]
ABLATION_NAMES = ["yolo11n", "yolo11n_cbam", "yolo11n_ema",
                  "yolo11n_p2", "yolo11n_full"]


def baseline_done(name: str) -> bool:
    return (RUNS_ROOT / "baseline" / name / "weights" / "best.pt").exists()


def ours_done() -> bool:
    return (RUNS_ROOT / "ours" / "yolo11n_full" / "weights" / "best.pt").exists()


def ablation_done(name: str) -> bool:
    return (RUNS_ROOT / "ablation" / name / "weights" / "best.pt").exists()


# ---- 工具 ----
def status_load() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"steps": {}, "started_at": None}


def status_save(st: dict) -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(st, indent=2, ensure_ascii=False),
                           encoding="utf-8")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_step(step_id: str, label: str, cmd: list[str],
             status: dict, env: dict | None = None) -> bool:
    """跑一步,记录耗时和退出码,返回是否成功.

    子进程 stdout 实时流到 runs/current.log(便于 tail -f 实时看)
    最终也叠到 runs/pipeline.log。
    """
    log(f"==> [{step_id}] {label}")
    log(f"    cmd: {' '.join(cmd)}")

    t0 = time.time()
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    current_log = RUNS_ROOT / "current.log"
    try:
        with current_log.open("w", encoding="utf-8") as cf:
            cf.write(f"=== [{step_id}] {label} ===\n")
            cf.write(f"=== started: {datetime.now().isoformat(timespec='seconds')} ===\n")
            cf.write(f"=== cmd: {' '.join(cmd)} ===\n\n")
            cf.flush()

            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=full_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,  # line-buffered
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            tail_buf: list[str] = []
            assert proc.stdout is not None
            for line in proc.stdout:
                cf.write(line)
                cf.flush()
                tail_buf.append(line)
                if len(tail_buf) > 200:
                    tail_buf = tail_buf[-200:]
            proc.wait()
            elapsed = time.time() - t0

            # 把最后 200 行也叠到 pipeline.log,便于事后回看
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(f"\n---- output of [{step_id}] (last {len(tail_buf)} lines) ----\n")
                f.writelines(tail_buf)
                f.write(f"---- exit: {proc.returncode} ----\n")

        status["steps"][step_id] = {
            "label": label,
            "exit": proc.returncode,
            "seconds": int(elapsed),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        status_save(status)
        if proc.returncode == 0:
            log(f"    [OK] done in {timedelta(seconds=int(elapsed))}")
            return True
        log(f"    [!!] exit {proc.returncode} after {timedelta(seconds=int(elapsed))}")
        return False
    except Exception as e:
        elapsed = time.time() - t0
        log(f"    [!!] crashed: {e}")
        status["steps"][step_id] = {
            "label": label,
            "exit": -1,
            "error": str(e),
            "seconds": int(elapsed),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        status_save(status)
        return False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=80,
                   help="所有训练阶段的 epochs(默认 80)")
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--device", type=str, default="0")
    p.add_argument("--skip", nargs="*", default=[],
                   choices=["baseline", "ours", "ablation",
                            "stats", "eval", "viz"],
                   help="跳过哪些大块")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    status = status_load()
    status.setdefault("started_at", datetime.now().isoformat(timespec="seconds"))
    status["epochs"] = args.epochs
    status_save(status)

    # 公共训练参数
    train_extra = ["--epochs", str(args.epochs),
                   "--batch", str(args.batch),
                   "--workers", str(args.workers),
                   "--device", args.device]
    extra_env = {
        "TORCH_HOME": "E:\\torch_cache",
        "ULTRALYTICS_DIR": "E:\\torch_cache\\ultralytics",
        "PYTHONIOENCODING": "utf-8",
    }

    log("=" * 60)
    log(f"  Pipeline start (epochs={args.epochs}, batch={args.batch})")
    log("=" * 60)

    # ----------------------------------------------------------
    # Phase 1: baselines (一个一个跑,某个挂了不影响下一个)
    # ----------------------------------------------------------
    if "baseline" not in args.skip:
        for name in BASELINE_NAMES:
            sid = f"baseline_{name}"
            if baseline_done(name):
                log(f"==> [{sid}] already done, skip")
                continue
            run_step(
                sid, f"train baseline {name}",
                [PYEXE, "train/train_baseline.py", "--only", name] + train_extra,
                status, env=extra_env,
            )

    # ----------------------------------------------------------
    # Phase 2: ours
    # ----------------------------------------------------------
    if "ours" not in args.skip:
        if ours_done():
            log("==> [ours] already done, skip")
        else:
            run_step(
                "ours", "train ours (yolo11n_full = CBAM + P2)",
                [PYEXE, "train/train_ours.py"] + train_extra,
                status, env=extra_env,
            )

    # ----------------------------------------------------------
    # Phase 3: ablation
    # ----------------------------------------------------------
    if "ablation" not in args.skip:
        # ablation 脚本本身有 --skip,我们逐个跳过已完成的
        skip_done = [n for n in ABLATION_NAMES if ablation_done(n)]
        if len(skip_done) == len(ABLATION_NAMES):
            log("==> [ablation] all done, skip")
        else:
            cmd = [PYEXE, "train/train_ablation.py"] + train_extra
            if skip_done:
                cmd += ["--skip"] + skip_done
                log(f"    ablation will skip already-done: {skip_done}")
            run_step("ablation", "train 5 ablation configs", cmd,
                     status, env=extra_env)

    # ----------------------------------------------------------
    # Phase 4: dataset stats
    # ----------------------------------------------------------
    if "stats" not in args.skip:
        run_step("dataset_stats", "dataset stats + figures",
                 [PYEXE, "data/dataset_stats.py"], status, env=extra_env)

    # ----------------------------------------------------------
    # Phase 5: eval
    # ----------------------------------------------------------
    if "eval" not in args.skip:
        for name, script in [
            ("eval_complexity",  "eval/eval_complexity.py"),
            ("eval_robustness",  "eval/eval_robustness.py"),
            ("eval_deployment",  "eval/eval_deployment.py"),
        ]:
            run_step(name, f"run {script}", [PYEXE, script], status,
                     env=extra_env)

    # ----------------------------------------------------------
    # Phase 6: visualize
    # ----------------------------------------------------------
    if "viz" not in args.skip:
        for name, script in [
            ("viz_curves",       "visualize/plot_results.py"),
            ("viz_gradcam",      "visualize/grad_cam.py"),
            ("viz_qualitative",  "visualize/make_qualitative.py"),
        ]:
            run_step(name, f"run {script}", [PYEXE, script], status,
                     env=extra_env)

    # ----------------------------------------------------------
    # 总结
    # ----------------------------------------------------------
    log("")
    log("=" * 60)
    log("  Pipeline finished")
    log("=" * 60)

    # 列出所有产物
    log("Tables in paper/tables/:")
    tables_dir = PAPER_ROOT / "tables"
    if tables_dir.exists():
        for p in sorted(tables_dir.glob("*")):
            log(f"   {p.name}  ({p.stat().st_size} bytes)")

    log("Figures in paper/figures/:")
    figs_dir = PAPER_ROOT / "figures"
    if figs_dir.exists():
        for p in sorted(figs_dir.glob("*")):
            log(f"   {p.name}  ({p.stat().st_size} bytes)")

    # 简要状态报告
    log("")
    log("Step results:")
    for sid, info in status["steps"].items():
        marker = "[OK]" if info.get("exit") == 0 else "[!!]"
        secs = info.get("seconds", 0)
        log(f"  {marker} {sid:<22} {timedelta(seconds=secs)}  "
            f"exit={info.get('exit')}")

    failed = [s for s, v in status["steps"].items() if v.get("exit") != 0]
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
