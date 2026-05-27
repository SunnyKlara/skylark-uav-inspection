#!/usr/bin/env bash
# claim-check.sh — 检查某文件的归属窗口和最近活动
# 用法：bash .kiro/skills/skylark-coordination/scripts/claim-check.sh <文件路径>

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <文件路径>"
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$PROJECT_ROOT"

FILE="$1"

echo "[claim-check] $FILE"
echo ""

# ── 1. 归属判断 ──
case "$FILE" in
    code/configs/*|code/data/*|code/eval/*|code/models/*|code/postprocess/*|code/runs/*|code/setup/*|code/train/*|code/visualize/*|code/yolo*.pt|code/run_pipeline*|code/_daemon_run*|code/0*.bat|ml/deploy/export_*|edge/inference/*)
        OWNER="Window-A"
        ;;
    paper/*|PROJECT_NORTH_STAR.md|MASTER_ARCHITECTURE.md|MULTI_WINDOW_PROTOCOL.md|EXPERIMENT_DESIGN_v2.md|FINALIZE_README.md|README.md|01_*.md|02_*.md|03_*.md|04_*.md|WINDOW_*_KICKOFF.md|docs/*)
        OWNER="Window-B"
        ;;
    platform/backend/*|edge/*|ml/deploy/build_trt*|ml/deploy/quantize*|.github/workflows/*|docker-compose.yml)
        OWNER="Window-C"
        ;;
    platform/frontend/*|simulation/*|docs/demo/*)
        OWNER="Window-D"
        ;;
    STATE.md|code/runs/.gpu_lock.json|requirements.txt)
        OWNER="共享 (见特殊协议)"
        ;;
    *)
        OWNER="(未在归属表中找到 — 默认禁止编辑)"
        ;;
esac

echo "  Owner:           $OWNER"

# ── 2. 文件是否存在 ──
if [ -f "$FILE" ]; then
    SIZE=$(stat -c%s "$FILE" 2>/dev/null || stat -f%z "$FILE" 2>/dev/null)
    MTIME=$(stat -c%y "$FILE" 2>/dev/null || stat -f%Sm "$FILE" 2>/dev/null)
    echo "  Size:            $SIZE bytes"
    echo "  Last modified:   $MTIME"
elif [ -d "$FILE" ]; then
    echo "  (是目录，不是文件)"
    exit 0
else
    echo "  (文件不存在)"
fi

# ── 3. STATE.md 中的 mention ──
if [ -f "STATE.md" ]; then
    HITS=$(grep -c "$FILE" STATE.md 2>/dev/null || echo "0")
    echo "  STATE mentions:  $HITS"
    if [ "$HITS" -gt 0 ]; then
        echo ""
        echo "  Recent STATE.md context:"
        grep -n "$FILE" STATE.md | head -5 | sed 's/^/    /'
    fi
fi

echo ""

# ── 4. 操作建议 ──
echo "─── 建议 ───"
case "$OWNER" in
    "Window-A")
        echo "  - 如果当前窗口是 A：可直接编辑"
        echo "  - 如果不是：在 STATE.md 写 handoff，等 Window-A 处理"
        ;;
    "Window-B")
        echo "  - 如果当前窗口是 B：可直接编辑"
        echo "  - 如果不是：写 handoff 到 STATE.md"
        ;;
    "Window-C"|"Window-D")
        echo "  - 该模块尚未启用（Q2/Q3 起）"
        echo "  - 当前禁止创建该模块文件"
        ;;
    "共享 (见特殊协议)")
        echo "  - 共享文件 — 编辑前后写时间戳，编辑窗口 < 30s"
        ;;
    *)
        echo "  - 未知归属 — 请先在 STATE.md 提案归属，等用户确认"
        ;;
esac
