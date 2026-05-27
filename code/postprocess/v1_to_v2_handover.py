"""
v1_to_v2_handover.py
=====================

监视 v1 daemon (GP_Pipeline_Daemon) 的状态，等它跑完后：
  1. 把 v1 daemon 的 schtasks 取消
  2. 注册并启动 v2 daemon (GP_Pipeline_Daemon_V2)，在系统启动时自动恢复

本脚本是一次性运行的——它会自我退出，不常驻。
建议在 v1 daemon 还在跑时启动它（PowerShell `start /b` 或后台进程）。

也可以让用户手动操作：
  1. 看 daemon.log 里有 "Pipeline finished"
  2. schtasks /delete /tn GP_Pipeline_Daemon /f
  3. schtasks /create /tn GP_Pipeline_Daemon_V2 /tr "%PROJECT%\_daemon_run_v2.bat" /sc onstart /rl highest /f
  4. schtasks /run /tn GP_Pipeline_Daemon_V2

用法:
  python postprocess/v1_to_v2_handover.py            # 监听并自动切换
  python postprocess/v1_to_v2_handover.py --no-watch # 直接切换（如果你确定 v1 已完成）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
V1_TASK = "GP_Pipeline_Daemon"
V2_TASK = "GP_Pipeline_Daemon_V2"
V1_BAT = PROJECT_ROOT / "_daemon_run.bat"
V2_BAT = PROJECT_ROOT / "_daemon_run_v2.bat"
V1_LOG = PROJECT_ROOT / "runs" / "daemon.log"


def schtasks_query(task: str) -> str:
    """返回任务状态原文，找不到返回空"""
    try:
        proc = subprocess.run(
            ["schtasks", "/query", "/tn", task, "/fo", "LIST"],
            capture_output=True, text=True, encoding="gbk", errors="replace",
        )
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


def v1_finished() -> bool:
    """v1 是否结束"""
    if not V1_LOG.exists():
        return False
    text = V1_LOG.read_text(encoding="utf-8", errors="replace")
    if "Pipeline finished" in text or "daemon finished" in text:
        return True
    # 任务运行状态
    state = schtasks_query(V1_TASK)
    if not state:
        return True   # 任务不存在 = 可视为结束
    if "正在运行" in state or "Running" in state:
        return False
    return True


def watch_v1(poll_sec: int = 60, max_hours: int = 48) -> bool:
    print(f"[watch] 等待 v1 daemon 完成（轮询 {poll_sec}s，超时 {max_hours}h）")
    deadline = time.time() + max_hours * 3600
    while time.time() < deadline:
        if v1_finished():
            print("[watch] v1 已完成")
            return True
        time.sleep(poll_sec)
    print("[watch] 超时")
    return False


def stop_v1() -> None:
    print(f"[stop_v1] 取消 {V1_TASK}")
    subprocess.run(["schtasks", "/end", "/tn", V1_TASK],
                   capture_output=True)
    subprocess.run(["schtasks", "/delete", "/tn", V1_TASK, "/f"],
                   capture_output=True)


def start_v2() -> None:
    if not V2_BAT.exists():
        raise FileNotFoundError(f"找不到 {V2_BAT}")

    print(f"[start_v2] 注册 {V2_TASK}")
    # 先删除（如果存在）
    subprocess.run(["schtasks", "/delete", "/tn", V2_TASK, "/f"],
                   capture_output=True)
    # 再注册（系统启动时运行）
    rc = subprocess.run([
        "schtasks", "/create", "/tn", V2_TASK,
        "/tr", f'"{V2_BAT}"',
        "/sc", "onstart",
        "/rl", "highest",
        "/f",
    ])
    if rc.returncode != 0:
        print("[start_v2] schtasks /create 失败")
        sys.exit(1)
    # 立即启动一次
    print(f"[start_v2] 立即启动一次")
    subprocess.run(["schtasks", "/run", "/tn", V2_TASK])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--no-watch", action="store_true")
    p.add_argument("--poll", type=int, default=60,
                   help="检查间隔秒（默认 60）")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not args.no_watch:
        ok = watch_v1(poll_sec=args.poll)
        if not ok:
            return 1

    stop_v1()
    start_v2()
    print()
    print("[OK] v2 daemon 已启动")
    print(f"  日志: {PROJECT_ROOT / 'runs' / 'v2' / 'daemon_v2.log'}")
    print(f"  状态: {PROJECT_ROOT / 'runs' / 'v2' / 'pipeline_v2_status.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
