#!/usr/bin/env bash
# 验证 VehicleState 的发布与**时间戳口径**。
#
# 重点是时间戳。契约要求 header.stamp 是"飞控采样时刻"，
# 而我们为根治 offboard 自发掉线关掉了 UXRCE_DDS_SYNCT，
# PX4 出站时间戳因此变成开机计时 —— 直接填进 header 会得到 1970 年附近的值。
# iface 自己用最小值滤波维护偏移做换算，本脚本验证换算真的对：
#   stamp 与墙钟的差应在百毫秒量级（传输 + 聚合延迟），
#   而不是几十年（换算漏了）或负几秒（偏移估计偏了）。
#
# 用法： bash test_vehicle_state.sh [输出目录]

set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

OUT="${1:-/tmp/skylark_vstate}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_vs_fifo.$$"
: > "$REPORT"
PASS=0; FAIL=0
log()  { echo "$*" | tee -a "$REPORT"; }
ok()   { log "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { log "  [FAIL] $*"; FAIL=$((FAIL+1)); }

cleanup() {
  log ""; log "--- 清理 ---"
  [[ -n "${NODE_PID:-}" ]] && kill -TERM "$NODE_PID" 2>/dev/null
  sleep 1; pkill -f autopilot_iface 2>/dev/null
  [[ -n "${CON_OPEN:-}" ]] && { exec 3>&- 2>/dev/null || true; }
  [[ -n "${PX4_PID:-}"   ]] && kill -TERM "$PX4_PID"   2>/dev/null
  [[ -n "${AGENT_PID:-}" ]] && kill -TERM "$AGENT_PID" 2>/dev/null
  sleep 2
  pkill -f px4_sitl 2>/dev/null; pkill -f 'bin/px4' 2>/dev/null
  pkill -f gz_x500 2>/dev/null; pkill -f MicroXRCEAgent 2>/dev/null
  pkill -f 'gz sim' 2>/dev/null; pkill -f 'ruby.*gz' 2>/dev/null
  rm -f "$FIFO"; sleep 1; log "清理完成"
}
trap cleanup EXIT

set +u
[[ -f "$HOME/.skylark_env.sh" ]] && source "$HOME/.skylark_env.sh"
source /opt/ros/humble/setup.bash 2>/dev/null
WS="${SKYLARK_WS:-$HOME/skylark_ws}"
[[ -f "$WS/install/setup.bash" ]] && source "$WS/install/setup.bash"
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
RF="$PX4_DIR/build/px4_sitl_default/rootfs"

log "=== VehicleState 验证 $(date '+%F %T') ==="
rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"
for pat in autopilot_iface px4_sitl 'bin/px4' gz_x500 MicroXRCEAgent 'gz sim'; do
  pkill -9 -f "$pat" 2>/dev/null
done
sleep 2

MicroXRCEAgent udp4 -p 8888 > "$OUT/agent.log" 2>&1 & AGENT_PID=$!
sleep 3
mkfifo "$FIFO"
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$FIFO" ) > "$PX4_LOG" 2>&1 & PX4_PID=$!
exec 3>"$FIFO"; CON_OPEN=1
for i in $(seq 1 200); do
  grep -qE 'uxrce_dds_client.*successfully created' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "PX4 第 ${i}s 退出"; exit 1; }
  sleep 1
done
sleep 12

# 两种口径各测一遍：SYNCT=1（出厂）与 SYNCT=0（我们的 SITL 设置）。
# 换算逻辑必须在两种口径下都给出合理的 stamp，否则就是只在一种配置下碰对了。
run_case() {
  local synct="$1"
  log ""
  log "=== 口径 UXRCE_DDS_SYNCT=${synct} ==="
  echo "param set UXRCE_DDS_SYNCT ${synct}" >&3; sleep 2
  echo "param save" >&3; sleep 2
  exec 3>&-
  kill -TERM "$PX4_PID" 2>/dev/null; sleep 3
  pkill -9 -f px4_sitl 2>/dev/null; pkill -9 -f 'bin/px4' 2>/dev/null
  pkill -9 -f gz_x500 2>/dev/null; pkill -9 -f 'gz sim' 2>/dev/null; sleep 3
  rm -f "$FIFO"; mkfifo "$FIFO"
  ( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$FIFO" ) >> "$PX4_LOG" 2>&1 & PX4_PID=$!
  exec 3>"$FIFO"
  for i in $(seq 1 200); do
    grep -qE 'uxrce_dds_client.*successfully created' "$PX4_LOG" 2>/dev/null && break
    kill -0 "$PX4_PID" 2>/dev/null || { log "  重启后 PX4 退出"; return 1; }
    sleep 1
  done
  sleep 12

  pkill -f autopilot_iface 2>/dev/null; sleep 1
  ros2 run skylark_autopilot_iface autopilot_iface > "$OUT/node_${synct}.log" 2>&1 & NODE_PID=$!
  sleep 12

  local hz
  hz=$(timeout 20 ros2 topic hz --window 40 /skylark_autopilot_iface/vehicle_state 2>/dev/null \
       | grep 'average rate' | tail -1 || true)
  log "  发布频率: ${hz:-无输出}"
  local fps
  fps=$(echo "$hz" | grep -oE '[0-9]+\.[0-9]+' | head -1)
  if [[ -n "${fps:-}" ]] && awk -v f="$fps" 'BEGIN{exit !(f > 7 && f < 13)}'; then
    ok "SYNCT=${synct}: 频率 ${fps} Hz 在 10 Hz 附近"
  else
    bad "SYNCT=${synct}: 频率 ${fps:-无} 不在 7~13 Hz"
  fi

  # 时间戳口径检查：用 python 取一帧，和本机墙钟比
  local delta
  delta=$(timeout 25 python3 - <<'PY' 2>/dev/null
import time, rclpy
from rclpy.node import Node
from skylark_flight_msgs.msg import VehicleState
rclpy.init()
n = Node("vs_probe")
got = {}
def cb(m):
    if "d" not in got:
        stamp = m.header.stamp.sec + m.header.stamp.nanosec / 1e9
        got["d"] = time.time() - stamp
        got["lat"] = m.latitude_deg
        got["agl"] = m.altitude_agl_m
        got["src"] = m.agl_source
        got["valid"] = m.position_valid
n.create_subscription(VehicleState, "/skylark_autopilot_iface/vehicle_state", cb, 10)
t0 = time.time()
while "d" not in got and time.time() - t0 < 15:
    rclpy.spin_once(n, timeout_sec=0.2)
if "d" in got:
    print(f"{got['d']:.3f} {got['lat']:.6f} {got['agl']:.2f} {got['src']} {got['valid']}")
rclpy.shutdown()
PY
)
  log "  一帧样本 [stamp 落后墙钟(s) 纬度 AGL agl_source position_valid]: ${delta:-取不到}"
  local dt
  dt=$(echo "${delta:-}" | awk '{print $1}')
  if [[ -n "${dt:-}" ]] && awk -v d="$dt" 'BEGIN{exit !(d > -1.0 && d < 1.0)}'; then
    ok "SYNCT=${synct}: stamp 与墙钟差 ${dt}s 在 ±1s 内，时钟域换算正确"
  else
    bad "SYNCT=${synct}: stamp 与墙钟差 ${dt:-未知}s 不合理（换算漏了或偏移估计偏了）"
  fi
  kill -TERM "$NODE_PID" 2>/dev/null; pkill -f autopilot_iface 2>/dev/null; NODE_PID=""
  return 0
}

run_case 0 || true
run_case 1 || true

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
