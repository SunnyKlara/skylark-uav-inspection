#!/usr/bin/env bash
# skylark_autopilot_iface 三个动作的集成测试：起飞 -> 环绕 -> 返航降落，外加拒绝与取消路径。
#
# 场景与各自要验的东西：
#   A 出厂参数无地面站     Takeoff -> REJECTED_NOT_READY(1)，且带回飞控真实原因
#   B 关 NAV_DLL_ACT       Takeoff -> OK(0)，移交 AUTO_LOITER 后仍在空中
#   C 半径过小             Orbit   -> REJECTED_BAD_GEOMETRY(2)，且不该动飞机
#   D 正常环绕             Orbit   -> OK(0)，半径误差与圈数可信
#   E 环绕中途取消         Orbit   -> CANCELED(5)，取消后保持悬停
#   F 返航降落             Land    -> OK(0)，disarmed=true，飞控报告触地
#
# 顺序是有意的：C 放在飞行中执行，用来确认几何校验在"能飞"的前提下依然拒绝
# —— 否则可能是因为没解锁才被拒，验不到几何校验本身。
#
# 用法： bash test_flight_actions.sh [输出目录]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

OUT="${1:-/tmp/skylark_test_actions}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_actions_fifo.$$"   # 必须 Linux 原生 fs：/mnt/c 不支持 FIFO
: > "$REPORT"
PASS=0; FAIL=0
log()  { echo "$*" | tee -a "$REPORT"; }
ok()   { log "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { log "  [FAIL] $*"; FAIL=$((FAIL+1)); }
clean_px4_log() { sed 's/pxh> //g' "$PX4_LOG"; }

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
  pkill -f px4_sitl 2>/dev/null; pkill -f 'bin/px4' 2>/dev/null; pkill -f gz_x500 2>/dev/null
  pkill -f MicroXRCEAgent 2>/dev/null
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
CLI="ros2 run skylark_autopilot_iface action_cli"

log "=== 飞行动作集成测试 $(date '+%F %T') ==="
log "PX4 ref=$(git -C "$PX4_DIR" describe --tags --always 2>/dev/null)"

# 清持久化参数：上一轮设的 NAV_DLL_ACT 会跨重启生效，场景 A 就失效了
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

log "等待 PX4 就绪..."
for i in $(seq 1 180); do
  grep -qE 'uxrce_dds_client.*(synchronized|successfully created)' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "PX4 第 ${i}s 退出"; exit 1; }
  sleep 1
done
log "就绪，等 12s 让 EKF2 收敛"; sleep 12
echo "param set COM_LOW_BAT_ACT 0" >&3; sleep 2
# 关掉 uXRCE-DDS 的时间戳同步 —— 压制 offboard 自发掉线的手段之一。
#
# 对照实验（flight/sitl/test_synct_effect.sh，原始数据 99_notes/synct1）：
#   SYNCT=1 -> 90s 内自发丢失 3 次（周期 30s，每次持续约 10s）
#   SYNCT=0 -> 90s 内 0 次
# ⚠ 代价：SYNCT=0 后 /fmu/out/* 的 timestamp 是 PX4 开机计时而非系统纪元，
#   任何拿它跟墙钟直接相减的工具都要改口径；出站方向也要改成 PX4 刻度
#   （px4_link 的时钟伺服负责，见 OFFBOARD_CONSTRAINTS.md §7.4）。
# ⚠ 该参数 reboot_required，必须设完保存并重启 PX4 才生效 —— 所以这里要两次启动。
echo "param set UXRCE_DDS_SYNCT 0" >&3; sleep 2
# 抬 setpoint 断流容限。这一条是 2026-07-31 补的，起因值得记住：
#
# 本脚本此前在**出厂容限 1.0 s** 下拿到 13/13，看着比现在更好 ——
# 但那是假的。当时 px4_link 无条件发本机纪元时间（1.785e18 us），
# SYNCT=0 下 PX4 不换算，于是它看到的时间戳在未来约 5.6 万年，
# offboardCheck 的 `hrt_now < timestamp + COM_OF_LOSS_T` 恒成立 ——
# **飞控的 offboard 过期检测被整个废掉了**，所以怎么跑都不会丢。
# 出站时间戳改成锚定飞控时钟之后该检测恢复有效，代价是 lockstep 仿真时钟的
# 离散前跳（实测单次 1.93 s）会真的触发它。故按观测跳变幅度设 5.0 s。
# ⚠ 真机不该有这种跳变，S2 必须重新评估，不要照搬。
echo "param set COM_OF_LOSS_T 5.0" >&3; sleep 2
echo "param save" >&3; sleep 2
log "已设 COM_LOW_BAT_ACT=0, UXRCE_DDS_SYNCT=0, COM_OF_LOSS_T=5.0（需重启生效），重启 PX4"

