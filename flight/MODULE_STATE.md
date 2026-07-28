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

- 当前活跃任务：**S1 开发环境已全部就绪**，下一步跑通 PX4 SITL + Gazebo，然后实现 `skylark_autopilot_iface`
- 启动时间：2026-07-27
- 预计完成：S1（纯软 SITL）3-4 周，低强度并行推进

### 环境就绪状态（2026-07-27 实测，全部核对过）

| 组件 | 实测值 | 与 `VERSIONS.md` 一致 |
|---|---|---|
| Ubuntu（WSL2） | 22.04 | ✅ |
| ROS 2 | humble | ✅ |
| PX4-Autopilot | `v1.17.0`（tag 精确匹配，33 子模块 0 缺失，2.6 GB） | ✅ |
| px4_msgs | `release/1.17` | ✅ |
| Gazebo | **Gazebo Sim 8.14.0**（Harmonic） | ✅ |
| Micro XRCE-DDS Agent | `/usr/local/bin/MicroXRCEAgent` | ✅ |
| **`skylark_flight_msgs`** | **14/14 接口已被 ROS 2 注册** | ✅ |
| `px4_ros_com` 示例 | 6 个可执行（含 `offboard_control`） | ✅ |
| NuttX 工具链 | `arm-none-eabi-gcc 10.3.1` | ✅ |
| WSL 资源 | nproc=12 / 内存 19Gi / swap 8Gi | ✅ 与 `.wslconfig` 一致 |

### 阻塞情况

- ⏸ **等用户操作**：6C 插 USB 刷固件 + 校准 + 导出 `.params` 基线（约 1 小时，无需配件）
      指导：`flight/docs/FLASH_AND_CALIBRATE_6C.md`（QGC 已装好，第 1 步可跳过）
- ⚠ **已知限制（不阻塞）**：Gazebo 只能软渲染（llvmpipe）。Ubuntu 22.04 的 Mesa 23.2
      没把 d3d12 接进 GLX 路径，`/usr/lib/wsl/lib` 与 `/dev/dxg` 都正常但用不上。
      功能完整、帧率低。改善路子见 `~/.skylark_env.sh` 内注释

---

## 3. 已完成（2026-07-27，本模块首日）

- [x] 2026-07-27：确认两台机器角色分工，写入 `HARDWARE_FLIGHT_LAYER.md` §4
- [x] 2026-07-27：版本锁定决策（PX4 v1.17.0 / px4_msgs release/1.17 / ROS 2 Humble / Ubuntu 22.04 / Gazebo Harmonic），单一来源 `flight/VERSIONS.md`
- [x] 2026-07-27：仿真器选型从 AirSim 改为 Gazebo Harmonic（AirSim 及其主要 fork Colosseum 均已归档）
- [x] 2026-07-27：接口契约包 `skylark_flight_msgs` 落地（6 msg + 5 action + 3 srv = 14 个接口）
- [x] 2026-07-27：写 `validate_interfaces.py` 并自测通过（14/14 接口无错误）
- [x] 2026-07-27：写 `dds_bandwidth.py`（设计期估算工具）。~~算出默认话题集占满 6C 串口 100.3%~~
      —— **该结论同日被实测推翻，见 §5 与 `docs/SERIAL_BUDGET.md` §7.1**。工具本身保留，
      职责收缩为「裁剪方案的 what-if 试算」，不再作为带宽数值的来源
