# 架构增量提案 — 飞控层 `flight/`

> 提案日期：2026-07-27
> 起草：Kiro（Window-E 筹建）
> 上承：`PROJECT_NORTH_STAR.md`、`MASTER_ARCHITECTURE.md`
> 状态：**已由用户授权执行**。本文同时作为决策记录（ADR）留档。
> 硬件：**Holybro Pixhawk 6C**（已到货）

---

## 0. 摘要

新增第五个模块层 `flight/`，把 `MASTER_ARCHITECTURE.md` §3.1 语境图右下角那个模糊占位符「无人机（大疆/PX4/AirSim 仿真）」实心化为**真实的 PX4 飞控闭环**。

**只增不改**：现有四层（`code/` `platform/` `edge/` `simulation/`）的归属与内容不变，`simulation/` 并入 `flight/sitl/`。

---

## 1. 变更背景：这是一次明确的方向变更

必须先承认矛盾。`PROJECT_NORTH_STAR.md`「不做什么」节写着：

> ❌ **不做硬件层**（飞控 / 控制算法 / 集群通信）—— 用现成大疆生态

`STATE.md` §9 也记录「不做飞控层（用大疆 SDK 或仿真替代）」，`MASTER_ARCHITECTURE.md` 结尾是「从今天起，不再变方向」。

**现在变更的理由**：

1. **硬件已到位**。Pixhawk 6C 在手，「用现成大疆生态」的前提（不碰飞控）已经不成立
2. **五维验收里「软硬协同」原本是软的**。原方案靠 Jetson 部署 + AirSim 仿真撑，答辩时被问「真机飞过吗」只能答没有。有了 6C，这一维从加分项变成硬证据
3. **原方案依赖的 AirSim 已死**（见 §3.2），本来就必须重做这块决策。既然要改，一并把飞控层做实

**变更代价**：见 §9 关键路径影响，以及 §12 范围取舍提请。

---

## 2. 已决策事项

### 2.1 决策一：仓库许可证 = AGPL-3.0

`ultralytics` 是 AGPL-3.0，网络传染。Skylark 目标包含对外可访问的 Web 平台，落入 AGPL 第 13 条。

已执行：新增 `LICENSE`（AGPL-3.0 官方全文，661 行）+ `THIRD_PARTY_LICENSES.md`（依赖矩阵 + copyleft 隔离策略）。

变更前本仓库**没有 LICENSE 文件**，法律上等于保留所有权利，与「完整开源」目标矛盾。

### 2.2 决策二：仿真器 = Gazebo Harmonic LTS，取代 AirSim

`MASTER_ARCHITECTURE.md` §6.1 原选型表给 AirSim 打 ✅、Gazebo 打 ❌，理由是「AirSim 虽停更但仓库 stable、社区活跃」和「Gazebo 视觉差、装机难」。这两条判断均已失效：

| 事实 | 核实方式 |
|---|---|
| microsoft/AirSim 已被微软**归档** | 微软官方项目页声明 |
| 主要社区 fork `CodexLabsLLC/Colosseum` **也已归档** | GitHub API `archived=true` |
| Gazebo Harmonic 是 **PX4 v1.16+ 官方仿真器** | 本地 `PX4-Autopilot/Tools/setup/ubuntu.sh` 第 215-231 行安装 `gz-harmonic` |
| Gazebo 视觉质量已足够 | AAS 内置 `swiss_town`（Pix4D 摄影测量实景）、`apple_orchard`（BlenderGIS 生成） |

**追加决定性理由**：飞控层开发机是 **AMD GPU**（见 §4）。Isaac Sim / Pegasus Simulator 要求 NVIDIA RTX，AirSim 的 UE 管线在 AMD + WSL2 上同样吃力。**Gazebo 是这台机器上唯一可行的选项**，不是折中，是唯一解。

### 2.3 决策三：`flight/` 归属新窗口 Window-E（飞控 + 仿真）

不并入 Window-C。理由：飞控知识域（PX4 参数、控制回路、飞行安全、串口调试）与 Window-C 的知识域（FastAPI、Docker、量化、TensorRT）几乎不重叠，混在一个窗口会互相污染上下文。原属 Window-D 的 `simulation/` 并入 Window-E —— Gazebo 世界与 SITL 本来就是一件事。

