# 串口与带宽预算（Pixhawk 6C）

> 结论先行（2026-07-27 实测修正）：**PX4 默认话题集在 921600 串口上约占裸容量的 52%，装得下。**
> SITL 悬停实测载荷 40.9 kB/s（飞控自报）／43.4 kB/s（订阅端实测），加每条 16 B 帧开销约 47.9 kB/s，
> 对 921600 8N1 的 92,160 B/s 裸容量为 52%。留有余量，**不裁剪也能跑**，但裁剪仍能换来更大安全边际。
>
> ~~原结论：默认话题集跑满串口（估算占用 100.3%），不裁剪一定丢包。~~
>
> **⚠ 为什么撤回原结论**（三个独立错误，详见 §7）：
> 1. 用错了 PX4 源 —— 估算读的是 Windows 侧 PX4 **main 分支**（`8e7b370`，浅克隆），
>    不是项目锁定的 **v1.17.0**。两份 `dds_topics.yaml` 有 9 处差异
> 2. 两个带宽大户的速率是猜的 —— v1.17.0 里 `vehicle_odometry` 与 `vehicle_attitude`
>    都没有 `rate_limit` 行，工具按 `--default-rate 10` 算，实测均为 100 Hz（**低估 10 倍**）
> 3. 预算公式重复扣开销 —— 分母乘了 0.65「扣除协议帧头」，分子又逐条加了 16 B 帧头
>
> 三个错误方向相反、大致相互抵消，所以原数字看着"合理"，实际站不住。
>
> 数据来源：
> - 实测：`flight/tools/measure_dds_topics.py`（SITL 悬停 25 s，PX4 v1.17.0，
>   结果存 `flight/tools/measured_dds_sitl_inflight.json`）
> - 飞控侧交叉验证：pxh 控制台 `uxrce_dds_client status` 的 `Payload tx`
> - 估算（仅作设计期参考）：`flight/tools/dds_bandwidth.py`
>
> 最后更新：2026-07-27（实测修正）

---

## 1. 为什么这份文档必须存在

6C 的两条硬约束（见 `HARDWARE_FLIGHT_LAYER.md` §3）：

- **没有以太网口**（6X 有，6C 没有）
- **只有 3 个串口**，机载电脑链路的实用上限是 921600 bps

这意味着飞控与机载电脑之间的**全部**状态交互要挤在一条串口里。而 PX4 默认桥接了 31 个下行话题，其中 `vehicle_odometry` 一个就跑 100 Hz。

在 6X（有千兆以太网）上这不是问题。在 6C 上这是首要设计约束。

---

## 2. 串口预算怎么算

**⚠ 原来的算法是错的，先说清楚错在哪：**

```
❌ 可用字节率 = 921600 / 10 × 0.65 ≈ 59,904 B/s     # 分母扣 35% 说是"协议开销"
❌ 每话题成本 = (载荷 + 16 B 帧头) × 速率            # 分子又逐条加帧头
```

同一份协议开销被扣了两次。占用率因此被系统性放大约 1.5 倍。

**修正后的算法** —— 开销只在分子出现一次：

```
裸容量   = 波特率 / 10 = 921600 / 10 = 92,160 B/s
线上字节 = Σ(CDR 载荷 × 速率) + 每条帧开销 × Σ速率
占用率   = 线上字节 / 裸容量
```

- 除以 10：8N1 串口每字节传 10 位（1 起始 + 8 数据 + 1 停止）。这一步是物理事实，保留
- 不再乘 0.65：那不是容量的一部分，而是**工程留白目标**。留白应作为判定阈值（建议 ≤70%），
  不该塞进分母 —— 塞进分母就没法回答"实际占了多少"这个问题

**每条消息的帧开销为什么必须单独算**：`dds_topics.h.em` 的发送循环里，每条 uORB 消息
都单独 `uxr_flash_output_streams(session)`，源码里还留着 `// TODO: fill up the MTU and
then flush, which reduces the packet overhead`。也就是说当前实现**不做 MTU 聚合**，
一条消息 = 一个帧。

