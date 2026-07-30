#!/usr/bin/env bash
# Revisit（降高复拍）的集成测试。
#
# 这个动作是「AI 反馈控制飞行决策」叙事的载体，所以除了功能，
# **两个延迟字段**也要验到：它们是论文的原始素材，先随便填后面很难回头做准。
#
# 场景与各自要验的东西：
#   A0 未起飞            -> REJECTED_NOT_READY(1)
#   A  请求 AGL 0.5 m    -> OK(0) 但 actual_agl_m 被抬到安全下限 3.0 m
#      验的是契约那句「调用方给出的值是请求而非命令」
#   B  紧接着同点再请求  -> REJECTED_RATE_LIMITED(3)（防误检导致反复下降）
#   C  正常复拍          -> OK(0)，actual_agl 与请求一致、回到原高度、
#                           两个延迟字段都 > 0 且有序（motion <= onstation）
#   D  偏移 80 m 的目标  -> REJECTED_UNSAFE(2)，且**不能**夹紧到 50 m 去拍错位置
#   E  下降途中取消      -> CANCELED(7)，且仍在空中
#
# 顺序有讲究：A 先跑，它会写下"上次复拍点"，B 紧接着才能验到限流；
# C 必须等限流窗口过去（脚本里显式等），否则会被 B 的记录挡住。
#
# 用法： bash test_revisit.sh [输出目录]

set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"
source "${SCRIPT_DIR}/sitl_params.sh"

OUT="${1:-/tmp/skylark_revisit}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_rv_fifo.$$"
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
RV="ros2 run skylark_inspection_mode revisit_cli"

log "=== Revisit 集成测试 $(date '+%F %T') ==="
log "PX4 ref=$(git -C "$PX4_DIR" describe --tags --always 2>/dev/null)"

send_rv() {  # send_rv <超时s> <revisit_cli 参数...>
  local tmo="$1"; shift
  timeout "$tmo" $RV --timeout 120 "$@" 2>&1
}
rc_of()    { grep -oE '^result_code=[0-9]+' | tail -1 | grep -oE '[0-9]+'; }
field_of() { grep -oE "^$1=[-0-9.]+" | tail -1 | grep -oE '[-0-9.]+'; }
result_block() { echo "$1" | sed -n '/^---- 结果 ----/,$p'; }

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

# 低电量阈值设 0：SITL 电池 1.5 分钟就进告警区，会盖掉本测试要验的东西。
# 那条守卫本身已由 test_inspect_sweep.sh 场景 F 单独挑衅过。
ros2 run skylark_inspection_mode inspection_mode \
  --ros-args -p battery_abort_threshold:=0.0 > "$OUT/inspection.log" 2>&1 & INSP_PID=$!
for i in $(seq 1 30); do
  grep -q '状态就绪' "$OUT/inspection.log" 2>/dev/null && break
  kill -0 "$INSP_PID" 2>/dev/null || { log "inspection_mode 退出"; break; }
  sleep 1
done
if grep -q '状态就绪' "$OUT/inspection.log" 2>/dev/null; then
  ok "两个节点就绪"
else
  bad "inspection_mode 未收到 iface 的状态话题"
  tail -20 "$OUT/inspection.log" | sed 's/^/    /' | tee -a "$REPORT"
fi
log "  节点启动行：$(grep -o '就绪：动作.*' "$OUT/inspection.log" | head -1)"

state_now() {
  timeout 14 python3 "$TOOLS/watch_vehicle_state.py" --duration 3 2>&1 | grep '结束状态' || echo "读不到"
}

# ---------------- A0 ----------------
log ""
log "=== A0: 未起飞时发 goal -> 期望 REJECTED_NOT_READY(1) ==="
OUT_A0=$(send_rv 40 --agl 5)
result_block "$OUT_A0" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_A0" | rc_of)
[[ "${RC:-}" == 1 ]] && ok "A0: REJECTED_NOT_READY(1)" || bad "A0: 期望 1，实际 ${RC:-无}"

