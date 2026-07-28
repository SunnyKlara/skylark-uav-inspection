#!/usr/bin/env bash
# SITL 冒烟测试 —— 无人值守，跑完自动清理，输出结论
#
# 验证链路：PX4 SITL(gz_x500) <--uXRCE-DDS--> MicroXRCEAgent <--> ROS 2
#
# 这是 S1 阶段的第一个客观验收点。它回答三个问题：
#   1. PX4 SITL 能不能起来（含 Gazebo 物理，可 headless）
#   2. DDS 桥能不能通（ROS 2 侧能否看到 /fmu/out/* 话题）
#   3. 话题频率是否符合 dds_topics.yaml 的 rate_limit 预期
#
# 用法：
#   bash smoke_test.sh              # 默认 headless（软渲染机器上更快更稳）
#   bash smoke_test.sh --gui        # 带 Gazebo 图形界面
#   bash smoke_test.sh --duration 60
#
# 退出码：0 = 全部通过；非 0 = 有检查项失败

set -uo pipefail

HEADLESS=1
DURATION=45
MODEL=gz_x500

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gui)      HEADLESS=0; shift ;;
    --duration) DURATION="${2:?}"; shift 2 ;;
    --model)    MODEL="${2:?}"; shift 2 ;;
    -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

RESULT_DIR="${SMOKE_OUT_DIR:-/tmp/skylark_smoke}"
mkdir -p "$RESULT_DIR"
AGENT_LOG="$RESULT_DIR/agent.log"
PX4_LOG="$RESULT_DIR/px4.log"
REPORT="$RESULT_DIR/report.txt"
: > "$REPORT"

