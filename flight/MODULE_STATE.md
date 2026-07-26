# 飞控层 MODULE STATE

> 上次更新：2026-07-27 by Window-E
> 上次同步主 STATE 时间：2026-07-27（本模块首次建立，同步登记于主 STATE §0.1 与 §6）
> 下次同步预计：下一个周日

---

## 1. 模块身份

- 模块名：飞控层（Flight Control Layer）
- 归属窗口：**Window-E（飞控 + 仿真）** — 本次新增的第 5 个窗口
- 所在目录：`flight/{ros2_ws,params,sitl,tools,docs}`
- 一句话职责：把 PX4 飞控接入 Skylark，提供「飞行动作」抽象给 `edge/` 调用，并承担地理配准与飞行安全
- 开发机器：`METAMECHBOOK01`（AMD RX 7600M XT，无 CUDA）— 与 ML 训练机物理隔离

---

## 2. 当前进度

- 当前活跃任务：**S0 骨架搭建已完成，等待用户执行首次硬件上电**
- 启动时间：2026-07-27
- 预计完成：S1（纯软 SITL）3-4 周，低强度并行推进
- 阻塞情况：
  - ⏸ **等用户操作**：6C 插 USB 刷固件 + 校准 + 导出 `.params` 基线（约 1 小时，无需配件）
  - ⏸ **等用户操作**：WSL2 装 Ubuntu 22.04（`wsl --install -d Ubuntu-22.04`），之后即可跑 `flight/sitl/bootstrap_wsl2.sh`
  - ⏸ **等用户拍板**：`HARDWARE_FLIGHT_LAYER.md` §12 的范围取舍（第三个检测场景 vs 真机闭环）

---

## 3. 已完成（2026-07-27，本模块首日）

- [x] 2026-07-27：确认两台机器角色分工，写入 `HARDWARE_FLIGHT_LAYER.md` §4
- [x] 2026-07-27：版本锁定决策（PX4 v1.17.0 / px4_msgs release/1.17 / ROS 2 Humble / Ubuntu 22.04 / Gazebo Harmonic），单一来源 `flight/VERSIONS.md`
- [x] 2026-07-27：仿真器选型从 AirSim 改为 Gazebo Harmonic（AirSim 及其主要 fork Colosseum 均已归档）
- [x] 2026-07-27：接口契约包 `skylark_flight_msgs` 落地（6 msg + 5 action + 3 srv = 14 个接口）
- [x] 2026-07-27：写 `validate_interfaces.py` 并自测通过（14/14 接口无错误）
- [x] 2026-07-27：写 `dds_bandwidth.py`，**算出 PX4 默认 DDS 话题集占满 6C 串口预算 100.3%**
- [x] 2026-07-27：三份实操文档（`WIRING_6C.md` / `SERIAL_BUDGET.md` / `SAFETY_CHECKLIST.md`）
- [x] 2026-07-27：WSL2 环境引导脚本 `bootstrap_wsl2.sh`（幂等，含 AMD 渲染兜底）
- [x] 2026-07-27：修复 `.kiro/skills/.../scripts/*.sh` 的 CRLF 行尾（4 个文件，WSL 下会报 bad interpreter），并加 `.gitattributes` 防复发

---

## 4. 待办（按优先级）

- [ ] [紧急·用户操作] 6C 首次上电：刷 v1.17.0 → 全套校准 → 导出 `pixhawk6c_bench_v1.params` → 登记到 `params/CHANGELOG.md`
- [ ] [紧急·用户操作] `wsl --install -d Ubuntu-22.04` + 配 `.wslconfig`
- [ ] [本周] 跑 `bootstrap_wsl2.sh`，确认 `colcon build` 通过、`ros2 interface show skylark_flight_msgs/action/InspectSweep` 有输出
- [ ] [本周] 跑通 PX4 官方 `offboard_control` 示例（SITL + Gazebo）
- [ ] [本周] 在 `release/1.17` 分支的 px4_msgs 上重跑 `dds_bandwidth.py`，校准 `SERIAL_BUDGET.md` 的估算
- [ ] [S1] 实现 `skylark_autopilot_iface`：Takeoff / Land / Orbit 三个 action 的 PX4 实现
- [ ] [S1] 实现 `skylark_inspection_mode`：InspectSweep / Revisit 状态机 + 声明式任务 YAML 解析
- [ ] [S1] 做一个光伏电站 Gazebo 世界（`sitl/worlds/`）
- [ ] [S1] 实现 `skylark_bridge`：DetectionArray + VehicleState 时间对齐 → GeoTaggedDetection
- [ ] [S1 验收] 仿真机自主起飞 → 扫掠 → 检出 → 降高复拍 → 返航，全程录屏
- [ ] [S2] 6C + 机载电脑地面联调（拆桨），验证串口带宽与 DDS 稳定性
- [ ] [S3] 真机飞行（需机架 / 电池 / 遥控 / 场地）
- [ ] [长期] 评估 `mc_nn_control`（PX4 自带端到端神经控制器，有 fmu-v6c 专用编译目标）— 见 `HARDWARE_FLIGHT_LAYER.md` §13，本期不做

