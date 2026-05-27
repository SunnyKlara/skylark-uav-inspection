#!/usr/bin/env bash
# status.sh — Skylark 项目一站式状态查看
# 用法：bash .kiro/skills/skylark-coordination/scripts/status.sh
# 输出：所有窗口在干什么、GPU 状态、daemon 状态

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Skylark Status — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

# ── 1. GPU 状态 ──
echo "─── GPU Lock ───"
LOCK_FILE="code/runs/.gpu_lock.json"
if [ -f "$LOCK_FILE" ]; then
    if command -v jq >/dev/null 2>&1; then
        OWNER=$(jq -r '.owner // "(none)"' "$LOCK_FILE")
        TASK=$(jq -r '.task // "(none)"' "$LOCK_FILE")
        STARTED=$(jq -r '.started_at // "(none)"' "$LOCK_FILE")
        RELEASED=$(jq -r '.released_at // "active"' "$LOCK_FILE")
        echo "  Owner:    $OWNER"
        echo "  Task:     $TASK"
        echo "  Started:  $STARTED"
        echo "  Status:   $RELEASED"
    else
        echo "  (install jq for parsed view)"
        cat "$LOCK_FILE"
    fi
else
    echo "  (no lock file — GPU available)"
fi
echo ""

# ── 2. nvidia-smi ──
echo "─── GPU Hardware ───"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu \
               --format=csv,noheader,nounits 2>/dev/null \
        | awk -F', ' '{ printf "  Util: %s%%   Mem: %s/%s MiB   Temp: %s°C\n", $1, $2, $3, $4 }'
else
    echo "  (nvidia-smi unavailable)"
fi
echo ""

# ── 3. Daemon ──
echo "─── v1 Daemon ───"
if command -v schtasks >/dev/null 2>&1; then
    STATE=$(schtasks /query /tn "GP_Pipeline_Daemon" /fo LIST 2>/dev/null | grep -E "^模式|^Status" | head -1 || echo "  (task not found)")
    echo "$STATE"
fi
LOG="code/runs/daemon.log"
if [ -f "$LOG" ]; then
    LAST=$(tail -1 "$LOG" 2>/dev/null)
    echo "  Last log: $LAST"
fi
echo ""

# ── 4. 当前训练 epoch（如有）──
echo "─── Current Training (if any) ───"
CUR_LOG="code/runs/current.log"
if [ -f "$CUR_LOG" ]; then
    tail -1 "$CUR_LOG" 2>/dev/null | head -c 250 && echo ""
else
    echo "  (no current.log)"
fi
echo ""

# ── 5. 各 MODULE_STATE 摘要 ──
echo "─── Module States ───"
for f in code/runs/MODULE_STATE_ML.md \
         paper/MODULE_STATE_PAPER.md \
         platform/backend/MODULE_STATE.md \
         platform/frontend/MODULE_STATE.md \
         edge/MODULE_STATE.md \
         simulation/MODULE_STATE.md
do
    if [ -f "$f" ]; then
        UPDATED=$(grep -m1 "上次更新" "$f" 2>/dev/null | head -c 80 || echo "(unknown)")
        echo "  $f"
        echo "    $UPDATED"
    fi
done
echo ""

# ── 6. 主 STATE.md 时间戳 ──
echo "─── 主 STATE.md ───"
if [ -f "STATE.md" ]; then
    grep -m1 "最后更新" STATE.md 2>/dev/null | head -c 100 || echo "  (no timestamp)"
    echo ""
fi
echo ""

# ── 7. 训练运行目录 ──
echo "─── Recent Training Runs ───"
if [ -d "code/runs" ]; then
    find code/runs -name "best.pt" -mtime -7 2>/dev/null | head -10 | while read pt; do
        DIR=$(dirname "$pt")
        SIZE=$(stat -c%s "$pt" 2>/dev/null || stat -f%z "$pt" 2>/dev/null)
        SIZE_MB=$((SIZE / 1024 / 1024))
        echo "  $DIR  (${SIZE_MB} MB)"
    done
fi
echo ""

# ── 8. Pending Handoffs（从 STATE.md 抓取）──
echo "─── Pending Handoffs ───"
if [ -f "STATE.md" ]; then
    awk '/^### 紧急 Handoffs/,/^### |^## /' STATE.md 2>/dev/null | head -20 || true
    awk '/^### 本周 Handoffs/,/^### |^## /' STATE.md 2>/dev/null | head -20 || true
fi
echo ""

echo "============================================================"
echo "  End of Status Report"
echo "============================================================"
