#!/usr/bin/env bash
# 起 SITL + 官方 offboard 示例，浸泡观察 offboard 信号是否自发丢失。
# 这是 docs/OFFBOARD_CONSTRAINTS.md §7.1 的数据来源。
#
# 结论：会自发丢失（90 s 内 2 次），根因是 PX4 侧时钟偏移估计陈旧，
# 与发布端无关。因此 offboard 类 action 必须按时间做去抖。
#
# 用法： bash soak_offboard.sh [时长秒] [输出目录]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

DURATION="${1:-90}"
OUT="${2:-/tmp/skylark_soak}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
# FIFO 必须在 Linux 原生 fs 上：/mnt/c 是 DrvFs，不支持 FIFO，
# mkfifo 会静默无效导致 px4 的 stdin 是坏的、启动 1 秒就退（踩过）
FIFO="/tmp/skylark_soak_fifo.$$"
: > "$REPORT"
log() { echo "$*" | tee -a "$REPORT"; }

kill_ob() {
  [[ -n "${OB_PID:-}" ]] && kill -TERM "$OB_PID" 2>/dev/null
  sleep 1; pkill -f offboard_control 2>/dev/null; sleep 1
  pgrep -f offboard_control >/dev/null 2>&1 && pkill -9 -f offboard_control 2>/dev/null
  OB_PID=""
}
cleanup() {
  log ""; log "--- 清理 ---"
  kill_ob
  if [[ -n "${CON_OPEN:-}" ]]; then
    echo "commander land" >&3 2>/dev/null || true; sleep 6
    exec 3>&- 2>/dev/null || true
  fi
  [[ -n "${PX4_PID:-}"   ]] && kill -TERM "$PX4_PID"   2>/dev/null
  [[ -n "${AGENT_PID:-}" ]] && kill -TERM "$AGENT_PID" 2>/dev/null
  sleep 2
  pkill -f px4_sitl 2>/dev/null; pkill -f 'bin/px4' 2>/dev/null; pkill -f gz_x500 2>/dev/null; pkill -f MicroXRCEAgent 2>/dev/null
  pkill -f 'gz sim' 2>/dev/null; pkill -f 'ruby.*gz' 2>/dev/null
  rm -f "$FIFO"; sleep 1; log "清理完成"
}
trap cleanup EXIT

set +u
[[ -f "$HOME/.skylark_env.sh" ]] && source "$HOME/.skylark_env.sh"
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
WS="${SKYLARK_WS:-$HOME/skylark_ws}"
RF="$PX4_DIR/build/px4_sitl_default/rootfs"
OB_BIN="$WS/install/px4_ros_com/lib/px4_ros_com/offboard_control"
[[ -x "$OB_BIN" ]] || { echo "找不到 offboard_control: $OB_BIN"; exit 1; }

log "=== offboard 浸泡测试 $(date '+%F %T') ==="
log "时长 ${DURATION}s   输出 ${OUT}"

# 清持久化参数：上一轮改的参数会跨重启生效，不清则结论不可复现
rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"
pkill -f offboard_control 2>/dev/null; pkill -f MicroXRCEAgent 2>/dev/null
pkill -f px4_sitl 2>/dev/null; pkill -f 'bin/px4' 2>/dev/null; pkill -f gz_x500 2>/dev/null; pkill -f 'gz sim' 2>/dev/null; sleep 2

MicroXRCEAgent udp4 -p 8888 > "$OUT/agent.log" 2>&1 & AGENT_PID=$!
sleep 3
mkfifo "$FIFO"
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$FIFO" ) > "$PX4_LOG" 2>&1 & PX4_PID=$!
exec 3>"$FIFO"; CON_OPEN=1

log "等待 PX4 就绪..."
for i in $(seq 1 180); do
  grep -qE 'uxrce_dds_client.*(synchronized|successfully created)' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "PX4 第 ${i}s 退出"; exit 1; }
  sleep 1
done
sleep 12
# 关掉两个会干扰长测试的失效保护：数传丢失会挡解锁，电池放电约 1.5 分钟后触发 RTL
echo "param set NAV_DLL_ACT 0" >&3; sleep 2
echo "param set COM_LOW_BAT_ACT 0" >&3; sleep 2
log "已关 NAV_DLL_ACT 与 COM_LOW_BAT_ACT"

log ""
log "--- 启动官方示例并浸泡 ${DURATION}s ---"
"$OB_BIN" > "$OUT/offboard.log" 2>&1 & OB_PID=$!
python3 "$TOOLS/watch_offboard_signal.py" --duration "$DURATION" 2>&1 | tee -a "$REPORT"
RC=${PIPESTATUS[0]}

log ""
log "--- 发布节点是否仍存活（决定丢失能否归因于发布端）---"
if kill -0 "$OB_PID" 2>/dev/null; then
  log "  存活（PID ${OB_PID}）-> 任何丢失都不是发布端停了"
else
  log "  已退出！丢失的原因就是它自己挂了，日志："
  tail -5 "$OUT/offboard.log" | sed 's/^/       /' | tee -a "$REPORT"
fi

log ""
log "watch_offboard_signal 退出码=${RC}（1 = 观察到自发丢失）"
log "报告: ${REPORT}"