---

## 5. 已知事实（关键产出）

> 这一段是给其他窗口看的。所有数值均可复核。

| 事实 | 数值 / 位置 | 时间 | 来源 |
|---|---|---|---|
| **PX4 默认 DDS 话题集下行带宽** | **60,060 B/s = 921600 串口预算的 100.3%** | 2026-07-27 | `flight/tools/dds_bandwidth.py` |
| 裁剪方案 B 后的带宽 | 39,385 B/s = 65.7% | 2026-07-27 | 同上，`--exclude` 五个话题 |
| 带宽第一大户 | `/fmu/out/vehicle_odometry` 100 Hz = 12,400 B/s（占默认总量 20.6%） | 2026-07-27 | 同上 |
| 6C 串口数量 | 3 个（TELEM1/2/3），**无以太网** | 2026-07-27 | PX4 官方 `flight_controller/pixhawk6c.md` |
| 6C 端口限流 | TELEM1 独立 1.5 A，其余端口**合计** 1.5 A | 2026-07-27 | 同上 |
| 6C 不是 PAB 形态 | 插不进 Holybro Jetson Baseboard，必须分体式 | 2026-07-27 | Holybro 飞控对比表 6C 的 Baseboard 栏为 N/A |
| 6C 编译目标 | `px4_fmu-v6c_default`，另有 neural/rover/raptor/visionTargetEst×2 | 2026-07-27 | `boards/px4/fmu-v6c/*.px4board` |
| TELEM2 设备节点 | `/dev/ttyS3`（UART5） | 2026-07-27 | PX4 官方串口映射表 |
| 接口契约规模 | 6 msg + 5 action + 3 srv = 14 个，全部通过静态校验 | 2026-07-27 | `validate_interfaces.py` |
| `mc_nn_control` 可用版本 | release/1.16、1.17、1.18、main 均存在 | 2026-07-27 | GitHub API contents 查询 |
| `NeuralControl` 内置耗时埋点 | `controller_time` / `inference_time`（μs），logger 订阅 → 自动进 `.ulg` | 2026-07-27 | `PX4-user_guide/en/msg_docs/NeuralControl.md` |
| AirSim 状态 | microsoft/AirSim 已归档，主要 fork Colosseum 亦已归档 | 2026-07-27 | GitHub API `archived=true` |

---

## 6. 与其他窗口的依赖

**我提供给**：

| 窗口 | 我提供什么 |
|---|---|
| Window-C（后端 + 边缘） | `skylark_flight_msgs` 接口契约 —— `edge/` 的推理节点按此发布 `DetectionArray`、调用 `Revisit` action。`GeoTaggedDetectionArray` 是上行到 `platform/` 的数据单元 |
| Window-B（论文 + 文档） | 串口带宽量化分析（可写进「工程约束分析」章）、真机 `.ulg` 飞行日志（「飞行验证」章）、端到端延迟分解实测 |
| Window-A（ML 主线） | 真机/仿真采集的图像可反哺训练；`Revisit` 复拍图像是「同一目标多分辨率」的天然数据源 |

**我依赖于**：

| 窗口 | 我需要什么 | 时机 |
|---|---|---|
| Window-A | 导出好的检测模型（ONNX/TRT），用于 S1 仿真闭环里的感知节点 | S1 中段，不紧急（可先用 yolo11n 官方权重占位） |
| Window-C | Jetson 上的推理服务与 `edge/` 目录结构；机载电脑是共用硬件，装机成本只付一次 | S2（Q2 中） |
| Window-B | 追认 `HARDWARE_FLIGHT_LAYER.md`，并更新 `MASTER_ARCHITECTURE.md` / `PROJECT_NORTH_STAR.md` 的相关段落 | 本周 |

