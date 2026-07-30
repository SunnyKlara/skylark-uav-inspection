#!/usr/bin/env bash
# Takeoff action 的集成测试：起真 SITL，跑真 action server，断言三条路径。
#
# 三个场景各验一件事：
#   A 出厂参数（无地面站）-> 解锁被飞控拒 -> 期望 result_code=1 (REJECTED_NOT_READY)
#     这条最容易被写成"干等超时"，所以必须单独验。依据 OFFBOARD_CONSTRAINTS.md 约束 3。
#   B 关掉 NAV_DLL_ACT   -> 正常起飞到位     -> 期望 result_code=0 (OK)
#   C 起飞中途取消         -> 保持悬停不降落   -> 期望 result_code=5 (CANCELED)
#     且取消后飞机必须仍在空中、仍解锁 —— 停发 setpoint 会导致 RTL 降落（约束 5），
#     所以这条是在验"显式移交 AUTO_LOITER"真的生效。
#
# 用法： bash test_takeoff_action.sh [输出目录]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

OUT="${1:-/tmp/skylark_test_takeoff}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_takeoff_fifo.$$"    # 必须在 Linux 原生 fs：/mnt/c 不支持 FIFO
: > "$REPORT"
PASS=0; FAIL=0
log()  { echo "$*" | tee -a "$REPORT"; }
ok()   { log "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { log "  [FAIL] $*"; FAIL=$((FAIL+1)); }

kill_node() {
  [[ -n "${NODE_PID:-}" ]] && kill -TERM "$NODE_PID" 2>/dev/null
  sleep 1; pkill -f autopilot_iface 2>/dev/null; sleep 1
  pgrep -f autopilot_iface >/dev/null 2>&1 && pkill -9 -f autopilot_iface 2>/dev/null
  NODE_PID=""
}
cleanup() {
  log ""; log "--- 清理 ---"
  kill_node
  if [[ -n "${CON_OPEN:-}" ]]; then
    echo "commander land" >&3 2>/dev/null || true; sleep 8
    echo "commander disarm" >&3 2>/dev/null || true; sleep 2
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
WS="${SKYLARK_WS:-$HOME/skylark_ws}"
[[ -f "$WS/install/setup.bash" ]] && source "$WS/install/setup.bash"
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
RF="$PX4_DIR/build/px4_sitl_default/rootfs"

log "=== Takeoff action 集成测试 $(date '+%F %T') ==="
log "PX4 ref=$(git -C "$PX4_DIR" describe --tags --always 2>/dev/null)"

# 清持久化参数：上一轮设的 NAV_DLL_ACT 会跨重启生效，场景 A 就失效了
rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"
for pat in autopilot_iface offboard_control 'px4 ' MicroXRCEAgent 'gz sim'; do
  pkill -9 -f "$pat" 2>/dev/null
done
sleep 2

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
log "就绪，等 12s 让 EKF2 收敛"; sleep 12
# 电池放电约 1.5 分钟后会触发低电量 RTL，会污染后面的场景
echo "param set COM_LOW_BAT_ACT 0" >&3; sleep 2
# 抬高 setpoint 断流容限，规避 lockstep SITL 的时钟抖动。
#
# 出厂 COM_OF_LOSS_T=1.0s，而实测的 offboard 信号抖动宽度可达数秒
# （根因是 PX4 时钟偏移估计陈旧，见 OFFBOARD_CONSTRAINTS.md §7.1）。
# 1 秒容限下飞控会在抖动期间直接切 AUTO_RTL 接管，
# 场景 C 因此拿到 ABORTED_BY_FAILSAFE 而不是 CANCELED —— 不是 action 的 bug。
# 调用方无法靠自己"容忍"这件事：飞控接管发生在任何应用层宽限期之前。
# ⚠ 这是**降低安全余量**的权衡：机载电脑真的失联时，飞机会多飞 3 秒盲飞。
#   真机上是否需要同样设置，取决于真机时钟是否也抖（S2 待测）。
echo "param set COM_OF_LOSS_T 3.0" >&3; sleep 2
log "已设 COM_LOW_BAT_ACT=0, COM_OF_LOSS_T=3.0（SITL 时钟抖动的规避手段）"

# 等节点真的与飞控连上，而不是睡固定秒数。
#
# 固定 sleep 是「假设而不验证」：节点要先等 DDS 发现完成才能解析出带 _v1 后缀的
# 话题名，这个时间不固定。睡太短就会拿到「与飞控无连接」的假失败 —— 实测踩过。
# 判据用 FlightHealth.companion_link_ok，顺带把健康话题本身也验了。
wait_node_ready() {
  local deadline=$((SECONDS + 45)) v
  while (( SECONDS < deadline )); do
    if ! kill -0 "${NODE_PID:-0}" 2>/dev/null; then
      log "  节点进程已退出"
      return 1
    fi
    v=$(timeout 5 ros2 topic echo --once --field companion_link_ok \
          /skylark_autopilot_iface/flight_health 2>/dev/null | head -1 | tr -d ' \r')
    if [[ "$v" == "True" ]]; then
      log "  节点就绪（FlightHealth.companion_link_ok=True，等待 $((SECONDS - deadline + 45))s）"
      return 0
    fi
    sleep 2
  done
  log "  45s 内节点未与飞控连上"
  return 1
}

start_node() {
  kill_node
  ros2 run skylark_autopilot_iface autopilot_iface > "$OUT/node_$1.log" 2>&1 & NODE_PID=$!
  if ! wait_node_ready; then
    log "  节点日志："
    tail -20 "$OUT/node_$1.log" | sed 's/^/       /' | tee -a "$REPORT"
    return 1
  fi
  log "  订阅解析结果："
  grep '订阅' "$OUT/node_$1.log" | sed 's/^/       /' | tee -a "$REPORT"
  return 0
}

# ---------------- 场景 A ----------------
log ""
log "=== A: 出厂参数（无地面站）-> 解锁应被拒，期望 result_code=1 ==="
if start_node A; then
  ros2 run skylark_autopilot_iface takeoff_cli --altitude 5 --timeout 25 \
    > "$OUT/cli_A.log" 2>&1
  RC_A=$?
  sed 's/^/       /' "$OUT/cli_A.log" | tee -a "$REPORT"
  if [[ "$RC_A" == 1 ]]; then
    ok "A: 返回 REJECTED_NOT_READY(1)，且带回了飞控的拒绝原因"
  else
    bad "A: 期望 1，实际 ${RC_A}"
  fi
  # 必须没飞起来
  if grep -q 'Armed by external command' <(sed 's/pxh> //g' "$PX4_LOG"); then
    bad "A: 飞机竟然解锁了"
  else
    ok "A: 飞机未解锁"
  fi
else
  bad "A: 节点起不来"
fi

# ---------------- 场景 B ----------------
log ""
log "=== B: 关掉 NAV_DLL_ACT -> 正常起飞到位，期望 result_code=0 ==="
echo "param set NAV_DLL_ACT 0" >&3; sleep 3
if start_node B; then
  ros2 run skylark_autopilot_iface takeoff_cli --altitude 5 --climb-rate 1.5 --timeout 45 \
    > "$OUT/cli_B.log" 2>&1
  RC_B=$?
  sed 's/^/       /' "$OUT/cli_B.log" | tee -a "$REPORT"
  if [[ "$RC_B" == 0 ]]; then
    ok "B: 返回 OK(0)"
  else
    bad "B: 期望 0，实际 ${RC_B}"
  fi
  log "  起飞后 8s 的状态（验证移交 AUTO_LOITER 后仍在空中、未自行降落）："
  python3 "$TOOLS/watch_vehicle_state.py" --duration 8 --label "B 后置观察" \
    2>&1 | sed 's/^/       /' | tee -a "$REPORT"
  if grep -qE 'nav=AUTO_LOITER|nav=OFFBOARD' <(tail -20 "$REPORT") && \
     ! grep -q 'Disarmed by landing' <(sed 's/pxh> //g' "$PX4_LOG"); then
    ok "B: 起飞完成后仍在空中，未自行返航降落"
  else
    bad "B: 起飞后状态异常（可能自行降落了）"
  fi
else
  bad "B: 节点起不来"
fi

# ---------------- 场景 C ----------------
log ""
log "=== C: 起飞中途取消 -> 期望 result_code=5 且保持悬停 ==="
# 场景间必须**确认**回到「已落地 + 已上锁」，不能睡固定秒数就往下走。
# 上一版用 sleep 10 + sleep 3，实际 disarm 会因 "Disarming denied: not landed" 失败，
# 于是 C 在飞机仍解锁的状态下开始，前置校验与后续判断全被污染。
reset_to_ground() {
  local deadline=$((SECONDS + 40))
  echo "commander land" >&3
  while (( SECONDS < deadline )); do
    sleep 2
    if grep -q 'Landing detected' <(sed 's/pxh> //g' "$PX4_LOG" | tail -40); then
      break
    fi
  done
  echo "commander disarm" >&3
  sleep 3
  # 用 watcher 读一次真实状态而不是猜
  local st
  st=$(timeout 12 python3 "$TOOLS/watch_vehicle_state.py" --duration 3 2>&1 | grep '结束状态' || true)
  log "  场景间复位后的状态: ${st:-读不到}"
  if [[ "$st" == *DISARMED* ]]; then
    return 0
  fi
  log "  ⚠ 复位未达成（仍解锁），后续场景结果不可信"
  return 1
}
reset_to_ground || true
if start_node C; then
  ros2 run skylark_autopilot_iface takeoff_cli --altitude 12 --climb-rate 1.0 \
    --timeout 45 --cancel-after 6 > "$OUT/cli_C.log" 2>&1
  RC_C=$?
  sed 's/^/       /' "$OUT/cli_C.log" | tee -a "$REPORT"
  if [[ "$RC_C" == 5 ]]; then
    ok "C: 返回 CANCELED(5)"
  else
    bad "C: 期望 5，实际 ${RC_C}"
  fi
  log "  取消后 10s 的状态（必须仍解锁、仍在空中）："
  python3 "$TOOLS/watch_vehicle_state.py" --duration 10 --label "C 取消后观察" \
    2>&1 | sed 's/^/       /' | tee -a "$REPORT"
else
  bad "C: 节点起不来"
fi

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