### 2.4 决策四：版本锁定

| 组件 | 锁定版本 | 理由 |
|---|---|---|
| PX4-Autopilot | **v1.17.0** | 与主要代码参考 AAS 完全对齐（AAS 亦锁 v1.17.0），零适配摩擦 |
| px4_msgs | **release/1.17** | 必须与固件版本严格对应 |
| ROS 2 | **Humble LTS** | PX4 官方推荐；且 Jetson 侧 JetPack 6 = Ubuntu 22 = Python 3.10 强制了这个选择 |
| Ubuntu（WSL2） | **22.04 LTS** | ROS 2 Humble 的官方平台 |
| Gazebo | **Harmonic LTS** | PX4 v1.16+ 官方仿真器，`ubuntu.sh` 自动安装 |
| Micro-XRCE-DDS-Agent | v2.4.3 起 | PX4 文档给定版本 |

版本号集中记录在 `flight/VERSIONS.md`，**只允许改那一处**。

备选方案 v1.16.2（有 2 轮补丁）已评估：更保守，但 AAS 的代码引用要做 msg 版本适配。判断为得不偿失。

---

## 3. 6C 的能力边界与由此导出的架构约束

规格来自 PX4 官方硬件页与 Holybro 文档，逐条核实。

| 项目 | 规格 |
|---|---|
| FMU | STM32H743，Cortex-M7 @ 480 MHz，2 MB Flash / 1 MB SRAM |
| IO 协处理器 | STM32F103 |
| IMU | ICM-42688-P + BMI055（双冗余，板载加热电阻温控） |
| 磁罗盘 / 气压 | IST8310 / MS5611 |
| 串口 | TELEM1（独立 1.5 A 限流）、TELEM2、TELEM3 —— **仅 3 个** |
| 以太网 | **无** |
| PWM | 16 路（IO 8 + FMU 8） |
| 电源 | 模拟电源模块，最大输入 6 V |
| 形态 | Pixhawk **连接器**标准，**非 PAB 模块化总线** |
| 编译目标 | `px4_fmu-v6c_default`（另有 neural / rover / raptor / visionTargetEst×2） |

### 导出的三条硬约束

**约束 1：必须走分体式，不能用 Jetson Baseboard。**
Holybro Pixhawk Jetson Baseboard 要求 **PAB 形态**飞控（如 6X）。6C 不是 PAB —— PX4 官方页只声明「符合 Pixhawk 连接器标准」，Holybro 飞控对比表中 6C 的 Baseboard 一栏为 N/A。
→ 6C + 独立机载电脑，TELEM2 串口互联（或 USB 转串口）。布线、供电、减振自行解决。
→ **AAS 的算法层与容器层可全抄，硬件部署层不可抄。**

**约束 2：图像数据绝不经飞控转发。**
无以太网，串口实用上限约 921600 bps。
→ 相机直接接机载电脑 USB/MIPI，视觉处理全部本地完成。串口只跑控制指令与状态回传，这点带宽绰绰有余。
→ 这条约束反过来**强化了 §5 的分层设计**：`edge/` 只发「看到了什么」，`flight/` 负责「怎么飞」。

**约束 3：串口预算必须提前规划。**
3 个串口的分配方案：

| 串口 | 分配 | 参数 |
|---|---|---|
| TELEM1 | 数传（QGC 地面站链路） | 默认 MAVLink |
| TELEM2 | **机载电脑 uXRCE-DDS** | `UXRCE_DDS_CFG=102`、`SER_TEL2_BAUD=921600`、`MAV_1_CONFIG=0` |
| TELEM3 | 预留（测距仪 / 第二数传 / 调试） | — |
| GPS1 | GNSS + 安全开关 | — |
| GPS2 | 预留（第二 GNSS / RTK） | — |

6C 的 TELEM2 映射到 `/dev/ttyS3`（UART5）。带宽紧张时通过裁剪 `PX4-Autopilot/src/modules/uxrce_dds_client/dds_topics.yaml` 中的话题与 `rate_limit` 字段调优。

