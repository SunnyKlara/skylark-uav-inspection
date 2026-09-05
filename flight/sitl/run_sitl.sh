#!/usr/bin/env bash
# 一键启动 Skylark SITL 仿真环境。
#
# 起三个进程（tmux 三面板，或不带 tmux 时给出手动指令）：
#   1. Micro XRCE-DDS Agent（UDP 8888）
#   2. PX4 SITL + Gazebo
#   3. 交互 shell（已 source 好 ROS 2 环境）
#
# 前置：先跑过 bootstrap_wsl2.sh
#
# 用法：
#   bash run_sitl.sh                      # 默认 gz_x500，带图形界面
#   bash run_sitl.sh --headless           # 不出图形（AMD/软渲染卡时用）
#   bash run_sitl.sh --model gz_x500_depth  # 换机型
#   bash run_sitl.sh --stop               # 停掉所有相关进程

set -uo pipefail

MODEL="gz_x500"
HEADLESS=0
STOP=0
SESSION="skylark_sitl"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --headless) HEADLESS=1; shift ;;
    --model)    MODEL="${2:?--model 需要参数}"; shift 2 ;;
    --stop)     STOP=1; shift ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

BOLD=$'\033[1m'; RED=$'\033[31m'; YLW=$'\033[33m'; RST=$'\033[0m'
die() { echo "${RED}错误:${RST} $*" >&2; exit 1; }

ENVFILE="${HOME}/.skylark_env.sh"
[[ -f "$ENVFILE" ]] || die "找不到 ${ENVFILE}。先跑 bootstrap_wsl2.sh"
# ROS 2 的 setup.bash 不是 `set -u` 安全的（内部引用 AMENT_TRACE_SETUP_FILES 等
# 未定义变量），在 set -u 下 source 会报 "unbound variable" 直接退出。
# 必须临时关闭 -u。实测踩过（2026-07-27）。
set +u
# shellcheck disable=SC1090
source "$ENVFILE"
set -u

PX4_DIR="${PX4_DIR:-${HOME}/PX4-Autopilot}"

# ---------- 停止 ----------
if [[ "$STOP" == 1 ]]; then
  echo "停止 SITL 相关进程..."
  tmux kill-session -t "$SESSION" 2>/dev/null && echo "  tmux 会话已关闭"
  pkill -f MicroXRCEAgent 2>/dev/null && echo "  MicroXRCEAgent 已停止"
  pkill -f 'px4' 2>/dev/null && echo "  px4 已停止"
  pkill -f 'gz sim' 2>/dev/null && echo "  gz sim 已停止"
  pkill -f 'ruby.*gz' 2>/dev/null || true
  echo "完成"
  exit 0
fi

# ---------- 前置检查 ----------
[[ -d "$PX4_DIR" ]] || die "找不到 PX4 目录 ${PX4_DIR}。先跑 bootstrap_wsl2.sh"
command -v MicroXRCEAgent >/dev/null 2>&1 || die "MicroXRCEAgent 未安装。先跑 bootstrap_wsl2.sh"
command -v gz >/dev/null 2>&1 || echo "${YLW}警告:${RST} 未找到 gz 命令，Gazebo 可能未安装"

# 已在跑的进程会导致端口冲突，先提示
if pgrep -f MicroXRCEAgent >/dev/null 2>&1; then
  echo "${YLW}警告:${RST} MicroXRCEAgent 已在运行。只允许一个 agent 占用同一通道。"
  echo "         先执行 bash run_sitl.sh --stop"
  exit 1
fi

# px4-rc.gzsim 里这两个变量都是「判空」而非判真假：
#   if [ -z "${PX4_GZ_STANDALONE}" ]  -> 空才由 PX4 自己启动 Gazebo
#   if [ -z "${HEADLESS}" ]           -> 空才启动 gz GUI
# 所以：
#   - 绝不能设 PX4_GZ_STANDALONE=0，"0" 是非空值，会让 PX4 以为 Gazebo 由外部启动，
#     结果既不拉起 Gazebo 也探测不到 world 名，最终 "Timed out waiting for Gazebo world"。
#     实测踩过（2026-07-27）。要 PX4 自己启动 Gazebo，就让它完全不存在。
#   - 需要无界面时才把 HEADLESS=1 作为命令前缀传进去；不需要时一个字都不传。
# 下面这个 HEADLESS 是本脚本的局部变量，未 export，不会泄漏给子进程。
PX4_CMD="make px4_sitl ${MODEL}"
[[ "$HEADLESS" == 1 ]] && PX4_CMD="HEADLESS=1 ${PX4_CMD}"

# ---------- 有 tmux：自动三面板 ----------
if command -v tmux >/dev/null 2>&1; then
  tmux has-session -t "$SESSION" 2>/dev/null && die "tmux 会话 ${SESSION} 已存在。先 --stop"

  tmux new-session  -d -s "$SESSION" -n sitl
  tmux send-keys    -t "${SESSION}:sitl.0" "MicroXRCEAgent udp4 -p 8888" C-m

  tmux split-window -t "${SESSION}:sitl" -h
  tmux send-keys    -t "${SESSION}:sitl.1" "cd ${PX4_DIR} && ${PX4_CMD}" C-m

  tmux split-window -t "${SESSION}:sitl.1" -v
  tmux send-keys    -t "${SESSION}:sitl.2" "source ${ENVFILE}" C-m
  tmux send-keys    -t "${SESSION}:sitl.2" "echo '等 PX4 起来后执行： ros2 topic list | grep /fmu/'" C-m

  tmux select-pane -t "${SESSION}:sitl.2"

  cat <<EOF

  ${BOLD}SITL 已在 tmux 会话 '${SESSION}' 中启动${RST}

  面板 0（左）  : XRCE Agent
  面板 1（右上）: PX4 SITL + Gazebo（${MODEL}$([[ "$HEADLESS" == 1 ]] && echo ", headless"))
  面板 2（右下）: 交互 shell

  附加会话:  tmux attach -t ${SESSION}
  切换面板:  Ctrl+b 然后方向键
  脱离会话:  Ctrl+b 然后 d
  全部停止:  bash run_sitl.sh --stop

  ${BOLD}验证链路${RST}（在面板 2）:
      ros2 topic list | grep /fmu/
      ros2 topic hz /fmu/out/vehicle_local_position
      ros2 interface list | grep skylark

  ${BOLD}跑官方 offboard 示例${RST}:
      ros2 run px4_ros_com offboard_control

EOF
  tmux attach -t "$SESSION"
  exit 0
fi

# ---------- 无 tmux：给手动指令 ----------
cat <<EOF

${YLW}未安装 tmux${RST}，请手动开三个终端（建议 sudo apt install tmux 后重跑本脚本）。

终端 1:
    MicroXRCEAgent udp4 -p 8888

终端 2:
    cd ${PX4_DIR}
    ${PX4_CMD}

终端 3:
    source ${ENVFILE}
    ros2 topic list | grep /fmu/
    ros2 run px4_ros_com offboard_control

EOF
exit 0