PASS=0
FAIL=0
declare -A RATE_OF   # base 名 -> 仿真时钟发布频率，第 4 节量、第 5 节算带宽用
say()  { echo "$*" | tee -a "$REPORT"; }
ok()   { say "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { say "  [FAIL] $*"; FAIL=$((FAIL+1)); }
info() { say "         $*"; }

# 把逻辑话题名解析成运行时真实存在的话题名。
#
# PX4 v1.17 起，dds_topics.yaml 里一个 _v 后缀都没有（实测 grep 计数 0），
# 后缀是运行时按每条消息的 MESSAGE_VERSION 常量拼上去的：
#   VehicleLocalPosition  MESSAGE_VERSION=1 -> /fmu/out/vehicle_local_position_v1
#   VehicleStatus         MESSAGE_VERSION=1 -> /fmu/out/vehicle_status_v1
#   VehicleAttitude       MESSAGE_VERSION=0 -> /fmu/out/vehicle_attitude
# 也就是同一份 yaml 下，有的话题带后缀有的不带，取决于那条消息的版本号。
# 写死名字必然踩空（2026-07-27 实测：查不到 local_position / status，
# 看着像 DDS 桥没通，其实桥好得很，是断言名过时了）。
# 按 ^/fmu/out/<base>(_v[0-9]+)?$ 匹配，将来版本号再涨也不用改脚本。
resolve_topic() {
  local base="$1" t
  for t in "${FMU_TOPICS[@]:-}"; do
    if [[ "$t" =~ ^/fmu/out/${base}(_v[0-9]+)?$ ]]; then echo "$t"; return 0; fi
  done
  return 1
}

# 采 Gazebo 的实时率（real-time factor）。
#
# 存在的理由：lockstep 模式下 PX4 的时间由 Gazebo 步进驱动（px4.log 里的
# lockstep_scheduler），仿真跑不到实时的话，ROS 2 侧所有墙钟频率都会等比降低。
# 不采这个值，就没法区分「DDS 桥丢速」和「仿真本身慢」—— 两者在
# ros2 topic hz 的输出里长得一模一样。
probe_rtf() {
  RTF=""
  command -v gz >/dev/null 2>&1 || { info "gz CLI 不可用，跳过 RTF 采样"; return 0; }
  local st out t0 t1
  st=$(timeout 8 gz topic -l 2>/dev/null | grep -m1 -E '^/world/[^/]+/stats$' || true)
  if [[ -z "$st" ]]; then
    info "未找到 Gazebo stats 话题，跳过 RTF 采样"
    return 0
  fi
  out=$(timeout 10 gz topic -e -t "$st" -n 5 2>/dev/null || true)
  RTF=$(echo "$out" | grep -m1 'real_time_factor' | awk '{print $2}')
  if [[ -z "$RTF" ]]; then
    # 兜底：stats 消息里没有 real_time_factor 字段时，用 sim_time 差分估
    t0=$(echo "$out" | grep -A2 -m1 '^sim_time' | grep -m1 'sec:' | awk '{print $2}')
    sleep 5
    t1=$(timeout 10 gz topic -e -t "$st" -n 1 2>/dev/null \
         | grep -A2 -m1 '^sim_time' | grep -m1 'sec:' | awk '{print $2}')
    if [[ -n "$t0" && -n "$t1" ]]; then
      RTF=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.3f",(b-a)/5}')
      info "RTF 由 sim_time 差分估算（5s 墙钟窗口）: ${RTF}"
    fi
  fi
  [[ -n "$RTF" ]] && info "Gazebo stats 话题: ${st}"
  return 0
}

cleanup() {
  say ""
  say "--- 清理 ---"
  [[ -n "${PX4_PID:-}"   ]] && kill -TERM "$PX4_PID"   2>/dev/null && info "已停 PX4 (pid $PX4_PID)"
  [[ -n "${AGENT_PID:-}" ]] && kill -TERM "$AGENT_PID" 2>/dev/null && info "已停 Agent (pid $AGENT_PID)"
  sleep 2
  pkill -f 'px4 ' 2>/dev/null
  pkill -f MicroXRCEAgent 2>/dev/null
  pkill -f 'gz sim' 2>/dev/null
  pkill -f 'ruby.*gz' 2>/dev/null
  sleep 1
  info "清理完成"
}
trap cleanup EXIT

say "=== SITL 冒烟测试 $(date '+%Y-%m-%d %H:%M:%S') ==="
say "模型: ${MODEL}   headless: ${HEADLESS}   观测时长: ${DURATION}s"
say ""

# ---------- 0. 环境 ----------
say "--- 0. 环境前置 ---"
# ROS 2 的 setup.bash 不是 `set -u` 安全的 —— 它内部引用 AMENT_TRACE_SETUP_FILES
# 等未定义变量，在 set -u 下 source 会直接报 "unbound variable" 并退出。
# 所以 source 前后必须临时关闭 -u。实测踩过（2026-07-27）。
set +u
# shellcheck disable=SC1090
[[ -f "$HOME/.skylark_env.sh" ]] && source "$HOME/.skylark_env.sh"
set -u
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"

[[ -n "${ROS_DISTRO:-}" ]] && ok "ROS 2 环境已加载 (${ROS_DISTRO})" || bad "ROS 2 环境未加载"
command -v MicroXRCEAgent >/dev/null && ok "MicroXRCEAgent 可用" || bad "MicroXRCEAgent 缺失"
[[ -x "${PX4_DIR}/build/px4_sitl_default/bin/px4" ]] \
  && ok "PX4 SITL 已编译" \
  || bad "PX4 SITL 未编译（先 cd ${PX4_DIR} && make px4_sitl_default）"
n_if=$(ros2 interface list 2>/dev/null | grep -c skylark_flight_msgs)
[[ "$n_if" == 14 ]] && ok "skylark_flight_msgs 已注册 (14 个)" || bad "skylark 接口数 = ${n_if}，期望 14"

if [[ "$FAIL" -gt 0 ]]; then
  say ""
  say "前置检查未通过，不继续。"
  exit 1
fi

# 清掉可能残留的旧进程，避免端口冲突
pkill -f MicroXRCEAgent 2>/dev/null
pkill -f 'px4 ' 2>/dev/null
sleep 2

# ---------- 1. Agent ----------
say ""
say "--- 1. 启动 Micro XRCE-DDS Agent (udp4 -p 8888) ---"
MicroXRCEAgent udp4 -p 8888 > "$AGENT_LOG" 2>&1 &
AGENT_PID=$!
sleep 3
if kill -0 "$AGENT_PID" 2>/dev/null; then
  ok "Agent 运行中 (pid ${AGENT_PID})"
else
  bad "Agent 启动失败，日志末尾："
  tail -5 "$AGENT_LOG" | sed 's/^/         /' | tee -a "$REPORT"
  exit 1
fi

# ---------- 2. PX4 SITL ----------
say ""
say "--- 2. 启动 PX4 SITL + Gazebo (${MODEL}) ---"
info "首次启动 Gazebo 需下载模型资源，可能较慢"
# ⚠ 千万不要设 PX4_GZ_STANDALONE=0。
#
# px4-rc.gzsim 的判断是 `if [ -z "${PX4_GZ_STANDALONE}" ]` —— 判的是"是否为空"，
# 不是判真假。传 "0" 是非空字符串，会让 PX4 走 standalone 分支：
# 既不启动 Gazebo，也不去探测 world 名，最后轮询 /world//scene/info 必然超时，
# 报 "Timed out waiting for Gazebo world"。
# 要让 PX4 自己拉起 Gazebo，就必须让这个变量完全不存在。
# 实测踩过（2026-07-27），排查方向很容易被误导到 Gazebo 本身。
#
# HEADLESS 同理是判空：`if [ -z "${HEADLESS}" ]` 才启动 GUI。
# 所以 HEADLESS=1（任何非空值）都能抑制 GUI。
(
  cd "$PX4_DIR" || exit 1
  if [[ "$HEADLESS" == 1 ]]; then
    HEADLESS=1 make px4_sitl "$MODEL"
  else
    make px4_sitl "$MODEL"
  fi
) > "$PX4_LOG" 2>&1 &
PX4_PID=$!

# 等 PX4 就绪：日志出现 DDS 数据写入器创建，或出现 px4 启动完成标志
say "  等待 PX4 就绪（最多 180s）..."
READY=0
for i in $(seq 1 180); do
  if grep -qE 'uxrce_dds_client.*(synchronized|successfully created)' "$PX4_LOG" 2>/dev/null; then
    READY=1; break
  fi
  if ! kill -0 "$PX4_PID" 2>/dev/null; then
    bad "PX4 进程已退出（第 ${i}s）"
    break
  fi
  sleep 1
done

if [[ "$READY" == 1 ]]; then
  ok "PX4 uxrce_dds_client 已与 Agent 建立连接"
  # PX4 把 "pxh> " 提示符不带换行地写进 stdout，整段日志会粘成一条巨型行，
  # 直接 grep 整行会往报告里灌几百个 pxh>。用 -o 只取匹配片段就绕过了。
  #
  # 注意别写成 `sed ... | grep -m1 -o ... || echo 兜底`：grep -m1 命中即退出，
  # 上游 sed 写管道时吃 SIGPIPE(141)，pipefail 把整条管道判为失败，
  # 于是兜底的 echo 也跟着执行，两段输出一起被命令替换捕获，
  # 报告里就会多出一行没缩进的假告警。实测踩过（2026-07-27）。
  # 单条命令没有管道，也就没有这个问题。
  info "$(grep -m1 -o 'synchronized with time offset [0-9]*us' "$PX4_LOG" 2>/dev/null \
          || echo '未取到时间同步偏移')"
else
  bad "180s 内未检测到 DDS 连接。PX4 日志末 15 行："
  sed 's/pxh> //g' "$PX4_LOG" | tail -15 | sed 's/^/         /' | tee -a "$REPORT"
fi

# ---------- 3. ROS 2 侧话题 ----------
say ""
say "--- 3. ROS 2 侧话题可见性 ---"
sleep 5
mapfile -t FMU_TOPICS < <(ros2 topic list 2>/dev/null | grep '^/fmu/' | sort)
say "  /fmu/ 话题总数: ${#FMU_TOPICS[@]}"
if [[ "${#FMU_TOPICS[@]}" -ge 10 ]]; then
  ok "话题已桥接（${#FMU_TOPICS[@]} 个）"
else
  bad "话题数偏少（${#FMU_TOPICS[@]}），DDS 桥可能未完全建立"
fi
for t in "${FMU_TOPICS[@]}"; do info "$t"; done

# ---------- 4. 关键话题频率 ----------
say ""
say "--- 4. 关键话题频率（仿真时钟发布率；上限读 dds_topics.yaml，下限为可用性要求）---"
probe_rtf
if [[ -n "${RTF:-}" ]]; then
  if awk -v r="$RTF" 'BEGIN{exit !(r>=0.5)}'; then
    ok "Gazebo 实时率 RTF=${RTF}（≥0.5，仿真跟得上墙钟）"
  else
    bad "Gazebo 实时率 RTF=${RTF} 偏低（<0.5）—— 仿真跑不到实时，下面所有墙钟频率会等比降低"
  fi
else
  info "RTF 未取到，下面的频率按 rate_limit 原值直接比较"
fi

# 从「正在跑的这份」build 对应的 dds_topics.yaml 里读上限。
#
# 不写死数字的理由是我已经栽过一次：期望值抄自 Windows 侧的 PX4 checkout
# (8e7b370)，而实际跑的是 WSL 侧的 v1.17.0 (d6f12ad1c4)，两份 yaml 不一样 ——
# Windows 那份给 vehicle_attitude 写了 rate_limit: 50，WSL 这份压根没这行。
# 于是测试报「100 Hz 偏离期望 50」，其实是断言的真值来源错了。
# 读文件就没有这个问题：$PX4_DIR 就是编译出当前二进制的那棵树。
yaml_rate_limit() {
  local base="$1" f="${PX4_DIR}/src/modules/uxrce_dds_client/dds_topics.yaml"
  [[ -f "$f" ]] || return 1
  awk -v t="/fmu/out/${base}" '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*-[[:space:]]*topic:/ {
      cur = $0; sub(/.*topic:[[:space:]]*/, "", cur); inblk = (cur == t); next
    }
    inblk && /rate_limit:/ { v = $2; sub(/\.$/, "", v); print v; exit }
  ' "$f"
}

