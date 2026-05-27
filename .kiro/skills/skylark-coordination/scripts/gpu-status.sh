#!/usr/bin/env bash
# gpu-status.sh — GPU lock 状态查看 + 可选强制清理
# 用法：
#   bash .kiro/skills/skylark-coordination/scripts/gpu-status.sh           # 查看
#   bash .kiro/skills/skylark-coordination/scripts/gpu-status.sh --check-stale  # 检查 stale
#   bash .kiro/skills/skylark-coordination/scripts/gpu-status.sh --force-clear  # 强制清

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$PROJECT_ROOT"

LOCK_FILE="code/runs/.gpu_lock.json"
ARBITER="code/postprocess/gpu_arbiter.py"

# ── 优先用 Python 仲裁器（如已存在）──
if [ -f "$ARBITER" ]; then
    PYEXE="${PYEXE:-E:/conda_envs/yolo/python.exe}"
    if [ ! -x "$PYEXE" ] && command -v python >/dev/null 2>&1; then
        PYEXE=python
    fi
    case "$1" in
        --check-stale) "$PYEXE" "$ARBITER" check-stale ;;
        --force-clear) "$PYEXE" "$ARBITER" force-clear --reason "${2:-manual via gpu-status.sh}" ;;
        *)             "$PYEXE" "$ARBITER" status ;;
    esac
    exit $?
fi

# ── Fallback：纯 bash 解析 ──
echo "(gpu_arbiter.py 尚未创建，使用 bash fallback)"
echo ""

if [ ! -f "$LOCK_FILE" ]; then
    echo "✅ GPU 空闲（无 lock 文件）"
    exit 0
fi

if command -v jq >/dev/null 2>&1; then
    OWNER=$(jq -r '.owner // "(none)"' "$LOCK_FILE")
    TASK=$(jq -r '.task // "(none)"' "$LOCK_FILE")
    STARTED=$(jq -r '.started_at // "(none)"' "$LOCK_FILE")
    RELEASED=$(jq -r '.released_at // ""' "$LOCK_FILE")
    PID=$(jq -r '.pid // 0' "$LOCK_FILE")

    echo "Lock file: $LOCK_FILE"
    echo "  Owner:        $OWNER"
    echo "  Task:         $TASK"
    echo "  Started:      $STARTED"

    if [ -z "$RELEASED" ] || [ "$RELEASED" = "null" ]; then
        echo "  Status:       🔴 ACTIVE"
        if [ "$1" = "--check-stale" ] && [ "$PID" != "0" ]; then
            if command -v tasklist >/dev/null 2>&1; then
                if tasklist /fi "PID eq $PID" 2>/dev/null | grep -q "$PID"; then
                    echo "  PID $PID:      ✅ alive"
                else
                    echo "  PID $PID:      ❌ DEAD (lock is stale!)"
                fi
            fi
        fi
    else
        echo "  Status:       ✅ released at $RELEASED"
    fi
else
    echo "(install jq for nicer output)"
    cat "$LOCK_FILE"
fi
