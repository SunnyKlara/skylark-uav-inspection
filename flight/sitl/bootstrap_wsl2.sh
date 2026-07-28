#!/usr/bin/env bash
# Skylark flight/ 层 SITL 环境引导（WSL2 Ubuntu 22.04）
#
# 目标：在 Windows + WSL2 上装好 PX4 SITL + Gazebo Harmonic + ROS 2 Humble + uXRCE-DDS，
#       跑通 PX4 官方 offboard 示例，为后续 flight/ 开发打底。
#
# 幂等：可反复执行。已完成的步骤会跳过。网络中断后直接重跑即可续。
#
# ⚠ 重要：不要在本脚本运行期间编辑它。
#   bash 是边读边执行的，中途修改文件会导致字节偏移错位，
#   典型症状是在一个语法完全正确的位置报 "syntax error near unexpected token"。
#   实测踩过（2026-07-27）。若必须边跑边改，先 cp 到 /tmp 再执行那个副本。
#
# 版本以 flight/VERSIONS.md 为唯一来源。改版本请改那里，然后同步本文件的变量。
#
# 用法：
#   bash bootstrap_wsl2.sh              # 全量执行
#   bash bootstrap_wsl2.sh --check      # 只检查环境，不安装
#   bash bootstrap_wsl2.sh --skip-px4   # 跳过 PX4（已装过时用）
#
# 前置条件（在 Windows PowerShell 里做，本脚本不能替你做）：
#   wsl --install -d Ubuntu-22.04
#   wsl --set-default Ubuntu-22.04
#   然后建 C:\Users\<你>\.wslconfig 限制 WSL 资源，见本文件末尾附录

set -euo pipefail

# ============================================================
# 版本（与 flight/VERSIONS.md 保持一致）
# ============================================================
PX4_VERSION="v1.17.0"
PX4_MSGS_BRANCH="release/1.17"
XRCE_AGENT_VERSION="v2.4.3"
ROS_DISTRO_NAME="humble"
REQUIRED_UBUNTU="22.04"

# ============================================================
# 路径
# ============================================================
PX4_DIR="${HOME}/PX4-Autopilot"
WS_DIR="${HOME}/skylark_ws"
AGENT_DIR="${HOME}/Micro-XRCE-DDS-Agent"

# ============================================================
# 参数解析
# ============================================================
CHECK_ONLY=false
SKIP_PX4=false
for arg in "$@"; do
  case "$arg" in
    --check)    CHECK_ONLY=true ;;
    --skip-px4) SKIP_PX4=true ;;
    -h|--help)  sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg（用 --help 看用法）"; exit 2 ;;
  esac
done

# ============================================================
# 输出helpers
# ============================================================
BOLD=$'\033[1m'; RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; RST=$'\033[0m'
step() { echo; echo "${BOLD}==> $*${RST}"; }
ok()   { echo "  ${GRN}[OK]${RST}   $*"; }
warn() { echo "  ${YLW}[WARN]${RST} $*"; }
fail() { echo "  ${RED}[FAIL]${RST} $*"; }
die()  { fail "$*"; exit 1; }

# ============================================================
# 0. 环境前置检查
# ============================================================
step "环境检查"

if ! grep -qi microsoft /proc/version 2>/dev/null; then
  warn "未检测到 WSL。本脚本为 WSL2 设计，在原生 Ubuntu 上也能跑，但 §渲染配置 部分可跳过。"
else
  ok "运行在 WSL 内"
fi

UBUNTU_VER="$(lsb_release -rs 2>/dev/null || echo unknown)"
if [[ "$UBUNTU_VER" != "$REQUIRED_UBUNTU" ]]; then
  fail "Ubuntu 版本是 ${UBUNTU_VER}，本项目锁定 ${REQUIRED_UBUNTU}（ROS 2 ${ROS_DISTRO_NAME} 的官方平台）"
  echo "     在 Windows PowerShell 里执行： wsl --install -d Ubuntu-22.04"
  die "版本不符，中止"
fi
ok "Ubuntu ${UBUNTU_VER}"

TOTAL_MEM_GB=$(awk '/MemTotal/ {printf "%.1f", $2/1024/1024}' /proc/meminfo)
echo "  可用内存: ${TOTAL_MEM_GB} GB"
if (( $(echo "$TOTAL_MEM_GB < 7.5" | bc -l 2>/dev/null || echo 0) )); then
  warn "内存 < 8 GB。PX4 编译并行度会受限，Gazebo 可能吃紧。"
  warn "建议在 Windows 侧配 .wslconfig 提高 WSL 内存上限（见本文件附录）"