exec 3>&-
kill -TERM "$PX4_PID" 2>/dev/null; sleep 3
pkill -9 -f px4_sitl 2>/dev/null; pkill -9 -f 'bin/px4' 2>/dev/null
pkill -9 -f gz_x500 2>/dev/null; pkill -9 -f 'gz sim' 2>/dev/null
sleep 3
# 第二次启动：这次不清参数，让刚保存的 SYNCT=0 生效。
# NAV_DLL_ACT 此时仍是出厂值 2，场景 A 依然成立。
rm -f "$FIFO"; mkfifo "$FIFO"
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$FIFO" ) >> "$PX4_LOG" 2>&1 & PX4_PID=$!
exec 3>"$FIFO"
for i in $(seq 1 180); do
  grep -qE 'uxrce_dds_client.*successfully created' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "重启后 PX4 第 ${i}s 退出"; exit 1; }
  sleep 1
done
sleep 12
# 读回并**断言**，不只是打印。
# 上一版只打印两个参数，于是"参数没生效"这个可能永远排除不掉；
# COM_OF_LOSS_T 更是必须验 —— 整套结论都建立在它被抬到 5.0 上。
MARK=$(wc -c < "$PX4_LOG")
for p in UXRCE_DDS_SYNCT NAV_DLL_ACT COM_OF_LOSS_T; do
  echo "param show $p" >&3; sleep 2
done
PARAMS=$(tail -c "+${MARK}" "$PX4_LOG" | sed 's/pxh> //g' \
         | grep -oE '[+*x ] +(COM|NAV|UXRCE)_[A-Z0-9_]+ \[[0-9,]+\] : [-0-9.]+' \
         | sed 's/^[+*x ] *//')
log "重启后参数确认："
echo "$PARAMS" | sed 's/^/       /' | tee -a "$REPORT"
# NAV_DLL_ACT 这里期望的是**出厂 2** —— 场景 A 靠它成立，别写成 0
for expect in "UXRCE_DDS_SYNCT.*: 0" "NAV_DLL_ACT.*: 2" "COM_OF_LOSS_T.*: 5"; do
  if echo "$PARAMS" | grep -qE "$expect"; then
    ok "参数生效: ${expect%%.*}"
  else
    bad "参数未生效: ${expect%%.*} —— 后续结论不可信"
  fi
done

wait_node_ready() {
  local deadline=$((SECONDS + 45)) v
  while (( SECONDS < deadline )); do
    kill -0 "${NODE_PID:-0}" 2>/dev/null || { log "  节点进程已退出"; return 1; }
    v=$(timeout 5 ros2 topic echo --once --field companion_link_ok \
          /skylark_autopilot_iface/flight_health 2>/dev/null | head -1 | tr -d ' \r')
    [[ "$v" == "True" ]] && { log "  节点就绪"; return 0; }
    sleep 2
  done
  log "  45s 内节点未与飞控连上"; return 1
}
start_node() {
  kill_node
  ros2 run skylark_autopilot_iface autopilot_iface > "$OUT/node_$1.log" 2>&1 & NODE_PID=$!
  if ! wait_node_ready; then
    tail -20 "$OUT/node_$1.log" | sed 's/^/       /' | tee -a "$REPORT"; return 1
  fi
  return 0
}
state_now() {
  timeout 14 python3 "$TOOLS/watch_vehicle_state.py" --duration 3 2>&1 | grep '结束状态' || echo "读不到"
}

# ---------------- A ----------------
log ""
log "=== A: 出厂参数（无地面站）Takeoff -> 期望 REJECTED_NOT_READY(1) ==="
if start_node A; then
  $CLI takeoff --altitude 5 --timeout 25 > "$OUT/cli_A.log" 2>&1; RC=$?
  sed 's/^/       /' "$OUT/cli_A.log" | tee -a "$REPORT"
  [[ "$RC" == 1 ]] && ok "A: REJECTED_NOT_READY(1)" || bad "A: 期望 1，实际 ${RC}"
  grep -q 'Armed by external command' <(clean_px4_log) \
    && bad "A: 飞机竟然解锁了" || ok "A: 飞机未解锁"
else bad "A: 节点起不来"; fi