→ 帧开销按**条数**摊，不按字节数摊。小消息高频发送时开销可能超过载荷本身
（`vehicle_control_mode` 载荷 28 B，加 16 B 帧头后成本涨 57%）。
这就是"话题数量比话题大小更重要"的源码级依据。

帧开销取 16 B/条仍是**估算**（XRCE 串行帧头 + submessage 头的量级）。要变成实测，
只能在真实串口上数字节 —— S2 阶段做，或用 socat 造 pty 对把 client 与 agent 都切到
serial 传输后统计。SITL 走 UDP，量不到串口帧。

---

## 2.5 实测结果（SITL 悬停，PX4 v1.17.0）

复现：`bash flight/sitl/measure_inflight.sh`（起 SITL → 关 `NAV_DLL_ACT` → 解锁 → 起飞 →
悬停 2.5 m → 采 25 s）。原始数据 `flight/tools/measured_dds_sitl_inflight.json`。

实际有数据的 13 个话题（其余 14 个在悬停状态下一条不发，见下方说明）：

| 话题 | CDR 载荷 B | 实测 Hz | B/s | yaml `rate_limit` |
|---|---:|---:|---:|---|
| `vehicle_odometry` | 120 | 99.99 | 11,998 | **无上限** |
| `vehicle_local_position_v1` | 220 | 49.98 | 10,996 | 50 |
| `vehicle_attitude` | 56 | 100.00 | 5,600 | **无上限** |
| `sensor_combined` | 52 | 100.00 | 5,200 | 无上限 |
| `vehicle_gps_position` | 168 | 30.30 | 5,091 | 50（源只有 30 Hz，限流未触发） |
| `vehicle_global_position` | 76 | 49.99 | 3,800 | 50 |
| `battery_status_v1` | 180 | 1.00 | 180 | 5 |
| `failsafe_flags` | 96 | 1.85 | 178 | — |
| `vehicle_status_v1` | 84 | 1.98 | 167 | 5 |
| `estimator_status_flags` | 104 | 0.99 | 103 | — |
| `vehicle_control_mode` | 28 | 1.98 | 56 | 50 |
| `timesync_status` | 48 | 0.99 | 48 | — |
| `vehicle_land_detected` | 24 | 1.00 | 24 | 5 |
| **合计** | | **440 msg/s** | **43,440** | |

**两个独立测量互相印证**：

| 口径 | 数值 | 说明 |
|---|---:|---|
| 订阅端实测（本表合计） | 43,440 B/s | rclpy `serialize_message` 长度，含 4 B CDR 封装头 |
| 飞控自报 `Payload tx` | 40,852 B/s | `num_payload_sent += topic_size`，纯 CDR 体，不含封装头 |
| 差值 | 2,588 B/s ≈ 5.9 B/条 | 与「4 B 封装头 + 取整」吻合 |

**加帧开销后的链路占用**：

```
40,852 (飞控自报载荷) + 16 × 440 (帧开销估算) = 47,893 B/s
47,893 / 92,160 = 52.0%   ← 对 921600 8N1 裸容量
```

52% 在 70% 的安全线以内 → **默认话题集不裁剪也装得下**。

### 三条必须说清的限制

1. **悬停 ≠ 全工况。** 14 个话题在这次测量里零消息：`airspeed_validated`（固定翼才有）、
   `gimbal_device_attitude_status`（没装云台）、`collision_constraints`（未启用内置避障）、
   `manual_control_setpoint`（SITL 没接遥控 —— **真机接了遥控这条会按 25 Hz 发，约 +2 kB/s**）、
   `wind`（EKF 未输出风估计）、`vtol_vehicle_status`、`transponder_report` 等。
   → 真机的实际占用会高于 52%，但抬升幅度在几个百分点量级，不改变结论。
2. **一次性话题测不到。** 订阅端刻意用 VOLATILE QoS（跳过 TRANSIENT_LOCAL 历史回放），
   代价是只在解锁瞬间发一次的话题（`home_position`）在采集窗口里看不见。
   对带宽预算无影响（一次性话题的 B/s 趋近 0），但不能据此说它"不发"。