fi

FREE_GB=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')
echo "  ${HOME} 可用空间: ${FREE_GB} GB"
(( FREE_GB >= 25 )) || warn "可用空间 < 25 GB。PX4 递归 clone + 编译产物约需 8-12 GB，Gazebo 资源另计。"

# GPU / 渲染探测
step "渲染后端探测"
GPU_VENDOR="unknown"
if command -v glxinfo >/dev/null 2>&1; then
  GPU_RENDERER="$(glxinfo -B 2>/dev/null | grep -i 'OpenGL renderer' || true)"
  echo "  ${GPU_RENDERER:-未获取到 OpenGL renderer}"
  if echo "$GPU_RENDERER" | grep -qi nvidia; then GPU_VENDOR="nvidia"
  elif echo "$GPU_RENDERER" | grep -qiE 'amd|radeon'; then GPU_VENDOR="amd"
  elif echo "$GPU_RENDERER" | grep -qi 'llvmpipe\|softpipe'; then GPU_VENDOR="software"
  fi
else
  warn "glxinfo 未安装，稍后会装 mesa-utils 再探测"
fi
echo "  判定: ${GPU_VENDOR}"

if [[ "$CHECK_ONLY" == true ]]; then
  step "仅检查模式，退出"
  exit 0
fi

# ============================================================
# 1. 基础依赖
# ============================================================
step "安装基础依赖"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  git curl wget ca-certificates gnupg lsb-release \
  build-essential cmake ninja-build ccache \
  python3 python3-pip python3-venv \
  mesa-utils x11-apps bc \
  >/dev/null
ok "基础依赖就绪"

# ============================================================
# 2. PX4 SITL + Gazebo Harmonic
# ============================================================
if [[ "$SKIP_PX4" == true ]]; then
  step "跳过 PX4（--skip-px4）"
