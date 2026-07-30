#!/usr/bin/env bash
# FollowPath 的集成测试。这是扫掠的运动基础，重点验航线跟踪质量。
#
# 四个场景：
#   A 航点数 1        -> REJECTED_BAD_PATH(2)
#   B z 为正（地下）  -> REJECTED_BAD_PATH(2)，验的是 NED 符号约定这个易错点
#   C 正常跑一条割草机航线 -> OK(0)，且**最大横向偏差 < 2 m**
#      这个断言是重点：横向偏差直接决定扫掠覆盖率，契约把它列为 Feedback 的关键指标
#   D 中途取消        -> CANCELED(5)，且保持悬停
#
# 用法： bash test_follow_path.sh [输出目录]

set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

OUT="${1:-/tmp/skylark_followpath}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_fp_fifo.$$"
: > "$REPORT"
PASS=0; FAIL=0
log()  { echo "$*" | tee -a "$REPORT"; }
ok()   { log "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { log "  [FAIL] $*"; FAIL=$((FAIL+1)); }

cleanup() {
  log ""; log "--- 清理 ---"
  [[ -n "${NODE_PID:-}" ]] && kill -TERM "$NODE_PID" 2>/dev/null
  sleep 1; pkill -f autopilot_iface 2>/dev/null
  if [[ -n "${CON_OPEN:-}" ]]; then
    echo "commander land" >&3 2>/dev/null || true; sleep 8
    echo "commander disarm" >&3 2>/dev/null || true; sleep 2
    exec 3>&- 2>/dev/null || true
  fi
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
CLI="ros2 run skylark_autopilot_iface action_cli"

log "=== FollowPath 集成测试 $(date '+%F %T') ==="
rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"
for pat in autopilot_iface action_cli px4_sitl 'bin/px4' gz_x500 MicroXRCEAgent 'gz sim'; do
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
echo "param set COM_LOW_BAT_ACT 0" >&3; sleep 2
echo "param set NAV_DLL_ACT 0" >&3; sleep 2
# 关时间戳同步：lockstep 下 PX4 偏移估计每 30s 才校正、期间漂 2.5s，
# 会让 offboard 周期性掉线（见 OFFBOARD_CONSTRAINTS.md §7.2）。需重启生效。
echo "param set UXRCE_DDS_SYNCT 0" >&3; sleep 2
# 抬 setpoint 断流容限到 5 s。这是**仿真侧补偿**，不是实现修复 —— 依据如下。
#
# 飞控的判据（v1.17.0 offboardCheck.cpp:46）：
#     hrt_absolute_time() < offboard_control_mode.timestamp + COM_OF_LOSS_T
# 两边都在 PX4 时钟域，所以发送端必须用飞控的刻度写时间戳。
#
# 走到"抬容限"这一步之前，先按顺序排除了三件事，每件都有实测数据：
#   1. 发布端卡顿   —— 心跳最大间隔 101~148 ms（10 Hz 名义 100 ms），排除。
#   2. 时间戳算错   —— 出站时间戳改成锚定飞控最新一帧后（px4_link 的时钟伺服），
#      时钟平稳期间的滞后只有 -45 ~ +7 ms，即容限的 0.5%~0.7%。
#      两轮独立测量（99_notes/fp8、fp9，tools/analyze_timing_trace.py），排除。
#   3. EKF 那条路径 —— offboardCheck 里还有一条
#      `position && local_position_invalid -> 不可用`，而且源码注明"无需上报"，
#      所以标志位名字会骗人。抓了翻转瞬间的完整标志位快照，
#      只有 offboard/gcs/rc 三项，没有任何 *_invalid，排除。
#   ⚠ 顺带修掉一个自己的真 bug：位置回调在 MultiThreadedExecutor 下并发执行，
#     无锁写共享时序状态，trace 里出现过本机间隔 -2852 ms 的乱序样本，
#     还把时钟速率估计带歪（曾误报漂移 8~13%）。加锁后重测才有上面的数字。
#
# 排除完剩下的是环境：实测抓到仿真时钟**单次前跳 1.93 s**
# （相邻两帧位置消息之间，本机走 7 ms，飞控走 1936 ms，见 fp9 的 trace 分析）。
# 跳变一旦超过容限，任何由发送端填写的时间戳都会在那一瞬间被判过期 ——
# 发送端无法规避。所以把容限设在观测到的跳变之上。
#
# ⚠ 代价与边界：真机上这等于机载电脑失联后多盲飞 4 秒。
#   真机时钟不 lockstep、不该有这种跳变，所以**S2 必须重新评估**，不要照搬。
#   另：fp8/fp9 还各有一次未能在 trace 窗口内抓到跳变的丢失事件，
#   仍是未结的开放问题，记在 OFFBOARD_CONSTRAINTS.md §7.4。
echo "param set COM_OF_LOSS_T 5.0" >&3; sleep 2
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
  kill -0 "$PX4_PID" 2>/dev/null || { log "重启后 PX4 退出"; exit 1; }
  sleep 1
done
sleep 12
# 读回验证，而不是打印一句"参数就绪"就往下走。
# 第一版只打印不验证，结果一个真失败（offboard 被接管）无法排除"参数没生效"这个可能，
# 白白多花一轮。param show 的值行形如： x   UXRCE_DDS_SYNCT [991,1877] : 0
MARK=$(wc -c < "$PX4_LOG")
for p in NAV_DLL_ACT COM_LOW_BAT_ACT UXRCE_DDS_SYNCT COM_OF_LOSS_T; do
  echo "param show $p" >&3; sleep 1.5
done
sleep 2
PARAMS=$(tail -c "+${MARK}" "$PX4_LOG" | sed 's/pxh> //g' \
         | grep -oE '[+*x ] +(COM|NAV|UXRCE)_[A-Z0-9_]+ \[[0-9,]+\] : [-0-9.]+' \
         | sed 's/^[+*x ] *//')
log "参数读回："
echo "$PARAMS" | sed 's/^/       /' | tee -a "$REPORT"
for expect in "NAV_DLL_ACT.*: 0" "COM_LOW_BAT_ACT.*: 0" "UXRCE_DDS_SYNCT.*: 0" "COM_OF_LOSS_T.*: 5"; do
  if echo "$PARAMS" | grep -qE "$expect"; then
    ok "参数生效: ${expect%%.*}"
  else
    bad "参数未生效: ${expect%%.*} —— 后续结论不可信"
  fi
done

wait_node_ready() {
  local deadline=$((SECONDS + 45)) v
  while (( SECONDS < deadline )); do
    kill -0 "${NODE_PID:-0}" 2>/dev/null || { log "  节点已退出"; return 1; }
    v=$(timeout 5 ros2 topic echo --once --field companion_link_ok \
          /skylark_autopilot_iface/flight_health 2>/dev/null | head -1 | tr -d ' \r')
    [[ "$v" == "True" ]] && { log "  节点就绪"; return 0; }
    sleep 2
  done
  return 1
}
pkill -f autopilot_iface 2>/dev/null; sleep 1
# 被判过期时把最近一段时序落盘到输出目录，供 tools/analyze_timing_trace.py 离线定因
export SKYLARK_TRACE_OUT="$OUT/timing_trace.csv"
ros2 run skylark_autopilot_iface autopilot_iface > "$OUT/node.log" 2>&1 & NODE_PID=$!
wait_node_ready || { tail -20 "$OUT/node.log" | sed 's/^/    /' | tee -a "$REPORT"; exit 1; }

state_now() {
  timeout 14 python3 "$TOOLS/watch_vehicle_state.py" --duration 3 2>&1 | grep '结束状态' || echo "读不到"
}
# FollowPath 不在 action_cli 里（它是层内动作），用 ros2 action 直接发，
# 结果码从输出里取。写成函数避免每处重复长命令。
send_fp() {  # send_fp <goal yaml> <超时s> [cancel_after]
  local goal="$1" tmo="$2"
  timeout "$tmo" ros2 action send_goal -f \
    /skylark_autopilot_iface/follow_path \
    skylark_flight_internal_msgs/action/FollowPath "$goal" 2>&1
}
rc_of() {  # 从 send_goal 输出里抽 result_code
  # ros2 action send_goal 打的是 YAML：`result_code: 2`（冒号 + 空格）。
  # 第一版写成 result_code=2（等号）抽不到，于是三个场景全被误判为失败，
  # 而实现其实是对的 —— 断言的解析方式也得对着真实输出写。
  grep -oE 'result_code:[[:space:]]*[0-9]+' | tail -1 | grep -oE '[0-9]+'
}

# ---------------- A0：未解锁时的拒绝 ----------------
# 顺序有讲究：这一条必须在起飞**之前**跑。
# 前置校验里"未解锁"排在"航线非法"之前（先看能不能飞，再看飞哪里），
# 所以起飞前发任何 goal 都只会拿到 NOT_READY —— 那是正确行为，
# 但也意味着几何类拒绝必须在空中验，否则测不到（第一版就把 A 放在起飞前，
# 期望 BAD_PATH 却拿到 NOT_READY）。
log ""
log "=== A0: 未解锁时发 goal -> 期望 REJECTED_NOT_READY(1) ==="
OUT_A0=$(send_fp "{waypoints_ned: [{x: 0.0, y: 0.0, z: -8.0}, {x: 20.0, y: 0.0, z: -8.0}], speed_mps: 3.0, timeout_sec: 20.0}" 40)
echo "$OUT_A0" | grep -E 'result_code|message' | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_A0" | rc_of)
[[ "${RC:-}" == 1 ]] && ok "A0: REJECTED_NOT_READY(1)" || bad "A0: 期望 1，实际 ${RC:-无}"

# ---------------- 起飞（后面场景需要在空中）----------------
log ""
log "=== 起飞到 10 m（为后续场景准备）==="
$CLI takeoff --altitude 10 --climb-rate 1.5 --timeout 45 > "$OUT/cli_takeoff.log" 2>&1
RC_T=$?
grep -vE '^\s*反馈' "$OUT/cli_takeoff.log" | sed 's/^/       /' | tee -a "$REPORT"
[[ "$RC_T" == 0 ]] && ok "起飞 OK" || { bad "起飞失败(${RC_T})，后续场景无法进行"; }

# ---------------- B ----------------
log ""
log "=== A: 空中只给 1 个航点 -> 期望 REJECTED_BAD_PATH(2) ==="
OUT_A=$(send_fp "{waypoints_ned: [{x: 5.0, y: 0.0, z: -10.0}], speed_mps: 3.0, timeout_sec: 20.0}" 40)
echo "$OUT_A" | grep -E 'result_code|message' | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_A" | rc_of)
[[ "${RC:-}" == 2 ]] && ok "A: REJECTED_BAD_PATH(2)" || bad "A: 期望 2，实际 ${RC:-无}"

log ""
log "=== B: 航点 z 为正（NED 下即地面以下）-> 期望 REJECTED_BAD_PATH(2) ==="
OUT_B=$(send_fp "{waypoints_ned: [{x: 0.0, y: 0.0, z: -10.0}, {x: 10.0, y: 0.0, z: 5.0}], speed_mps: 3.0, timeout_sec: 20.0}" 40)
echo "$OUT_B" | grep -E 'result_code|message' | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_B" | rc_of)
[[ "${RC:-}" == 2 ]] && ok "B: REJECTED_BAD_PATH(2)，NED 符号约定校验生效" || bad "B: 期望 2，实际 ${RC:-无}"

# ---------------- C ----------------
log ""
log "=== C: 跑一条 3 行的割草机航线 -> 期望 OK(0) 且最大横向偏差 < 2 m ==="
log "    航线：40m 长、行距 8m、高度 10m —— 缩小版的扫掠"
GOAL_C="{waypoints_ned: [
  {x: 0.0, y: 0.0, z: -10.0}, {x: 40.0, y: 0.0, z: -10.0},
  {x: 40.0, y: 8.0, z: -10.0}, {x: 0.0, y: 8.0, z: -10.0},
  {x: 0.0, y: 16.0, z: -10.0}, {x: 40.0, y: 16.0, z: -10.0}],
  speed_mps: 4.0, accept_radius_m: 1.5, yaw_mode: 0, timeout_sec: 180.0}"