---

## 4. 两台机器的角色分工

这是本次落地中发现的重要事实，必须写进架构。

| 机器 | 标识 | 硬件 | 角色 | 窗口 |
|---|---|---|---|---|
| ML 训练机 | E 盘 / `Administrator` | RTX 5060 Ti 16 GB（Blackwell sm_120）、32 GB RAM | v2 训练、量化、TensorRT、论文实验 | Window-A / B |
| 飞控开发机 | `METAMECHBOOK01` / `Klara` | **AMD RX 7600M XT + 780M 核显**、C 盘 1907 GB | PX4 固件、SITL、ROS 2、QGC 刷参、真机联调 | **Window-E** |

**三个后果**：

1. **GPU 抢卡问题不存在。** 飞控层与 v2 训练在物理隔离的两台机器上。此前「装 Gazebo 会抢卡拖慢训练」的担忧作废
2. **飞控开发机没有 CUDA。** AAS 的 Docker 栈跑不了（其 `check_requirements.sh` 要求 `nvidia-driver-580` + nvidia-container-toolkit）。→ 本机走**原生 WSL2 安装**，不用 Docker。AAS 作为**代码参考**而非可运行栈
3. **机载 AI 推理必须在 Jetson 上验证**，不能在飞控开发机上模拟。→ `edge/` 的量化与 benchmark 仍归 Window-C，在 ML 机 + Jetson 上做

**同步机制**：GitHub。两台机器各自 clone，通过 PR/分支协作。`STATE.md` 冲突按正常 git merge 处理 —— 这实际上比原「同一 workspace 多窗口」假设更干净，因为有 git 作为仲裁。

---

## 5. `flight/` 目录设计

```
flight/
├── README.md                       模块入口
├── MODULE_STATE.md                 按 module-state.md schema 的状态快照
├── VERSIONS.md                     版本锁定单一来源
│
├── ros2_ws/src/
│   ├── skylark_flight_msgs/        ★ 接口契约（先做，且只有这个是"必须先做"的）
│   │   ├── action/                 Takeoff / Land / Orbit / InspectSweep / Revisit
│   │   ├── msg/                    VehicleState / DetectionGeoTagged / FlightHealth
│   │   └── srv/                    SetSpeed / SetReposition / AbortMission
│   ├── skylark_autopilot_iface/    action 的 PX4 实现（对应 AAS 的 px4_interface.cpp）
│   ├── skylark_inspection_mode/    巡检任务状态机（航线 → 检出 → 复拍 → 续飞）
│   └── skylark_bridge/             flight ↔ edge ↔ platform 数据流粘合
│
├── params/
│   ├── pixhawk6c_<机架>_vN.params  QGC 导出的完整参数快照（版本化）
│   └── CHANGELOG.md                每次改参数记一行：改了什么 / 为什么 / 飞行验证结果
│
├── sitl/
│   ├── bootstrap_wsl2.sh           幂等环境引导（Ubuntu 22.04 + Humble + PX4 + Gazebo）
│   ├── run_sitl.sh                 一键起 SITL + XRCE Agent
│   └── worlds/                     光伏电站 Gazebo 世界
│
└── docs/
    ├── WIRING_6C.md                分体式接线（含供电与减振）
    ├── SAFETY_CHECKLIST.md         每次飞行前检查单
    └── SERIAL_BUDGET.md            串口与带宽预算
```

---

## 6. 接口契约（本提案的技术核心）

**设计原则来自 AAS**：`autopilot_interface` 用同一套 `.action` 定义，配 `px4_interface.cpp` 与 `ardupilot_interface.cpp` 两个实现。换飞控 = 换一个节点。

Skylark 的定位是「**通用**无人机航拍 AI 巡检平台」。如果飞控层直接耦合 PX4 的 uORB 话题，「通用」两字就是空话。所以**先定契约，再写实现**。

### 边界 1：`flight/` ↔ `edge/`（机上，ROS 2）

