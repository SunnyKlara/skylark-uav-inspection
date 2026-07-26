# `flight/` — 飞控层

Skylark 的第 5 个模块层。把 PX4 飞控接入平台，向 `edge/` 提供「飞行动作」抽象。

**硬件**：Holybro Pixhawk 6C
**归属**：Window-E（飞控 + 仿真）
**许可证**：AGPL-3.0（随仓库）

---

## 从哪读起

按这个顺序，别跳：

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | [`../HARDWARE_FLIGHT_LAYER.md`](../HARDWARE_FLIGHT_LAYER.md) | 架构增量提案。为什么要有这一层、三个边界契约、三阶段路线 |
| 2 | [`VERSIONS.md`](VERSIONS.md) | 版本锁定。**所有版本号的唯一来源** |
| 3 | [`MODULE_STATE.md`](MODULE_STATE.md) | 当前进度、已知事实、待办、风险 |
| 4 | [`docs/FLASH_AND_CALIBRATE_6C.md`](docs/FLASH_AND_CALIBRATE_6C.md) | **硬件从这里开始。**刷固件 + 校准 + 导出基线，逐步照做，只需飞控 + USB 线 |
| 5 | [`sitl/WINDOWS_SETUP.md`](sitl/WINDOWS_SETUP.md) | **软件环境从这里开始。**需要管理员权限与重启的部分，Kiro 做不了 |
| 6 | [`docs/WIRING_6C.md`](docs/WIRING_6C.md) | 接线。**接线前必读，开头三条红线会烧板子** |
| 7 | [`docs/SERIAL_BUDGET.md`](docs/SERIAL_BUDGET.md) | 串口带宽。本层最大的架构约束 |
| 8 | [`docs/SAFETY_CHECKLIST.md`](docs/SAFETY_CHECKLIST.md) | 飞行前检查单。**打印出来带到场地** |
| 9 | [`ros2_ws/src/skylark_flight_msgs/`](ros2_ws/src/skylark_flight_msgs/) | 接口契约。先看 `action/*.action` |

---

## 目录结构

```
flight/
├── README.md                本文件
├── VERSIONS.md              版本锁定（单一来源）
├── MODULE_STATE.md          模块状态（按项目 schema）
│
├── ros2_ws/src/
│   └── skylark_flight_msgs/    ✅ 接口契约（已完成，14 个接口）
│       ├── msg/                   状态与感知数据
│       ├── action/                飞行动作
│       ├── srv/                   即时指令
│       └── validate_interfaces.py  静态校验器
│   ├── skylark_autopilot_iface/ ⏳ action 的 PX4 实现（待做）
│   ├── skylark_inspection_mode/ ⏳ 巡检任务状态机（待做）
│   └── skylark_bridge/          ⏳ 地理配准与数据粘合（待做）
│
├── params/
│   ├── CHANGELOG.md         ✅ 参数变更规范（每次改参数加一行）
│   └── *.params             ⏳ QGC 导出的基线快照（待首次导出）
│
├── sitl/
│   ├── bootstrap_wsl2.sh    ✅ 环境引导（幂等）
│   ├── run_sitl.sh          ✅ 一键启动 SITL
│   └── worlds/              ⏳ 光伏电站 Gazebo 世界（待做）
│
├── tools/
│   └── dds_bandwidth.py     ✅ 串口带宽估算器
│
└── docs/
    ├── FLASH_AND_CALIBRATE_6C.md  ✅ 刷固件与校准，逐步操作指导
    ├── WIRING_6C.md         ✅ 分体式接线
    ├── SERIAL_BUDGET.md     ✅ 带宽预算
    └── SAFETY_CHECKLIST.md  ✅ 飞行安全检查单
```

---

## 核心设计原则

### 1. 接口契约先行

先定 `.action`，再写实现。同一套契约将来可以配 PX4 和 ArduPilot 两个实现 —— 换飞控只换一个节点。

Skylark 定位是「**通用**无人机航拍 AI 巡检平台」。飞控层若直接耦合 PX4 的 uORB 话题，「通用」就是空话。

### 2. 视觉节点永远不发 setpoint

