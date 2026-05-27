#!/usr/bin/env bash
# sync.sh — 周日同步：检查所有 MODULE_STATE 与主 STATE 偏差
# 用法：bash .kiro/skills/skylark-coordination/scripts/sync.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Skylark Sync Report — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

# ── 1. 列出所有 MODULE_STATE ──
echo "─── 已发现的 MODULE_STATE 文件 ───"

declare -a MODULES=(
    "code/runs/MODULE_STATE_ML.md|Window-A|ML 主线"
    "paper/MODULE_STATE_PAPER.md|Window-B|论文 + 文档"
    "platform/backend/MODULE_STATE.md|Window-C|平台后端"
    "platform/frontend/MODULE_STATE.md|Window-D|平台前端"
    "edge/MODULE_STATE.md|Window-C|边缘部署"
    "simulation/MODULE_STATE.md|Window-D|仿真"
)

for entry in "${MODULES[@]}"; do
    IFS='|' read -r FILE WINDOW DESC <<< "$entry"
    if [ -f "$FILE" ]; then
        UPDATED=$(grep -m1 "上次更新" "$FILE" 2>/dev/null | head -c 80 || echo "(unknown)")
        echo "  ✅ $FILE  ($WINDOW — $DESC)"
        echo "      $UPDATED"
    else
        echo "  ⏳ $FILE  ($WINDOW — $DESC)  [not yet activated]"
    fi
done
echo ""

# ── 2. 检查主 STATE.md ──
echo "─── 主 STATE.md ───"
if [ -f "STATE.md" ]; then
    grep -m1 "最后更新" STATE.md 2>/dev/null | head -c 100 || echo "  (no timestamp)"
    echo ""
    SIZE=$(wc -l < STATE.md)
    echo "  Lines: $SIZE"
else
    echo "  ❌ 主 STATE.md 缺失！"
fi
echo ""

# ── 3. 检查偏差（简化版）──
echo "─── 潜在偏差检查 ───"

# 检查每个 MODULE_STATE 中的"已知事实"是否在主 STATE 出现
for entry in "${MODULES[@]}"; do
    IFS='|' read -r FILE WINDOW DESC <<< "$entry"
    [ ! -f "$FILE" ] && continue

    # 抽取 MODULE_STATE 第 5 节（已知事实）的关键数字
    awk '/^## 5\. 已知事实/,/^## /' "$FILE" 2>/dev/null \
        | grep -oE '[0-9]+\.[0-9]+' \
        | sort -u \
        | while read num; do
            if [ -n "$num" ] && ! grep -q "$num" STATE.md 2>/dev/null; then
                echo "  ⚠️  $FILE 提到的数字 $num 未在主 STATE.md 中出现"
            fi
        done
done
echo ""

# ── 4. Pending handoffs 数量 ──
echo "─── Pending Handoffs ───"
if [ -f "STATE.md" ]; then
    PENDING=$(awk '/^### 紧急 Handoffs/,/^### |^## /' STATE.md 2>/dev/null \
              | grep -c "^- \[" 2>/dev/null || echo "0")
    THIS_WEEK=$(awk '/^### 本周 Handoffs/,/^### |^## /' STATE.md 2>/dev/null \
                | grep -c "^- \[" 2>/dev/null || echo "0")
    echo "  紧急: $PENDING"
    echo "  本周: $THIS_WEEK"
fi
echo ""

# ── 5. GPU 利用率（基于 lock history）──
echo "─── GPU 利用率（最近 7 天）───"
LOCK_FILE="code/runs/.gpu_lock.json"
if [ -f "$LOCK_FILE" ] && command -v jq >/dev/null 2>&1; then
    HIST_COUNT=$(jq '.history | length' "$LOCK_FILE" 2>/dev/null || echo "0")
    if [ "$HIST_COUNT" -gt 0 ]; then
        TOTAL_HOURS=$(jq '[.history[].duration_hours // 0] | add' "$LOCK_FILE" 2>/dev/null || echo "0")
        echo "  历史 claim 次数: $HIST_COUNT"
        echo "  累计 GPU 小时:    $TOTAL_HOURS"
    else
        echo "  (no history yet)"
    fi
else
    echo "  (lock file 或 jq 不可用)"
fi
echo ""

# ── 6. 输出建议 ──
echo "─── 建议合并到主 STATE ───"
echo "  1. 检查上面 ⚠️ 标记的数字偏差"
echo "  2. 把每个 MODULE_STATE 第 2 节（当前进度）的最新一行汇总到主 STATE §6"
echo "  3. 如果 pending handoffs > 5，考虑清理已完成的归档到 docs/handoff_archive/"
echo "  4. 更新主 STATE 顶部的"最后更新"时间戳"
echo ""

echo "============================================================"
echo "  End of Sync Report"
echo "============================================================"