# ---------------- 起飞 ----------------
log ""
log "=== 起飞到 15 m（模拟巡航高度）==="
$CLI takeoff --altitude 15 --climb-rate 1.5 --timeout 60 > "$OUT/cli_takeoff.log" 2>&1
RC_T=$?
grep -vE '^\s*反馈' "$OUT/cli_takeoff.log" | sed 's/^/       /' | tee -a "$REPORT"
[[ "$RC_T" == 0 ]] && ok "起飞 OK" || bad "起飞失败(${RC_T})，后续场景无法进行"

# ---------------- A：夹紧 ----------------
log ""
log "=== A: 请求 AGL 0.5 m -> 期望 OK(0) 且 actual_agl_m 被抬到 3.0 m ==="
log "    验契约那句「调用方给出的值是请求而非命令，实际执行值见 actual_*」"
OUT_A=$(send_rv 150 --agl 0.5 --hover 3 --burst 99)
echo "$OUT_A" > "$OUT/raw_A.log"
echo "$OUT_A" | grep -E '^\s+阶段' | sed 's/^/       /' | tee -a "$REPORT"
result_block "$OUT_A" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_A" | rc_of)
[[ "${RC:-}" == 0 ]] && ok "A: OK(0)" || bad "A: 期望 0，实际 ${RC:-无}"
AGL_A=$(echo "$OUT_A" | field_of actual_agl_m)
log "  actual_agl_m=${AGL_A:-?}（请求 0.5，安全下限 3.0）"
# 断言带 ±0.5 m 容差：actual_agl_m 是**实测**到达高度（契约原文「实际到达的
# 复拍高度」），不是夹紧后的指令值。钉死等于 3.00 就是把指令值当实测值，
# 而那正是 rv1 那一轮的 bug —— 请求 6 m、实际停在 6.74 m、却回报 6.00。
if [[ -n "${AGL_A:-}" ]] && awk -v a="$AGL_A" 'BEGIN{exit !(a >= 2.5 && a <= 3.5)}'; then
  ok "A: 复拍高度被抬到安全下限附近（实测 ${AGL_A} m，要求 3.0 m）"
else
  bad "A: actual_agl_m=${AGL_A:-无}，安全下限没生效或偏差过大"
fi
echo "$OUT_A" | grep -q '实测' \
  && ok "A: message 同时给出实测与要求高度（GSD 可核算）" \
  || bad "A: message 没区分实测与要求高度"
echo "$OUT_A" | grep -q '安全下限' \
  && ok "A: message 说明了为什么被改（夹紧要留痕）" \
  || bad "A: 夹紧了却没说明原因，调用方会以为自己算错"
echo "$OUT_A" | grep -q '连拍张数 99 压到上限 20' \
  && ok "A: 连拍张数被压到上限 20" || bad "A: 连拍张数上限未生效"

# ---------------- B：限流 ----------------
log ""
log "=== B: 紧接着同点再请求 -> 期望 REJECTED_RATE_LIMITED(3) ==="
log "    契约理由：防止误检导致飞机在同一点反复下降"
OUT_B=$(send_rv 40 --agl 6)
result_block "$OUT_B" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_B" | rc_of)
[[ "${RC:-}" == 3 ]] && ok "B: REJECTED_RATE_LIMITED(3)" || bad "B: 期望 3，实际 ${RC:-无}"

# ---------------- D：偏移超限（放在这里，因为它不受限流影响：位置不同）----------------
log ""
log "=== D: 目标点偏移约 80 m -> 期望 REJECTED_UNSAFE(2) ==="
log "    偏移超限必须**拒**而不是夹到 50 m —— 夹了就是去拍一个调用方没要求的位置"
read -r FAR_LAT FAR_LON < <(python3 - <<'PY'
from skylark_inspection_mode.geometry import ned_to_latlon
# 从 SITL home 往北 80 m
print("%.9f %.9f" % ned_to_latlon(80.0, 0.0, 47.397742, 8.545594))
PY
)
OUT_D=$(send_rv 40 --target "$FAR_LAT" "$FAR_LON" --agl 6)
result_block "$OUT_D" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_D" | rc_of)
[[ "${RC:-}" == 2 ]] && ok "D: REJECTED_UNSAFE(2)" || bad "D: 期望 2，实际 ${RC:-无}"
echo "$OUT_D" | grep -q '偏移上限' \
  && ok "D: 消息点明是偏移超限，并说明为何不夹紧" || bad "D: 拒绝理由不具体"