3. **SITL 速率 ≠ 真机速率。** `sensor_combined` / `vehicle_attitude` / `vehicle_odometry`
   的 100 Hz 由仿真的 IMU 与 EKF2 输出节奏决定，真机 ICM-42688-P 的速率链不同。
   **S2 阶段必须在 6C 上重测**，方法见 §6。

---

## 3. 四个方案的估算结果（⚠ 已被 §2.5 的实测取代，保留作对照）

下表由 `dds_bandwidth.py` 算出，用的是 **PX4 main 分支**的 yaml 与 **10 Hz 默认速率假设**，
分母还多扣了一次 0.65。**数值不可引用**，保留是为了留下审计轨迹、以及裁剪方案的相对排序仍有参考价值：

| 方案 | 裁掉的话题 | 字节率 | 占预算 | 判定 |
|---|---|---:|---:|---|
| **默认** | 无 | 60,060 B/s | **100.3%** | ❌ 跑满，必然丢包 |
| **A** | 固定翼 + 云台 + 避障 + 遥控透传 | 51,785 B/s | 86.4% | ⚠ 余量不足 |
| **B** | A + `vehicle_odometry` | 39,385 B/s | **65.7%** | ✅ 可用 |
| **C** | B + `vehicle_gps_position` + `position_setpoint_triplet` | 29,300 B/s | 48.9% | ✅ 宽松 |

### 各方案裁掉什么、为什么能裁

**方案 A** —— 裁掉本项目用不到的：

| 话题 | Hz | B/s | 为什么能裁 |
|---|---:|---:|---|
| `airspeed_validated` | 50 | 2,850 | 空速，固定翼才用，多旋翼无意义 |
| `gimbal_device_attitude_status` | 20 | 1,400 | 没装云台。装了再加回来 |
| `collision_constraints` | 50 | 2,000 | 未启用 PX4 内置避障（避障在机载电脑侧做） |
| `manual_control_setpoint` | 25 | 2,025 | 遥控杆量透传到 ROS 2，本项目不需要 |

**方案 B** —— 再裁 `vehicle_odometry`（100 Hz，12,400 B/s，**单话题占默认总量的 20.6%**）：

这是带宽第一大户。它存在的意义是给外部视觉/激光里程计做融合（`EKF2_EV_*` 那套）。
本项目是**室外 GPS 巡检**，位置来源是 GNSS，不做 VIO 融合。
→ 可以整条裁掉。位姿信息从 `vehicle_local_position` + `vehicle_attitude` 拿就够了。

⚠ **如果后续要做 GNSS 拒止环境（桥下、厂房内）的 VIO 巡检，这条必须加回来**，届时带宽会重新变紧，可能需要换 6X 或加以太网方案。这是架构决策点，记在这里备查。

**方案 C** —— 再裁两个诊断类话题：

| 话题 | 为什么能裁 |
|---|---|
| `vehicle_gps_position` | 原始 GNSS 报文（159 B / 50 Hz = 8,750 B/s）。经纬度从 `vehicle_global_position` 已经能拿到，原始报文只用于诊断卫星数、HDOP 等。改成 1 Hz 或只在调试时开 |
| `position_setpoint_triplet` | 251 字节，任务航点三元组。本项目用 Offboard + 自定义状态机，不走 PX4 内置 mission |

---

## 4. 推荐配置

**S1 SITL 阶段**：不裁。仿真走 UDP，没有串口瓶颈，保留全部话题便于探索。

**S2 / S3 真机阶段**：⚠ 建议已随实测改变。

实测显示默认话题集只占裸容量 52%，**"必须裁剪"的前提不成立**。修正后的建议：

1. **先按默认配置上真机测一轮**。这是最省事也最诚实的做法 —— 现在有 §6 的正确测法，
   直接量真机的实际占用，不必先按估算去裁
2. **若实测超过 70%**，优先裁 `vehicle_odometry`（单条 12.0 kB/s，占实测总量 27.6%，
   本项目做 GPS 巡检不需要 VIO 融合），一条就能降到 40% 附近
