#!/usr/bin/env bash
# InspectSweep 的集成测试：skylark_inspection_mode -> FollowPath -> PX4。
#
# 这是第一条**跨两个包**的端到端测试：任务语义在 inspection_mode，
# 运动在 autopilot_iface，两个节点都要起。
#
# 场景与各自要验的东西：
#   A0 未起飞          -> REJECTED_NOT_READY(1)，理由要指名 ready_for_offboard
#   A  行距 40 m       -> REJECTED_COVERAGE(3)，且消息要给出可操作的建议行距
#      这条是契约点名的硬要求（"而不是默默地漏拍"），必须单独验
#   B  区域排不下两行  -> REJECTED_BAD_GEOMETRY(2)，且不能与覆盖率码混淆
#   C  正常扫掠        -> OK(0)，rows_completed == rows_total，横向偏差 < 2 m
#   D  断点续飞        -> OK(0)，只飞剩下的行（验 resume_from_row 闭合关系）
#   E  中途取消        -> CANCELED(7)，且仍在空中
#   F  **挑衅**：把低电量阈值抬到 0.99 -> 必须立刻 ABORTED_LOW_BATTERY(6)
#      加它的理由同场景 H：A~E 验的都是"该做到的做到了"，
#      而低电量主动中止是条"该拦下"的路径，不主动制造就永远验不到。
#
# 用法： bash test_inspect_sweep.sh [输出目录]

set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"
source "${SCRIPT_DIR}/sitl_params.sh"

