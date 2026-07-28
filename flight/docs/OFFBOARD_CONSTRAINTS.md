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

### 7.1 一个尚未坐实但影响实现的观察：示例的时间戳写法在 lockstep 下不可靠

阶段 A 里发布节点全程存活（日志确认 SIGTERM 是 25 s 后我们自己发的），
但 PX4 在第 16.22 s 就报了 `offboard_control_signal_lost`。

**合理解释**（未做对照实验，勿当结论）：官方示例用 `this->get_clock()->now()`
（ROS 时钟 = 墙钟）填 `timestamp`，而 PX4 在 lockstep 下走仿真时钟。
先前实测过两者存在会漂移的秒级偏移（最大 -4.7 s，PX4 时钟超前）。
一旦偏移超过 `COM_OF_LOSS_T`（1.0 s），PX4 就会把持续到达的 setpoint 判为过期。

**对实现的影响是明确的**：`skylark_autopilot_iface` 不要照抄示例的时间戳写法。
可选做法（按可靠性排序）：
1. 订阅任一 `/fmu/out/*` 话题，用最近收到的 PX4 `timestamp` 加本地经过时间外推
2. 用 `/fmu/out/timesync_status` 的偏移量把本地时钟换算到 PX4 时钟域
3. 节点开 `use_sim_time` 并确认 `/clock` 源确实是 PX4 时钟（SITL 下未验证）

待验证：把时间戳改成 PX4 时钟域后，长时间 offboard 是否就不再掉线。
这是 Takeoff action 的第一个回归测试项。

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
