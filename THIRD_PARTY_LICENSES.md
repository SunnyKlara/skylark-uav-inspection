# 第三方许可证与合规策略

> 决策日期：2026-07-27
> 决策人：用户确认，Kiro 执行
> 关联文件：`LICENSE`（AGPL-3.0）

---

## 1. 本项目为什么是 AGPL-3.0

**根因：`ultralytics` 是 AGPL-3.0。**

Skylark 的检测模型训练与推理建立在 Ultralytics YOLO 之上（见 `code/train/`、`code/models/`）。AGPL-3.0 是**网络传染性** copyleft：

> 若用户通过计算机网络与程序交互，你必须向这些用户提供对应源码。

Skylark 的既定目标（`PROJECT_NORTH_STAR.md`）包含「一个真实可访问的 Web 平台（域名 + HTTPS + 注册登录）」。这正好落入 AGPL 第 13 条的网络交互条款。

因此：

| 事项 | 结论 |
|---|---|
| 整仓许可证 | **AGPL-3.0** |
| `platform/backend/` 能否 MIT | ❌ 不能 |
| 学术使用（论文、毕设、答辩） | ✅ 完全不受影响 |
| 开源到 GitHub | ✅ 本来就是既定目标，天然合规 |
| 闭源商业化 | ❌ 需购买 Ultralytics 商业许可，或替换 Ultralytics |

**在此之前本仓库没有 LICENSE 文件**，法律上等同「保留所有权利」，与「完整开源」的目标矛盾。本次补齐。

---

## 2. 依赖许可证矩阵

许可证信息通过 GitHub API 核实于 2026-07-27。

### 2.1 宽松许可（可自由使用，保留版权声明即可）

| 依赖 | 许可证 | 用途 |
|---|---|---|
| `PX4/PX4-Autopilot` | BSD-3-Clause | 飞控固件 |
| `PX4/px4_msgs` | BSD-3-Clause | uORB 的 ROS 2 消息定义 |
| `PX4/px4_ros_com` | BSD-3-Clause | Offboard 示例 |
| `Auterion/px4-ros2-interface-lib` | BSD-3-Clause | 自定义飞行模式 |
| `mavlink/MAVSDK` | BSD-3-Clause | MAVLink SDK（备选路径） |
| `eProsima/Micro-XRCE-DDS-Agent` | Apache-2.0 | 机载侧 DDS agent |
| `PX4/flight_review` | BSD-3-Clause | 日志分析 |
| `mavlink/qgroundcontrol` | Apache-2.0 | 地面站 |
| `JacopoPan/aerial-autonomy-stack` | MIT | 架构参考 |
| `PRBonn/kiss-icp` | MIT | LiDAR 里程计 |
| `LukasBommes/PV-Hawk` | MIT | 光伏巡检管线参考 |
| Gazebo / gz-harmonic | Apache-2.0 | 仿真 |
| ROS 2 Humble 核心 | Apache-2.0 | 中间件 |

### 2.2 网络传染 copyleft（已接受）

| 依赖 | 许可证 | 影响 |
|---|---|---|
| `ultralytics/ultralytics` | **AGPL-3.0** | 决定了本项目整仓许可证 |

### 2.3 强 copyleft（**默认不集成**，见第 3 节隔离策略）

| 依赖 | 许可证 | 若集成的后果 |
|---|---|---|
| `hku-mars/FAST_LIO` | GPL-2.0 | 链接即传染 |
| `HKUST-Aerial-Robotics/VINS-Fusion` | GPL-3.0 | 链接即传染 |
| `ZJU-FAST-Lab/ego-planner-swarm` | GPL-3.0 | 链接即传染 |
| `ZJU-FAST-Lab/ego-planner` | GPL-3.0 | 同上 |

> 说明：本项目已是 AGPL-3.0，与 GPL-3.0 兼容方向上没有法律冲突（AGPL-3.0 与 GPL-3.0 可互操作）。
> 但 **GPL-2.0（如 FAST_LIO）与 GPL-3.0/AGPL-3.0 不兼容**，除非上游声明 "or later"。
> 这是隔离策略存在的真实理由，不只是洁癖。

---

## 3. Copyleft 隔离策略

**做法照抄 `aerial-autonomy-stack`**：它默认只集成 MIT 的 KISS-ICP，把 FAST-LIO / OpenVINS 等 GPL 组件放在 `BUILD_ADVANCED_ODOM=true` 编译开关之后。这是架构决策，不是法务动作。

Skylark 的执行规则：

1. **默认构建（default build）只包含宽松许可 + AGPL 组件。** 任何 `git clone` 后的默认 `colcon build` / `docker compose up` 不得引入 GPL 代码
2. **GPL 组件放在显式编译开关后**，命名约定 `WITH_GPL_<组件名>=ON`，默认 `OFF`
3. **开关状态必须记录在 `flight/MODULE_STATE.md` 与 `edge/MODULE_STATE.md`**
4. **不静态链接 GPL-2.0 组件**（与本仓 AGPL-3.0 不兼容）。若确需 FAST-LIO，走独立进程 + ROS 2 话题通信，并在文档中显式说明进程边界
5. **论文与毕设不受本节约束** —— 学术研究用途下这些组件都可自由使用，只是不进本仓库的默认发行版

---

## 4. 待处理事项

| 事项 | 时机 | 说明 |
|---|---|---|
| 决定是否保留商业化可能 | Q2 之前 | 若要，需在 `edge/` 与 `platform/` 中把 Ultralytics 换成 Apache-2.0/BSD 系的检测框架，或购买商业许可 |
| 为 GPL 组件建立编译开关 | 引入第一个 GPL 组件时 | 目前尚无 GPL 组件进入构建 |
| 补 `NOTICE` 文件 | 首次对外发布前 | 汇总所有依赖的版权声明 |

---

## 5. 源码可用性声明（AGPL 第 13 条要求）

对外部署 Web 平台时，必须在页面可见位置提供本仓库地址：

```
Skylark UAV Inspection Platform
Copyright (C) 2026 SunnyKlara
Licensed under AGPL-3.0. Source: https://github.com/SunnyKlara/skylark-uav-inspection
```

建议实现位置：`platform/frontend/` 页脚 + 后端 `GET /api/about` 返回该信息。