---

## 7. 风险与决策记录

- [2026-07-27] **决策**：仓库许可证定为 AGPL-3.0。根因是 `ultralytics` 为 AGPL-3.0 且本项目要对外提供 Web 服务。详见 `THIRD_PARTY_LICENSES.md`
- [2026-07-27] **决策**：仿真器 AirSim → Gazebo Harmonic。除 AirSim 已归档外，追加决定性理由是本机为 AMD GPU，Isaac Sim/Pegasus 跑不了，AAS 的 CUDA Docker 栈也跑不了
- [2026-07-27] **决策**：`flight/` 归 Window-E 而非 Window-C。知识域不重叠，混窗口会污染上下文。原属 Window-D 的 `simulation/` 并入本模块
- [2026-07-27] **决策**：版本锁定 v1.17.0 对齐 AAS，而非更保守的 v1.16.2。理由是代码参考零适配摩擦 > 两轮补丁
- [2026-07-27] **风险**：串口带宽是本模块最大的架构约束。默认配置已占满 100.3%。若后续要做 GNSS 拒止环境的 VIO 巡检，`vehicle_odometry` 必须加回来，带宽会重新变紧 → 届时只能换 6X（有以太网 + PAB）或坚持「机载处理完只回传结论」的现有架构
- [2026-07-27] **风险**：ROS 2 Humble 官方配对 Gazebo Fortress，本项目用 Harmonic。基础闭环不需要 `ros_gz`（PX4 直连 gz transport，ROS 2 经 uXRCE-DDS 连 PX4），仅相机取流需要桥。届时按 AAS 的 GStreamer 方案或验证 `ros-humble-ros-gzharmonic`
- [2026-07-27] **风险（最高）**：挤占论文时间。Q1 是论文季且在关键路径上。缓解措施是 `HARDWARE_FLIGHT_LAYER.md` §8 的「低强度并行」硬约束（每周 3-5 小时，优先安排在 v2 训练等待时段）。**每周日 review 时若发现论文进度落后于原计划，立刻暂停本模块**
- [2026-07-27] **风险**：AMD GPU 上 Gazebo 渲染性能未知。`bootstrap_wsl2.sh` 已内置 `MESA_D3D12_DEFAULT_ADAPTER_NAME` 与 `LIBGL_ALWAYS_SOFTWARE` 兜底；最差退路是 `HEADLESS=1` 只用传感器数据不出图
- [2026-07-27] **事故记录**：Kiro 在重构工作副本目录时，`Move` 失败后紧随的 `Remove-Item -Recurse` 无条件执行，误删了本仓库的本地 clone。因是零本地修改的干净 clone，重新 clone 即完全恢复，无数据损失。教训已记录：不把清理动作链在可能失败的操作之后
- [2026-07-27] **行尾问题（已加固，但性质与初判不同）**：在本机工作区发现 `.kiro/skills/skylark-coordination/scripts/` 下 4 个 `.sh` 为 CRLF 行尾。
  用 `git ls-files --eol` 核实后确认：**仓库内(index)一直是 LF**，CRLF 是本机 `core.autocrlf=true` 在 checkout 时生成的，仓库内容本身没有缺陷。
  但这仍是**实际风险**：从 WSL 访问 Windows 工作区（`bash /mnt/c/.../status.sh`）会拿到 CRLF 版本并报 `bad interpreter: /usr/bin/env bash^M`。Window-E 正好要这么用。
  处置：新增 `.gitattributes` 声明 `*.sh text eol=lf`，强制任何平台 checkout 都得到 LF。已用 `git check-attr` 与 `git ls-files --eol` 验证生效（`i/lf w/lf attr/text eol=lf`）。
  初判「已存在的 bug」不准确，此处更正留档
- [2026-07-27] **未决**：`HARDWARE_FLIGHT_LAYER.md` §12 的范围取舍提请（第三个检测场景 vs 真机闭环 + 视频→台账管线）。按 `PROJECT_NORTH_STAR.md`「广 vs 深优先深」原则应选后者，但涉及 `MASTER_ARCHITECTURE.md` 的「≥3 场景」承诺，等用户拍板