else
  step "PX4-Autopilot ${PX4_VERSION}"

  # git 传输加固。
  # 实测（2026-07-27）本机到 github.com 的链路不稳定，一次性递归 clone（1.5-2 GB）
  # 反复失败于 "GnuTLS recv error (-54)" / "fetch-pack: unexpected disconnect"；
  # 子模块阶段还会出现 "curl 16 Error in the HTTP2 framing layer"（git/curl 在
  # HTTP/2 上的已知不稳定问题，强制 HTTP/1.1 可规避）。
  # 对策：① 调大缓冲、放宽低速判定、关压缩；② 主仓库与子模块分两步，各自可重试可续传。
  #
  # ⚠ 这些设置用 GIT_CONFIG_COUNT 环境变量注入，**不写进任何 config 文件**。
  #
  # 早先这里写的是 `git config --global`，那是错的，而且已经在本机造成实际污染：
  #   - 作用域是整台机器的所有仓库，与 PX4 无关的仓库一并被改
  #   - 脚本既不告知也不还原，用户不知道自己的 git 被动过
  #   - 最有害的是 lowSpeedLimit=0 + lowSpeedTime=999999 —— 等于**取消所有仓库的
  #     网络超时**，此后任何 git 操作卡住都不会自己失败，只能手动中断
  # 环境变量注入能拿到同样的加固效果，进程退出即失效。
  # git >= 2.31 支持该机制（Ubuntu 22.04 自带 2.34.1，已实测）。
  #
  # 低速阈值也改成了「慢链路扛得住、真断线仍会及时失败」的值，
  # 而不是原来那种永不超时。
  export GIT_CONFIG_COUNT=5
  export GIT_CONFIG_KEY_0=http.postBuffer   GIT_CONFIG_VALUE_0=524288000
  export GIT_CONFIG_KEY_1=http.lowSpeedLimit GIT_CONFIG_VALUE_1=1000
  export GIT_CONFIG_KEY_2=http.lowSpeedTime  GIT_CONFIG_VALUE_2=300
  export GIT_CONFIG_KEY_3=core.compression   GIT_CONFIG_VALUE_3=0
  export GIT_CONFIG_KEY_4=http.version       GIT_CONFIG_VALUE_4=HTTP/1.1

  # 检测旧版脚本留下的全局污染并告知。
  # 这里刻意**只提示不自动删** —— 用户可能出于自己的原因设过同名项，
  # 脚本静默删掉，性质和当初静默写入一样坏。要不要清由用户决定。
  POLLUTED=()
  for k in http.postBuffer http.lowSpeedLimit http.lowSpeedTime core.compression http.version; do
    git config --global --get "$k" >/dev/null 2>&1 && POLLUTED+=("$k")
  done
  if (( ${#POLLUTED[@]} > 0 )); then
    warn "检测到全局 git 配置里有 ${#POLLUTED[@]} 项可能是本脚本旧版本写入的："
    for k in "${POLLUTED[@]}"; do
      warn "    ${k} = $(git config --global --get "$k")"
    done
    warn "  本次运行已改用环境变量注入，不再需要这些全局项。"
    warn "  尤其检查 http.lowSpeedTime —— 若是 999999，等于所有仓库都不再有网络超时。"
    warn "  确认无用后可自行清除："
    for k in "${POLLUTED[@]}"; do
      warn "    git config --global --unset-all ${k}"
    done
  fi

  # ---- 第 1 步：主仓库（不含子模块），可重试 ----
  if [[ -d "${PX4_DIR}/.git" ]]; then
    CURRENT_TAG="$(git -C "$PX4_DIR" describe --tags --exact-match 2>/dev/null || echo '<非 tag>')"
    ok "主仓库已存在，当前: ${CURRENT_TAG}"
    if [[ "$CURRENT_TAG" != "$PX4_VERSION" ]]; then
      warn "版本与 VERSIONS.md 锁定的 ${PX4_VERSION} 不一致，尝试切换"
      git -C "$PX4_DIR" fetch --tags --force || warn "fetch tags 失败"
      git -C "$PX4_DIR" checkout "$PX4_VERSION" || warn "checkout ${PX4_VERSION} 失败"
    fi
  else
    echo "  clone 主仓库（不含子模块，约 400-600 MB）..."
    CLONED=0
    for attempt in 1 2 3 4 5; do
      echo "    尝试 ${attempt}/5 ..."
      if [[ -d "${PX4_DIR}/.git" ]]; then
        # 上次留下了不完整的仓库 -> 续传而不是重来
        if git -C "$PX4_DIR" fetch --tags origin "$PX4_VERSION" 2>&1 \
           && git -C "$PX4_DIR" checkout "$PX4_VERSION" 2>&1; then
          CLONED=1; break
        fi
      else
        if git clone --branch "$PX4_VERSION" \
             https://github.com/PX4/PX4-Autopilot.git "$PX4_DIR" 2>&1; then
          CLONED=1; break
        fi
      fi
      warn "    第 ${attempt} 次未成功，10 秒后重试（已下载部分会保留续传）"
      sleep 10
    done
    if [[ "$CLONED" != 1 ]]; then
      die "主仓库 clone 5 次均失败。网络到 github.com 不稳定。
     可稍后重跑本脚本（幂等，会自动续传），或手动执行：
       git clone --branch ${PX4_VERSION} https://github.com/PX4/PX4-Autopilot.git ${PX4_DIR}"
    fi
    ok "主仓库 clone 完成"
  fi

  # ---- 第 2 步：子模块，逐个可重试（单个失败不至于全盘重来）----
  step "PX4 子模块"
  SUBMOD_OK=0
  for attempt in 1 2 3 4 5 6; do
    echo "  子模块同步 尝试 ${attempt}/6 ..."
    if git -C "$PX4_DIR" submodule update --init --recursive --jobs 4 2>&1; then
      SUBMOD_OK=1; break
    fi
    warn "  第 ${attempt} 次未完成，10 秒后重试（已完成的子模块会跳过）"
    sleep 10
  done
  if [[ "$SUBMOD_OK" == 1 ]]; then
    ok "子模块同步命令已成功返回"
  else
    warn "子模块未全部完成。可重跑本脚本续传，或手动："
    warn "  git -C ${PX4_DIR} submodule update --init --recursive"
  fi

  # ---- 第 3 步：内容审计（命令成功 ≠ 内容完整）----
  #
  # 实测踩过（2026-07-27）：不稳定网络下部分子模块会进入半成品状态 ——
  # `git submodule status` 报告已在正确 commit（无 `-` 前缀），但工作树里只有
  # 一个几十字节的 .git 指针文件，源码完全没 checkout。
  # 于是 `grep -c '^-'` 返回 0，看起来正常，直到编译时报：
  #   CMake Error: Cannot find source file: heatshrink/heatshrink_decoder.c
  # 本次有 7 个子模块中招。所以必须审计内容，不能只信 status。
  step "PX4 子模块内容审计"
  AUDIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools" 2>/dev/null && pwd)/check_px4_submodules.sh"
  if [[ -f "$AUDIT" ]]; then
    if PX4_DIR="$PX4_DIR" bash "$AUDIT" >/dev/null 2>&1; then
      ok "子模块内容完整"
    else
      warn "发现内容为空的子模块，自动修复中（用 --force 强制重新 checkout）..."
      if PX4_DIR="$PX4_DIR" bash "$AUDIT" --repair; then
        ok "子模块修复完成"
      else
        warn "仍有子模块未修复，编译可能失败。手动重试："
        warn "  bash ${AUDIT} --repair"
      fi
    fi
  else
    # 找不到工具时做个最小内联检查，至少别让问题静默通过
    BAD=0
    while read -r _ p _; do
      [[ -n "$p" ]] || continue
      [[ -d "$p" ]] || { BAD=$((BAD+1)); continue; }
      (( $(find "${PX4_DIR}/${p}" -type f 2>/dev/null | head -3 | wc -l) < 3 )) && BAD=$((BAD+1))
    done < <(git -C "$PX4_DIR" submodule status --recursive 2>/dev/null)
    if (( BAD > 0 )); then
      warn "检测到 ${BAD} 个子模块内容为空，执行强制同步"
      git -C "$PX4_DIR" submodule update --init --force --recursive --jobs 4 || \
        warn "强制同步未完全成功"
    else
      ok "子模块内容完整"
    fi
  fi

  step "PX4 工具链 + Gazebo Harmonic"
  # ubuntu.sh 会装 NuttX 交叉编译工具链、Python 依赖，以及 gz-harmonic
  # （已在本地源码核实：Tools/setup/ubuntu.sh 支持 22.04，安装 gz-harmonic）
  if command -v gz >/dev/null 2>&1; then
    ok "Gazebo 已安装: $(gz --version 2>/dev/null | head -1)"
  else
    echo "  执行 PX4 官方安装脚本（会装工具链 + Gazebo Harmonic，约 10-20 分钟）..."
    bash "${PX4_DIR}/Tools/setup/ubuntu.sh"
    ok "PX4 工具链与 Gazebo 安装完成"
    warn "首次安装后建议重启 WSL：在 PowerShell 执行 wsl --shutdown，然后重新进入"
  fi
fi

# ============================================================
# 3. ROS 2 Humble
# ============================================================
step "ROS 2 ${ROS_DISTRO_NAME}"
if [[ -f "/opt/ros/${ROS_DISTRO_NAME}/setup.bash" ]]; then
  ok "已安装"
else
  # ---- ROS 2 apt 源 ----
  # 用官方的 ros2-apt-source .deb（现行推荐方式，自带正确的 GPG 密钥与源定义），
  # 取代早年手动下 ros.key + 写 sources.list 的做法。
  echo "  添加 ROS 2 apt 源（官方 ros2-apt-source .deb）..."
  ROS_APT_VER="$(curl -fsSL https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
                 | grep -oP '"tag_name":\s*"\K[^"]+' || echo '1.2.0')"
  CODENAME="$(. /etc/os-release && echo "$UBUNTU_CODENAME")"
  DEB="/tmp/ros2-apt-source.deb"
  if curl -fsSL -o "$DEB" \
      "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_VER}/ros2-apt-source_${ROS_APT_VER}.${CODENAME}_all.deb"; then
    sudo apt-get install -y "$DEB" >/dev/null
    ok "ros2-apt-source ${ROS_APT_VER} (${CODENAME}) 已安装"
  else
    warn "官方 .deb 下载失败，回退到手动添加源"
    sudo curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      -o /usr/share/keyrings/ros-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu ${CODENAME} main" \
      | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null
  fi

  # ---- 必要的变通：把 ROS 源强制改成 http ----
  #
  # 实测（2026-07-27，Windows 侧与 WSL 侧结果一致）：
  #   https://packages.ros.org 返回的证书是 CN=*.osuosl.org（Oregon State University
  #   Open Source Lab，ROS 官方托管方），SAN 只含 *.osuosl.org 与 osuosl.org，
  #   不含 packages.ros.org  ->  curl rc=60 / apt "证书主机名不匹配"。
  #   这是服务端证书配置问题，不是本机或 WSL 的问题。
  #   同一路径走 http:// 返回 HTTP 200，仓库本身可达。
  #
  # 为什么改用 http 是安全的：
  #   apt 的完整性保障来自 InRelease 文件的 GPG 签名（密钥来自上面那个可信 .deb），
  #   而不是来自 TLS。TLS 在这里只提供保密性（隐藏"你在下什么包"），
  #   不提供完整性。篡改过的包会因签名校验失败被 apt 拒绝。
  #   Debian/Ubuntu 官方源默认也是 http，原理相同。
  #
  # 若哪天上游修好了证书，把下面这段删掉即可。
  for f in /etc/apt/sources.list.d/ros2*.list /etc/apt/sources.list.d/ros2*.sources; do
    [[ -f "$f" ]] || continue
    if grep -q 'https://packages.ros.org' "$f"; then
      sudo sed -i 's|https://packages\.ros\.org|http://packages.ros.org|g' "$f"
      warn "已把 $(basename "$f") 中的 ROS 源改为 http（上游证书主机名不匹配，见脚本内注释）"
    fi
  done

  sudo apt-get update -qq
  echo "  安装 ros-${ROS_DISTRO_NAME}-desktop（约 2 GB，10-20 分钟）..."
  sudo apt-get install -y "ros-${ROS_DISTRO_NAME}-desktop" \
    python3-colcon-common-extensions python3-rosdep >/dev/null
  ok "ROS 2 ${ROS_DISTRO_NAME} 安装完成"
fi

# PX4 官方要求的 Python 依赖（版本敏感，empy 3.4+ 会导致 PX4 构建失败）
step "Python 依赖"
python3 -m pip install --user -q -U 'empy==3.3.4' pyros-genmsg setuptools packaging
ok "empy 3.3.4 / pyros-genmsg / setuptools"

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init >/dev/null 2>&1 || true
fi
rosdep update --rosdistro "$ROS_DISTRO_NAME" >/dev/null 2>&1 || warn "rosdep update 失败（通常是网络问题，可稍后重试）"

# ============================================================
# 4. Micro XRCE-DDS Agent
# ============================================================
step "Micro XRCE-DDS Agent ${XRCE_AGENT_VERSION}"
if command -v MicroXRCEAgent >/dev/null 2>&1; then
  ok "已安装: $(command -v MicroXRCEAgent)"
else
  if [[ ! -d "${AGENT_DIR}/.git" ]]; then
    # 与工作区 clone 同样的链路风险，带重试
    for i in 1 2 3 4 5 6; do
      rm -rf "$AGENT_DIR"
      git clone -b "$XRCE_AGENT_VERSION" \
        https://github.com/eProsima/Micro-XRCE-DDS-Agent.git "$AGENT_DIR" 2>&1 && break
      warn "  Agent clone 第 ${i}/6 次失败，8 秒后重试"
      sleep 8
    done
    [[ -d "${AGENT_DIR}/.git" ]] || die "Micro-XRCE-DDS-Agent clone 6 次均失败"
  fi
  mkdir -p "${AGENT_DIR}/build"
  pushd "${AGENT_DIR}/build" >/dev/null
  cmake .. -DCMAKE_BUILD_TYPE=Release >/dev/null
  make -j"$(nproc)" >/dev/null
  sudo make install >/dev/null
  sudo ldconfig /usr/local/lib/
  popd >/dev/null
  ok "Agent 编译安装完成"
fi

# ============================================================
# 5. Skylark ROS 2 工作区
# ============================================================
step "Skylark 工作区 ${WS_DIR}"
mkdir -p "${WS_DIR}/src"

# 带重试的 clone 助手。
# 实测本机到 github.com 的链路会随机抛 GnuTLS recv error / HTTP2 framing error，
# 单次 clone 失败会因 `set -e` 直接终止整个脚本。所有 clone 都必须走这里。
clone_retry() {
  local url="$1" dest="$2"; shift 2
  local extra=("$@")
  if [[ -d "${dest}/.git" ]] && [[ -n "$(ls -A "$dest" 2>/dev/null)" ]]; then
    return 0
  fi
  local i
  for i in 1 2 3 4 5 6; do
    rm -rf "$dest"
    if git clone "${extra[@]}" "$url" "$dest" 2>&1; then
      return 0
    fi
    warn "  clone $(basename "$dest") 第 ${i}/6 次失败，8 秒后重试"
    sleep 8
  done
  return 1
}

if [[ ! -d "${WS_DIR}/src/px4_msgs/.git" ]]; then
  clone_retry https://github.com/PX4/px4_msgs.git "${WS_DIR}/src/px4_msgs" -b "$PX4_MSGS_BRANCH" \
    || die "px4_msgs clone 6 次均失败。重跑本脚本可续，或手动 clone 到 ${WS_DIR}/src/px4_msgs"
  ok "px4_msgs (${PX4_MSGS_BRANCH})"
else
  ACTUAL_BRANCH="$(git -C "${WS_DIR}/src/px4_msgs" rev-parse --abbrev-ref HEAD)"
  if [[ "$ACTUAL_BRANCH" != "$PX4_MSGS_BRANCH" ]]; then
    warn "px4_msgs 当前在 ${ACTUAL_BRANCH}，锁定的是 ${PX4_MSGS_BRANCH}"
    warn "版本不一致会导致话题字段错位。修正: git -C ${WS_DIR}/src/px4_msgs checkout ${PX4_MSGS_BRANCH}"
  else
    ok "px4_msgs (${ACTUAL_BRANCH})"
  fi
fi

if [[ ! -d "${WS_DIR}/src/px4_ros_com/.git" ]]; then
  clone_retry https://github.com/PX4/px4_ros_com.git "${WS_DIR}/src/px4_ros_com" \
    || die "px4_ros_com clone 6 次均失败。重跑本脚本可续，或手动 clone 到 ${WS_DIR}/src/px4_ros_com"
  ok "px4_ros_com（官方示例，含 offboard_control）"
fi

# 把仓库里的 skylark 包软链进工作区，这样改代码不用来回拷
step "链接 Skylark 自有包"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKYLARK_SRC="$(cd "${SCRIPT_DIR}/../ros2_ws/src" && pwd)"
if [[ -d "$SKYLARK_SRC" ]]; then
  for pkg in "$SKYLARK_SRC"/*/; do
    [[ -d "$pkg" ]] || continue
    name="$(basename "$pkg")"
    target="${WS_DIR}/src/${name}"
    if [[ -L "$target" ]]; then
      ok "${name}（软链已存在）"
    elif [[ -e "$target" ]]; then
      warn "${target} 已存在且不是软链，跳过"
    else
      ln -s "$pkg" "$target"
      ok "${name} -> 软链到工作区"
    fi
  done
else
  warn "未找到 ${SKYLARK_SRC}，跳过链接"
fi

# ============================================================
# 6. 构建工作区
# ============================================================
step "构建工作区"
# ROS 2 的 setup.bash 不是 `set -u` 安全的（内部引用 AMENT_TRACE_SETUP_FILES 等
# 未定义变量），本脚本开头是 `set -euo pipefail`，直接 source 会报
# "unbound variable" 并因 set -e 终止整个脚本。必须临时关闭 -u。
# 实测踩过（2026-07-27，在 smoke_test.sh 上先暴露出来）。
set +u
# shellcheck disable=SC1090
source "/opt/ros/${ROS_DISTRO_NAME}/setup.bash"
set -u
pushd "$WS_DIR" >/dev/null
if colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release; then
  ok "colcon build 成功"
else
  fail "colcon build 失败。常见原因："
  echo "     1. empy 版本不对 -> pip install -U 'empy==3.3.4'"
  echo "     2. 内存不足被 OOM kill -> colcon build --parallel-workers 1"
  echo "     3. px4_msgs 分支与固件不一致 -> 见上方 WARN"
  popd >/dev/null
  exit 1
fi
popd >/dev/null

# ============================================================
# 7. 渲染配置（AMD / 软渲染兜底）
# ============================================================
step "Gazebo 渲染配置"
GPU_RENDERER="$(glxinfo -B 2>/dev/null | grep -i 'OpenGL renderer' || true)"
echo "  ${GPU_RENDERER:-未获取到}"

RCFILE="${HOME}/.skylark_env.sh"
{
  echo "# Skylark flight/ 环境变量 — 由 bootstrap_wsl2.sh 生成于 $(date -Iseconds)"
  echo "source /opt/ros/${ROS_DISTRO_NAME}/setup.bash"
  echo "[ -f ${WS_DIR}/install/setup.bash ] && source ${WS_DIR}/install/setup.bash"
  echo "export PX4_DIR=${PX4_DIR}"
  echo "export SKYLARK_WS=${WS_DIR}"
  if echo "$GPU_RENDERER" | grep -qiE 'amd|radeon'; then
    echo "# AMD GPU：WSL2 下走 Mesa d3d12 driver"
    echo "export MESA_D3D12_DEFAULT_ADAPTER_NAME=AMD"
  fi
  if echo "$GPU_RENDERER" | grep -qi 'llvmpipe\|softpipe'; then
    echo "# 未检测到硬件加速，强制软渲染以保证 Gazebo 可用（帧率低但功能完整）"
    echo "export LIBGL_ALWAYS_SOFTWARE=1"
  fi
} > "$RCFILE"
ok "环境变量写入 ${RCFILE}"

# 必须同时挂到 .bashrc 与 .profile。
#
# 原因（2026-07-27 实测踩过）：Ubuntu 默认 ~/.bashrc 开头有
#   case $- in *i*) ;; *) return;; esac
# 非交互 shell 会在此直接 return，追加在文件末尾的 source 行永远执行不到。
# 后果是 `wsl -- bash -lc '...'`、CI、以及任何非交互调用都拿不到 ROS 环境，
# 表现为 ros2 命令找不到、ROS_DISTRO 为空 —— 很容易误判成安装失败。
# ~/.profile 由登录 shell 读取且没有交互性判断，正好补上这个缺口。
if ! grep -q 'skylark_env.sh' "${HOME}/.bashrc" 2>/dev/null; then
  echo "[ -f ${RCFILE} ] && source ${RCFILE}" >> "${HOME}/.bashrc"
  ok "已加入 ~/.bashrc（交互式终端）"
else
  ok "~/.bashrc 已配置"
fi
if ! grep -q 'skylark_env.sh' "${HOME}/.profile" 2>/dev/null; then
  printf '\n# Skylark flight/ 环境（登录 shell，含非交互 bash -lc）\n[ -f %s ] && . %s\n' \
    "${RCFILE}" "${RCFILE}" >> "${HOME}/.profile"
  ok "已加入 ~/.profile（非交互登录 shell）"
else
  ok "~/.profile 已配置"
fi

# ============================================================
# 完成
# ============================================================
step "完成"
cat <<EOF

  ${BOLD}下一步（开三个终端）${RST}

  终端 1 — 启动 XRCE Agent（仿真走 UDP 8888）：
      MicroXRCEAgent udp4 -p 8888

  终端 2 — 启动 PX4 SITL + Gazebo：
      cd ${PX4_DIR}
      make px4_sitl gz_x500
      # 无图形界面时用： HEADLESS=1 make px4_sitl gz_x500

  终端 3 — 跑官方 offboard 示例（先确认 1、2 已连上）：
      source ${RCFILE}
      ros2 topic list | grep /fmu/          # 应能看到 fmu 话题
      ros2 run px4_ros_com offboard_control

  ${BOLD}验证 Skylark 接口契约已注册${RST}
      source ${RCFILE}
      ros2 interface list | grep skylark
      ros2 interface show skylark_flight_msgs/action/InspectSweep

  ${BOLD}编译 6C 固件（S2 阶段用）${RST}
      cd ${PX4_DIR} && make px4_fmu-v6c_default

  ${BOLD}提醒${RST}
  - 版本以 flight/VERSIONS.md 为准，不要随手升级
  - 每次新终端记得 source ${RCFILE}（已写入 .bashrc，新开终端自动生效）
  - 首次装完 Gazebo 建议 wsl --shutdown 后重进

EOF

exit 0

# ============================================================
# 附录：Windows 侧的 .wslconfig
# ============================================================
# 建 C:\Users\<你的用户名>\.wslconfig（无扩展名），内容示例：
#
#   [wsl2]
#   memory=16GB
#   processors=8
#   swap=8GB
#   localhostForwarding=true
#
# 改完在 PowerShell 执行： wsl --shutdown  然后重新进入 WSL
# 不配的话，编译 PX4 或跑 Gazebo 可能把 Windows 主机内存吃满导致卡死。
