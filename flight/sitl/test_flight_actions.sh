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
#   G 起飞中途取消         Takeoff -> CANCELED(5)，且仍解锁在空中（验显式移交 LOITER）
#   H **挑衅**：SIGKILL 机载节点 -> 飞控必须接管，并测出接管延迟
#
# 顺序是有意的：C 放在飞行中执行，用来确认几何校验在"能飞"的前提下依然拒绝
# —— 否则可能是因为没解锁才被拒，验不到几何校验本身。
# G 放在 F 之后，因为 F 已确认落地上锁，正是 G 需要的起始状态；
# H 放最后，因为它必然以飞控接管 + RTL 收场。
#
# A~G 验的都是「该做到的做到了」。H 是唯一验「该拦下的拦下了」的一条 ——
# 加它的直接原因是 2026-07-31 那次：整套测试 13/13 全绿，而飞控的 offboard
# 过期检测其实已被出站时间戳的 bug 整个废掉（详见 H 处的注释）。
#
# 用法： bash test_flight_actions.sh [输出目录]

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
TOOLS="${REPO_ROOT}/flight/tools"
# SITL 参数的单一来源（值与理由都写在那里，不要在本文件里再写死数字）
source "${SCRIPT_DIR}/sitl_params.sh"

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
# 参数与理由都在 sitl_params.sh。这里刻意**不设 NAV_DLL_ACT**：
# 场景 A 要它保持出厂 2（headless 下挡解锁），验「解锁被拒且带回飞控真实原因」。
sitl_params_apply 3
log "已设 ${SITL_PARAM_SUMMARY}（SYNCT 需重启生效），重启 PX4"

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
# 读回并**断言**，不只是打印。只打印的话「参数没生效」这个可能永远排除不掉，
# 一次真失败就得多花一轮才能定性 —— 吃过这个亏。
# 额外带上 NAV_DLL_ACT，这里期望的是**出厂 2**（场景 A 靠它成立，别写成 0）。
PARAMS=$(sitl_params_readback 3 "$PX4_LOG" NAV_DLL_ACT)
log "重启后参数确认："
echo "$PARAMS" | sed 's/^/       /' | tee -a "$REPORT"
sitl_params_assert "$PARAMS" "NAV_DLL_ACT.*: 2"

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

# ---------------- G ----------------
# 这一条从 test_takeoff_action.sh 搬过来（那个脚本已删）。
# 两个脚本的场景 A/B 本来就重复，只有「起飞中途取消」是独占的，
# 而重复的代价是两份参数块要同步 —— 实际已经漂了（一份停在 COM_OF_LOSS_T=3.0）。
#
# 验的是**显式移交 AUTO_LOITER 真的生效**：取消起飞后如果只是停发 setpoint，
# 飞控会按约束 5 接管并降落。所以「仍解锁 + 仍在空中」才是这条的实质断言。
# 放在 F 之后：F 已确认落地上锁，正好是这条需要的起始状态。
log ""
log "=== G: 起飞中途取消 -> 期望 CANCELED(5) 且保持悬停 ==="
if start_node G; then
  $CLI takeoff --altitude 12 --climb-rate 1.0 --timeout 45 --cancel-after 6 \
    > "$OUT/cli_G.log" 2>&1; RC=$?
  grep -vE '^\s*反馈' "$OUT/cli_G.log" | sed 's/^/       /' | tee -a "$REPORT"
  [[ "$RC" == 5 ]] && ok "G: CANCELED(5)" || bad "G: 期望 5，实际 ${RC}"
  ST=$(state_now); log "  取消后状态: ${ST}"
  [[ "$ST" == *ARMED* && "$ST" != *DISARMED* ]] \
    && ok "G: 取消后仍解锁在空中（移交 LOITER 生效，未被接管降落）" \
    || bad "G: 取消后状态异常 —— 可能是停发 setpoint 导致飞控接管"
else bad "G: 节点起不来"; fi