OUT="${1:-/tmp/skylark_inspect_sweep}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_isweep_fifo.$$"
: > "$REPORT"
PASS=0; FAIL=0
log()  { echo "$*" | tee -a "$REPORT"; }
ok()   { log "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { log "  [FAIL] $*"; FAIL=$((FAIL+1)); }

cleanup() {
  log ""; log "--- 清理 ---"
  pkill -f inspection_mode 2>/dev/null
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
  pkill -9 -f px4_sitl 2>/dev/null; pkill -9 -f 'bin/px4' 2>/dev/null
  pkill -9 -f gz_x500 2>/dev/null; pkill -9 -f MicroXRCEAgent 2>/dev/null
  pkill -9 -f 'gz sim' 2>/dev/null; pkill -9 -f 'ruby.*gz' 2>/dev/null
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
SWEEP="ros2 run skylark_inspection_mode sweep_cli"

log "=== InspectSweep 集成测试 $(date '+%F %T') ==="
log "PX4 ref=$(git -C "$PX4_DIR" describe --tags --always 2>/dev/null)"

# ---------------- 区域角点：由 home 加偏移算出，不写死 ----------------
# 用仓库自己的 geometry 模块换算，顺带证明它在测试环境里可导入。
# PX4 SITL 默认 home（Zurich Irchel Park）就是 EKF 的经纬度参考点，
# 而 inspection_mode 是从 VehicleState 反解参考点的 —— 两者必须一致，
# 所以这里也用同一个 home。
read -r A_LAT A_LON B_LAT B_LON < <(python3 - <<'PY'
from skylark_inspection_mode.geometry import ned_to_latlon
HOME = (47.397742, 8.545594)
# 区域：行方向（北）40 m x 横向（东）24 m -> 行距 6 m 下 5 行
a = ned_to_latlon(0.0, 0.0, *HOME)
b = ned_to_latlon(40.0, 24.0, *HOME)
print(f"{a[0]:.9f} {a[1]:.9f} {b[0]:.9f} {b[1]:.9f}")
PY
)
log "区域角点：A=(${A_LAT}, ${A_LON})  B=(${B_LAT}, ${B_LON})  即 40m(北) x 24m(东)"

# 统一走 sweep_cli，不用 `ros2 action send_goal`。两个实测理由：
#   1. 取消不可靠：靠 kill -INT 让 send_goal 转发取消，在 FollowPath 上能用，
#      在 InspectSweep 上实测**一次取消都没发出**（客户端日志无痕迹、
#      服务端没收到、扫掠一路跑完拿到 OK，见 99_notes/isw2 场景 E）。
#      sweep_cli 走显式 cancel_goal_async，行为确定。
#   2. 输出可断言：sweep_cli 打 key=value，退出码即 result_code；
#      而 YAML 的 `result_code: 0` 在 shell 侧 grep 已经踩过两次坑。
send_sweep() {  # send_sweep <超时s> <sweep_cli 的额外参数...>
  local tmo="$1"; shift
  timeout "$tmo" $SWEEP \
    --corner-a "$A_LAT" "$A_LON" --corner-b "$B_LAT" "$B_LON" \
    --heading 0.0 --altitude 15.0 --speed 4.0 --spacing 6.0 \
    --min-overlap 0.25 --hfov 0.0 --timeout 240 "$@" 2>&1
}
rc_of()    { grep -oE '^result_code=[0-9]+' | tail -1 | grep -oE '[0-9]+'; }
field_of() { grep -oE "^$1=[-0-9.]+" | tail -1 | grep -oE '[-0-9.]+'; }
result_block() {  # 只打结果段，不打几百条 Feedback（报告是审计线索，得可读）
  echo "$1" | sed -n '/^---- 结果 ----/,$p'
}

# ---------------- 起 PX4 ----------------
rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"
for pat in inspection_mode autopilot_iface action_cli px4_sitl 'bin/px4' gz_x500 MicroXRCEAgent 'gz sim'; do
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
# 扫掠全程在空中，不需要「无地面站挡解锁」这个前置条件
echo "param set NAV_DLL_ACT 0" >&3; sleep 2
sitl_params_apply 3
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
PARAMS=$(sitl_params_readback 3 "$PX4_LOG" NAV_DLL_ACT)
log "参数读回："
echo "$PARAMS" | sed 's/^/       /' | tee -a "$REPORT"
sitl_params_assert "$PARAMS" "NAV_DLL_ACT.*: 0"

# ---------------- 起两个节点 ----------------
wait_iface_ready() {
  local deadline=$((SECONDS + 45)) v
  while (( SECONDS < deadline )); do
    kill -0 "${NODE_PID:-0}" 2>/dev/null || { log "  iface 已退出"; return 1; }
    v=$(timeout 5 ros2 topic echo --once --field companion_link_ok \
          /skylark_autopilot_iface/flight_health 2>/dev/null | head -1 | tr -d ' \r')
    [[ "$v" == "True" ]] && { log "  iface 就绪"; return 0; }
    sleep 2
  done
  return 1
}
ros2 run skylark_autopilot_iface autopilot_iface > "$OUT/iface.log" 2>&1 & NODE_PID=$!
wait_iface_ready || { tail -20 "$OUT/iface.log" | sed 's/^/    /' | tee -a "$REPORT"; exit 1; }

# 低电量阈值先设 0，理由必须写清：
# SITL 电池约 1.5 分钟就掉进告警区（设计文档 §6 记过），而扫掠要飞 1~2 分钟。
# 不关掉的话测的是电池模型而不是扫掠。这条守卫本身**不是**摆设，
# 所以场景 F 会把阈值抬回去单独挑衅它。
ros2 run skylark_inspection_mode inspection_mode \
  --ros-args -p battery_abort_threshold:=0.0 > "$OUT/inspection.log" 2>&1 & INSP_PID=$!
for i in $(seq 1 25); do
  grep -q '就绪：动作 inspect_sweep' "$OUT/inspection.log" 2>/dev/null && break
  kill -0 "$INSP_PID" 2>/dev/null || { log "inspection_mode 第 ${i}s 退出"; \
      tail -20 "$OUT/inspection.log" | sed 's/^/    /' | tee -a "$REPORT"; exit 1; }
  sleep 1
done
# 「节点起来了」不等于「节点能判断飞机状态」：话题发现要一点时间，
# 这期间发 goal 会拿到"收不到 vehicle_state"而不是真正的拒绝理由。
# 实测同一条断言一轮过一轮不过（isw1 vs isw2），所以等节点**自己报**状态就绪，
# 而不是在这里 sleep 几秒。
for i in $(seq 1 30); do
  grep -q '状态就绪' "$OUT/inspection.log" 2>/dev/null && break
  kill -0 "$INSP_PID" 2>/dev/null || { log "inspection_mode 退出"; break; }
  sleep 1
done
if grep -q '状态就绪' "$OUT/inspection.log" 2>/dev/null; then
  ok "两个节点就绪（inspection_mode 已收到 vehicle_state 与 flight_health）"
else
  bad "inspection_mode 未收到 iface 的状态话题"
  tail -20 "$OUT/inspection.log" | sed 's/^/    /' | tee -a "$REPORT"
fi

state_now() {
  timeout 14 python3 "$TOOLS/watch_vehicle_state.py" --duration 3 2>&1 | grep '结束状态' || echo "读不到"
}

# ---------------- A0 ----------------
log ""
log "=== A0: 未起飞时发 goal -> 期望 REJECTED_NOT_READY(1) ==="
OUT_A0=$(send_sweep 40)
result_block "$OUT_A0" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_A0" | rc_of)
[[ "${RC:-}" == 1 ]] && ok "A0: REJECTED_NOT_READY(1)" || bad "A0: 期望 1，实际 ${RC:-无}"
echo "$OUT_A0" | grep -q 'ready_for_offboard' \
  && ok "A0: 理由指名 ready_for_offboard，可定位" \
  || bad "A0: 拒绝理由不具体"

# ---------------- 起飞 ----------------
log ""
log "=== 起飞到 15 m（扫掠高度）==="
$CLI takeoff --altitude 15 --climb-rate 1.5 --timeout 60 > "$OUT/cli_takeoff.log" 2>&1
RC_T=$?
grep -vE '^\s*反馈' "$OUT/cli_takeoff.log" | sed 's/^/       /' | tee -a "$REPORT"
[[ "$RC_T" == 0 ]] && ok "起飞 OK" || bad "起飞失败(${RC_T})，后续场景无法进行"

# ---------------- A ----------------
log ""
log "=== A: 行距 40 m（幅宽 35.56 m）-> 期望 REJECTED_COVERAGE(3) ==="
log "    契约要求「而不是默默地漏拍」，所以这条必须是专门的结果码"
OUT_A=$(send_sweep 40 --spacing 40.0)
result_block "$OUT_A" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_A" | rc_of)
[[ "${RC:-}" == 3 ]] && ok "A: REJECTED_COVERAGE(3)" || bad "A: 期望 3，实际 ${RC:-无}"
echo "$OUT_A" | grep -qE '降到 [0-9.]+ m' \
  && ok "A: 消息给出了可操作的建议行距" \
  || bad "A: 消息没给建议值，调用方只知道被拒不知道怎么改"

# ---------------- B ----------------
log ""
log "=== B: 横向只有 8 m（排不下两行）-> 期望 REJECTED_BAD_GEOMETRY(2) ==="
read -r NB_LAT NB_LON < <(python3 - <<'PY'
from skylark_inspection_mode.geometry import ned_to_latlon
b = ned_to_latlon(40.0, 8.0, 47.397742, 8.545594)
print(f"{b[0]:.9f} {b[1]:.9f}")
PY
)
OUT_B=$(timeout 40 $SWEEP --corner-a "$A_LAT" "$A_LON" \
        --corner-b "$NB_LAT" "$NB_LON" --heading 0.0 --altitude 15.0 \
        --speed 4.0 --spacing 6.0 --min-overlap 0.25 --hfov 0.0 --timeout 240 2>&1)
result_block "$OUT_B" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_B" | rc_of)
[[ "${RC:-}" == 2 ]] && ok "B: REJECTED_BAD_GEOMETRY(2)，未与覆盖率码混淆" \
  || bad "B: 期望 2，实际 ${RC:-无}"

# ---------------- C ----------------
log ""
log "=== C: 正常扫掠 40x24 m、行距 6 m -> 期望 OK(0) 且 5 行全完成 ==="
OUT_C=$(send_sweep 300)
echo "$OUT_C" > "$OUT/raw_C.log"      # 完整输出（含反馈采样）留在这里备查
echo "$OUT_C" | grep -E '^\s+反馈' | awk 'NR%4==1' | sed 's/^/       /' | tee -a "$REPORT"
result_block "$OUT_C" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_C" | rc_of)
[[ "${RC:-}" == 0 ]] && ok "C: OK(0)" || bad "C: 期望 0，实际 ${RC:-无}"
RT=$(echo "$OUT_C" | field_of rows_total)
RCOMP=$(echo "$OUT_C" | field_of rows_completed)
log "  rows_total=${RT:-?} rows_completed=${RCOMP:-?}"
[[ "${RT:-}" == 5 ]] && ok "C: rows_total=5（横向 24 m / 行距 6 m -> 4 段 + 1）" \
  || bad "C: rows_total 期望 5，实际 ${RT:-无}"
[[ -n "${RCOMP:-}" && "${RCOMP:-}" == "${RT:-x}" ]] \
  && ok "C: 全部 ${RCOMP} 行完成" || bad "C: 只完成 ${RCOMP:-?}/${RT:-?} 行"
XTE=$(echo "$OUT_C" | grep -oE 'max_cross_track_error_m=[0-9.]+' | tail -1 \
      | grep -oE '[0-9.]+')
log "  最大横向偏差: ${XTE:-未取到} m（来自 InspectSweep 的 message 转述）"
if [[ -n "${XTE:-}" ]] && awk -v e="$XTE" 'BEGIN{exit !(e < 2.0)}'; then
  ok "C: 最大横向偏差 ${XTE} m < 2 m，覆盖率有保障"
else
  bad "C: 最大横向偏差 ${XTE:-未取到} m 过大，扫掠会漏拍"
fi

# ---------------- D ----------------
log ""
log "=== D: resume_from_row=2 -> 期望 OK(0)，只飞剩下 3 行 ==="
log "    验的是契约的闭合关系：resume_from_row = last_completed_row + 1 能接上"
OUT_D=$(send_sweep 300 --resume-from-row 2)
echo "$OUT_D" > "$OUT/raw_D.log"
result_block "$OUT_D" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_D" | rc_of)
[[ "${RC:-}" == 0 ]] && ok "D: OK(0)" || bad "D: 期望 0，实际 ${RC:-无}"
RT_D=$(echo "$OUT_D" | field_of rows_total)
RCOMP_D=$(echo "$OUT_D" | field_of rows_completed)
LAST_D=$(echo "$OUT_D" | field_of last_completed_row)
log "  rows_total=${RT_D:-?} rows_completed=${RCOMP_D:-?} last_completed_row=${LAST_D:-?}"
[[ "${RT_D:-}" == 5 ]] && ok "D: rows_total 仍是全局 5（不是剩余 3）" \
  || bad "D: rows_total 期望 5，实际 ${RT_D:-无} —— 全局编号错位会毁掉闭合关系"
[[ "${RCOMP_D:-}" == 3 ]] && ok "D: 只飞了剩下 3 行" \
  || bad "D: rows_completed 期望 3，实际 ${RCOMP_D:-无}"
[[ "${LAST_D:-}" == 4 ]] && ok "D: last_completed_row=4（全局末行）" \
  || bad "D: last_completed_row 期望 4，实际 ${LAST_D:-无}"

# ---------------- E ----------------
log ""
log "=== E: 中途取消 -> 期望 CANCELED(7) 且仍在空中 ==="
OUT_E=$(send_sweep 90 --cancel-after 20)
echo "$OUT_E" > "$OUT/raw_E.log"
echo "$OUT_E" | grep -E '发送取消' | sed 's/^/       /' | tee -a "$REPORT"
result_block "$OUT_E" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_E" | rc_of)
[[ "${RC:-}" == 7 ]] && ok "E: CANCELED(7)" || bad "E: 期望 7，实际 ${RC:-无}"
ST=$(state_now); log "  取消后状态: ${ST}"
[[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
  && ok "E: 取消后仍在空中" || bad "E: 取消后状态异常"

# ---------------- F：挑衅低电量守卫 ----------------
log ""
log "=== F: 把低电量阈值抬到 0.99 -> 期望立刻 ABORTED_LOW_BATTERY(6) ==="
log "    低电量主动中止是「该拦下」的路径，不主动制造就永远验不到"
ros2 param set /skylark_inspection_mode battery_abort_threshold 0.99 \
  2>&1 | sed 's/^/       /' | tee -a "$REPORT"
OUT_F=$(send_sweep 30)
result_block "$OUT_F" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_F" | rc_of)
[[ "${RC:-}" == 6 ]] && ok "F: ABORTED_LOW_BATTERY(6)" || bad "F: 期望 6，实际 ${RC:-无}"
ST=$(state_now); log "  中止后状态: ${ST}"
# 关键断言：飞机**不能**在 OFFBOARD。
#
# 只断言"仍在空中"是不够的 —— 上一轮（isw1）守卫因为跑了旧代码而没生效，
# 扫掠照常起飞，那条"仍在空中"照样 PASS，把真失败盖过去了。
# 主动中止的实质是"根本没开始飞"，而"有没有在飞"看的是 nav_state。
[[ "$ST" != *OFFBOARD* ]] \
  && ok "F: 未进入 OFFBOARD —— 中止发生在起飞之前，守卫真的拦住了" \
  || bad "F: 仍在 OFFBOARD —— 扫掠已经飞起来了，守卫没拦住"
[[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
  && ok "F: 主动中止未导致飞机掉下来（仍解锁悬停）" || bad "F: 中止后状态异常"

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
