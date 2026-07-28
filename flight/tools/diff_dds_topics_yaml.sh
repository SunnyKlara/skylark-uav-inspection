#!/usr/bin/env bash
# 比对两棵 PX4 源码树的 dds_topics.yaml。
#
# 存在的理由：docs/SERIAL_BUDGET.md 的 headline 数字曾经用错了源 —— 读的是
# Windows 侧那棵 PX4 **main 分支浅克隆**，而项目锁定的是 v1.17.0。
# 两份 yaml 有 9 处差异，其中 vehicle_odometry / vehicle_attitude 的 rate_limit
# 有无直接决定带宽结论。这个脚本把这类差异一次性摊出来。
#
# 教训一般化：估算工具的输入必须与「正在跑的那个二进制」出自同一棵源码树。
#
# 用法：
#   bash diff_dds_topics_yaml.sh                       # 用默认的两个路径
#   bash diff_dds_topics_yaml.sh <yamlA> <yamlB>

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
REL_YAML=src/modules/uxrce_dds_client/dds_topics.yaml

# 默认 A：仓库同级的 Windows 侧 checkout（历史上算错数字用的那棵）
# 默认 B：WSL 里锁定版本的 checkout（权威）
A="${1:-${REPO_ROOT}/../01_px4_core/PX4-Autopilot/${REL_YAML}}"
B="${2:-${PX4_DIR:-$HOME/PX4-Autopilot}/${REL_YAML}}"

for f in "$A" "$B"; do
  [[ -f "$f" ]] || { echo "找不到: $f"; exit 1; }
done

# 从 Windows 路径读的文件可能是 CRLF，摊平前统一行尾
TA=$(mktemp); TB=$(mktemp)
sed 's/\r$//' "$A" > "$TA"; sed 's/\r$//' "$B" > "$TB"
trap 'rm -f "$TA" "$TB" /tmp/flat_a.$$ /tmp/flat_b.$$' EXIT

ref_of() { git -C "$(dirname "$1")/../../.." describe --tags --always 2>/dev/null || echo '未知'; }

echo "=== 被比对的两棵树 ==="
printf '  A: %s\n     ref=%s\n' "$A" "$(ref_of "$A")"
printf '  B: %s\n     ref=%s\n' "$B" "$(ref_of "$B")"

count() {
  printf '%s %s' \
    "$(grep -c '^[[:space:]]*-[[:space:]]*topic:' "$1")" \
    "$(grep -c 'rate_limit:' "$1")"
}
echo ""
echo "=== 规模 ==="
printf '  A: 话题 %s 条, rate_limit %s 条\n' $(count "$TA")
printf '  B: 话题 %s 条, rate_limit %s 条\n' $(count "$TB")

# 摊平成 "话题<TAB>rate_limit"。注释行要跳过，否则被注释掉的话题会污染归属
flatten() {
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*-[[:space:]]*topic:/ {
      if (cur != "") print cur "\t" (lim == "" ? "无上限" : lim)
      cur = $0; sub(/.*topic:[[:space:]]*/, "", cur); lim = ""
      next
    }
    /rate_limit:/ { lim = $2; sub(/\.$/, "", lim) }
    END { if (cur != "") print cur "\t" (lim == "" ? "无上限" : lim) }
  ' "$1" | sort
}
flatten "$TA" > "/tmp/flat_a.$$"
flatten "$TB" > "/tmp/flat_b.$$"

echo ""
echo "=== 逐话题差异 ==="
join -t$'\t' -a1 -a2 -e '(不存在)' -o 0,1.2,2.2 "/tmp/flat_a.$$" "/tmp/flat_b.$$" \
  | awk -F'\t' 'BEGIN{ printf "  %-46s %-12s %-12s\n", "话题", "A", "B" }
                $2 != $3 { printf "  %-46s %-12s %-12s  <== 不同\n", $1, $2, $3; n++ }
                END { printf "\n  共 %d 处差异\n", n+0 }'