# ---------------- H：挑衅测试 ----------------
# 这一条的存在理由，比它验的内容更重要，所以写长一点。
#
# 2026-07-31 发现：px4_link 曾无条件发本机纪元时间，SYNCT=0 下 PX4 不换算，
# 于是它看到的时间戳在未来约 5.6 万年，offboardCheck 的
#     hrt_now < timestamp + COM_OF_LOSS_T
# 恒成立 —— **飞控的 offboard 过期检测被整个废掉了**，机载电脑真死了也发现不了。
# 而当时整套测试是 13/13 全绿。原因很简单：所有场景都在验「该做到的做到了」，
# 没有一条在验「该拦下的拦下了」。
#
# 所以这里主动制造那个故障：SIGKILL 机载节点（模拟机载电脑猝死），
# 断言飞控**必须**接管。刻意用 kill -9 而不是加一个「停发心跳」的测试钩子：
# 钩子路径和真实故障路径不是同一条，验了钩子等于没验。
#
# 观测用 watch_vehicle_state.py 直接订阅 /fmu/out/vehicle_status —— 它不依赖
# 我们的节点，这正是本场景需要的性质（节点已经被杀了）。
log ""
log "=== H: SIGKILL 机载节点 -> 飞控必须接管（挑衅测试）==="
log "    容限 COM_OF_LOSS_T=${SITL_COM_OF_LOSS_T}s，期望接管延迟与之同量级"
if [[ -n "${NODE_PID:-}" ]] && kill -0 "$NODE_PID" 2>/dev/null; then
  # 起一个长 Orbit 把飞机带进 OFFBOARD。客户端放后台：节点被杀后它会失联，
  # 那是预期行为，结果码不看。
  $CLI orbit --radius 10 --altitude 12 --speed 2 --revolutions 5 \
    --timeout 180 > "$OUT/cli_H.log" 2>&1 & CLI_PID=$!
  # 等飞控真的进了 OFFBOARD 再动手，别按秒数猜
  if timeout 60 python3 "$TOOLS/watch_vehicle_state.py" --duration 50 --expect-nav 14 \
       > "$OUT/H_wait_offboard.log" 2>&1; then
    ok "H: 已进入 OFFBOARD（前置条件成立）"
    # 观测器先起来，再杀节点。t0_epoch 由观测器自己打印，用它和 kill 时刻对齐 ——
    # 用「启动脚本前 date 一次」估 t0 会有 1~2s 的 rclpy 启动误差，
    # 对 5s 量级的测量不可接受。
    python3 "$TOOLS/watch_vehicle_state.py" --duration 25 --label "H 杀节点后" \
      --csv "$OUT/H_provoke.csv" > "$OUT/H_provoke.log" 2>&1 & W_PID=$!
    sleep 4
    T_KILL=$(date +%s.%N)
    log "  SIGKILL 机载节点（PID ${NODE_PID}），kill 时刻 ${T_KILL}"
    kill -9 "$NODE_PID" 2>/dev/null
    pkill -9 -f autopilot_iface 2>/dev/null
    NODE_PID=""
    wait "$W_PID" 2>/dev/null || true
    kill -9 "$CLI_PID" 2>/dev/null; wait "$CLI_PID" 2>/dev/null || true
    sed 's/^/       /' "$OUT/H_provoke.log" | tee -a "$REPORT"
    # 从时间线里取「nav 离开 OFFBOARD」那一跳，算出相对 kill 时刻的延迟
    LAT=$(python3 - "$OUT/H_provoke.log" "$T_KILL" <<'PY'
import re, sys
log, t_kill = sys.argv[1], float(sys.argv[2])
t0 = None
for line in open(log, encoding="utf-8", errors="replace"):
    m = re.match(r"t0_epoch=([0-9.]+)", line.strip())
    if m:
        t0 = float(m.group(1))
    # 形如：  [  6.23s] nav OFFBOARD -> AUTO_RTL
    m = re.search(r"\[\s*([0-9.]+)s\]\s+nav OFFBOARD -> (\S+)", line)
    if m and t0 is not None:
        print(f"{t0 + float(m.group(1)) - t_kill:.2f} {m.group(2)}")
        break
PY
)
    if [[ -n "${LAT:-}" ]]; then
      LAT_S=${LAT%% *}; LAT_TO=${LAT##* }
      log "  接管延迟 ${LAT_S}s，接管后模式 ${LAT_TO}"
      ok "H: 飞控接管了（模式 -> ${LAT_TO}）"
      # 断言带**刻意给宽**，不要收窄成「约等于 COM_OF_LOSS_T」。
      #
      # 理由：这个延迟是用**墙钟**量的，而超时是按**飞控时钟**计的，
      # 而 lockstep 仿真时钟会离散前跳（实测单次 1.93 s，见 §7.4）。
      # 倒计时期间跳一次，墙钟延迟就被压掉相应的量。
      # 实测值：2026-07-31 act6 一轮量到 2.94 s（容限 5.0 s）——
      # 差的那 2 秒与观测到的跳变幅度同量级。
      # 本场景的实质断言是「接管到底发生了没有」（旧代码根本不会接管），
      # 延迟只作量级校验，收窄只会换来假红。
      # 下界 1s 是为了排除「接管其实由别的原因触发」这种巧合。
      HI=$(awk -v t="$SITL_COM_OF_LOSS_T" 'BEGIN{print t+7}')
      if awk -v l="$LAT_S" -v hi="$HI" 'BEGIN{exit !(l >= 1.0 && l <= hi)}'; then
        ok "H: 接管延迟 ${LAT_S}s 落在 [1.0, ${HI}]s —— 与 COM_OF_LOSS_T 同量级"
      else
        bad "H: 接管延迟 ${LAT_S}s 不在 [1.0, ${HI}]s，触发原因可疑"
      fi
    else
      bad "H: 25s 内飞控**没有**接管 —— offboard 过期检测失效（正是本场景要防的回归）"
    fi
  else
    bad "H: 50s 内没进 OFFBOARD，前置条件不成立，本场景未测到"
    kill -9 "$CLI_PID" 2>/dev/null; wait "$CLI_PID" 2>/dev/null || true
  fi
else
  bad "H: 节点不在运行，前置条件不成立"
fi

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