3. **再不够就降 `rate_limit`**，而不是删话题 —— 保留话题意味着保留诊断能力

`vehicle_gps_position` 不建议裁：实测只有 5.1 kB/s（估算说 8.75 kB/s，高估 42%，
因为 SITL 的 GPS 源只有 30 Hz，50 的 `rate_limit` 压根没触发），
而卫星数与定位精度在真机调试阶段很值钱。花 5 kB/s 买这个可见性是划算的。

**若实测发现方案 B 仍丢包**：优先降 `rate_limit` 而不是删话题。例如：

```yaml
  - topic: /fmu/out/vehicle_local_position
    type: px4_msgs::msg::VehicleLocalPosition
    rate_limit: 20.       # 从 50 降到 20，省 6,240 B/s
```

巡检任务的控制频率需求不高（Offboard 只要 ≥2 Hz 就能维持，见 PX4 官方 Offboard 文档），50 Hz 的位置更新对巡检是过剩的。

---

## 5. 怎么改

裁剪不是改机载电脑，是**改固件里的 `dds_topics.yaml` 后重新编译刷入**：

```bash
# 在 WSL2 的 PX4-Autopilot 里
$EDITOR src/modules/uxrce_dds_client/dds_topics.yaml
make px4_fmu-v6c_default
# 刷入：QGC 自定义固件，或 make px4_fmu-v6c_default upload
```

⚠ **修改后必须同步记录到 `flight/params/CHANGELOG.md`**，因为这是固件级改动，不是参数改动 —— 换一块板子或重刷官方固件就丢了。这是最容易踩的坑：调好的话题裁剪，重刷官方固件后全部复原，然后"莫名其妙又丢包了"。

---

## 6. 实测校准

### ❌ 不要用 `ros2 topic hz` / `ros2 topic bw` 做校准

本文档此前推荐这两个命令，**那是错的**，按它做会得出偏低且不可复现的数字。

它们量的是**订阅端每秒收到多少**，不是飞控发了多少。`/fmu/out/*` 是 BEST_EFFORT
QoS，rclpy 订阅端跟不上时消息静默丢弃。实测证据（2026-07-27，同一个健康系统）：

| 现象 | 数据 |
|---|---|
| `ros2 topic hz /fmu/out/vehicle_local_position_v1` 两轮读数 | 50.004 Hz / 21.427 Hz（两轮 Gazebo RTF 都是 1.0） |
| 同一时刻时间戳法读数 | 稳定 49.9~50.1 Hz |
| 订阅端落后最新消息 | 4~18 s（在排 TRANSIENT_LOCAL 历史积压） |

`ros2 topic bw` 同病：它的 B/s 也是接收速率。它的 `Message size mean` 可以用，
但精度只到 0.01 KB（225 B 显示成 0.22 KB）。

### ✅ 正确的三个校准手段

```bash
# 1) 订阅端：用消息内 timestamp 反推发布频率 + 精确 CDR 字节数
#    对丢包免疫（丢包只让间隔变整数倍，不改变众数结构；估计量用截尾均值）
python3 flight/tools/measure_dds_topics.py --duration 25 --out measured.json

# 2) 飞控自报（独立交叉验证，强烈建议每次都对一下）
#    真机走 QGC → Analyze → MAVLink Console；SITL 走 pxh 控制台
uxrce_dds_client status          # 看 Payload tx / timesync converged
#    口径：num_payload_sent 累加各话题 CDR 体大小，不含 XRCE 帧头

# 3) 飞控侧的 uORB 侧真实频率（排除桥的影响，定位问题在源还是在桥）
uorb top -1
```

**两个来源必须对照**。订阅端数值应比飞控自报高约 4 B/条（rclpy 的 CDR 封装头）。
差得更多说明订阅端在丢包，这时订阅端的数不可信、飞控自报的可信。

### SITL 下给 pxh 控制台发命令

真机可以用 QGC 的 MAVLink Console，SITL headless 没有终端。用 FIFO 顶住 stdin：

