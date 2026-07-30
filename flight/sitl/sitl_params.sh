#!/usr/bin/env bash
# SITL 下 PX4 参数的**单一来源**。供其它 sitl 脚本 source，不要直接执行。
#
# 为什么要收拢
# ------------
# 2026-07-31 清点时，6 个脚本各自手写了一遍参数块，而且已经漂了：
#   test_flight_actions.sh / test_follow_path.sh -> COM_OF_LOSS_T=5.0 + SYNCT=0
#   test_takeoff_action.sh                       -> COM_OF_LOSS_T=3.0，不设 SYNCT
# 后者当时还能跑过，但那是运气（SYNCT 保持出厂 1 时时钟伺服会自动发纪元时间），
# 不是设计。更糟的是它的注释还在引用**已经撤回**的结论。
# 参数值决定了所有 offboard 结论的可信度，这种东西不能散落在 6 份注释里。
#
# 刻意不放进来的
# --------------
# NAV_DLL_ACT：各脚本对它的期望不同，必须由调用方自己控制。
#   test_flight_actions.sh 的场景 A 要它保持**出厂 2**（headless 下挡解锁，
#   用来验「解锁被拒且带回飞控真实原因」），之后才设 0；
#   test_follow_path.sh 一开始就设 0。写进公共块会悄悄毁掉场景 A。
# UXRCE_DDS_SYNCT 的对照实验（test_synct_effect.sh / test_vehicle_state.sh）
#   本身要两个口径都跑，所以那两个脚本不用这里的 apply。

# ---- 参数值与理由 ----
#
# COM_LOW_BAT_ACT=0：SITL 电池约 1.5 分钟放完，出厂动作 3(RTL) 会在测试中途
#   把飞机带走，污染后续场景。
#
# UXRCE_DDS_SYNCT=0：关掉 uXRCE-DDS 的时间戳同步。受控对照各 90 s
#   （test_synct_effect.sh，原始数据 99_notes/synct1）：出厂 1 时自发丢失 3 次，
#   设 0 后 0 次。⚠ 代价：/fmu/out/* 的 timestamp 变成 PX4 开机计时而非系统纪元，
#   出站方向也必须改用 PX4 刻度（px4_link 的时钟伺服负责）。
#   ⚠ reboot_required —— 设完必须 param save 并重启 PX4 才生效。
#
# COM_OF_LOSS_T=5.0：抬 setpoint 断流容限。这是**仿真侧补偿**，不是实现修复。
#   依据（详见 docs/OFFBOARD_CONSTRAINTS.md §7.4）：lockstep 仿真时钟会离散前跳，
#   实测单次 1.93 s（相邻两帧位置消息之间本机走 7 ms、飞控走 1936 ms）。
#   跳变超过容限时，任何由发送端填写的时间戳都会在那一瞬间被判过期，
#   发送端无法规避。发布端与时间戳算法都已单独排除（心跳间隔 101~148 ms，
#   平稳期时间戳滞后 −45~+7 ms，即容限的 0.5%~0.7%）。
#   ⚠ 真机没有 lockstep，不该有这种跳变，S2 必须重新评估，不要照搬。
#   ⚠ 代价：机载电脑真失联时飞机会多盲飞约 4 秒 —— 这一点由
#     test_flight_actions.sh 的「挑衅」场景实测背书（SIGKILL 节点后测接管延迟）。
SITL_COM_LOW_BAT_ACT=0
SITL_UXRCE_DDS_SYNCT=0
SITL_COM_OF_LOSS_T=5.0

# 供断言与日志引用，避免调用方再写死数字
SITL_PARAM_SUMMARY="COM_LOW_BAT_ACT=${SITL_COM_LOW_BAT_ACT}, UXRCE_DDS_SYNCT=${SITL_UXRCE_DDS_SYNCT}, COM_OF_LOSS_T=${SITL_COM_OF_LOSS_T}"

# sitl_params_apply <pxh_fd>
#   往 pxh 控制台的文件描述符写 param set，并 param save。
#   调用方负责之后重启 PX4（SYNCT 是 reboot_required）。
sitl_params_apply() {
  local fd="$1"
  echo "param set COM_LOW_BAT_ACT ${SITL_COM_LOW_BAT_ACT}" >&"$fd"; sleep 2
  echo "param set UXRCE_DDS_SYNCT ${SITL_UXRCE_DDS_SYNCT}" >&"$fd"; sleep 2
  echo "param set COM_OF_LOSS_T ${SITL_COM_OF_LOSS_T}" >&"$fd"; sleep 2
  echo "param save" >&"$fd"; sleep 2
}

# sitl_params_readback <pxh_fd> <px4_log> [额外参数名...]
#   发 param show 并把解析后的值行打到 stdout（每行形如 COM_OF_LOSS_T [282,509] : 5.0000）。
#   只截取本次 mark 之后的日志，避免读到上一轮的旧值 —— 踩过。
sitl_params_readback() {
  local fd="$1" px4log="$2"; shift 2
  local mark; mark=$(wc -c < "$px4log")
  local p
  for p in COM_LOW_BAT_ACT UXRCE_DDS_SYNCT COM_OF_LOSS_T "$@"; do
    echo "param show $p" >&"$fd"; sleep 1.5
  done
  sleep 2
  tail -c "+${mark}" "$px4log" | sed 's/pxh> //g' \
    | grep -oE '[+*x ] +(COM|NAV|UXRCE)_[A-Z0-9_]+ \[[0-9,]+\] : [-0-9.]+' \
    | sed 's/^[+*x ] *//'
}

# sitl_params_assert <读回文本> [额外期望正则...]
#   逐项断言并调用**调用方定义的** ok/bad 计数函数。
#   为什么一定要断言而不是打印：只打印的话，「参数没生效」这个可能永远排除不掉，
#   一次真失败就得多花一轮才能定性 —— 实测吃过这个亏。
sitl_params_assert() {
  local parsed="$1"; shift
  local expect
  # 注意 COM_OF_LOSS_T 的读回是 5.0000，所以正则只匹配到整数位
  for expect in "COM_LOW_BAT_ACT.*: ${SITL_COM_LOW_BAT_ACT}" \
                "UXRCE_DDS_SYNCT.*: ${SITL_UXRCE_DDS_SYNCT}" \
                "COM_OF_LOSS_T.*: ${SITL_COM_OF_LOSS_T%%.*}" \
                "$@"; do
    if echo "$parsed" | grep -qE "$expect"; then
      ok "参数生效: ${expect%%.*}"
    else
      bad "参数未生效: ${expect%%.*} —— 后续结论不可信"
    fi
  done
}