| 方向 | 话题 / 接口 | 类型 |
|---|---|---|
| `edge/` → | `/skylark/detections` | `DetectionArray`（视觉检出，带图像时间戳） |
| `flight/` → | `/skylark/vehicle_state` | `VehicleState`（位姿 + GNSS + 电量 + 时间戳） |
| `flight/` → | `/skylark/flight_health` | `FlightHealth`（模式、解锁状态、失效保护标志） |
| `edge/` 调用 | `/skylark/revisit` (action) | 请求「降高复拍」 |
| `edge/` 调用 | `/skylark/inspect_sweep` (action) | 请求「沿阵列扫掠」 |

**铁律：`edge/` 的视觉节点永远不发 setpoint。**
它只发布「我看到了什么」，然后 `send_goal` 请求一个高层动作。所有飞行安全逻辑收敛在 `flight/` 一处。

这条设计的直接价值：答辩必问「你的 AI 判断错了会怎样」。有了这个边界，答案是可指认的 —— 「所有飞行指令只从 `skylark_autopilot_iface` 一个节点出，那里有速度、高度、地理围栏三重约束，视觉节点物理上无法绕过」。

### 边界 2：`flight/` ↔ `platform/`

**不直连。** 机上数据由 `edge/` 汇总后经图传/4G 上行到 `platform/`。

理由：`platform/` 不应该知道 PX4 的存在。否则 Web 平台绑死在一种飞控上，而「通用平台」是 `MASTER_ARCHITECTURE.md` §1.2 的定位。

### 边界 3：任务定义 = 配置，不是代码

照抄 AAS 的 `missions/*.yaml` 声明式行为树：

```yaml
type: Sequence
name: PV_Array_Inspection
children:
  - action: takeoff
    params: { altitude: 25.0 }
  - action: inspect_sweep
    params: { rows: 8, row_spacing_m: 6.0, speed_mps: 3.0, overlap: 0.3 }
  - action: land
    params: { altitude: 20.0 }
on_detection:
  - action: revisit
    params: { descend_to_m: 8.0, hover_sec: 4.0, capture_burst: 5 }
```

**这条决定产品形态**：任务写在 YAML 里，前端才能让用户配置巡检航线；写死在 C++ 里，前端就只剩一个看板。`MASTER_ARCHITECTURE.md` §4 Q3-M8 规划了「用户创建项目时选场景」，那必然要求任务是可配置的数据。

---

## 7. 三阶段实施与验收标准

| 阶段 | 内容 | 硬性验收标准 | 硬件依赖 | 预估 |
|---|---|---|---|---|
| **S1 纯软 SITL** | WSL2 装 Ubuntu 22.04 + ROS 2 Humble + PX4 v1.17 SITL + Gazebo Harmonic；跑通官方 offboard 示例；实现巡检状态机 | 仿真机自主起飞 → 按航线飞光伏世界 → 检出缺陷 → 自动降高复拍 → 返航，全程录屏 | **无**（6C 都不用插） | 3-4 周 |
| **S2 HITL / 地面联调** | 6C 真机 + 机载电脑，**拆桨**，验证串口带宽、DDS 稳定性、时间同步 | `ros2 topic hz /fmu/out/vehicle_local_position` 稳定在预期频率，连续 30 min 不断连；`ros2 action send_goal` 能改变飞控模式 | 6C + 机载电脑 + 线材 | 2-3 周 |
| **S3 真机飞行** | 整机组装 → 地面测试 → 系绳低空 → 自由飞行 | 户外完整自主巡检一次，`.ulg` 能在 `flight_review` 正常解析，无 failsafe 触发 | 完整机架 + 电池 + 遥控 + 场地 | 4-6 周 |

**S1 完全不需要 6C，也不需要 NVIDIA GPU。** 意味着现在就能开始。

---

## 8. 时机与关键路径影响

`MASTER_ARCHITECTURE.md` §5 的关键路径是：v2 训练 → 实验章 → 中文初稿 → SCI 投稿。**这条链不能动。**

修正后的排期（基于「两台机器物理隔离」这一新事实）：

