# Offboard 控制的真实约束（实测）

> 这份文档是 `skylark_autopilot_iface` 的设计依据。所有数字都是在 PX4 **v1.17.0** +
> Gazebo Harmonic + headless SITL 上实测的，不是从文档抄的。
>
> 复现：`bash flight/sitl/exp_offboard_constraints.sh`
> 原始数据：`99_notes/exp_offboard{,2,3}/`（report.txt + state_*.csv 状态时间线）
> 最后更新：2026-07-28

---

## 1. 六条硬约束

| # | 约束 | 实测值 | 对 action 设计的影响 |
|---|---|---|---|
| 1 | 进入 OFFBOARD 模式**不需要解锁** | 出厂参数下 0.56 s 就从 AUTO_LOITER 切到 OFFBOARD，此时仍是 DISARMED | 模式与解锁是两道**独立的门**。action 不能用「进了 OFFBOARD」推断「已解锁」 |
| 2 | 切模式前必须已有 setpoint 流 | 官方示例先以 10 Hz 发满 10 条再切模式 | action 必须先起心跳，再切模式，再解锁。顺序反了会被拒 |
| 3 | headless SITL 下**解锁会被拒** | `Preflight Fail: No connection to the GCS` → `Arming denied: Resolve system health failures first` | 「解锁被拒 + 原因」是一条**正常返回路径**，不是超时。必须把原因回传给调用方 |
| 4 | setpoint 断流容限 `COM_OF_LOSS_T` | **1.0 s**（出厂值） | 心跳发布频率下限。官方示例用 10 Hz，余量 10 倍。低于 1 Hz 必然触发失效保护 |
| 5 | 断流后的行为是 **RTL 并自动降落** | 断流 → ~1 s 触发 `Failsafe activated` → `AUTO_RTL` → `RTL: land at destination` → 约 12 s 后 `Disarmed by landing` | **停止发 setpoint 不是安全的收尾方式**。action 结束/被取消时必须显式移交到 AUTO_LOITER 等模式，否则飞机会自己返航降落 |
| 6 | 爬升速率 | 从地面到 4.5 m 用 7.30 s，约 0.65 m/s | action 的超时阈值按此量级设，别按瞬时完成设 |
| 7 | headless SITL 下 `gcs_connection_lost` 与 `manual_control_signal_lost` **恒为真** | `failsafe_flags` 全程报这两项（没 QGC 也没遥控） | 这就是约束 3 的机制。action 不能把「有 failsafe 标志位」当成异常，要**按标志位逐项判断** |

### 7.1 一个未解释的观察：发布节点存活但 offboard 信号被判丢失

阶段 A 里发布节点全程存活（日志确认 SIGTERM 是 25 s 后我们自己发的），
但 PX4 在第 16.22 s 就报了 `offboard_control_signal_lost`。

**先前写在这里的解释是错的，已撤回。** 原文说「示例用 ROS 时钟填 timestamp
而 PX4 走仿真时钟，偏移超过容限导致 setpoint 被判过期」，据此要求实现层自己
做时钟换算。读源码后该说法不成立：

```c
// dds_topics.h.em / 生成后的 dds_topics.h，入站分支
const int64_t time_offset_us = session->time_offset / 1000;
ucdr_deserialize_trajectory_setpoint(*ub, data, time_offset_us);
ucdr_deserialize_offboard_control_mode(*ub, data, time_offset_us);
```

**入站 `/fmu/in/*` 的 timestamp 已经由 `uxrce_dds_client` 用 `time_offset_us`
换算过。** 所以用 ROS 时钟填 `timestamp` 是设计上正确的做法，示例没错，
实现层也不需要额外换算。

**浸泡测试给出了机制证据，但现象是间歇性的：3 轮里只有 1 轮复现。**
复现脚本：`bash flight/sitl/soak_offboard.sh [时长秒] [输出目录]`
原始数据：`99_notes/soak/report.txt`（90 s，复现）、`99_notes/soak2/`（45 s，未复现）。

⚠ 不要把下面这组数据当作「每次都会这样」。**触发条件未知**，
所以既不能靠它算出丢失频率，也不能据此判断一次几分钟的飞行必然会遇到。
能确定的只有「它会发生」，这已经足以决定实现必须容错。

复现的那一轮里发布节点全程存活（PID 核实），90 s 内自发丢失 2 次，且**每次恢复
都紧跟一次时钟偏移跳变，跳变过程中偏移会瞬间变成 0**：

```
[ 0.52s] offboard_control_signal_lost: None -> True     ← 尚未发 setpoint，正常
[ 7.02s] timesync 偏移跳变: -1785406211247446 -> 0 -> -1785406209466230us
[ 7.11s] offboard_control_signal_lost: True -> False    ← 跳变后立刻恢复
[27.23s] offboard_control_signal_lost: False -> True    ← 自发丢失
[37.73s] timesync 偏移跳变: ... -> 0 -> -1785406207770396us
[37.79s] offboard_control_signal_lost: True -> False    ← 又是跳变后立刻恢复
[88.01s] offboard_control_signal_lost: False -> True
```