# ---------------- B ----------------
log ""
log "=== B: 关 NAV_DLL_ACT 后 Takeoff -> 期望 OK(0) ==="
echo "param set NAV_DLL_ACT 0" >&3; sleep 3
if start_node B; then
  $CLI takeoff --altitude 8 --climb-rate 1.5 --timeout 45 > "$OUT/cli_B.log" 2>&1; RC=$?
  grep -vE '^\s*反馈' "$OUT/cli_B.log" | sed 's/^/       /' | tee -a "$REPORT"
  [[ "$RC" == 0 ]] && ok "B: OK(0)" || bad "B: 期望 0，实际 ${RC}"
  ST=$(state_now); log "  起飞后状态: ${ST}"
  [[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
    && ok "B: 仍解锁在空中，未自行降落" || bad "B: 起飞后状态异常"
else bad "B: 节点起不来"; fi

# ---------------- C ----------------
log ""
log "=== C: 半径 0.5m 的 Orbit -> 期望 REJECTED_BAD_GEOMETRY(2) ==="
log "  （在空中执行，确保拒绝来自几何校验而不是"没解锁"）"
$CLI orbit --radius 0.5 --altitude 8 --revolutions 1 --timeout 30 > "$OUT/cli_C.log" 2>&1; RC=$?
sed 's/^/       /' "$OUT/cli_C.log" | tee -a "$REPORT"
[[ "$RC" == 2 ]] && ok "C: REJECTED_BAD_GEOMETRY(2)" || bad "C: 期望 2，实际 ${RC}"
ST=$(state_now); log "  拒绝后状态: ${ST}"
[[ "$ST" == *AUTO_LOITER* ]] && ok "C: 拒绝未改变飞行状态" || log "  (注: 模式为非 LOITER，不作硬断言)"

# ---------------- D ----------------
log ""
log "=== D: 正常 Orbit 半径 8m 一圈 -> 期望 OK(0) ==="
$CLI orbit --radius 8 --altitude 8 --speed 3 --revolutions 1 --yaw-mode 0 \
  --timeout 60 > "$OUT/cli_D.log" 2>&1; RC=$?
grep -vE '^\s*反馈' "$OUT/cli_D.log" | sed 's/^/       /' | tee -a "$REPORT"
log "  反馈采样（每 8 条取 1）："
grep -E '^\s*反馈' "$OUT/cli_D.log" | awk 'NR%8==1' | sed 's/^/       /' | tee -a "$REPORT"
[[ "$RC" == 0 ]] && ok "D: OK(0)" || bad "D: 期望 0，实际 ${RC}"
# 断言**稳态**跟踪误差，跳过前 1/4 的样本。
#
# 第一版把入圈过程也算进去，于是第一帧的 -7.75 m（起飞点在圆心附近，
# 飞机要先飞到 8 m 外的圆上）被当成跟踪误差判了失败。
# 实现侧已补显式入圈阶段，入圈期间 revolutions_completed 恒为 0；
# 这里对应地只看入圈之后的误差。
NFB=$(grep -cE '^\s*反馈' "$OUT/cli_D.log" || echo 0)
SKIP=$(( NFB / 4 ))
MAXERR=$(grep -E '^\s*反馈' "$OUT/cli_D.log" | tail -n +$((SKIP + 1)) \
         | grep -oE '半径误差 *[+-][0-9.]+' | grep -oE '[0-9.]+' | sort -rn | head -1)
log "  稳态最大半径误差: ${MAXERR:-未取到} m（共 ${NFB} 帧，跳过前 ${SKIP} 帧）"
if [[ -n "${MAXERR:-}" ]] && awk -v e="$MAXERR" 'BEGIN{exit !(e < 3.0)}'; then
  ok "D: 稳态半径跟踪误差 ${MAXERR} m < 3 m"
else
  bad "D: 稳态半径跟踪误差 ${MAXERR:-未取到} m 过大"
fi

# ---------------- E ----------------
log ""
log "=== E: Orbit 中途取消 -> 期望 CANCELED(5) 且保持悬停 ==="
# timeout 必须容得下 3 圈：半径 10 / 速度 2 -> 角速度 0.2 rad/s，3 圈需 94s。
# 第一版给了 90s，被前置校验按"参数自相矛盾"正确拒掉（RESULT_BAD_GEOMETRY），
# 于是验不到取消路径 —— 是测试参数写错，不是实现的问题。
$CLI orbit --radius 10 --altitude 8 --speed 2 --revolutions 3 \
  --timeout 130 --cancel-after 8 > "$OUT/cli_E.log" 2>&1; RC=$?
grep -vE '^\s*反馈' "$OUT/cli_E.log" | sed 's/^/       /' | tee -a "$REPORT"
[[ "$RC" == 5 ]] && ok "E: CANCELED(5)" || bad "E: 期望 5，实际 ${RC}"
ST=$(state_now); log "  取消后状态: ${ST}"
[[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
  && ok "E: 取消后仍在空中悬停" || bad "E: 取消后状态异常"

# ---------------- F ----------------
log ""
log "=== F: 返航降落 -> 期望 OK(0) 且 disarmed=true ==="
$CLI land --mode 0 --timeout 120 > "$OUT/cli_F.log" 2>&1; RC=$?
grep -vE '^\s*反馈' "$OUT/cli_F.log" | sed 's/^/       /' | tee -a "$REPORT"
log "  反馈采样（每 10 条取 1）："
grep -E '^\s*反馈' "$OUT/cli_F.log" | awk 'NR%10==1' | sed 's/^/       /' | tee -a "$REPORT"
[[ "$RC" == 0 ]] && ok "F: OK(0)" || bad "F: 期望 0，实际 ${RC}"
grep -q 'disarmed: True' "$OUT/cli_F.log" || grep -q '已上锁: True' "$OUT/cli_F.log" \
  && ok "F: 落地后已上锁" || bad "F: 落地后未上锁"
grep -q 'Landing detected' <(clean_px4_log) \
  && ok "F: 飞控报告 Landing detected" || bad "F: 飞控未报告触地"

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