| 阶段 | 原计划 | 修正后 | 理由 |
|---|---|---|---|
| S1 SITL | Q2 中后段 | **现在起，低强度并行** | 无 GPU 冲突；安装/编译多为长时间无人值守，正好填 v2 训练的等待时间 |
| S2 HITL | Q3 初 | Q2 中（与 Window-C 的 Jetson 装机合并） | 同一台机载电脑，装机成本只付一次 |
| S3 真机 | Q3 末–Q4 初 | 不变 | 需要场地与天气，2-3 月较合适 |

**「低强度并行」的定义**：每周 3-5 小时，且优先安排在 v2 训练跑着、你只能等结果的时段。**不允许挤占论文写作时间。**

**现在立刻能做且只需 1 小时的事**（不依赖任何配件）：
6C 插 USB → QGC 刷 v1.17.0 → 全套校准 → 导出 `.params` 快照进 `flight/params/`。
产出一份「已知良好」基线配置，以后任何参数改动都能 diff。硬件放着会积灰，配置基线做出来就是永久资产。

---

## 9. 对现有文档的修改清单

| 文件 | 修改 | 归属窗口 | 状态 |
|---|---|---|---|
| `LICENSE` | 新增（AGPL-3.0） | — | ✅ 已执行 |
| `THIRD_PARTY_LICENSES.md` | 新增 | — | ✅ 已执行 |
| `HARDWARE_FLIGHT_LAYER.md` | 新增（本文） | Window-B 追认 | ✅ 已执行 |
| `MASTER_ARCHITECTURE.md` §6.1 | 仿真选型 AirSim → Gazebo Harmonic（旧决策折叠保留） | Window-B | ✅ 已执行 |
| `MASTER_ARCHITECTURE.md` §3.1 | C4 语境图：模糊占位符「无人机（大疆/PX4/AirSim）」→ 具体硬件栈 | Window-B | ✅ 已执行 |
| `MASTER_ARCHITECTURE.md` §3.3 | 技术栈表：仿真改 Gazebo，新增「飞控」「飞控通信」两行 | Window-B | ✅ 已执行 |
| `MASTER_ARCHITECTURE.md` §3.4 | 仓库组织增加 `flight/` | Window-B | ✅ 已执行 |
| `MASTER_ARCHITECTURE.md` §2 §4 | 五维验收与 Q3 路线图（场景数、Q3-M9 重写） | Window-B | ✅ 已执行 |
| `MASTER_ARCHITECTURE.md` §5 §8 | 风险点（AirSim 装机）与学习路径 M9 | Window-B | ✅ 已执行 |
| `.kiro/skills/.../references/windows.md` | 归属表增加 Window-E + 独占清单 + 特殊约定 | 共享（需提案） | ✅ 已执行 |
| `.kiro/skills/.../references/gpu-arbiter.md` | Q3 仿真不再参与 GPU 仲裁（跑在另一台机器） | 共享 | ✅ 已执行 |
| `.kiro/skills/.../references/handoff.md` | 仿真集成协作场景改为 Window-E ↔ Window-C | 共享 | ✅ 已执行 |
| `.kiro/steering/skylark-multi-window.md` | 铁律 1 归属表增加 `flight/**` + 机器分工 + 窗口识别 | 共享（需提案） | ✅ 已执行 |
| `MULTI_WINDOW_PROTOCOL.md` | Window-D 职责去掉 AirSim 仿真 | Window-B | ✅ 已执行 |
| `STATE.md` | Window-E 登记、机器分工、决策批次、handoff、修改日志、仿真选型 | 共享 | ✅ 已执行 |
| `PROJECT_NORTH_STAR.md`「不做硬件层」 | **保留原文加删除线 + 追加变更批注** | Window-B | ✅ 已执行 |
| `PROJECT_NORTH_STAR.md` 五条标准 | 场景数 3→2 + 视频→台账管线 | Window-B | ✅ 已执行 |
| `WINDOW_D_KICKOFF.md` | 头部加「⚠ 2026-07-27 变更说明（启动前必读）」对照表 | Window-B | ⚠ 部分执行，见下 |

