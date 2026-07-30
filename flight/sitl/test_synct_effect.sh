#!/usr/bin/env bash
# 验证 UXRCE_DDS_SYNCT=0 能否消除 offboard 信号的自发丢失。
#
# 背景：lockstep SITL 下 uxrce_dds_client 的时钟偏移估计会周期性重置，
# 重置瞬间 session->time_offset 变成 0。此时一个 ROS 纪元的时间戳
# （1.785e18 us）被当作 PX4 时间解释，误差是几十年量级 ——
# **抬高 COM_OF_LOSS_T 完全无效**，这解释了为什么设了 3.0s 还是会被接管。
#
# UXRCE_DDS_SYNCT=0 关掉时间戳同步后，PX4 不再换算入站时间戳，
# 偏移估计出错也就伤不到 offboard。这是根治方向，且对真机同样适用。
# 注意该参数 reboot_required: true，必须设完重启 PX4 才生效。
#
# 做法：同一台机器上跑两轮，各 90s，只差 UXRCE_DDS_SYNCT，比较丢失次数。
#
# 用法： bash test_synct_effect.sh [输出目录]

set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

OUT="${1:-/tmp/skylark_synct}"
mkdir -p "$OUT"
REPORT="$OUT/report.txt"
: > "$REPORT"
log() { echo "$*" | tee -a "$REPORT"; }

set +u
[[ -f "$HOME/.skylark_env.sh" ]] && source "$HOME/.skylark_env.sh"
WS="${SKYLARK_WS:-$HOME/skylark_ws}"
[[ -f "$WS/install/setup.bash" ]] && source "$WS/install/setup.bash"
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
RF="$PX4_DIR/build/px4_sitl_default/rootfs"
OB_BIN="$WS/install/px4_ros_com/lib/px4_ros_com/offboard_control"

kill_all() {
  for pat in offboard_control px4_sitl 'bin/px4' gz_x500 MicroXRCEAgent 'gz sim' 'ruby.*gz'; do
    pkill -9 -f "$pat" 2>/dev/null
  done
  sleep 2
}
cleanup() { log ""; log "--- 清理 ---"; kill_all; rm -f /tmp/skylark_synct_fifo.*; log "清理完成"; }
trap cleanup EXIT

# 跑一轮：$1=SYNCT 值，$2=时长
run_round() {
  local synct="$1" dur="$2" tag="round_${1}"
  local fifo="/tmp/skylark_synct_fifo.$$_${synct}"
  local px4log="$OUT/${tag}_px4.log"

  log ""
  log "=== 一轮：UXRCE_DDS_SYNCT=${synct}，浸泡 ${dur}s ==="
  kill_all
  rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"

  MicroXRCEAgent udp4 -p 8888 > "$OUT/${tag}_agent.log" 2>&1 &
  local agent_pid=$!
  sleep 3
  rm -f "$fifo"; mkfifo "$fifo"
  ( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$fifo" ) > "$px4log" 2>&1 &
  local px4_pid=$!
  exec 4>"$fifo"

  for i in $(seq 1 180); do
    grep -qE 'uxrce_dds_client.*(synchronized|successfully created)' "$px4log" 2>/dev/null && break
    kill -0 "$px4_pid" 2>/dev/null || { log "  PX4 第 ${i}s 退出"; exec 4>&-; return 1; }
    sleep 1
  done
  sleep 10

  # 设参数。SYNCT 需要重启才生效，所以设完重启整个 PX4
  echo "param set UXRCE_DDS_SYNCT ${synct}" >&4; sleep 2
  echo "param save" >&4; sleep 2
  log "  已设 UXRCE_DDS_SYNCT=${synct} 并保存，重启 PX4 使其生效"
  exec 4>&-
  kill -TERM "$px4_pid" 2>/dev/null; sleep 3
  pkill -9 -f px4_sitl 2>/dev/null; pkill -9 -f 'bin/px4' 2>/dev/null
  pkill -9 -f gz_x500 2>/dev/null; pkill -9 -f 'gz sim' 2>/dev/null
  sleep 3

  # 重启（这次不清参数，让刚保存的 SYNCT 生效）
  rm -f "$fifo"; mkfifo "$fifo"
  ( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$fifo" ) >> "$px4log" 2>&1 &
  px4_pid=$!
  exec 4>"$fifo"
  for i in $(seq 1 180); do
    grep -qE 'uxrce_dds_client.*successfully created' "$px4log" 2>/dev/null && break
    kill -0 "$px4_pid" 2>/dev/null || { log "  重启后 PX4 第 ${i}s 退出"; exec 4>&-; return 1; }
    sleep 1
  done
  sleep 10
  echo "param show UXRCE_DDS_SYNCT" >&4; sleep 2
  local shown
  shown=$(sed 's/pxh> //g' "$px4log" | grep -oE '[+*x ] +UXRCE_DDS_SYNCT \[[0-9,]+\] : [0-9]+' | tail -1)
  log "  重启后确认参数: ${shown:-读不到}"
  echo "param set NAV_DLL_ACT 0" >&4; sleep 2
  echo "param set COM_LOW_BAT_ACT 0" >&4; sleep 2

  "$OB_BIN" > "$OUT/${tag}_offboard.log" 2>&1 &
  local ob_pid=$!
  python3 "$TOOLS/watch_offboard_signal.py" --duration "$dur" 2>&1 | tee -a "$REPORT"
  local rc=${PIPESTATUS[0]}

  if kill -0 "$ob_pid" 2>/dev/null; then
    log "  发布节点全程存活 -> 任何丢失都不是发布端停了"
  else
    log "  ⚠ 发布节点自己退了，本轮结论无效"
  fi

  echo "commander disarm force" >&4 2>/dev/null || true
  exec 4>&-
  kill -TERM "$ob_pid" 2>/dev/null
  kill -TERM "$px4_pid" 2>/dev/null; kill -TERM "$agent_pid" 2>/dev/null
  kill_all
  rm -f "$fifo"
  log "  本轮 watch_offboard_signal 退出码=${rc}（1 = 观察到自发丢失）"
  return "$rc"
}

log "=== UXRCE_DDS_SYNCT 对 offboard 信号稳定性的影响 $(date '+%F %T') ==="
DUR="${DUR:-90}"

run_round 1 "$DUR"; RC_ON=$?
run_round 0 "$DUR"; RC_OFF=$?

log ""
log "=== 对照结论 ==="
log "  SYNCT=1（默认，做时间戳换算）: $([[ "$RC_ON" == 1 ]] && echo '观察到自发丢失' || echo '未观察到丢失')"
log "  SYNCT=0（关闭换算）:           $([[ "$RC_OFF" == 1 ]] && echo '观察到自发丢失' || echo '未观察到丢失')"
if [[ "$RC_ON" == 1 && "$RC_OFF" == 0 ]]; then
  log "  => 关掉 SYNCT 消除了丢失。这是根治手段，比抬高 COM_OF_LOSS_T 有效"
elif [[ "$RC_ON" == 0 && "$RC_OFF" == 0 ]]; then
  log "  => 两轮都没复现。现象是间歇性的，本次对照不足以判定，需多轮或更长时间"
elif [[ "$RC_OFF" == 1 ]]; then
  log "  => 关掉 SYNCT 后仍有丢失，说明根因不只是时间戳换算，需另找"
fi
log ""
log "报告: ${REPORT}"
