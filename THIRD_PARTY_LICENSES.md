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
| 闭源商业化 | **✅ 已决定不做**（2026-07-27 用户拍板），此项不再是约束 |

### 商业化路径 —— 已决定不走（2026-07-27）

用户明确决定**不做商业化**。这条决定把 AGPL-3.0 从「一个需要权衡的选择」变成「零成本的最优解」。

**解锁了什么**：

| 事项 | 变更前 | 变更后 |
|---|---|---|
| 是否要评估替换 Ultralytics | Q2 前必须决定，替换预计数周 | **取消该任务**，直接用 Ultralytics 最新版 |
| GPL 组件能否进默认构建 | 需谨慎，怕堵死商业路径 | **可以**（详见 §2.3 与 §3 的实测核实结果） |
| 许可证决策的后续开销 | 需持续跟踪 | **归零**，本文件之后基本不用再改 |

**对「事业起点」定位的影响**：`PROJECT_NORTH_STAR.md` 写着「不是毕设。是一个事业起点」。
这条依然成立，只是路径明确为**开源作品集 / 技术能力 / 行业影响力**，而非闭源产品变现。
这与北极星「学到的东西 > 做出来的产品 > 论文叙事」的优先级完全一致 —— 开源反而更利于前两项。

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

### 2.3 强 copyleft 组件 —— 经实测核实，**全部与 AGPL-3.0 兼容**

> ⚠ **2026-07-27 更正**：本节原先写「GPL-2.0（如 FAST_LIO）与 AGPL-3.0 不兼容」，
> 并据此把隔离策略的理由建立在法律冲突上。**逐个读 LICENSE 正文核实后，该判断不成立。**
> 关键在 "any later version"（or-later）条款 —— 原判断遗漏了这一点。

核实方法：`99_notes/_check_licenses.py` 读取各仓库 LICENSE 正文，检查版本声明与 or-later 条款。

| 依赖 | 实测许可证 | 与 AGPL-3.0 兼容 | 依据 |
|---|---|---|---|
| `hku-mars/FAST_LIO` | **GPL-2.0-or-later** | ✅ | LICENSE 含 "any later version"，可升级到 GPL-3.0 |
| `HKUST-Aerial-Robotics/VINS-Fusion` | **GPL-3.0-or-later** | ✅ | GPL-3.0 §13 明文允许与 AGPL-3.0 组合 |
| `ZJU-FAST-Lab/ego-planner-swarm` | **GPL-3.0-or-later** | ✅ | 同上 |
| `PRBonn/kiss-icp` | MIT | ✅ | 宽松许可 |
| `LukasBommes/PV-Hawk` | MIT | ✅ | 宽松许可 |

**结论**：**没有任何一个候选组件因许可证而被排除。** 组合它们进 AGPL-3.0 项目是合法的
（整体作品受 AGPL-3.0 约束，本项目本来就要开源，无额外成本）。

**两个实操注意点**（合法 ≠ 无需处理）：

1. **必须保留原始版权声明与许可证文本**。集成任何 GPL/MIT 组件时，其 LICENSE 文件与
   源码文件头的版权声明不得删除
2. **必须在 `NOTICE` 中列明**（见 §4）。首次对外发布前汇总

**一个踩坑记录**：VINS-Fusion 的许可证文件名是 **`LICENCE`**（英式拼写），
只搜 `LICENSE` 会漏掉，进而误判为「无许可证声明」。`_check_licenses.py` 已修正为两种拼写都查。

---

## 3. 重型依赖隔离策略（原「Copyleft 隔离策略」，理由已变更）

> ⚠ **2026-07-27 降级**：本节原名「Copyleft 隔离策略」，理由有两条：
> ①保留闭源商业化可能 ②GPL-2.0 与 AGPL-3.0 不兼容。
>
> **这两条理由现在都不成立了** —— ①用户已决定不做商业化（§1）；②经实测核实全部兼容（§2.3）。
>
> 但策略本身**仍然保留**，因为还有一条独立且真实的理由：**构建体量与可复现性**。
> 诚实起见，这里改名并重写理由，而不是删掉假装从来没写过错误的依据。

### 保留的真实理由

`PROJECT_NORTH_STAR.md` 的验收标准之一是「代码 review-ready（任何人 clone 都能在 30 分钟内跑起来）」。

FAST-LIO / VINS-Fusion / ego-planner 都是重型 C++ 依赖，各自带 PCL、Ceres、Eigen、
OpenCV 等一长串传递依赖，编译时间以十分钟计。全部塞进默认构建会直接破坏那条 30 分钟目标。

`aerial-autonomy-stack` 的做法值得抄：默认只集成 MIT 的 KISS-ICP（轻），把 FAST-LIO /
OpenVINS 等放在 `BUILD_ADVANCED_ODOM=true` 编译开关之后。这是**工程决策**，与许可证无关。

### 执行规则（已按新理由改写）

1. **默认构建保持精简。** `git clone` 后的默认 `colcon build` 应在普通笔记本上于合理时间内完成，
   不引入重型 SLAM/规划依赖
2. **重型组件放显式编译开关后**，命名约定 `WITH_<组件名>=ON`，默认 `OFF`
   （原约定 `WITH_GPL_<组件名>` 已废弃 —— 用许可证命名是基于已被推翻的前提）
3. **开关状态记录在对应模块的 `MODULE_STATE.md`**，让其他窗口知道当前构建包含什么
4. **必须保留所有第三方组件的版权声明与许可证文本。** 这条与许可证种类无关，MIT 也一样要求
5. **进程隔离按工程需要决定，不再按许可证决定。** 若 FAST-LIO 用独立进程 + ROS 2 话题通信，
   理由应是「崩溃隔离 / 独立重启 / 便于替换」，而非许可证兼容性
6. **论文与毕设不受本节约束** —— 学术用途下这些组件都可自由使用

---

## 4. 待处理事项

| 事项 | 状态 | 说明 |
|---|---|---|
| ~~决定是否保留商业化可能~~ | ✅ **已关闭（2026-07-27）** | 用户决定不做商业化。不替换 Ultralytics，AGPL-3.0 永久确定 |
| ~~核实 GPL 组件与 AGPL-3.0 的兼容性~~ | ✅ **已关闭（2026-07-27）** | 逐个读 LICENSE 正文核实，全部兼容。见 §2.3 |
| 为重型组件建立编译开关 | ⏳ 引入第一个重型依赖时 | 目前 `flight/` 只有接口契约包，无重型依赖 |
| 补 `NOTICE` 文件 | ⏳ 首次对外部署前 | 汇总所有依赖的版权声明。可用 `_check_licenses.py` 扫描生成初稿 |
| 页面显示源码地址 | ⏳ Web 平台上线前 | AGPL §13 硬性要求，见 §5 |

**本文件之后基本不需要再改。** 许可证方向已经锁定，唯一的持续义务是新增依赖时在 §2 登记。

---

## 5. 源码可用性声明（AGPL 第 13 条要求）

对外部署 Web 平台时，必须在页面可见位置提供本仓库地址：

```
Skylark UAV Inspection Platform
Copyright (C) 2026 SunnyKlara
Licensed under AGPL-3.0. Source: https://github.com/SunnyKlara/skylark-uav-inspection
```

建议实现位置：`platform/frontend/` 页脚 + 后端 `GET /api/about` 返回该信息。