```bash
mkfifo /tmp/px4_in
( cd "$PX4_DIR" && HEADLESS=1 make px4_sitl gz_x500 < /tmp/px4_in ) > px4.log 2>&1 &
exec 3>/tmp/px4_in        # 必须用 fd 顶住写端，否则 px4 读到 EOF 立刻退出
echo "uxrce_dds_client status" >&3
```

⚠ headless SITL 里解锁会被拒（`Preflight Fail: No connection to the GCS`，因为没有
QGC 连上来）。测飞行工况前先 `param set NAV_DLL_ACT 0`，并且**必须验证**
日志里出现 `Armed` 与 `Takeoff detected` —— 否则拿到的是静止数据。
可运行示例见 `flight/sitl/measure_inflight.sh`（含解锁/起飞的结果校验）。

**S2 阶段的验收标准**（修正 `HARDWARE_FLIGHT_LAYER.md` §7 的表述）：
用上面手段 1 测得 `vehicle_local_position` 的发布频率稳定在 `rate_limit` 附近
（不是用 `ros2 topic hz`），且 `uxrce_dds_client status` 连续 30 分钟保持
`Running, connected` 与 `timesync converged: true`。

---

## 7. 估算工具的已知偏差

`dds_bandwidth.py` 的精度声明（工具内也有同样说明）：

| 偏差来源 | 方向 |
|---|---|
| 未计算 CDR 序列化对齐填充 | 低估，通常几字节/消息 |
| 帧开销按固定 16 B 估计 | 可能低估 |
| 变长数组按声明最大长度计 | 高估 |
| 无 `rate_limit` 的话题速率用假设值（默认 10 Hz） | 不确定 |
| `px4_msgs` 版本必须与固件一致 | 不一致时字段不匹配，工具会报警 |

### 7.1 已确认发生的三个错误（2026-07-27 实测暴露）

不是"可能偏差"，是实际算错了。记在这里备查。

**错误一：源不对。** §9 的复现命令指向 Windows 侧的 `01_px4_core/PX4-Autopilot`，
那是 **main 分支 `8e7b370` 的浅克隆**，不是锁定的 v1.17.0；`px4_msgs` 同样是 main。
两份 `dds_topics.yaml` 实测有 **9 处差异**，其中两处直接决定结论：

| 话题 | main（算数字用的） | v1.17.0（锁定的） |
|---|---|---|
| `vehicle_odometry` | `rate_limit: 100` | **无上限** |
| `vehicle_attitude` | `rate_limit: 50` | **无上限** |

话题总数也不同（69 vs 65）。核实脚本：`flight/tools/diff_dds_topics_yaml.sh`。

**错误二：`--default-rate 10` 对最大的两个话题失效。** v1.17.0 里 `vehicle_odometry`
与 `vehicle_attitude` 都没有 `rate_limit`，工具按 10 Hz 算，实测都是 100 Hz ——
这两条合计被低估 15.8 kB/s。反方向上，14 个悬停时压根不发的话题被算成了真实负载
（方案 A 声称裁掉的 8.3 kB/s 里有一大部分本来就不存在）。

**错误三：分母重复扣开销。** 见 §2 修正说明。

**教训**：估算工具的输入必须与"正在跑的那个二进制"来自同一棵源码树。
判据的真值来源如果能从文件读出来，就不要写死数字或用默认假设 ——
`measure_dds_topics.py` 与 `smoke_test.sh` 现在都是运行时读 yaml。

---

## 8. 串口分配（最终方案）

| 端口 | 分配 | 波特率 | 说明 |
|---|---|---|---|
| TELEM1 | 数传 → 地面站 QGC | 57600 | 默认 MAVLink，独立 1.5 A 限流 |
| **TELEM2** | **机载电脑 uXRCE-DDS** | **921600** | 本文档的主题 |
| TELEM3 | 预留 | — | 测距仪 / 第二数传 / 调试 |
| GPS1 | GNSS + 罗盘 + 安全开关 | — | 固定用途 |
| GPS2 | 预留 | — | RTK 或第二 GNSS |