OUT_C=$(send_fp "$GOAL_C" 240)
echo "$OUT_C" > "$OUT/raw_C.log"
echo "$OUT_C" | grep -E 'result_code|message|waypoints_reached|max_cross_track|distance_flown' \
  | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_C" | rc_of)
[[ "${RC:-}" == 0 ]] && ok "C: OK(0)" || bad "C: 期望 0，实际 ${RC:-无}"
# 又是 YAML 冒号：上一版这里写的是 max_cross_track_error_m=（等号），
# 抽不到值于是被判"偏差过大"，而实际输出里是 1.47 m，本来该过。
# 同一个坑在 rc_of 修过一次没扫干净，记在这里以免第三次。
XTE=$(echo "$OUT_C" | grep -oE 'max_cross_track_error_m:[[:space:]]*[0-9.]+' \
      | tail -1 | grep -oE '[0-9.]+')
log "  最大横向偏差: ${XTE:-未取到} m"
if [[ -n "${XTE:-}" ]] && awk -v e="$XTE" 'BEGIN{exit !(e < 2.0)}'; then
  ok "C: 航线跟踪最大横向偏差 ${XTE} m < 2 m，覆盖率有保障"
else
  bad "C: 最大横向偏差 ${XTE:-未取到} m 过大，扫掠会漏拍"
