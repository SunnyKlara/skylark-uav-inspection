# 串口与带宽预算（Pixhawk 6C）

> 结论先行：**PX4 的默认 `dds_topics.yaml` 在 6C 的 921600 串口上是跑满的（估算占用 100.3%）。**
> 不裁剪就直接联调，一定丢包。
>
> 数据来源：`flight/tools/dds_bandwidth.py` 基于 PX4 v1.17 的 `dds_topics.yaml` 与 `px4_msgs` 实际消息定义计算。
> 最后更新：2026-07-27

---

## 1. 为什么这份文档必须存在

6C 的两条硬约束（见 `HARDWARE_FLIGHT_LAYER.md` §3）：

- **没有以太网口**（6X 有，6C 没有）
- **只有 3 个串口**，机载电脑链路的实用上限是 921600 bps

这意味着飞控与机载电脑之间的**全部**状态交互要挤在一条串口里。而 PX4 默认桥接了 31 个下行话题，其中 `vehicle_odometry` 一个就跑 100 Hz。

在 6X（有千兆以太网）上这不是问题。在 6C 上这是首要设计约束。

---

## 2. 串口预算怎么算

```
可用字节率 = 波特率 / 10 × 有效载荷率
           = 921600 / 10 × 0.65
           ≈ 59,904 B/s
```

- 除以 10：8N1 串口每字节要传 10 位（1 起始 + 8 数据 + 1 停止）
- ×0.65：扣除 XRCE-DDS 协议帧头、会话管理、重传开销。这是保守估计值，实测可校准

每条消息的开销按 16 字节计（XRCE-DDS 帧头）。小消息高频发送时，**开销可能超过载荷本身** —— 例如 `mode_completed` 载荷仅 10 字节，加上 16 字节开销后实际成本翻了 2.6 倍。这是"话题数量比话题大小更重要"的原因。

---

## 3. 四个方案的实算结果

用 `dds_bandwidth.py` 计算，只算下行（飞控 → 机载电脑，这是瓶颈方向）：

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

**S2 / S3 真机阶段**：用**方案 B**。

理由：方案 C 虽然更宽松，但裁掉 `vehicle_gps_position` 后失去卫星数与定位精度的实时可见性 —— 真机调试阶段这些诊断信息很值钱。方案 B 的 65.7% 已经在安全线（70%）以内，没必要再压。

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

估算只用于设计阶段。联调时必须实测：

```bash
# 机载电脑侧：单话题实际带宽
ros2 topic bw /fmu/out/vehicle_local_position

# 机载电脑侧：实际频率（对比 rate_limit 是否生效）
ros2 topic hz /fmu/out/vehicle_local_position

# 飞控侧（QGC → Analyze → MAVLink Console）：客户端状态与丢包
uxrce_dds_client status

# 飞控侧：uORB 话题的真实发布频率
uorb top
```

**S2 阶段的验收标准**（见 `HARDWARE_FLIGHT_LAYER.md` §7）：
`ros2 topic hz /fmu/out/vehicle_local_position` 稳定在预期频率，连续 30 分钟不断连。

把实测值填回本文档，替换估算值。

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

⚠ 本次计算用的 `px4_msgs` 是本地 clone 的 **main 分支**，而项目锁定的是 **release/1.17**。
两者的消息定义可能有差异。到 WSL2 建好 `release/1.17` 的工作区后，用正确分支重跑一次校准。

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

```powershell
cd c:\Users\Klara\Desktop\PX4

# 默认配置
python skylark\flight\tools\dds_bandwidth.py `
  --dds-topics 01_px4_core\PX4-Autopilot\src\modules\uxrce_dds_client\dds_topics.yaml `
  --msg-dir 02_ros2_bridge\px4_msgs\msg --publications-only

# 方案 B
python skylark\flight\tools\dds_bandwidth.py `
  --dds-topics 01_px4_core\PX4-Autopilot\src\modules\uxrce_dds_client\dds_topics.yaml `
  --msg-dir 02_ros2_bridge\px4_msgs\msg --publications-only `
  --exclude airspeed_validated gimbal_device collision_constraints manual_control_setpoint vehicle_odometry
```

---

## 10. 这份分析的论文价值

这组数据可以直接写进论文的「系统实现」或「工程约束分析」章节：

> 在成本敏感的机载平台上，飞控与机载计算单元之间的通信带宽是被普遍低估的设计约束。
> 本文以 Pixhawk 6C（无以太网接口，串口上限 921600 bps）为例，量化了 PX4 默认
> uXRCE-DDS 话题集的带宽占用（估算 60.1 KB/s，占链路可用预算的 100.3%），
> 并给出面向巡检任务的话题裁剪方案，将占用降至 65.7%。

公开文献里给这类完整量化的很少 —— 多数论文用 6X 或 Jetson 一体板，直接走以太网，遇不到这个约束。这是**低成本平台特有的工程贡献**，且是你现有实验做不到的。
