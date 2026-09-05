#!/usr/bin/env bash
# smoke_test.sh 里三个纯函数的单元测试。不启仿真，秒级反馈。
#
# 为什么值得单独测：这三个函数是冒烟测试三次误报的根源。
#   resolve_topic    —— 话题名写死导致「DDS 桥没通」的假故障（真因是 v1.17 的 _v1 后缀）
#   yaml_rate_limit  —— 期望值抄自另一棵源码树，报出「100 Hz 偏离期望 50」
#   _trimmed_hz      —— 用众数估计双峰间隔，算出 62.5 Hz（超过话题自身上限，物理不可能）
# 每个坑都对应下面一条用例，钉住免得回归。
#
# 用法： bash smoke_test_units.sh

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# 默认取同目录的被测脚本；把本脚本拷到别处跑时用 SMOKE_SRC 指过去
SRC="${SMOKE_SRC:-${SCRIPT_DIR}/smoke_test.sh}"
TMP=/tmp/smoke_under_test.sh

[[ -f "$SRC" ]] || { echo "找不到 $SRC"; exit 1; }
cp "$SRC" "$TMP"
sed -i 's/\r$//' "$TMP"   # 从 /mnt/c 读到的可能是 CRLF

bash -n "$TMP" && echo "SYNTAX-OK" || { echo "SYNTAX-FAIL"; exit 1; }

# 按函数名精确抽取函数体再 source。
# 不要用「截取文件前半段」的办法 —— yaml_rate_limit 定义在第 4 节，
# 截到 trap 处就抽不到它，会报 command not found（那是脚手架的锅，不是被测函数的锅）。
extract_fn() {
  awk -v pat="$1() {" 'index($0, pat) == 1 { inf = 1 } inf { print } inf && /^\}$/ { exit }' "$TMP"
}
{
  echo 'say() { echo "$*"; }; ok() { echo "  [PASS] $*"; }'
  echo 'bad() { echo "  [FAIL] $*"; }; info() { echo "         $*"; }'
  extract_fn resolve_topic
  extract_fn yaml_rate_limit
  extract_fn _trimmed_hz
} > /tmp/smoke_fns.sh

bash -n /tmp/smoke_fns.sh || { echo "抽取出的函数体语法不合法"; exit 1; }
# shellcheck disable=SC1091
source /tmp/smoke_fns.sh
for fn in resolve_topic yaml_rate_limit _trimmed_hz; do
  declare -F "$fn" >/dev/null || { echo "抽取失败: $fn 未定义"; exit 1; }
done
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"

FAILED=0

echo "--- yaml_rate_limit（真值 = 锁定版本 v1.17.0 的 dds_topics.yaml）---"
expect_limit() {
  local base="$1" want="$2" got
  got=$(yaml_rate_limit "$base" || true); got="${got:-无上限}"
  if [[ "$got" == "$want" ]]; then
    printf '  %-28s -> [%s]\n' "$base" "$got"
  else
    printf '  %-28s -> [%s]  期望 [%s]  [不符]\n' "$base" "$got" "$want"; FAILED=1
  fi
}
expect_limit vehicle_local_position 50
expect_limit vehicle_attitude       无上限
expect_limit vehicle_status         5
expect_limit vehicle_land_detected  5
# 这个话题在 yaml 里是注释掉的，必须识别为无上限而不是误取注释里的值
expect_limit vehicle_angular_velocity 无上限

echo "--- resolve_topic（输入取自实测到的话题名）---"
FMU_TOPICS=(
  /fmu/out/vehicle_attitude
  /fmu/out/vehicle_local_position_v1
  /fmu/out/vehicle_status_v1
  /fmu/out/vehicle_odometry
)
expect_topic() {
  local base="$1" want="$2" got
  got=$(resolve_topic "$base" || true); got="${got:-未解析到}"
  if [[ "$got" == "$want" ]]; then
    printf '  %-28s -> [%s]\n' "$base" "$got"
  else
    printf '  %-28s -> [%s]  期望 [%s]  [不符]\n' "$base" "$got" "$want"; FAILED=1
  fi
}
expect_topic vehicle_attitude       /fmu/out/vehicle_attitude
expect_topic vehicle_local_position /fmu/out/vehicle_local_position_v1
expect_topic vehicle_status         /fmu/out/vehicle_status_v1
expect_topic vehicle_wind           未解析到