# 用消息内的 timestamp 反推「仿真时钟下的发布频率」，而不是数订阅端每秒收到几条。
#
# 为什么不能用 ros2 topic hz：它量的是 rclpy 订阅端的到达率。/fmu/out/* 是
# best-effort，订阅端跟不上时消息会排队甚至丢，读数系统性偏低且随机器负载乱跳。
# 实测（2026-07-27）：同一个健康系统，vehicle_local_position 两轮分别报
# 50.004 Hz 和 21.427 Hz，而两轮 RTF 都是 1.0 —— 差异全在订阅端。
# 同时测到订阅端落后最新消息 4~8 秒（在读积压），这才是低读数的真因。
#
# timestamp 是 PX4 自己的时钟，不受订阅端延迟影响：消息晚到但时间戳不变。
# 所以 (条数-1)/时间戳跨度 = 真实发布频率，而且天然在仿真时钟下，
# RTF 这个变量直接从判据里消失了。
#
# 估计量用「剔除离群后的截尾均值」，不用众数也不用裸跨度：
#   - 众数不行：限流器作用在量化的源上时间隔是双峰的（lpos 是 16ms/24ms
#     交替，均值 20ms=50Hz），取众数会挑中单峰，算出 62.5 Hz 这种
#     超过自身上限的荒谬值。
#   - 裸跨度不行：样本里偶发非单调时间戳会污染首末差。
# 估计量单独成函数，方便脱离仿真用合成数据做单测
#（用例在同目录 smoke_test_units.sh：双峰间隔、卡顿、非单调、样本不足）。
# 入参：每行一个微秒时间戳的文件。输出一行："频率 离群数 非单调数"
_trimmed_hz() {
  awk '
    NR == 1 { prev = $1; next }
    { d = $1 - prev; prev = $1; if (d > 0) dd[++k] = d; else nonmono++ }
    END {
      if (k < 5) { print "0 0 0"; exit }
      for (i = 1; i <= k; i++) s[i] = dd[i]
      for (i = 1; i < k; i++) for (j = i+1; j <= k; j++) if (s[j] < s[i]) { t=s[i]; s[i]=s[j]; s[j]=t }
      med = s[int((k+1)/2)]
      lo = med * 0.2; hi = med * 5
      sum = 0; m = 0; out = 0
      for (i = 1; i <= k; i++) {
        if (dd[i] >= lo && dd[i] <= hi) { sum += dd[i]; m++ } else out++
      }
      printf "%.3f %d %d\n", (m > 0 ? 1e6 / (sum / m) : 0), out, nonmono + 0
    }
  ' "$1"
}