那个瞬间的 0 正对应源码里的 `session->time_offset = 0`（重置分支）。
**推测的链路**（与观测一致，但未做受控实验证明因果）：lockstep 下 PX4 的偏移估计
逐渐陈旧 → 入站 setpoint 的时间戳漂出 `COM_OF_LOSS_T`（1.0 s）容限被判过期
→ `offboard_control_signal_lost` 置真 → 一次重新同步把偏移纠回来 → 标志清除。

两轮之间还有个可能相关的差异：复现那轮 `timesync` 的 `round_trip_time` 最大 4000 us，
未复现那轮全程为 0。即两轮的同步交互本身就不同，值得作为下次排查的切入点。

注意复现那一轮飞机未解锁，所以没触发 RTL；**解锁飞行时同样的抖动会真的触发失效保护**。

`uxrce_dds_client.cpp` 每秒做一次 `uxr_sync_session`，并且**会失去收敛**：

```c
} else if (_timesync_converged && !_timesync.sync_converged()) {
        PX4_DEBUG("time sync no longer converged");
}
```

失去收敛时 `session->time_offset` 变化，在途 setpoint 的时间戳会随之偏移，
可能被判过期。麻烦的是这两条日志是 `PX4_DEBUG`，**默认级别不打印**，
所以历史日志里查不到，只能靠订阅 `/fmu/out/timesync_status` 观察偏移量跳变来定性。

### 7.2 根因已定，且有根治手段：`UXRCE_DDS_SYNCT=0`

做了受控对照（`bash flight/sitl/test_synct_effect.sh`，同机同条件各 90 s，
只差一个参数，原始数据 `99_notes/synct1/report.txt`）：

| `UXRCE_DDS_SYNCT` | 自发丢失 | 偏移跳变 | 备注 |
|---|---:|---:|---|
| 1（出厂） | **3 次 / 90 s** | 6 | 周期 30 s，每次持续约 10 s，即约 1/3 时间处于丢失态 |
| 0 | **0 次 / 90 s** | 0 | 同时 `nav_state` 能正常进入 OFFBOARD |

**机制**：偏移估计逐次为 `-1785419768.15s → -1785419765.92s → -1785419763.33s`，
即 **lockstep 仿真时钟比墙钟慢约 8%（每 30 s 漂 2.5 s）**，而 PX4 每 30 s 才校正一次。
漂移一旦超过 `COM_OF_LOSS_T`，入站 setpoint 被判过期 → 信号丢失 → 下次校正后恢复。

**因此「抬高 `COM_OF_LOSS_T`」不是解决办法**，只是把边界往后挪：
漂移峰值 2.5 s，设成 3.0 s 时好时坏 —— 集成测试里实测到设了 3.0 仍被
`AUTO.RTL` 接管。关掉时间戳换算才是解决。

**代价，必须记住**：
- `SYNCT=0` 后 `/fmu/out/*` 的 `timestamp` 是 **PX4 开机计时**而非系统纪元。
  任何拿它跟墙钟直接相减的工具都要改口径
  （`measure_dds_topics.py` 只用时间戳**差值**算频率，不受影响；
  `watch_vehicle_state.py` 里与墙钟比较的部分会失去意义）。
- 真机上是否也需要关，取决于真机时钟是否同样漂。真机没有 lockstep，
  预期稳定得多，**S2 必须重测再决定**，不要照搬 SITL 的设置。

### 7.3 对 action 实现的影响（不依赖上面的缓解是否启用）

`offboard_control_signal_lost` 可能在发布端完全正常时出现。判据用**时间**而不是次数：
`failsafe_flags` 实测只有约 1.85 Hz，按「连续 N 帧」算会隐含一个随发布频率变化的时长。
实现里用「该标志持续为真超过 grace 秒」，默认 3 s。

但要认清这个去抖的作用范围：**它只影响我们何时报告，保护不了飞行。**
`COM_OF_LOSS_T` 出厂 1.0 s，飞控会在任何应用层宽限期到期前就切 `AUTO_RTL` 接管
（集成测试场景 B 实测到「飞控接管（模式 AUTO.RTL），原因: offboard_signal_lost」）。
所以这类问题只能在飞控侧解决，不能靠调用方容忍。

## 2. 官方示例的机制（`px4_ros_com` 的 `offboard_control`）

```
10 Hz 定时器：
  ├─ 第 10 拍：发 VEHICLE_CMD_DO_SET_MODE(param1=1, param2=6)  → 切 OFFBOARD
  │            发 VEHICLE_CMD_COMPONENT_ARM_DISARM(param1=1)   → 解锁
  └─ 每一拍：  发 OffboardControlMode{position=true} + TrajectorySetpoint{z=-5.0}
```