> **⚠ `WINDOW_D_KICKOFF.md` 的遗留问题**：该文档正文（含要复制粘贴给新窗口的「启动语句」段）
> 仍有 19 处 AirSim / `simulation/` / 「前端 + 仿真」的过时表述。已在头部加了权威变更对照表，
> 但**正文未逐处改写** —— 它写于 2026-05-27，距实际启用（Q3，约 12 月）还有 5 个月，届时必然要整体重写。
>
> **已登记 handoff 给 Window-B**（见 `STATE.md` §待办交接）：Q3 启动 Window-D 之前必须重写该文档。
> 在此之前，启动 Window-D 时**必须把头部变更说明一并粘贴**，否则新窗口会按过时职责范围干活。

关于最后一条：北极星文档的价值在于**记录当时的判断**。不应该悄悄改掉历史判断假装从来没说过，而应该保留原文并标注「2026-07-27 变更，理由见 `HARDWARE_FLIGHT_LAYER.md` §1」。这是审计轨迹，也是诚实。

---

## 10. 风险与应对

| 风险 | 概率 | 应对 |
|---|---|---|
| WSL2 + Gazebo 在 AMD GPU 上渲染性能不足 | 中 | Gazebo 支持 `LIBGL_ALWAYS_SOFTWARE` 软渲染兜底；巡检世界不需要照片级真实。若仍不行，退路是 `HEADLESS` 模式 + 只用传感器数据 |
| 串口 921600 带宽不够跑所需话题 | 中 | 裁剪 `dds_topics.yaml`（逐话题设 `rate_limit`）。这本身是可写进论文的调优实验 |
| ROS 2 Humble 与 Gazebo Harmonic 版本配对（Humble 官方配 Fortress） | 中 | 基础闭环不需要 `ros_gz` —— PX4 直连 Gazebo（gz transport），ROS 2 经 uXRCE-DDS 连 PX4。仅相机取流需要桥，届时按 AAS 的 GStreamer 方案或验证 `ros-humble-ros-gzharmonic` |
| 真机首飞损毁 | 中 | S1/S2 全部通过才进 S3；拆桨测试 → 系绳低空 → 自由飞行，三级递进；失效保护参数先配齐 |
| 挤占论文时间 | **高** | §8 的「低强度并行」是硬约束。每周末 review 时检查：论文进度是否落后于原计划？若是，暂停 flight/ |

---

## 11. 对五维验收的影响

| 维度 | 原状态 | 加入 `flight/` 后 |
|---|---|---|
| 论文 | 第 5 章局限里写「尚未真机验证」 | 新增「系统集成与飞行验证」章，含真实 `.ulg` 日志分析 |
| 产品 | Web 平台 + 3 场景 | 同上，演示视频从仿真变真机 |
| **软硬协同** | Jetson 部署 + AirSim 仿真 | **真机 PX4 闭环**：起飞→巡航→检出→AI 反馈调整飞行→报告 |
| 工程质量 | pytest + CI/CD | 增加接口契约、参数版本化、飞行前检查单 |
| 个人能力 | Web 全栈 + 边缘 AI | + 飞控系统集成、控制系统调试 |

**新增的第一手发现候选**：端到端延迟实测分解 —— 相机曝光 → 取流 → 推理 → ROS 2 话题 → action → PX4 setpoint → 姿态响应，每一段的延迟。公开文献里给完整实测分解的很少，且这是现有实验做不到的。比再做一组 CBAM 消融有价值。

---

## 12. 范围取舍 — ✅ 已由用户拍板执行（2026-07-27）

`PROJECT_NORTH_STAR.md` 决策原则：

> 当遇到「广 vs 深」取舍时：**优先深**，但要保证至少有一个广度示例。

加入 `flight/` 后，两件事在**时间上直接竞争**：

| 事项 | 类型 | 成本 |
|---|---|---|
| 「≥3 个检测场景」的第三个场景（道路/屋顶） | 广 | 3-4 周（数据清洗 + 标注转换 + 训练） |
| 真机飞行闭环 + 「视频→缺陷台账」管线 | 深 | 8-10 周 |

**提请**：把第三个检测场景换成「真机闭环 + 视频→台账管线」。

场景数从 3 降到 2（光伏 + 输电），仍满足「至少一个广度示例」。深度显著提升。