# ---------------- 等限流窗口过去 ----------------
log ""
log "=== 等限流窗口（${SITL_REVISIT_WAIT:-32}s）过去，再验正常路径 ==="
log "    不等的话 C 会被 A 的记录挡住 —— 那不是 bug，是限流在正常工作"
sleep "${SITL_REVISIT_WAIT:-32}"

# ---------------- C：正常复拍 + 延迟字段 ----------------
log ""
log "=== C: 正常复拍到 6 m -> 期望 OK(0)，两个延迟字段有序且合理 ==="
OUT_C=$(send_rv 180 --agl 6 --hover 4 --burst 5)
echo "$OUT_C" > "$OUT/raw_C.log"
echo "$OUT_C" | grep -E '^\s+阶段' | sed 's/^/       /' | tee -a "$REPORT"
result_block "$OUT_C" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_C" | rc_of)
[[ "${RC:-}" == 0 ]] && ok "C: OK(0)" || bad "C: 期望 0，实际 ${RC:-无}"
AGL_C=$(echo "$OUT_C" | field_of actual_agl_m)
# 6 m 没越界，所以指令值不该被夹；而**实测**值要落在到位容差内 ——
# 这条同时在验"到达半径 < 高度容差"这个参数耦合关系真的成立。
if [[ -n "${AGL_C:-}" ]] && awk -v a="$AGL_C" 'BEGIN{exit !(a >= 5.5 && a <= 6.5)}'; then
  ok "C: 实测到达 ${AGL_C} m，落在要求 6 m 的容差内"
else
  bad "C: actual_agl_m=${AGL_C:-无}，偏离要求的 6.0 m 超过容差"
fi
echo "$OUT_C" | grep -q '偏离要求' \
  && bad "C: message 报告高度偏离超容差 —— 到达半径与容差的耦合关系没成立" \
  || ok "C: 实测高度未触发偏离告警"
echo "$OUT_C" | grep -q '^returned_to_origin=True' \
  && ok "C: 已回到原高度/原位" || bad "C: returned_to_origin 不为 True"
L_M=$(echo "$OUT_C" | field_of latency_goal_to_motion_ms)
L_S=$(echo "$OUT_C" | field_of latency_goal_to_onstation_ms)
log "  延迟: goal->动作 ${L_M:-?} ms, goal->到位稳定 ${L_S:-?} ms"
# 断言只做"有序 + 量级合理"，不钉具体数值：这两个数是**测量结果**，
# 钉死会变成把仿真的偶然性写进断言。有序性才是它们必须满足的性质。
if [[ -n "${L_M:-}" && -n "${L_S:-}" ]] \
   && awk -v m="$L_M" -v s="$L_S" 'BEGIN{exit !(m > 0 && s > m && s < 60000)}'; then
  ok "C: 延迟字段有序且量级合理（0 < motion < onstation < 60s）"
else
  bad "C: 延迟字段不合理（motion=${L_M:-无} onstation=${L_S:-无}）"
fi
echo "$OUT_C" | grep -q '^images_captured=0' \
  && ok "C: images_captured 如实为 0（拍摄触发未实现，message 有说明）" \
  || bad "C: images_captured 不为 0，但拍摄触发并未实现"

# ---------------- E：下降途中取消 ----------------
log ""
log "=== E: 下降途中取消 -> 期望 CANCELED(7) 且仍在空中 ==="
sleep "${SITL_REVISIT_WAIT:-32}"     # 同样要等限流窗口
OUT_E=$(send_rv 120 --agl 4 --hover 20 --cancel-after 6)
echo "$OUT_E" > "$OUT/raw_E.log"
echo "$OUT_E" | grep -E '^\s+阶段|发送取消' | sed 's/^/       /' | tee -a "$REPORT"
result_block "$OUT_E" | sed 's/^/       /' | tee -a "$REPORT"
RC=$(echo "$OUT_E" | rc_of)
[[ "${RC:-}" == 7 ]] && ok "E: CANCELED(7)" || bad "E: 期望 7，实际 ${RC:-无}"
ST=$(state_now); log "  取消后状态: ${ST}"
[[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
  && ok "E: 取消后仍在空中" || bad "E: 取消后状态异常"

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
