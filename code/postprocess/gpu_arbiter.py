"""
gpu_arbiter.py
==============

Skylark 项目的 GPU 资源仲裁器。

实现 `MULTI_WINDOW_PROTOCOL.md` §3 铁律 2 + skill `references/gpu-arbiter.md`。

设计目标：
  - 单 GPU（5060 Ti）多窗口环境下，确保任意时刻最多 1 个 GPU 任务在跑
  - 通过文件锁（runs/.gpu_lock.json）协调，无需 Redis/SQLite
  - Stale lock（owner 进程已死）可被任意窗口 force-clear
  - 训练脚本通过 atexit 自动 release，避免泄漏

子命令：
  status        显示当前 lock 状态
  claim         占用 GPU
  release       释放当前 lock
  check-stale   检查 lock 是否 stale（owner pid 已死）
  force-clear   强制清理 stale lock

用法（命令行）：
  python code/postprocess/gpu_arbiter.py status
  python code/postprocess/gpu_arbiter.py claim --owner Window-A --task "v2 baseline 200ep" --estimated-hours 15
  python code/postprocess/gpu_arbiter.py release
  python code/postprocess/gpu_arbiter.py force-clear --reason "PID 12345 dead"

用法（被训练脚本调用）：
  from postprocess.gpu_arbiter import claim_or_die, release
  claim_or_die(owner="Window-A", task="...", estimated_hours=15)
  try:
      train(...)
  finally:
      release()
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = PROJECT_ROOT / "runs" / ".gpu_lock.json"


# ============================================================================
#  工具
# ============================================================================
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_dt() -> datetime:
    return datetime.now()


def _load_lock() -> dict:
    if not LOCK_FILE.exists():
        return _empty_lock()
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _empty_lock()


def _save_lock(lock: dict) -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(
        json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _empty_lock() -> dict:
    return {
        "owner": None,
        "task": None,
        "started_at": None,
        "estimated_end": None,
        "pid": 0,
        "can_be_preempted": False,
        "released_at": None,
        "history": [],
    }


def _is_active(lock: dict) -> bool:
    return (
        lock.get("owner") is not None
        and lock.get("released_at") is None
    )


def _pid_alive(pid: int) -> bool:
    """检查 PID 对应进程是否还活着（Windows + Unix 通用）"""
    if not pid or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED, False, int(pid)
            )
            if handle == 0:
                return False
            # 检查 ExitCode（259 = STILL_ACTIVE）
            exit_code = ctypes.c_ulong(0)
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            )
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == 259
        else:
            os.kill(int(pid), 0)
            return True
    except Exception:
        return False


def _format_age(ts_iso: str) -> str:
    if not ts_iso:
        return "(unknown)"
    try:
        ts = datetime.fromisoformat(ts_iso)
        delta = _now_dt() - ts
        if delta.days > 0:
            return f"{delta.days}d {delta.seconds // 3600}h ago"
        h = delta.seconds // 3600
        m = (delta.seconds % 3600) // 60
        if h > 0:
            return f"{h}h {m}m ago"
        return f"{m}m ago"
    except Exception:
        return ts_iso


# ============================================================================
#  子命令
# ============================================================================
def cmd_status(args: argparse.Namespace) -> int:
    lock = _load_lock()
    print("=" * 60)
    print("  GPU Lock Status")
    print("=" * 60)

    if not _is_active(lock):
        print("  Status:       ✅ AVAILABLE (no active lock)")
        print()
        history = lock.get("history") or []
        if history:
            last = history[-1]
            print(f"  Last release: {last.get('released_at', '?')}  "
                  f"by {last.get('owner', '?')}")
        return 0

    print(f"  Status:       🔴 ACTIVE")
    print(f"  Owner:        {lock.get('owner')}")
    print(f"  Task:         {lock.get('task')}")
    started = lock.get("started_at")
    print(f"  Started:      {started}  ({_format_age(started)})")
    est_end = lock.get("estimated_end")
    if est_end:
        print(f"  Est. release: {est_end}")
    pid = lock.get("pid", 0)
    if pid:
        alive = _pid_alive(int(pid))
        marker = "✅ alive" if alive else "❌ DEAD (stale lock!)"
        print(f"  PID:          {pid}  ({marker})")
        if not alive:
            print()
            print("  ⚠️  Lock is STALE. Use:")
            print("     python code/postprocess/gpu_arbiter.py force-clear --reason '...'")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    lock = _load_lock()

    # 已被占用且 owner 仍活着 → 拒绝
    if _is_active(lock):
        pid = int(lock.get("pid") or 0)
        if pid and _pid_alive(pid):
            print(f"❌ GPU is already claimed by {lock.get('owner')} "
                  f"(task: {lock.get('task')}, pid: {pid}).")
            print("   Wait for release or use force-clear if you suspect stale lock.")
            return 2
        else:
            print(f"⚠️ Detected stale lock (owner: {lock.get('owner')}, pid: {pid}).")
            print("   Auto-clearing and proceeding to claim.")
            lock = _force_clear_in_memory(lock, reason=f"auto-clear stale on claim by {args.owner}")

    # 写新 lock
    new_lock = {
        "owner": args.owner,
        "task": args.task,
        "started_at": _now_iso(),
        "estimated_end": (
            _now_dt().replace(microsecond=0).isoformat(timespec="seconds")
            if args.estimated_hours <= 0
            else (_now_dt() + _timedelta_hours(args.estimated_hours))
                  .replace(microsecond=0).isoformat(timespec="seconds")
        ),
        "pid": int(args.pid or os.getpid()),
        "can_be_preempted": bool(args.can_be_preempted),
        "released_at": None,
        "history": lock.get("history") or [],
    }
    _save_lock(new_lock)
    print(f"✅ GPU claimed by {args.owner}")
    print(f"   Task: {args.task}")
    print(f"   PID:  {new_lock['pid']}")
    print(f"   Est. release: {new_lock['estimated_end']}")
    return 0


def _timedelta_hours(h: float):
    from datetime import timedelta
    return timedelta(hours=float(h))


def cmd_release(args: argparse.Namespace) -> int:
    lock = _load_lock()
    if not _is_active(lock):
        print("ℹ️ No active lock to release.")
        return 0

    history = lock.get("history") or []
    started = lock.get("started_at")
    released = _now_iso()
    duration_hours = 0.0
    if started:
        try:
            duration_hours = (datetime.fromisoformat(released) -
                              datetime.fromisoformat(started)).total_seconds() / 3600.0
        except Exception:
            pass

    history.append({
        "owner": lock.get("owner"),
        "task": lock.get("task"),
        "started_at": started,
        "released_at": released,
        "duration_hours": round(duration_hours, 2),
    })
    if len(history) > 50:
        history = history[-50:]  # 保留最近 50 条

    new_lock = _empty_lock()
    new_lock["history"] = history
    new_lock["released_at"] = released  # 给 status 看
    _save_lock(new_lock)
    print(f"✅ GPU released. Duration: {duration_hours:.2f} h")
    return 0


def _force_clear_in_memory(lock: dict, reason: str) -> dict:
    """force-clear 不写盘版本，供 claim 时使用"""
    history = lock.get("history") or []
    history.append({
        "owner": lock.get("owner"),
        "task": lock.get("task"),
        "started_at": lock.get("started_at"),
        "released_at": _now_iso(),
        "duration_hours": None,
        "force_cleared": True,
        "reason": reason,
    })
    new_lock = _empty_lock()
    new_lock["history"] = history
    return new_lock


def cmd_force_clear(args: argparse.Namespace) -> int:
    lock = _load_lock()
    if not _is_active(lock):
        print("ℹ️ No active lock to clear.")
        return 0

    pid = int(lock.get("pid") or 0)
    alive = _pid_alive(pid) if pid else False
    if alive and not args.yes_kill_alive:
        print(f"❌ Owner PID {pid} is still ALIVE.")
        print("   Refusing to force-clear by default. Pass --yes-kill-alive to override.")
        print("   You should investigate why the active task isn't releasing properly.")
        return 3

    new_lock = _force_clear_in_memory(lock, reason=args.reason or "manual")
    _save_lock(new_lock)
    print(f"✅ Force-cleared lock from {lock.get('owner')} (task: {lock.get('task')})")
    print(f"   Reason: {args.reason}")
    return 0


def cmd_check_stale(args: argparse.Namespace) -> int:
    lock = _load_lock()
    if not _is_active(lock):
        print("ℹ️ No active lock.")
        return 0

    pid = int(lock.get("pid") or 0)
    if pid and _pid_alive(pid):
        print(f"✅ Lock is healthy. Owner PID {pid} is alive.")
        return 0
    print(f"⚠️ Lock is STALE. Owner: {lock.get('owner')}, PID: {pid} (dead).")
    print(f"   Recommended: python code/postprocess/gpu_arbiter.py force-clear --reason 'stale pid'")
    return 4


# ============================================================================
#  对外 API（被训练脚本 import）
# ============================================================================
def claim_or_die(owner: str, task: str, estimated_hours: float = 1.0,
                 can_be_preempted: bool = False) -> None:
    """供训练脚本调用：claim 失败立刻退出"""
    args = argparse.Namespace(
        owner=owner,
        task=task,
        estimated_hours=estimated_hours,
        can_be_preempted=can_be_preempted,
        pid=os.getpid(),
    )
    rc = cmd_claim(args)
    if rc != 0:
        sys.exit(rc)


def release() -> None:
    """供训练脚本调用：忽略错误的 release"""
    try:
        cmd_release(argparse.Namespace())
    except Exception as e:
        print(f"⚠️ release failed: {e}", file=sys.stderr)


# ============================================================================
#  CLI 入口
# ============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(prog="gpu_arbiter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="显示 lock 状态")

    sp_claim = sub.add_parser("claim", help="占用 GPU")
    sp_claim.add_argument("--owner", required=True,
                          choices=["Window-A", "Window-B", "Window-C", "Window-D"])
    sp_claim.add_argument("--task", required=True, help="任务描述")
    sp_claim.add_argument("--estimated-hours", type=float, default=1.0)
    sp_claim.add_argument("--can-be-preempted", action="store_true")
    sp_claim.add_argument("--pid", type=int, default=0,
                          help="PID（默认当前进程）")

    sub.add_parser("release", help="释放当前 lock")

    sub.add_parser("check-stale", help="检查 lock 是否 stale")

    sp_force = sub.add_parser("force-clear", help="强制清除 stale lock")
    sp_force.add_argument("--reason", required=True, help="清除原因（写入 history）")
    sp_force.add_argument("--yes-kill-alive", action="store_true",
                          help="即使 owner 进程仍活着也强制清（危险）")

    args = ap.parse_args()

    handlers = {
        "status":      cmd_status,
        "claim":       cmd_claim,
        "release":     cmd_release,
        "check-stale": cmd_check_stale,
        "force-clear": cmd_force_clear,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