**支撑理由**：现有 `code/` 只做到「单张图检测出框」。从「出框」到「电站缺陷台账」之间的**组件跟踪、多帧关联、地理配准**，才是「巡检平台」与「检测模型」的本质区别 —— 这恰好是论文里最容易做出第一手贡献的地方，也是第三个场景给不了的。参考实现：`PV-Hawk`（MIT，博士项目，完整管线）。

**✅ 已执行（2026-07-27，用户拍板）。** 同步修改的文件：

| 文件 | 位置 | 改动 |
|---|---|---|
| `PROJECT_NORTH_STAR.md` | 五条衡量标准 §2 产品 | 「≥3 场景」→「≥2 场景 + 视频→台账管线」，附变更批注 |
| `MASTER_ARCHITECTURE.md` | §2 五维验收表 | 同上 |
| `MASTER_ARCHITECTURE.md` | §4 Q3-M7 | 第 3 个场景（RDD2022 道路病害）划掉 |
| `MASTER_ARCHITECTURE.md` | §4 Q3-M9 | 整节重写：AirSim + 大疆 RTMP → 6C 真机闭环 + 视频→台账管线，归属移交 Window-E |
| `MASTER_ARCHITECTURE.md` | §4 Q3 产出 | 「3 个检测场景」→「2 个检测场景 + 真机闭环 + 台账管线」 |
| `STATE.md` | §2 五维当前状态 / §9 平台路径 / 待决策段 | 同步 |
| `WINDOW_D_KICKOFF.md` | 启动前检查 / Q3 期望产出 / 归属 | 场景数改 2；`simulation/` 移交 Window-E |
| `flight/MODULE_STATE.md` | §7 风险与决策 | 「未决」→ 已决 |

**腾出的 3-4 周去向**：投入 `flight/` 的 S3 真机阶段与「视频→缺陷台账」管线。
两者合计仍需 8-10 周，因此 Q3 的实际压力**没有减小** —— 这次取舍换的是**深度**，不是工期。
这一点必须说清楚，否则会误以为"少做一个场景就轻松了"。

---

## 13. 机会登记：PX4 自带端到端神经控制器（本期不做）

发现于本地 `PX4-Autopilot` 源码，逐条可复核：

| 证据 | 内容 |
|---|---|
| `boards/px4/fmu-v6c/neural.px4board` | **专为 6C 准备的板级配置**。开 `CONFIG_LIB_TFLM=y`（TensorFlow Lite Micro）+ `CONFIG_MODULES_MC_NN_CONTROL=y`，关掉 FW/VTOL/Rover 模块腾 flash。编译命令 `make px4_fmu-v6c_neural` |
| `src/modules/mc_nn_control/control_net.hpp` | `control_net_tflite_size = 15088` —— 15 KB TFLite 模型以字节数组编进固件 |
| 官方文档 `modules_controller.md` | 端到端控制器：输入 `[pos_err(3), att(6), vel(3), ang_vel(3)]` 共 15 维，输出 `[Actuator motors(4)]`。**跳过位置环、姿态环、角速率环、混控器全链路** |
| uORB `NeuralControl` | 含 `controller_time` 与 `inference_time`（微秒），Publisher `mc_nn_control`，Subscriber `logger` → **每个控制周期的推理耗时自动写进 `.ulg`** |
| 版本可用性 | release/1.16、1.17、1.18、main 均存在 |

**为什么登记**：`inference_time` 内置埋点意味着「STM32H743 上端到端神经控制器的实时性实测」这组数据**不需要写任何测量代码** —— 飞一次，用 `flight_review` 解析日志就有。这类完整实测在公开文献中罕见。

**为什么本期不做**：`Kconfig` 里 `default n`，说明尚未作为生产默认配置，稳定性与适用包线未知；训练管线来源不明。真机跑未验证的控制器风险过高。

**定位**：Q3/Q4 的「一切顺利则加分」项，**不进主线**。主线仍是视觉巡检闭环。

**建议动作**：开题时向导师提一句。它能让课题叙事从「YOLO 改进 + 部署」升级为「端到端智能飞行系统」，但作为选项而非承诺。

---

## 14. 一行结尾

> 先定 30 行接口契约，再写 3000 行实现。
> 先在仿真里飞一百次，再在天上飞第一次。