# 结果写全局变量：SIM_HZ / CATCHUP / N_SAMP / N_OUT / N_NONMONO
sim_hz() {
  local topic="$1" nsamp="$2" tmo="$3" f
  SIM_HZ=""; CATCHUP="?"; N_SAMP=0; N_OUT=0; N_NONMONO=0
  # 订阅时显式声明 VOLATILE，直接绕开历史回放。
  #
  # PX4 发布端 durability 是 TRANSIENT_LOCAL（ros2 topic info -v 可查），
  # 默认订阅会先收到写端缓存的**最旧**历史消息（实测 lpos 起始落后 4.8s、
  # status 落后 14.6s，随后才单调收敛到 ±0.03s）。
  # QoS 兼容规则只要求订阅端的 durability 不强于发布端，所以声明 VOLATILE
  # 依然能匹配上，但不会收到历史 —— 一上来就是实时消息。
  #
  # 上一版不知道有这个选项，改用「采 2 倍样本、丢掉前一半」来排空，
  # 采样时间翻倍还得额外维护一套逻辑。现在两边都省了。
  # measure_dds_topics.py 用 rclpy 走的是同一条路（DurabilityPolicy.VOLATILE），
  # 两个工具的测量机制保持一致。
  #
  # 附带教训：别用 `ros2 topic echo --once` 去取"最新一条"做参照 ——
  # 在 TRANSIENT_LOCAL 话题上它返回的是缓存里最旧的那条。第一版这么写，
  # 于是 vehicle_status 报出 18.1s 的假"积压"。
  # 每条样本打上到达时刻，落成两列："到达墙钟us  消息timestamp us"。
  # 必须记到达时刻才能算追赶倍数：只用 date 卡住整个管道的首尾是不行的，
  # 那段墙钟里含 rclpy 建节点 + DDS 发现的好几秒空转（一条消息都没到），
  # 会把倍数压到 0.48 这种明显低于 RTF 的假值。实测踩过（2026-07-27）。
  local f_pair sim_span wall_span
  f_pair=$(mktemp); f=$(mktemp)
  timeout "$tmo" ros2 topic echo --qos-durability volatile --qos-reliability best_effort \
      --field timestamp "$topic" 2>/dev/null \
    | python3 -u -c "
import sys, time
want = $nsamp
n = 0
for line in sys.stdin:
    line = line.strip()
    if not line.isdigit():
        continue
    print(f'{int(time.time() * 1e6)} {line}', flush=True)
    n += 1
    if n >= want:
        break
" > "$f_pair" || true
  awk '{print $2}' "$f_pair" > "$f"
  # 追赶倍数 = 这批样本的仿真时间跨度 ÷ 它们的到达墙钟跨度。
  # 比值不受 PX4↔本机时钟偏移影响（偏移在各自相减里抵消），所以比
  # 「末条时间戳 vs 墙钟」可靠 —— 后者把未知的几秒时钟偏移和真实延迟
  # 混在一起分不开（实测偏移到 -4.7s，PX4 时钟超前，原因未查明）。
  #   ≈RTF  -> 实时消费，正常
  #   >RTF  -> 在排积压。改用 VOLATILE 之后不该再出现，若出现说明订阅端跟不上
  #
  # 墙钟跨度必须按**样本到达时刻**算，不能用整个管道的首尾时间 ——
  # 后者含 rclpy 建节点与 DDS 发现的数秒空转（一条消息都没到），
  # 会把倍数压到 0.48 这种低于 RTF 的假值。实测踩过（2026-07-27）。
  sim_span=$(awk 'NR==1{a=$2} END{printf "%.3f", ($2-a)/1e6}' "$f_pair")
  wall_span=$(awk 'NR==1{a=$1} END{printf "%.3f", ($1-a)/1e6}' "$f_pair")
  CATCHUP=$(awk -v s="$sim_span" -v w="$wall_span" \
    'BEGIN{ printf "%.2f", (w > 0 ? s/w : 0) }')
  rm -f "$f_pair"
  N_SAMP=$(wc -l < "$f")
  if [[ "$N_SAMP" -lt 15 ]]; then rm -f "$f"; return 1; fi
  read -r SIM_HZ N_OUT N_NONMONO < <(_trimmed_hz "$f")
  rm -f "$f"
  [[ -n "$SIM_HZ" && "$SIM_HZ" != "0.000" ]]
}

