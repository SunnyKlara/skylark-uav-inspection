#!/usr/bin/env bash
# 审计并修复 PX4 子模块「已登记但工作树为空」的问题。
#
# 为什么需要这个工具（2026-07-27 实测踩过）：
#   在不稳定的网络上做 `git submodule update --init --recursive` 时，
#   部分子模块会进入一种半成品状态 —— `git submodule status` 报告它已在正确 commit
#   （无 `-` 前缀），但工作树里只有一个几十字节的 `.git` 指针文件，源码完全没 checkout。
#
#   后果：`git submodule status --recursive | grep -c '^-'` 返回 0，看起来一切正常，
#   但编译时报源文件找不到。本次的具体表现是：
#     CMake Error at cmake/px4_add_library.cmake:42 (add_library):
#       Cannot find source file: heatshrink/heatshrink_decoder.c
#   排查方向很容易被误导到 CMake 或 PX4 版本上，实际是子模块内容缺失。
#
#   关键点：修复必须用 `--force`。不加 force 时 git 认为当前已是目标 commit 会直接跳过。
#
# 用法：
#   bash check_px4_submodules.sh            # 只审计，不改动
#   bash check_px4_submodules.sh --repair   # 审计并修复发现的问题
#
# 退出码：0 = 无问题；1 = 发现问题（--repair 模式下表示修复后仍有问题）

set -uo pipefail

PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
REPAIR=0
MIN_FILES=3   # 文件数低于此值视为异常

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repair)  REPAIR=1; shift ;;
    --px4-dir) PX4_DIR="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

BOLD=$'\033[1m'; RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; RST=$'\033[0m'

[[ -d "${PX4_DIR}/.git" ]] || { echo "${RED}找不到 PX4 仓库: ${PX4_DIR}${RST}"; exit 2; }
cd "$PX4_DIR" || exit 2

echo "${BOLD}PX4 子模块审计${RST}  ($PX4_DIR)"
echo "判定阈值: 工作树文件数 < ${MIN_FILES} 视为异常"
echo

BROKEN=()
TOTAL=0
while read -r _ path _; do
  [[ -n "$path" ]] || continue
  TOTAL=$((TOTAL+1))
  if [[ ! -d "$path" ]]; then
    printf '  %-70s %s\n' "$path" "${RED}[目录不存在]${RST}"
    BROKEN+=("$path")
    continue
  fi
  n=$(find "$path" -type f 2>/dev/null | head -"$((MIN_FILES+1))" | wc -l)
  if (( n < MIN_FILES )); then
    printf '  %-70s %s\n' "$path" "${RED}[异常: ${n} 个文件]${RST}"
    BROKEN+=("$path")
  fi
done < <(git submodule status --recursive 2>/dev/null)

echo
echo "子模块总数: ${TOTAL}   异常: ${#BROKEN[@]}"

if (( ${#BROKEN[@]} == 0 )); then
  echo "${GRN}全部正常。${RST}"
  exit 0
fi

if (( REPAIR == 0 )); then
  echo
  echo "${YLW}发现 ${#BROKEN[@]} 个异常子模块。加 --repair 修复：${RST}"
  echo "  bash $0 --repair"
  exit 1
fi

# ---------- 修复 ----------
echo
echo "${BOLD}开始修复${RST}"

# 传输加固：本机到 github.com 链路不稳，这几项能显著降低 clone 失败率。
#
# ⚠ 用 `-c` 逐命令覆盖，**不写进任何 config 文件**。
# 早先这里写的是 `git config --global`，那是错的：
#   - 作用域是整台机器的所有仓库，不只是 PX4
#   - 脚本既不告知也不还原，用户不知道自己的 git 被改了
#   - lowSpeedTime=999999 尤其有害 —— 等于取消了所有仓库的网络超时，
#     以后任何 git 操作卡住都不会自己退出，只能手动中断
# 一次性覆盖能拿到同样的加固效果，且进程退出后不留痕迹。
GIT_HARDEN=(
  -c http.version=HTTP/1.1
  -c http.postBuffer=524288000
  -c http.lowSpeedLimit=1000      # 低于 1 KB/s 持续 300s 才判超时，
  -c http.lowSpeedTime=300        # 慢链路能扛，真断线仍会及时失败
)

STILL_BAD=()
for p in "${BROKEN[@]}"; do
  echo "  --- $p ---"
  fixed=0
  for i in 1 2 3 4 5; do
    # --force 是关键：不加时 git 认为已在目标 commit 会跳过
    git "${GIT_HARDEN[@]}" submodule update --init --force --recursive "$p" >/dev/null 2>&1
    n=$(find "$p" -type f 2>/dev/null | head -"$((MIN_FILES+1))" | wc -l)
    if (( n >= MIN_FILES )); then
      echo "    ${GRN}OK${RST}（第 ${i} 次，现有 ${n}+ 个文件）"
      fixed=1
      break
    fi
    echo "    第 ${i}/5 次未成功，6 秒后重试"
    sleep 6
  done
  (( fixed == 1 )) || STILL_BAD+=("$p")
done

echo
if (( ${#STILL_BAD[@]} == 0 )); then
  echo "${GRN}全部修复成功。${RST}"
  echo "建议接着验证编译：cd ${PX4_DIR} && make px4_sitl_default -j\$(nproc)"
  exit 0
fi

echo "${RED}仍有 ${#STILL_BAD[@]} 个未修复：${RST}"
for p in "${STILL_BAD[@]}"; do echo "  $p"; done
echo
echo "手动尝试："
echo "  cd ${PX4_DIR}"
echo "  git submodule update --init --force --recursive"
exit 1