- [x] 2026-07-27：三份实操文档（`WIRING_6C.md` / `SERIAL_BUDGET.md` / `SAFETY_CHECKLIST.md`）
- [x] 2026-07-27：WSL2 环境引导脚本 `bootstrap_wsl2.sh`（幂等，含 AMD 渲染兜底）
- [x] 2026-07-27：修复 `.kiro/skills/.../scripts/*.sh` 的 CRLF 行尾（4 个文件，WSL 下会报 bad interpreter），并加 `.gitattributes` 防复发
- [x] 2026-07-27：写 `docs/FLASH_AND_CALIBRATE_6C.md` —— 6C 刷固件与校准的逐步操作指导（10 步 + 11 条故障排查 + 17 项检查表），依据官方文档撰写
- [x] 2026-07-27：**核实 PX4 当前 stable 实为 v1.17.0**（`releases/latest` 与 `stable` 分支双重确认），更正此前「v1.18.0 是 stable」的错误判断。有利后果：QGC 默认选项刷的就是我们锁定的版本，无需手动下固件
- [x] 2026-07-27：**装好 QGroundControl v5.0.8** 并验证启动（`C:\Program Files\QGroundControl\bin\QGroundControl.exe`，597 MB，AMD 显卡下无需 GPU 兼容模式）
- [x] 2026-07-27：**装好 WSL2 + Ubuntu 22.04 全套 SITL 环境，且未重启 Windows**
      （详见 `sitl/WINDOWS_SETUP.md`。WSL 2.7.11 / 内核 6.18.33.2 / WSLg 1.0.73.2）
- [x] 2026-07-27：**`colcon build` 成功，`skylark_flight_msgs` 14 个接口全部被 ROS 2 注册**
      —— 这是接口契约的第一次真实编译验证（此前只有 Windows 上的静态语法检查）
- [x] 2026-07-27：修 bootstrap 三处真实缺陷：所有 clone 加 6 次重试 + `http.version HTTP/1.1`；
      env 文件同时挂 `~/.profile`（`.bashrc` 对非交互 shell 会提前 return）；
      加「运行期间勿改本脚本」警告（bash 边读边执行，实测踩过）

---

## 4. 待办（按优先级）

- [x] [已完成 2026-07-27] 装 QGroundControl v5.0.8（Kiro 代装 + 启动验证，AMD 显卡直接可用）
- [ ] [紧急·用户操作] 6C 首次上电：刷 v1.17.0 → 全套校准 → 导出 `pixhawk6c_bench_v1.params` → 登记到 `params/CHANGELOG.md`
      **指导文档已就绪**：`flight/docs/FLASH_AND_CALIBRATE_6C.md`（第 1 步已可跳过）
- [ ] [紧急·用户操作] `wsl --install -d Ubuntu-22.04` + 配 `.wslconfig`
- [ ] [本周] 跑 `bootstrap_wsl2.sh`，确认 `colcon build` 通过、`ros2 interface show skylark_flight_msgs/action/InspectSweep` 有输出
- [x] [已完成 2026-07-27] **SITL 冒烟测试** `flight/sitl/smoke_test.sh`：13 项检查，PX4↔DDS↔ROS 2 全链路通，
      RESULT=PASS。含纯函数单测 `flight/sitl/smoke_test_units.sh`（不启仿真、秒级反馈，全部通过）
- [x] [已完成 2026-07-27] **带宽实测校准**：不是"用 release/1.17 重跑估算"，而是直接实测取代估算。
      新增 `flight/tools/measure_dds_topics.py`，并用飞控自报的 `Payload tx` 交叉验证。
      结论从「占满 100.3%」修正为「占裸容量 52%，装得下」，`SERIAL_BUDGET.md` 已重写
- [ ] [本周] 跑通 PX4 官方 `offboard_control` 示例（SITL + Gazebo）
- [ ] [待办] 把 `SERIAL_BUDGET.md` 的修正同步到主 `STATE.md` §9.1 与 §16
      —— 那里仍写着已撤回的 60,060 B/s / 100.3%。`STATE.md` 是共享文件，改前先与用户确认