```
edge/ 的推理节点  ──发布──►  /skylark/detections      「我看到了什么」
                  ──调用──►  /skylark/revisit (action) 「请降高复拍」
                                      │
                            flight/ 独占飞行决策与安全约束
                                      │
                                      ▼
                              PX4 setpoint
```

`edge/` 物理上无法绕过 `flight/` 直接控制飞机。所有速度、高度、地理围栏约束收敛在一处。

答辩必问「你的 AI 判断错了会怎样」—— 这个边界让答案可指认。

### 3. 任务是配置，不是代码

巡检航线写成声明式 YAML，不是硬编在 C++ 里。这样前端才能让用户配置任务。

```yaml
type: Sequence
name: PV_Array_Inspection
children:
  - action: takeoff
    params: { altitude: 25.0 }
  - action: inspect_sweep
    params: { rows: 8, row_spacing_m: 6.0, speed_mps: 3.0 }
  - action: land
on_detection:
  - action: revisit
    params: { descend_to_m: 8.0, capture_burst: 5 }
```

格式参考 `aerial-autonomy-stack` 的 `missions/*.yaml`。

---

## 快速上手

### 第一步：环境（用户操作，需管理员 + 重启）

完整步骤见 **[`sitl/WINDOWS_SETUP.md`](sitl/WINDOWS_SETUP.md)**。核心是一条命令：

```powershell
# 以管理员身份运行 PowerShell
wsl --install --no-launch -d Ubuntu-22.04
# 然后重启电脑
```

`.wslconfig` 已按本机硬件（31.3 GB 内存 / 16 核）生成于 `C:\Users\Klara\.wslconfig`，
取值 memory=20GB / processors=12 / swap=8GB，不用手动建。

### 第二步：装依赖

```bash
# WSL2 Ubuntu 22.04 里
cd /mnt/c/Users/Klara/Desktop/PX4/skylark/flight/sitl
bash bootstrap_wsl2.sh --check      # 先只检查
bash bootstrap_wsl2.sh              # 确认无误后全量安装（首次约 40-60 分钟）
```

### 第三步：跑 SITL

```bash
bash run_sitl.sh                    # 自动开三个 tmux 面板
# 或手动开三个终端，见 bootstrap_wsl2.sh 结尾提示
```

### 第四步：验证接口契约已注册

```bash
source ~/.skylark_env.sh
ros2 interface list | grep skylark
ros2 interface show skylark_flight_msgs/action/InspectSweep
```

---

## 常用命令

```bash
# 校验接口定义（不需要 ROS 2，Windows 上也能跑）
python ros2_ws/src/skylark_flight_msgs/validate_interfaces.py

# 估算串口带宽占用
python tools/dds_bandwidth.py \
  --dds-topics ~/PX4-Autopilot/src/modules/uxrce_dds_client/dds_topics.yaml \
  --msg-dir ~/skylark_ws/src/px4_msgs/msg --publications-only

# 编译 6C 固件
cd ~/PX4-Autopilot && make px4_fmu-v6c_default

# 实测话题带宽与频率（联调时用）
ros2 topic bw /fmu/out/vehicle_local_position
ros2 topic hz /fmu/out/vehicle_local_position

# 飞控侧诊断（QGC → Analyze → MAVLink Console）
uxrce_dds_client status
uorb top
listener vehicle_local_position
```

---

## 三条不要违反的规则

1. **桨叶是最后装的。** 任何软件调试、参数修改、固件刷写，桨必须在机外
2. **版本以 `VERSIONS.md` 为准。** 毕设期间不升级 PX4，`px4_msgs` 分支必须与固件严格对应
3. **改了任何参数或固件，回到 S2 地面联调重新验证。** 不允许「改一个参数直接飞」

---

## 参考资料位置

参考仓库都在工作区上层，不在本仓库内：

| 内容 | 位置 |
|---|---|
| PX4 固件源码 | `../../01_px4_core/PX4-Autopilot/` |
| PX4 官方文档（可离线 grep） | `../../01_px4_core/PX4-user_guide/` |
| 架构主参考 aerial-autonomy-stack | `../../03_fullstack_ref/aerial-autonomy-stack/` |
| 光伏巡检管线参考 PV-Hawk | `../../07_domain_pv/PV-Hawk/` |
| 全部 32 个参考仓库索引 | `../../README.md` + `../../INVENTORY.md` |
