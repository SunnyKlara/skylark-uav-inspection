#!/usr/bin/env bash
# 实测 offboard 控制的硬约束 —— docs/OFFBOARD_CONSTRAINTS.md 的数据来源。
#
# 四个阶段，各回答一个问题：
#   A 出厂参数下官方示例能否解锁？        （答：不能，No connection to the GCS）
#   B 关掉 NAV_DLL_ACT 后的干净时序        （进 OFFBOARD / 解锁 / 爬升各多久）
#   C setpoint 断流后多久掉出 OFFBOARD、去哪 （答：~1s 触发，转 AUTO_RTL 并自动降落）
#   D 恢复发布能否自行回到 OFFBOARD
#
# 三个必须做对否则结论全错的地方（都实际踩过，见文档 §3）：
#   1. 开跑前删掉持久化参数，否则上一轮的设置会静默生效
#   2. 杀 offboard 节点要按可执行杀，不能杀 `ros2 run` 的包装进程
#   3. 长测试前关掉低电量动作，否则电池 RTL 会被误当成 offboard 失效保护
#
# 用法： bash exp_offboard_constraints.sh [输出目录]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"

OUT="${1:-/tmp/skylark_exp_offboard}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; AGENT_LOG="$OUT/agent.log"; REPORT="$OUT/report.txt"
# FIFO 必须建在 Linux 原生文件系统上。
# 放到 $OUT 里试过一次：当 $OUT 指向 /mnt/c（DrvFs 不支持 FIFO）时 mkfifo 无效，
# px4 的 stdin 立刻是坏的，启动 1 秒就退出，现象看起来像 PX4 自己崩了。
FIFO="/tmp/skylark_px4_console.$$"
: > "$REPORT"
log() { echo "$*" | tee -a "$REPORT"; }
clean_log() { sed 's/pxh> //g' "$PX4_LOG" | grep -vE '^(commander|param|uxrce|uorb)[a-z_0-9 .-]{0,40}$'; }

# 按可执行名杀，并核实真的没了。
# `ros2 run` 是 Python 启动器，SIGTERM 只结束包装进程，被启动的可执行会继续发
# setpoint —— 那会让「断流」测试测到假象（实测踩过）。
kill_offboard() {
  [[ -n "${OB_PID:-}" ]] && kill -TERM "$OB_PID" 2>/dev/null
  sleep 1; pkill -f 'offboard_control' 2>/dev/null; sleep 1
  if pgrep -f 'offboard_control' >/dev/null 2>&1; then
    log "  ⚠ 仍有残留，强杀"; pkill -9 -f 'offboard_control' 2>/dev/null; sleep 1
  fi
  OB_PID=""
}

cleanup() {
  log ""; log "--- 清理 ---"
  kill_offboard
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
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
WS="${SKYLARK_WS:-$HOME/skylark_ws}"
RF="$PX4_DIR/build/px4_sitl_default/rootfs"
OB_BIN="$WS/install/px4_ros_com/lib/px4_ros_com/offboard_control"

[[ -x "$OB_BIN" ]] || { echo "找不到 offboard_control 可执行: $OB_BIN"; exit 1; }
[[ -f "$TOOLS/watch_vehicle_state.py" ]] || { echo "找不到 watch_vehicle_state.py"; exit 1; }

log "=== offboard 约束实测 $(date '+%F %T') ==="
log "PX4 ref=$(git -C "$PX4_DIR" describe --tags --always 2>/dev/null)   输出=${OUT}"

log ""
log "--- 清空持久化参数（否则上一轮设置会静默生效，结论作废）---"
for f in "$RF/parameters.bson" "$RF/parameters_backup.bson"; do
  [[ -f "$f" ]] && { log "  删除 $(basename "$f")（$(stat -c%s "$f") 字节）"; rm -f "$f"; } \
                || log "  $(basename "$f") 本就不存在"
done

pkill -f 'offboard_control' 2>/dev/null
pkill -f MicroXRCEAgent 2>/dev/null; pkill -f px4_sitl 2>/dev/null; pkill -f 'bin/px4' 2>/dev/null; pkill -f gz_x500 2>/dev/null
pkill -f 'gz sim' 2>/dev/null; sleep 2

MicroXRCEAgent udp4 -p 8888 > "$AGENT_LOG" 2>&1 & AGENT_PID=$!
sleep 3
rm -f "$FIFO"; mkfifo "$FIFO"
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < "$FIFO" ) > "$PX4_LOG" 2>&1 & PX4_PID=$!
# 必须用 fd 顶住 FIFO 写端，否则 px4 读到 EOF 立刻退出
exec 3>"$FIFO"; CON_OPEN=1