# 频率断言。语义上有两条独立的线，混在一起判会得出错误结论：
#
#   上限 = yaml 的 rate_limit。这是「限流器的闸门」，不是目标值。
#          实际频率 = min(源频率, rate_limit)。所以低于上限完全正常
#          （vehicle_status 静止时只有 ~2 Hz，闸门开到 5 也上不去），
#          超过上限才是 bug —— 说明限流没生效。没有 rate_limit 行 = 不限流。
#
#   下限 = 我们自己的可用性要求。这条 yaml 里没有，必须显式定义：
#          姿态/位置低于 20 Hz 就没法拿来做位置环和 offboard 控制。
#
# 两条线都在仿真时钟下比，不乘 RTF —— sim_hz 量的就是仿真时钟频率，
# rate_limit 也是仿真时钟下的值，量纲本来就一致。
# 订阅端延迟单独作为 info 报出来：它反映的是本机 Python 订阅端的吞吐，
# 不是飞控或桥的问题，但对我们后面写 ROS 2 节点有参考价值（100 Hz 的话题
# 用 rclpy 直接订会积压，得降频或换 rclcpp）。
check_rate() {
  local base="$1" floor="$2" nsamp="$3" tmo="$4" topic limit ceil
  if ! topic=$(resolve_topic "$base"); then
    bad "/fmu/out/${base}  ROS 2 侧不存在（已按 _v[0-9]+ 后缀模糊匹配）"
    return
  fi
  if ! sim_hz "$topic" "$nsamp" "$tmo"; then
    bad "${topic}  ${tmo}s 内只采到 ${N_SAMP} 条时间戳，样本不足"
    return
  fi
  RATE_OF["$base"]="$SIM_HZ"
  limit=$(yaml_rate_limit "$base" || true)
  if awk -v a="$SIM_HZ" -v f="$floor" 'BEGIN{ exit !(a < f) }'; then
    bad "${topic}  ${SIM_HZ} Hz 低于可用下限 ${floor}（仿真时钟，${N_SAMP} 条样本）"
    return
  fi
  if [[ -n "$limit" ]]; then
    ceil=$(awk -v v="$limit" 'BEGIN{ printf "%.2f", v*1.2 }')
    if awk -v a="$SIM_HZ" -v c="$ceil" 'BEGIN{ exit !(a > c) }'; then
      bad "${topic}  ${SIM_HZ} Hz 超过 rate_limit ${limit}（含 20% 容差上界 ${ceil}）—— 限流未生效"
      return
    fi
    ok "${topic}  ${SIM_HZ} Hz（yaml 上限 ${limit}，可用下限 ${floor}）"
  else
    ok "${topic}  ${SIM_HZ} Hz（yaml 未限流，可用下限 ${floor}）"
  fi
  info "  ↑ ${N_SAMP} 条样本，离群 ${N_OUT} 个，非单调 ${N_NONMONO} 个，追赶倍数 ${CATCHUP}（≈RTF 为实时消费，>RTF 为在排历史积压）"
}
#          话题                     下限  采样条数  超时
check_rate vehicle_local_position     20     200      30
check_rate vehicle_attitude           20     200      30
check_rate vehicle_status            0.5      25      30