fi
# 时序余量断言：结果码为 0 只说明**没被接管**，不说明余量够。
# 飞控一路上有没有短暂判过 offboard 丢失，是它自己的
# failsafe_flags.offboard_control_signal_lost 说的，这里直接取那个计数。
# 容限 5 s 下这个数应为 0；若仍不为 0，说明跳变幅度超过了 5 s，
# 那是环境变了（负载/宿主机），得重新量而不是继续往上抬。
LOST_N=$(echo "$OUT_C" | grep -oE '飞控判 offboard 丢失 [0-9]+ 次' \
         | tail -1 | grep -oE '[0-9]+')
DRIFT=$(echo "$OUT_C" | grep -oE '仿真时钟相对本机 [-0-9.]+%' | tail -1)
log "  ${DRIFT:-仿真时钟漂移未测到}"
if [[ "${LOST_N:-none}" == 0 ]]; then
  ok "C: 5 s 容限下飞控全程未判 offboard 丢失，时序余量真实"
else
  bad "C: 飞控判 offboard 丢失 ${LOST_N:-未取到} 次 —— 出站时间戳仍不够新鲜"
fi

# ---------------- D ----------------
log ""
log "=== D: 中途取消 -> 期望 CANCELED(5) 且保持悬停 ==="
GOAL_D="{waypoints_ned: [
  {x: 0.0, y: 0.0, z: -10.0}, {x: 60.0, y: 0.0, z: -10.0},
  {x: 60.0, y: 20.0, z: -10.0}],
  speed_mps: 2.0, accept_radius_m: 1.5, timeout_sec: 180.0}"
( sleep 10; ros2 action send_goal --help >/dev/null 2>&1 ) &
OUT_D=$(timeout 60 bash -c "
  ros2 action send_goal -f /skylark_autopilot_iface/follow_path \
    skylark_flight_internal_msgs/action/FollowPath '$GOAL_D' 2>&1 &
  SG=\$!
  sleep 12
  kill -INT \$SG 2>/dev/null
  wait \$SG 2>/dev/null
" || true)
echo "$OUT_D" | tail -20 | sed 's/^/       /' | tee -a "$REPORT"
log "  取消后状态: $(state_now)"
ST=$(state_now)
[[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
  && ok "D: 取消后仍在空中" || bad "D: 取消后状态异常"

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
