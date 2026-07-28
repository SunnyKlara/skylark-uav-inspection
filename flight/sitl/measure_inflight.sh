#!/usr/bin/env bash
# 实测 PX4 经 uXRCE-DDS 出来的话题带宽 —— 这是 docs/SERIAL_BUDGET.md §2.5 数字的来源。
#
# 默认在「解锁 + 悬停」状态下测。为什么必须飞起来：静止未解锁时有一批话题一条不发
# （home_position 要解锁后才发、wind 要 EKF 估出风速、position_setpoint_triplet 随模式变），
# 拿静止数据当串口预算依据会失真 —— 而这个数字是要写进论文的。
#
# 用法：
#   bash measure_inflight.sh                 # 解锁起飞后测 25s（权威口径）
#   bash measure_inflight.sh --duration 40
#   bash measure_inflight.sh --no-takeoff    # 静止未解锁测（作对照用）
#
# 顺带演示一个能力：用 FIFO 给 pxh 控制台发命令。
# headless SITL 没有终端，真机可用 QGC 的 MAVLink Console，SITL 只能这么来。
# 有了它，`uxrce_dds_client status`、`uorb top`、`commander arm` 都能脚本化。
# make 会把 stdin 透传给 px4，所以用 FIFO 顶住 stdin 就能持续喂命令；
# 必须用 exec 开一个 fd 顶住写端，否则 px4 立刻读到 EOF 退出。

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)   # flight/sitl -> skylark

DURATION=25
TAKEOFF=1
OUT_JSON=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)   DURATION="${2:?}"; shift 2 ;;
    --no-takeoff) TAKEOFF=0; shift ;;
    --out)        OUT_JSON="${2:?}"; shift 2 ;;
    -h|--help)    sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

if [[ -z "$OUT_JSON" ]]; then
  if [[ "$TAKEOFF" == 1 ]]; then
    OUT_JSON="${REPO_ROOT}/flight/tools/measured_dds_sitl_inflight.json"
  else
    OUT_JSON="${REPO_ROOT}/flight/tools/measured_dds_sitl.json"
  fi
fi
LOGDIR="${MEASURE_OUT_DIR:-/tmp/skylark_measure}"
mkdir -p "$LOGDIR"
PX4_LOG="$LOGDIR/px4.log"; AGENT_LOG="$LOGDIR/agent.log"; REPORT="$LOGDIR/report.txt"
FIFO="$LOGDIR/px4_console_in"
: > "$REPORT"
log() { echo "$*" | tee -a "$REPORT"; }
# px4 会把 "pxh> " 提示符和逐字符回显写进 stdout，日志读起来全是噪声，统一过一遍
clean_log() { sed 's/pxh> //g' "$PX4_LOG" | grep -vE '^(commander|param|uxrce|uorb)[a-z_0-9 -]{0,40}$'; }

cleanup() {
  log ""; log "--- 清理 ---"
  if [[ -n "${CON_OPEN:-}" ]]; then
    echo "commander land" >&3 2>/dev/null || true
    sleep 3
    exec 3>&- 2>/dev/null || true
  fi
  [[ -n "${PX4_PID:-}"   ]] && kill -TERM "$PX4_PID"   2>/dev/null
  [[ -n "${AGENT_PID:-}" ]] && kill -TERM "$AGENT_PID" 2>/dev/null
  sleep 2
  pkill -f 'px4 ' 2>/dev/null; pkill -f MicroXRCEAgent 2>/dev/null
  pkill -f 'gz sim' 2>/dev/null; pkill -f 'ruby.*gz' 2>/dev/null
  rm -f "$FIFO"
  sleep 1; log "清理完成"
}
trap cleanup EXIT

# ROS 2 的 setup.bash 不是 set -u 安全的，source 前后必须关掉
set +u
[[ -f "$HOME/.skylark_env.sh" ]] && source "$HOME/.skylark_env.sh"
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
export PX4_DIR

log "=== DDS 带宽实测 $(date '+%F %T') ==="
log "PX4 源码树: ${PX4_DIR}  ref=$(git -C "$PX4_DIR" describe --tags --always 2>/dev/null)"
log "工况: $([[ "$TAKEOFF" == 1 ]] && echo '解锁悬停' || echo '静止未解锁（对照）')   采集 ${DURATION}s"
log "输出: ${OUT_JSON}"

