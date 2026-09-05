#!/usr/bin/env bash
# 验证「Gazebo Harmonic 相机图像 -> ROS 2 Humble」这条链，并量出实际帧率。
#
# 这是项目风险清单里最后一条未验证项：ROS 2 Humble 官方配对 Gazebo Fortress，
# 本项目锁 Harmonic。OSRF 仓库提供了 ros-humble-ros-gzharmonic 变体，
# 本脚本验证它真的能用，并回答两个决定 S1 感知链可行性的问题：
#   Q1 gz 侧的图像话题叫什么（默认命名由 world/model/link/sensor 拼出来，必须实测）
#   Q2 这台机器（只有 llvmpipe 软渲染）能跑出多少帧率
#      —— 1280x960@30Hz 的相机在软渲染下大概率跑不满，这直接决定
#         感知节点该按什么频率设计，以及要不要降分辨率
#
# 用法： bash test_camera_bridge.sh [输出目录] [观测秒数]

set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)

OUT="${1:-/tmp/skylark_camera}"
DUR="${2:-25}"
mkdir -p "$OUT"
PX4_LOG="$OUT/px4.log"; REPORT="$OUT/report.txt"
FIFO="/tmp/skylark_cam_fifo.$$"
: > "$REPORT"
PASS=0; FAIL=0
log()  { echo "$*" | tee -a "$REPORT"; }
ok()   { log "  [PASS] $*"; PASS=$((PASS+1)); }
bad()  { log "  [FAIL] $*"; FAIL=$((FAIL+1)); }

cleanup() {
  log ""; log "--- 清理 ---"
  [[ -n "${BRIDGE_PID:-}" ]] && kill -TERM "$BRIDGE_PID" 2>/dev/null
  sleep 1; pkill -f image_bridge 2>/dev/null
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
MODEL="${MODEL:-gz_x500_mono_cam}"

log "=== 相机取流验证 $(date '+%F %T') ==="
log "机型 ${MODEL}   观测 ${DUR}s"
log "渲染后端: $(glxinfo -B 2>/dev/null | grep -i 'OpenGL renderer' || echo '未知（无 glxinfo）')"
log "ros_gz 版本: $(dpkg -l 2>/dev/null | awk '/ros-gzharmonic-image/{print $3}')"

rm -f "$RF/parameters.bson" "$RF/parameters_backup.bson"
for pat in image_bridge px4_sitl 'bin/px4' gz_x500 MicroXRCEAgent 'gz sim'; do
  pkill -9 -f "$pat" 2>/dev/null
done
sleep 2

MicroXRCEAgent udp4 -p 8888 > "$OUT/agent.log" 2>&1 & AGENT_PID=$!
sleep 3
mkfifo "$FIFO"
# 相机传感器需要渲染。HEADLESS=1 只是不开 GUI，gz sim -s 仍会离屏渲染，
# 在 llvmpipe 上这是纯 CPU 软渲染 —— 帧率就是本脚本要量的东西。
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl "$MODEL" < "$FIFO" ) > "$PX4_LOG" 2>&1 & PX4_PID=$!
exec 3>"$FIFO"; CON_OPEN=1

log ""
log "等待 PX4 就绪..."
for i in $(seq 1 240); do
  grep -qE 'uxrce_dds_client.*successfully created' "$PX4_LOG" 2>/dev/null && break
  kill -0 "$PX4_PID" 2>/dev/null || { log "PX4 第 ${i}s 退出，日志末 10 行："; \
      sed 's/pxh> //g' "$PX4_LOG" | tail -10 | sed 's/^/       /' | tee -a "$REPORT"; exit 1; }
  sleep 1
done
log "就绪，等 12s 让传感器起来"; sleep 12