- [ ] [S2] 在真串口上实测 XRCE 帧开销（现在是 16 B/条的估算）。
      也可先用 socat 造 pty 对、把 client 与 agent 都切到 serial 传输，在 SITL 里先量一版
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
| **PX4 默认 DDS 话题集下行带宽（实测）** | **飞控自报 40,852 B/s ／订阅端实测 43,440 B/s；计入 16 B/条帧开销约 47,893 B/s = 921600 8N1 裸容量(92,160 B/s)的 52.0%** | 2026-07-27 | `measure_dds_topics.py`（SITL 悬停 25s）+ pxh `uxrce_dds_client status` 双向交叉验证 |
| ~~默认话题集占满串口 100.3%~~ | ~~60,060 B/s~~ **已撤回**：三个已确认错误（源用了 PX4 main 而非锁定的 v1.17.0；无 `rate_limit` 的两个大户按 10 Hz 猜、实测 100 Hz；分母重复扣一次协议开销）。详见 `docs/SERIAL_BUDGET.md` §7.1 | 2026-07-27 | 同上 |
| 带宽第一大户（实测） | `/fmu/out/vehicle_odometry` 120 B × 99.99 Hz = 11,998 B/s，占实测总量 **27.6%**；v1.17.0 里该话题**无 `rate_limit`** | 2026-07-27 | 同上 |
| 两份 `dds_topics.yaml` 的差异 | PX4 main(`8e7b370`) vs v1.17.0：**9 处不同**，话题数 69 vs 65 | 2026-07-27 | `flight/tools/diff_dds_topics_yaml.sh` |
| **XRCE 帧开销按条数摊，不按字节摊** | `dds_topics.h.em` 发送循环每条消息单独 `uxr_flash_output_streams`，源码留有 `// TODO: fill up the MTU and then flush` | 2026-07-27 | 源码 `src/modules/uxrce_dds_client/dds_topics.h.em:143` |
| **`ros2 topic hz` / `bw` 不能用于带宽校准** | 量的是订阅端到达率。同一健康系统两轮读数 50.004 / 21.427 Hz（RTF 均为 1.0）；订阅端因 TRANSIENT_LOCAL 历史回放落后 4~18 s。正确方法见 `SERIAL_BUDGET.md` §6 | 2026-07-27 | `flight/sitl/smoke_test.sh`、`flight/tools/measure_dds_topics.py`；排查过程的一次性诊断脚本留在工作区 `99_notes/`（未入库） |
| PX4 v1.17 话题名带版本后缀 | `dds_topics.yaml` 里无 `_v` 后缀，运行时按各消息的 `MESSAGE_VERSION` 拼：`VehicleLocalPosition`(=1)→`vehicle_local_position_v1`，`VehicleAttitude`(=0)→无后缀 | 2026-07-27 | `msg/versioned/*.msg` + 实测话题表 |
| SITL 下可脚本化 pxh 控制台 | 用 FIFO 顶住 stdin（`exec 3>fifo`）即可发 `commander arm` / `uxrce_dds_client status` / `uorb top`。headless 下解锁需先 `param set NAV_DLL_ACT 0`，否则报 `Preflight Fail: No connection to the GCS` | 2026-07-27 | `flight/sitl/measure_inflight.sh` |
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
- [2026-07-27] **决策（用户拍板）**：**不做商业化**。AGPL-3.0 永久确定，不替换 Ultralytics。
  对本模块的影响：`flight/` 可自由集成 GPL 组件（ego-planner 避障、FAST_LIO/VINS-Fusion 定位），
  不必再为「保留商业路径」而回避 —— 这为后续 GNSS 拒止环境巡检留了路
- [2026-07-27] **纠正自己此前的错误判断**：原先在 `THIRD_PARTY_LICENSES.md` 写「GPL-2.0（FAST_LIO）与 AGPL-3.0 不兼容」，并据此把隔离策略建立在法律冲突上。
  逐个读 LICENSE 正文核实后该判断**不成立** —— 遗漏了 "any later version" 条款。
  实测：FAST_LIO = GPL-2.0-**or-later**（可升级到 GPL-3.0）、VINS-Fusion / ego-planner-swarm = GPL-3.0-or-later、kiss-icp / PV-Hawk = MIT。**五个候选组件全部与 AGPL-3.0 兼容**。
  隔离策略保留但改名为「重型依赖隔离策略」，理由改写为构建体量与可复现性。
  教训：判断许可证兼容性必须读 LICENSE 正文里的版本条款，不能只看 GitHub API 返回的 SPDX 标识（它不区分 only 与 or-later）