echo "--- resolve_topic 反例：不能把 vehicle_status 匹配成前缀延伸 ---"
FMU_TOPICS=(/fmu/out/vehicle_status_flags /fmu/out/vehicle_statusfoo)
expect_topic vehicle_status 未解析到

echo "--- _trimmed_hz（合成数据，期望值可手算）---"
gen() {  # gen <文件> <间隔序列...>  单位 us
  local f="$1"; shift
  local t=1000000 reps=$((300 / $#))
  : > "$f"; echo "$t" >> "$f"
  for ((r = 0; r < reps; r++)); do
    for d in "$@"; do t=$((t + d)); echo "$t" >> "$f"; done
  done
}
check_hz() {  # check_hz <名称> <文件> <期望Hz> <期望离群> <期望非单调>
  local name="$1" f="$2" e_hz="$3" e_out="$4" e_nm="$5" hz out nm verdict=OK
  read -r hz out nm < <(_trimmed_hz "$f")
  awk -v a="$hz" -v e="$e_hz" 'BEGIN{ exit !(a >= e*0.98 && a <= e*1.02) }' || verdict="频率偏差"
  [[ "$out" == "$e_out" ]] || verdict="离群数不符"
  [[ "$nm"  == "$e_nm"  ]] || verdict="非单调数不符"
  [[ "$verdict" == OK ]] || FAILED=1
  printf '  %-32s -> %8s Hz  离群 %s  非单调 %s   期望 %s/%s/%s  [%s]\n' \
    "$name" "$hz" "$out" "$nm" "$e_hz" "$e_out" "$e_nm" "$verdict"
}

gen /tmp/tc1.txt 20000
check_hz "均匀 20ms" /tmp/tc1.txt 50 0 0

# 双峰是限流器作用在量化源上的真实形态（lpos 实测就是 16/24ms 交替，均值 20ms）
gen /tmp/tc2.txt 16000 24000
check_hz "双峰 16/24ms（lpos 实况）" /tmp/tc2.txt 50 0 0

# 造卡顿必须把空洞之后的时间戳整体平移；只改一行会让下一行相对它回退，
# 凭空造出一个非单调点（第一版就这么错的，然后误判成估计量的问题）
gen /tmp/tc3.txt 16000 24000
awk 'NR>=5{print $1+200000; next}{print}' /tmp/tc3.txt > /tmp/tc3b.txt
check_hz "双峰 + 1 个 200ms 卡顿" /tmp/tc3b.txt 50 1 0

gen /tmp/tc4.txt 20000
awk 'NR==10{print 1000; next}{print}' /tmp/tc4.txt > /tmp/tc4b.txt
check_hz "含 1 个回退时间戳" /tmp/tc4b.txt 50 1 1

printf '1000000\n1020000\n1040000\n' > /tmp/tc5.txt
read -r hz5 _ _ < <(_trimmed_hz /tmp/tc5.txt)
if [[ "$hz5" == "0.000" || "$hz5" == "0" ]]; then
  printf '  %-32s -> %8s Hz   （样本不足，正确拒绝）\n' "只有 3 条样本" "$hz5"
else
  printf '  %-32s -> %8s Hz   期望 0（样本不足应拒绝）  [不符]\n' "只有 3 条样本" "$hz5"; FAILED=1
fi

echo ""
if [[ "$FAILED" == 0 ]]; then echo "全部用例通过"; else echo "有用例失败"; fi
exit "$FAILED"
