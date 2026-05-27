"""
run_pipeline_v2.py
==================

v2 全套实验流水线编排（E1 + E2 + E3 + E4 + 评估组）。

特性：
  - 串行跑（一张卡），失败不阻塞后续
  - 已完成（best.pt 存在）自动跳过
  - 中断后再次启动会用 last.pt 续训
  - 状态写到 runs/v2/pipeline_v2_status.json
  - 输出叠到 runs/v2/pipeline_v2.log

跑法:
  python run_pipeline_v2.py                          # 全套（推荐路径）
  python run_pipeline_v2.py --skip cbam_pos          # 跳过 E3
  python run_pipeline_v2.py --only e2                # 只跑 E2

阶段:
  e1   = 3 baselines × 200ep (45h)
  e2   = 5 ablation × 200ep  (75h)
  e3   = 3 cbam_pos × 200ep  (45h)
  e4   = ours × {100, 300}ep (30h)
  eval = 复杂度 + 鲁棒性 + 部署 + 可视化 (3h)
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
RUNS_V2 = PROJECT_ROOT / "runs" / "v2"
STATUS_FILE = RUNS_V2 / "pipeline_v2_status.json"
LOG_FILE = RUNS_V2 / "pipeline_v2.log"


# ============================================================================
#  实验定义
# ============================================================================
class Step:
    def __init__(self, sid: str, group: str, name: str,
                 epochs: int = 200, tag: str = ""):
        self.sid = sid
        self.group = group
        self.name = name
        self.epochs = epochs
        self.tag = tag

    @property
    def run_name(self) -> str:
        return self.name + self.tag

    @property
    def out_dir(self) -> Path:
        return RUNS_V2 / self.group / self.run_name

    def is_done(self) -> bool:
        return (self.out_dir / "weights" / "best.pt").exists()

    def has_partial(self) -> bool:
        return (self.out_dir / "weights" / "last.pt").exists() and not self.is_done()


STEPS_E1: list[Step] = [
    Step("e1_yolov8n",  "baseline", "yolov8n",  epochs=200),
    Step("e1_yolov10n", "baseline", "yolov10n", epochs=200),
    Step("e1_yolo11n",  "baseline", "yolo11n",  epochs=200),
]

STEPS_E2: list[Step] = [
    Step("e2_a0_yolo11n",      "ablation", "yolo11n",       epochs=200),
    Step("e2_a1_cbam",         "ablation", "yolo11n_cbam",  epochs=200),
    Step("e2_a2_ema",          "ablation", "yolo11n_ema",   epochs=200),
    Step("e2_a3_p2",           "ablation", "yolo11n_p2",    epochs=200),
    Step("e2_a4_full",         "ablation", "yolo11n_full",  epochs=200),
]

STEPS_E3: list[Step] = [
    Step("e3_cbam_p3only", "cbam_pos", "yolo11n_cbam_p3only", epochs=200),
    Step("e3_cbam_p3p4",   "cbam_pos", "yolo11n_cbam_p3p4",   epochs=200),
    Step("e3_cbam_p5only", "cbam_pos", "yolo11n_cbam_p5only", epochs=200),
]

STEPS_E4: list[Step] = [
    Step("e4_full_ep100", "budget", "yolo11n_full", epochs=100, tag="_ep100"),
    Step("e4_full_ep300", "budget", "yolo11n_full", epochs=300, tag="_ep300"),
]

EVAL_STEPS: list[tuple[str, str]] = [
    ("eval_complexity",  "eval/eval_complexity.py"),
    ("eval_robustness",  "eval/eval_robustness.py"),
    ("eval_deployment",  "eval/eval_deployment.py"),
    ("viz_curves",       "visualize/plot_results.py"),
    ("viz_gradcam",      "visualize/grad_cam.py"),
    ("viz_qualitative",  "visualize/make_qualitative.py"),
]


# ============================================================================
#  状态管理
# ============================================================================
def status_load() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"steps": {}, "started_at": None}


def status_save(st: dict) -> None:
    RUNS_V2.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(
        json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    RUNS_V2.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================================
#  执行单步
# ============================================================================
def run_train_step(step: Step, status: dict) -> bool:
    if step.is_done():
        log(f"==> [{step.sid}] 已有 best.pt，跳过")
        return True

    cmd = [PYEXE, "train/train_v2.py",
           "--group", step.group,
           "--name", step.name,
           "--epochs", str(step.epochs)]
    if step.tag:
        cmd += ["--tag", step.tag]
    if step.has_partial():
        cmd += ["--resume"]
        log(f"==> [{step.sid}] 检测到 last.pt，续训")
    else:
        log(f"==> [{step.sid}] 新训")

    log(f"    cmd: {' '.join(cmd)}")

    t0 = time.time()
    env = os.environ.copy()
    env.update({
        "TORCH_HOME": "E:\\torch_cache",
        "ULTRALYTICS_DIR": "E:\\torch_cache\\ultralytics",
        "PYTHONIOENCODING": "utf-8",
    })

    current_log = RUNS_V2 / "current.log"
    try:
        with current_log.open("w", encoding="utf-8") as cf:
            cf.write(f"=== [{step.sid}] {step.run_name} ===\n")
            cf.write(f"=== started: {datetime.now().isoformat(timespec='seconds')} ===\n")
            cf.write(f"=== cmd: {' '.join(cmd)} ===\n\n")
            cf.flush()

            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, text=True, encoding="utf-8", errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                cf.write(line)
                cf.flush()
            proc.wait()
            elapsed = time.time() - t0

        status["steps"][step.sid] = {
            "name": step.run_name,
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
        status["steps"][step.sid] = {
            "name": step.run_name,
            "exit": -1,
            "error": str(e),
            "seconds": int(elapsed),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        status_save(status)
        return False


def run_eval_step(sid: str, script: str, status: dict) -> bool:
    log(f"==> [{sid}] {script}")
    cmd = [PYEXE, script]
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    status["steps"][sid] = {
        "exit": proc.returncode,
        "seconds": int(elapsed),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    status_save(status)
    if proc.returncode == 0:
        log(f"    [OK] done in {timedelta(seconds=int(elapsed))}")
        return True
    # eval 失败时打末尾几行
    log(f"    [!!] exit {proc.returncode}")
    if proc.stdout:
        for ln in (proc.stdout or "").splitlines()[-15:]:
            log(f"      | {ln}")
    return False


# ============================================================================
#  主入口
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["e1", "e2", "e3", "e4", "eval"], default=None,
                   help="只跑某一阶段")
    p.add_argument("--skip", nargs="*", default=[],
                   choices=["e1", "e2", "e3", "e4", "eval"],
                   help="跳过某些阶段")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    status = status_load()
    status.setdefault("started_at",
                      datetime.now().isoformat(timespec="seconds"))
    status_save(status)

    log("=" * 60)
    log("  Pipeline v2 start")
    log("=" * 60)

    phases = []
    if args.only:
        if args.only == "e1":
            phases = [("e1", STEPS_E1)]
        elif args.only == "e2":
            phases = [("e2", STEPS_E2)]
        elif args.only == "e3":
            phases = [("e3", STEPS_E3)]
        elif args.only == "e4":
            phases = [("e4", STEPS_E4)]
        elif args.only == "eval":
            phases = [("eval", None)]
    else:
        phases = [
            ("e1", STEPS_E1),
            ("e2", STEPS_E2),
            ("e3", STEPS_E3),
            ("e4", STEPS_E4),
            ("eval", None),
        ]

    for phase_id, steps in phases:
        if phase_id in args.skip:
            log(f"==> 跳过阶段 {phase_id}")
            continue

        log("")
        log(f"========== Phase {phase_id} ==========")

        if phase_id == "eval":
            for sid, script in EVAL_STEPS:
                run_eval_step(sid, script, status)
        else:
            assert steps is not None
            for step in steps:
                run_train_step(step, status)

    log("")
    log("=" * 60)
    log("  Pipeline v2 finished")
    log("=" * 60)

    failed = [s for s, v in status["steps"].items()
              if v.get("exit") not in (0, None)]
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