- [2026-07-27] **决策**：仿真器 AirSim → Gazebo Harmonic。除 AirSim 已归档外，追加决定性理由是本机为 AMD GPU，Isaac Sim/Pegasus 跑不了，AAS 的 CUDA Docker 栈也跑不了
- [2026-07-27] **决策**：`flight/` 归 Window-E 而非 Window-C。知识域不重叠，混窗口会污染上下文。原属 Window-D 的 `simulation/` 并入本模块
- [2026-07-27] **决策**：版本锁定 v1.17.0 对齐 AAS，而非更保守的 v1.16.2。理由是代码参考零适配摩擦 > 两轮补丁
- [2026-07-27] **风险（已按实测下调，但没消失）**：串口带宽仍是本模块最大的架构约束。
  ~~默认配置已占满 100.3%~~ → 实测占裸容量 **52%**，默认配置装得下（见 §5）。
  风险的实质变了：不再是「一上手就丢包」，而是「余量只有 40 kB/s，加任何高频话题都会吃掉它」。
  若后续要做 GNSS 拒止环境的 VIO 巡检，`vehicle_odometry`（单条 12.0 kB/s）必须保留，
  再叠加 VIO 相关话题就会重新变紧 → 届时只能换 6X（有以太网 + PAB）或坚持「机载处理完只回传结论」的现有架构
- [2026-07-27] **风险**：ROS 2 Humble 官方配对 Gazebo Fortress，本项目用 Harmonic。基础闭环不需要 `ros_gz`（PX4 直连 gz transport，ROS 2 经 uXRCE-DDS 连 PX4），仅相机取流需要桥。届时按 AAS 的 GStreamer 方案或验证 `ros-humble-ros-gzharmonic`
- [2026-07-27] **风险（最高）**：挤占论文时间。Q1 是论文季且在关键路径上。缓解措施是 `HARDWARE_FLIGHT_LAYER.md` §8 的「低强度并行」硬约束（每周 3-5 小时，优先安排在 v2 训练等待时段）。**每周日 review 时若发现论文进度落后于原计划，立刻暂停本模块**
- [2026-07-27] **风险**：AMD GPU 上 Gazebo 渲染性能未知。`bootstrap_wsl2.sh` 已内置 `MESA_D3D12_DEFAULT_ADAPTER_NAME` 与 `LIBGL_ALWAYS_SOFTWARE` 兜底；最差退路是 `HEADLESS=1` 只用传感器数据不出图
- [2026-07-27] **事故记录**：Kiro 在重构工作副本目录时，`Move` 失败后紧随的 `Remove-Item -Recurse` 无条件执行，误删了本仓库的本地 clone。因是零本地修改的干净 clone，重新 clone 即完全恢复，无数据损失。教训已记录：不把清理动作链在可能失败的操作之后
- [2026-07-27] **行尾问题（已加固，但性质与初判不同）**：在本机工作区发现 `.kiro/skills/skylark-coordination/scripts/` 下 4 个 `.sh` 为 CRLF 行尾。
  用 `git ls-files --eol` 核实后确认：**仓库内(index)一直是 LF**，CRLF 是本机 `core.autocrlf=true` 在 checkout 时生成的，仓库内容本身没有缺陷。
  但这仍是**实际风险**：从 WSL 访问 Windows 工作区（`bash /mnt/c/.../status.sh`）会拿到 CRLF 版本并报 `bad interpreter: /usr/bin/env bash^M`。Window-E 正好要这么用。
  处置：新增 `.gitattributes` 声明 `*.sh text eol=lf`，强制任何平台 checkout 都得到 LF。已用 `git check-attr` 与 `git ls-files --eol` 验证生效（`i/lf w/lf attr/text eol=lf`）。
  初判「已存在的 bug」不准确，此处更正留档
- [2026-07-27] **决策（已由用户拍板）**：范围取舍执行 —— 第三个检测场景（道路/屋顶）换成「真机飞行闭环 + 视频→缺陷台账管线」。场景数 3→2（光伏 + 输电）。
  依据 `PROJECT_NORTH_STAR.md`「广 vs 深优先深，但保证至少一个广度示例」原则。已同步修改 8 处文档，清单见 `HARDWARE_FLIGHT_LAYER.md` §12。
  **对本模块的影响**：S3 真机阶段从「加分项」升级为**验收硬指标**，Q3-M9 的归属从 Window-D 移交本模块。
  **必须记住**：换的是深度不是工期 —— 腾出的 3-4 周被真机 + 台账管线（8-10 周）吸收，Q3 压力未减