log "等待 PX4 就绪..."
for i in $(seq 1 180); do
  grep -qE 'uxrce_dds_client.*(synchronized|successfully created)' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "PX4 第 ${i}s 退出"; exit 1; }
  sleep 1
done
log "就绪，等 12s 让 EKF2 收敛"; sleep 12

console() { echo "$1" >&3; sleep "${2:-2}"; }
# param show 的值行形如： x   COM_OF_LOSS_T [285,509] : 1.0000
show_params() {
  local mark; mark=$(wc -c < "$PX4_LOG")
  for p in "$@"; do echo "param show $p" >&3; sleep 1.2; done
  sleep 1.5
  tail -c "+${mark}" "$PX4_LOG" | sed 's/pxh> //g' \
    | grep -oE '[+*x ] +(COM|NAV|SIM)_[A-Z0-9_]+ \[[0-9,]+\] : [-0-9.]+' \
    | sed 's/^[+*x ] */       /' | tee -a "$REPORT"
}
watch() { python3 "$TOOLS/watch_vehicle_state.py" "$@" 2>&1 | tee -a "$REPORT"; }

log ""
log "--- 出厂参数确认 ---"
show_params NAV_DLL_ACT COM_LOW_BAT_ACT COM_OF_LOSS_T COM_OBL_RC_ACT
log "  期望：NAV_DLL_ACT=2（数传丢失动作）  COM_OF_LOSS_T=1.0（setpoint 断流容限）"

# ---------- A ----------
log ""
log "=== A: 出厂参数下跑官方示例，看解锁会不会被拒 ==="
"$OB_BIN" > "$OUT/offboard_A.log" 2>&1 & OB_PID=$!
watch --duration 25 --csv "$OUT/state_A.csv" --label "A 出厂参数" --expect-nav 14 --expect-alt 3.0
RC_A=${PIPESTATUS[0]}
kill_offboard
log "  退出码=${RC_A}（预期 1：能进 OFFBOARD 但爬不起来，因为没解锁）"
clean_log | grep -E 'Arming denied|Preflight Fail: No connection' | tail -3 | sed 's/^/       /' | tee -a "$REPORT"

# ---------- B ----------
log ""
log "=== B: 关掉数传失效保护与低电量动作，测干净时序 ==="
console "param set NAV_DLL_ACT 0" 2
console "param set COM_LOW_BAT_ACT 0" 2
show_params NAV_DLL_ACT COM_LOW_BAT_ACT
"$OB_BIN" > "$OUT/offboard_B.log" 2>&1 & OB_PID=$!
watch --duration 40 --csv "$OUT/state_B.csv" --label "B 正常路径" --expect-nav 14 --expect-alt 4.5
RC_B=${PIPESTATUS[0]}
log "  退出码=${RC_B}（预期 0）"
clean_log | grep -E 'Armed by|Takeoff detected' | tail -3 | sed 's/^/       /' | tee -a "$REPORT"

# ---------- C / D ----------
if [[ "$RC_B" == 0 ]]; then
  log ""
  log "=== C: 悬停中断掉 setpoint ==="
  MARK=$(wc -c < "$PX4_LOG")
  kill_offboard
  watch --duration 30 --csv "$OUT/state_C.csv" --label "C setpoint 断流"
  log "  这段窗口内 PX4 的事件（核对紧跟 Failsafe 的那一行是不是 battery）："
  tail -c "+${MARK}" "$PX4_LOG" | sed 's/pxh> //g' \
    | grep -iE 'failsafe|battery|navigator|Landing detected|Disarmed' \
    | tail -10 | sed 's/^/       /' | tee -a "$REPORT"

  log ""
  log "=== D: 恢复发布，看能否自行回到 OFFBOARD ==="
  "$OB_BIN" > "$OUT/offboard_D.log" 2>&1 & OB_PID=$!
  watch --duration 20 --csv "$OUT/state_D.csv" --label "D 恢复发布" --expect-nav 14
  log "  退出码=${PIPESTATUS[0]}"
else
  log ""
  log "=== C/D 跳过：阶段 B 未进入悬停 ==="
  tail -10 "$OUT/offboard_B.log" | sed 's/^/       /' | tee -a "$REPORT"
fi

log ""
log "报告: ${REPORT}"
log "状态时间线 CSV: ${OUT}/state_{A,B,C,D}.csv"
log "结论汇总见 docs/OFFBOARD_CONSTRAINTS.md"