# ---------- Q1: gz 侧的图像话题 ----------
log ""
log "=== Q1: gz 侧的图像话题名 ==="
GZ_TOPICS=$(timeout 15 gz topic -l 2>/dev/null || true)
echo "$GZ_TOPICS" | grep -iE 'image|camera' | sed 's/^/       /' | tee -a "$REPORT"
GZ_IMG=$(echo "$GZ_TOPICS" | grep -E '/image$' | head -1)
if [[ -n "$GZ_IMG" ]]; then
  ok "找到 gz 图像话题: ${GZ_IMG}"
else
  bad "gz 侧没有 /image 结尾的话题，相机没起来"
  log "  gz 话题全表（前 30 条）："
  echo "$GZ_TOPICS" | head -30 | sed 's/^/       /' | tee -a "$REPORT"
  exit 1
fi

log "  gz 侧原始帧率（不经 ROS，作为上限参考）："
GZ_HZ=$(timeout 12 gz topic -i -t "$GZ_IMG" 2>/dev/null | head -5 || true)
echo "${GZ_HZ:-  取不到}" | sed 's/^/       /' | tee -a "$REPORT"

# ---------- Q2: 桥到 ROS 2 并量帧率 ----------
log ""
log "=== Q2: 经 image_bridge 桥到 ROS 2，量实际帧率 ==="
ros2 run ros_gz_image image_bridge "$GZ_IMG" > "$OUT/bridge.log" 2>&1 & BRIDGE_PID=$!
sleep 8
if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
  bad "image_bridge 启动失败，日志："
  tail -15 "$OUT/bridge.log" | sed 's/^/       /' | tee -a "$REPORT"
  exit 1
fi
ok "image_bridge 运行中"

ROS_IMG="$GZ_IMG"     # image_bridge 保持同名话题
log "  ROS 2 侧话题（含 image 的）："
timeout 10 ros2 topic list 2>/dev/null | grep -i image | sed 's/^/       /' | tee -a "$REPORT"

log ""
log "  量 ${DUR}s 帧率与消息尺寸："
HZ_OUT=$(timeout "$((DUR + 5))" ros2 topic hz --window 100 "$ROS_IMG" 2>/dev/null \
         | grep 'average rate' | tail -1 || true)
log "       ros2 topic hz: ${HZ_OUT:-无输出}"
FPS=$(echo "$HZ_OUT" | grep -oE '[0-9]+\.[0-9]+' | head -1)

# 分辨率与编码从一帧消息头里读
FRAME_INFO=$(timeout 20 ros2 topic echo --once --field height "$ROS_IMG" 2>/dev/null | head -1 || true)
FRAME_W=$(timeout 20 ros2 topic echo --once --field width "$ROS_IMG" 2>/dev/null | head -1 || true)
FRAME_ENC=$(timeout 20 ros2 topic echo --once --field encoding "$ROS_IMG" 2>/dev/null | head -1 || true)
log "       分辨率 ${FRAME_W:-?}x${FRAME_INFO:-?}   编码 ${FRAME_ENC:-?}"

if [[ -n "${FPS:-}" ]]; then
  ok "ROS 2 侧收到图像，帧率 ${FPS} fps"
  # 模型 SDF 里 update_rate 是 30。软渲染下跑不满是预期的，
  # 但低于 2 fps 就无法支撑"边飞边检测"，要当结论记下来
  if awk -v f="$FPS" 'BEGIN{exit !(f >= 2.0)}'; then
    ok "帧率 ${FPS} fps >= 2 fps，可支撑低频巡检检测"
  else
    bad "帧率 ${FPS} fps < 2 fps，软渲染下不足以边飞边检测（需降分辨率或换机器）"
  fi
else
  bad "ROS 2 侧收不到图像"
fi

log ""
log "  CPU 负载（软渲染的代价）: $(awk '{print $1, $2, $3}' /proc/loadavg)  核数 $(nproc)"

log ""
log "=== 结论 ==="
log "  通过 ${PASS} 项，失败 ${FAIL} 项"
[[ "$FAIL" == 0 ]] && log "  RESULT=PASS" || log "  RESULT=FAIL"
log "  报告: ${REPORT}"
exit "$([[ "$FAIL" == 0 ]] && echo 0 || echo 1)"