要点：
- `OffboardControlMode` 与 `TrajectorySetpoint` **必须成对发**，只发一个不生效
- `VehicleCommand.from_external` 必须为 `true`，否则被当作内部指令
- 示例只解锁一次（计数到 11 就停），**不做降落也不做异常处理** —— 它是最小示例，
  不能直接当作 action 的实现骨架
- 示例用 `this->get_clock()->now()` 填 `timestamp`（ROS 时钟）。SITL 下由于
  uxrce_dds_client 做过时间同步，两边基本对齐；真机上这个假设要复核

## 3. 三个会让 SITL 实验失效的陷阱

这三个都实际把我的结论带偏过，记下来避免重犯。

### 3.1 PX4 SITL 会持久化参数

参数存在 `build/px4_sitl_default/rootfs/parameters.bson`（外加 `parameters_backup.bson`），
**跨重启保留**。上一轮实验改的参数会静默影响下一轮。

我因此得出过错误结论：v2 里 `NAV_DLL_ACT` 的"出厂值"显示为 0，据此判断
「官方示例不需要关失效保护就能解锁」。实际那个 0 是前一轮实验设进去的。
删档重测后，出厂值确认是 2，解锁确实被拒。

```bash
# 实验前清空，保证可复现
rm -f "$PX4_DIR/build/px4_sitl_default/rootfs/parameters.bson" \
      "$PX4_DIR/build/px4_sitl_default/rootfs/parameters_backup.bson"
```

⚠ 注意不是 `rootfs/eeprom/parameters*` —— 那是我最初猜的路径，不存在。

### 3.2 `kill -TERM` 打在 `ros2 run` 上杀不掉真正的进程

`ros2 run` 是个 Python 启动器，SIGTERM 只结束包装进程，被启动的可执行继续运行。
后果是「以为停了 setpoint，其实一直在发」，据此测出的失效保护时间全是假的。

```bash
# 直接跑安装目录下的可执行，PID 可控
"$WS/install/px4_ros_com/lib/px4_ros_com/offboard_control" &
# 停止后必须核实
pkill -f offboard_control; pgrep -f offboard_control && echo "还有残留"
```

### 3.3 SITL 电池会放电，约 1.5 分钟后污染任何飞行测试

`COM_LOW_BAT_ACT` 出厂值为 3，低电量会触发 RTL。我一度把这个 RTL 当成了
setpoint 断流的失效保护。

```bash
param set COM_LOW_BAT_ACT 0     # 只告警不动作，用于长测试
```

**别用日志判断失效保护的原因。** 我先写过「看紧跟 `Failsafe activated` 的那一行」，
这条判据是错的：`tone_alarm` 的提示音与触发原因无关。实测中由 setpoint 断流
触发的失效保护，紧跟的一行照样是 `battery warning (fast)`。

可靠判据是 `/fmu/out/failsafe_flags`，它按原因分了标志位：

| 字段 | 含义 |
|---|---|
| `offboard_control_signal_lost` | setpoint 断流 |
| `gcs_connection_lost` | 地面站链路丢失（就是约束 3 拦住解锁的那个） |
| `manual_control_signal_lost` | 遥控信号丢失 |
| `battery_warning` | 电池告警等级（枚举见 `BatteryStatus.msg`） |

辅助判据是**时序**：断流后约 `COM_OF_LOSS_T`（1.0 s）触发的，基本可断定是 offboard 丢失；
飞了一分多钟才触发的，先怀疑电池。

## 4. 由此确定的 Takeoff action 骨架

```
接到 goal（目标高度、超时）
  ├─ 前置校验：EKF2 有效（vehicle_local_position.z_valid）、已收到 vehicle_status
  ├─ 起心跳：10 Hz 发 OffboardControlMode + TrajectorySetpoint（当前位置 + 目标高度）
  ├─ 攒够 ≥10 拍后切 OFFBOARD 模式，确认 nav_state==14
  ├─ 请求解锁，然后**必须区分三种结果**：
  │    ARMED                  -> 继续
  │    Arming denied          -> 立刻 abort，把 PX4 的拒绝原因回传（约束 3）
  │    超时无响应              -> abort，报"无响应"，与"被拒"分开报
  ├─ 持续发心跳并反馈高度进度（爬升约 0.65 m/s，超时按此设）
  ├─ 到达目标高度 ±阈值 -> succeed
  └─ 收尾（无论成功、失败、被取消）：
       显式切到 AUTO_LOITER 交还控制权，**不能只是停发 setpoint**（约束 5）
```

需要单独测的开放项：
- 移交到 AUTO_LOITER 后停发 setpoint 是否安全（预期安全，因为已不在 OFFBOARD，但未实测）
- 真机上 `COM_OF_LOSS_T` 是否仍为 1.0 s，以及串口链路下 10 Hz 心跳的实际抖动
- 真机的 GCS 连接要求（S2 阶段有 QGC 在线时约束 3 应自动满足，需验证）