pkill -f MicroXRCEAgent 2>/dev/null; pkill -f 'px4 ' 2>/dev/null
pkill -f 'gz sim' 2>/dev/null; sleep 2

MicroXRCEAgent udp4 -p 8888 > "$AGENT_LOG" 2>&1 & AGENT_PID=$!
sleep 3

rm -f "$FIFO"; mkfifo "$FIFO"
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$FIFO" ) > "$PX4_LOG" 2>&1 & PX4_PID=$!
exec 3>"$FIFO"
CON_OPEN=1

log "等待 PX4 就绪..."
for i in $(seq 1 180); do
  grep -qE 'uxrce_dds_client.*(synchronized|successfully created)' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "PX4 第 ${i}s 退出，日志末 10 行："; \
      clean_log | tail -10 | sed 's/^/         /' | tee -a "$REPORT"; exit 1; }
  sleep 1
done
log "PX4 就绪，等 12s 让 EKF2 收敛"
sleep 12

console() { log "  -> pxh: $1"; echo "$1" >&3; sleep "${2:-3}"; }

log ""
log "--- 验证 FIFO 控制台 ---"
before=$(wc -c < "$PX4_LOG")
console "commander status" 4
if [[ "$(wc -c < "$PX4_LOG")" -gt "$before" ]]; then
  log "  [OK] 控制台有响应"
else
  log "  [FAIL] 控制台无响应，FIFO 方案不成立"
  exit 1
fi

if [[ "$TAKEOFF" == 1 ]]; then
  log ""
  log "--- 解锁并起飞 ---"
  # 必须先关数传丢失失效保护：headless SITL 没有 QGC 连上来，NAV_DLL_ACT>0 会让
  # 解锁被拒（Preflight Fail: No connection to the GCS）。
  # 而且必须**验证**解锁与起飞的结果 —— 第一版只是发命令不看结果，
  # 结果拿静止数据当"飞行中"数据报了出来（两组总带宽几乎一样，本该立刻起疑）。
  console "param set NAV_DLL_ACT 0" 2
  console "commander arm" 5
  if clean_log | grep -q 'Arming denied'; then
    log "  [FAIL] 解锁被拒，健康检查未通过："
    clean_log | grep -E 'Arming denied|Preflight Fail' | tail -6 | sed 's/^/         /' | tee -a "$REPORT"
    log "  不继续 —— 静止数据不能当飞行数据用（要静止对照请加 --no-takeoff）"
    exit 1
  fi
  log "  [OK] 已解锁"
  console "commander takeoff" 15
  if clean_log | grep -q 'Takeoff detected'; then
    log "  [OK] 检测到起飞"
    clean_log | grep -E 'takeoff altitude|Takeoff detected' | tail -2 | sed 's/^/         /' | tee -a "$REPORT"
  else
    log "  [FAIL] 日志里没有 'Takeoff detected'，起飞未确认"
    clean_log | tail -8 | sed 's/^/         /' | tee -a "$REPORT"
    exit 1
  fi
  log "  等 8s 让悬停稳定"
  sleep 8
fi

log ""
log "--- 采集 ${DURATION}s ---"
python3 "${REPO_ROOT}/flight/tools/measure_dds_topics.py" \
  --duration "$DURATION" --out "$OUT_JSON" 2>&1 | tee -a "$REPORT"
rc=${PIPESTATUS[0]}

log ""
log "--- 飞控自报的 DDS 状态（独立于订阅端的第二个测量源）---"
console "uxrce_dds_client status" 4
clean_log | grep -E 'Payload tx|Payload rx|timesync converged|Running,' | tail -4 \
  | sed 's/^/       /' | tee -a "$REPORT"
log ""
log "  ↑ 口径：num_payload_sent 累加各话题 CDR 体大小，不含 XRCE 帧头。"
log "    应比订阅端实测值低约 4 B/条（rclpy serialize_message 多带 CDR 封装头）。"
log "    差得更多说明订阅端在丢包，此时飞控自报的数才可信。"

log ""
log "退出码 = ${rc}   报告: ${REPORT}"
exit "$rc"