无以太网口，无扩展余量。若未来需要更高带宽（VIO / 多传感器融合），只有两条路：
1. 换 6X（有千兆以太网 + PAB 形态，可上 Jetson Baseboard）
2. 数据在机载电脑侧处理完再回传结论，不回传原始数据（当前架构就是这么设计的）

---

## 9. 复现本文档的数字

### 实测（§2.5 的数字，这是权威来源）

```bash
# 在 WSL2 里跑。全程无人值守约 3 分钟：起 SITL → 解锁 → 起飞 → 悬停采样 → 清理
bash flight/sitl/measure_inflight.sh                  # 权威口径（悬停）
bash flight/sitl/measure_inflight.sh --no-takeoff     # 静止对照
# 输出：flight/tools/measured_dds_sitl_inflight.json（悬停）
#      flight/tools/measured_dds_sitl.json（静止）
#      $MEASURE_OUT_DIR/report.txt，默认 /tmp/skylark_measure/report.txt
#      （报告尾部含飞控自报的 Payload tx，用于与订阅端实测交叉验证）
```

### 估算（⚠ 仅设计期参考，数值不可引用）

⚠ **必须用锁定版本的源**。此前用的是 Windows 侧 `01_px4_core/PX4-Autopilot`，
那是 PX4 **main 分支的浅克隆**，不是 v1.17.0 —— 这是 §7.1 错误一的直接来源。
锁定版本的源在 WSL 里：`~/PX4-Autopilot`（v1.17.0）与 `~/ros2_ws/src/px4_msgs`（release/1.17）。

```bash
# 在 WSL2 里跑，用锁定版本的两棵树
python3 /mnt/c/Users/Klara/Desktop/PX4/skylark/flight/tools/dds_bandwidth.py \
  --dds-topics ~/PX4-Autopilot/src/modules/uxrce_dds_client/dds_topics.yaml \
  --msg-dir    ~/ros2_ws/src/px4_msgs/msg \
  --publications-only \
  --default-rate 100          # ⚠ 不要用默认的 10：v1.17.0 里无 rate_limit 的
                              #   vehicle_odometry / vehicle_attitude 实测都是 100 Hz

# 核实两份 yaml 的差异（解释历史数字为什么对不上）
bash flight/tools/diff_dds_topics_yaml.sh
```

---

## 10. 这份分析的论文价值

这组数据可以直接写进论文的「系统实现」或「工程约束分析」章节：

> 在成本敏感的机载平台上，飞控与机载计算单元之间的通信带宽是被普遍低估的设计约束。
> 本文以 Pixhawk 6C（无以太网接口，串口上限 921600 bps）为例，用两种互相独立的方法
> 实测了 PX4 v1.17.0 默认 uXRCE-DDS 话题集的下行占用：订阅端按消息时间戳反推的
> 43.4 KB/s，与飞控固件自报的 40.9 KB/s（两者差值可由 CDR 封装头解释）。
> 计入协议帧开销后约占 8N1 链路裸容量的 52%。进一步分析表明，
> 由于当前实现对每条消息单独 flush 而不做 MTU 聚合，帧开销随**消息条数**而非
> 字节数增长，因此话题数量比话题体积对带宽的影响更大。

⚠ **不要再引用 60.1 KB/s / 100.3%** —— 那组估算有三个已确认的错误（见 §7.1）。

这段的论文价值反而比原来更高：从"我算了一下"变成"我用两种独立方法测了，
还交叉验证了差值来源，并从源码解释了开销的标度规律"。

另外多出一个可写的点：**估算与实测的偏差分解**。同一份配置，估算 60.1 KB/s
vs 实测 40.9 KB/s，偏差来自三个方向相反的误差源（源码版本不一致、无 `rate_limit`
话题的速率假设、事件驱动话题被当作常发负载）。这类"为什么设计期估算会错"的分析
在工程论文里比一个孤立的数字更有说服力。

公开文献里给这类完整量化的很少 —— 多数论文用 6X 或 Jetson 一体板，直接走以太网，遇不到这个约束。这是**低成本平台特有的工程贡献**，且是你现有实验做不到的。