# ---------- 5. 实际带宽（校准 SERIAL_BUDGET.md 的估算）----------
say ""
say "--- 5. 实测带宽（用于校准 docs/SERIAL_BUDGET.md 的估算值）---"
# 带宽不能直接取 ros2 topic bw 的 B/s —— 那是订阅端的接收速率，
# 订阅端积压时同样偏低（和上面 ros2 topic hz 一个毛病）。
# 链路预算要的是「消息大小 × 发布频率」：大小从 bw 的 mean size 取（这个值稳定，
# 不受延迟影响），频率用上面 sim_hz 量到的仿真时钟发布率。
# 注意这是纯 payload，不含 DDS/XRCE 的帧头与 QoS 开销，作为下限估算用。
for base in vehicle_local_position vehicle_attitude vehicle_status; do
  if ! t=$(resolve_topic "$base"); then
    info "/fmu/out/${base}  话题不存在，跳过"
    continue
  fi
  szline=$(timeout 15 ros2 topic bw "$t" 2>/dev/null | grep -m1 'Message size mean' || true)
  if [[ -z "$szline" ]]; then
    info "${t}  未取到消息大小"
    continue
  fi
  # "Message size mean: 0.22 KB" / "... 56 B" -> 统一成字节
  bytes=$(echo "$szline" | awk '
    { for (i = 1; i <= NF; i++) if ($i == "mean:") { v = $(i+1); u = $(i+2); break } }
    END {
      mult = (u == "KB") ? 1024 : (u == "MB") ? 1048576 : 1
      printf "%.0f", v * mult
    }')
  rate="${RATE_OF[$base]:-}"
  if [[ -n "$rate" ]]; then
    info "$(awk -v t="$t" -v b="$bytes" -v r="$rate" \
      'BEGIN{ printf "%-42s %5s B × %7.2f Hz = %8.2f kB/s (%.1f kbps, 纯 payload)", \
              t, b, r, b*r/1000, b*r*8/1000 }')"
  else
    info "${t}  ${bytes} B/条（未取到发布频率，无法算带宽）"
  fi
done

# ---------- 6. 观测一段时间确认稳定 ----------
say ""
say "--- 6. 稳定性观测 ${DURATION}s ---"
sleep "$DURATION"
if kill -0 "$PX4_PID" 2>/dev/null; then
  ok "PX4 存活 ${DURATION}s 未崩溃"
else
  bad "PX4 在观测期内退出"
fi
if kill -0 "$AGENT_PID" 2>/dev/null; then
  ok "Agent 存活 ${DURATION}s"
else
  bad "Agent 在观测期内退出"
fi

# ---------- 结论 ----------
say ""
say "=== 结论 ==="
say "  通过 ${PASS} 项，失败 ${FAIL} 项"
say "  Gazebo 实时率 RTF: ${RTF:-未取到}（第 4 节的频率是仿真时钟发布率，与 RTF 无关）"
say "  日志: ${PX4_LOG} / ${AGENT_LOG}"
say "  报告: ${REPORT}"
[[ "$FAIL" == 0 ]] && say "  RESULT=PASS" || say "  RESULT=FAIL"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
