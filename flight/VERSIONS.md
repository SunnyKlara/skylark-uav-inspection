# 版本锁定 — 单一来源

> **本文件是 flight/ 层所有版本号的唯一权威来源。**
> 任何脚本、文档、Dockerfile 需要版本号时，引用本文件，不要各自硬编。
> 改版本 = 只改这里 + 更新 §4 变更记录。
>
> 决策依据见 `HARDWARE_FLIGHT_LAYER.md` §2.4。

---

## 1. 锁定版本

| 组件 | 版本 | 来源 |
|---|---|---|
| PX4-Autopilot | **v1.17.0** | `https://github.com/PX4/PX4-Autopilot` tag `v1.17.0` |
| px4_msgs | **release/1.17** | `https://github.com/PX4/px4_msgs` branch `release/1.17` |
| Micro-XRCE-DDS-Agent | **v2.4.3** | `https://github.com/eProsima/Micro-XRCE-DDS-Agent` tag `v2.4.3` |
| ROS 2 | **Humble Hawksbill (LTS)** | apt `ros-humble-desktop` |
| Ubuntu (WSL2) | **22.04 LTS (Jammy)** | `wsl --install -d Ubuntu-22.04` |
| Gazebo | **Harmonic (LTS)** | apt `gz-harmonic`（由 PX4 `Tools/setup/ubuntu.sh` 自动安装） |
| 飞控编译目标 | **`px4_fmu-v6c_default`** | Holybro Pixhawk 6C |

### 一致性铁律

**`px4_msgs` 的分支必须与固件版本严格对应。** 不一致时的症状是：话题能看到但字段错位、反序列化失败、或看似正常但数值离谱。这是 PX4 + ROS 2 新手最常踩、且最难自己诊断的坑。

从 PX4 v1.16 起引入了消息版本管理，允许 ROS 2 侧用不同版本的消息定义，但**需要额外运行 Message Translation Node**。本项目不走这条路 —— 严格对齐版本更简单可靠。

---

## 2. 为什么选 v1.17.0

| 理由 | 说明 |
|---|---|
| **与主要代码参考对齐** | `aerial-autonomy-stack`（本项目的架构参考）锁定 PX4 v1.17.0 + px4_msgs release/1.17。对齐后可以直接照抄它的代码，零适配摩擦 |
| 正式 stable 版本 | 经 Dronecode 测试团队在硬件矩阵上验证过 |
| 支持 `mc_nn_control` | 神经控制模块与 `fmu-v6c/neural.px4board` 在 release/1.16 起就有，v1.17 包含（见 `HARDWARE_FLIGHT_LAYER.md` §13） |
| 6C 是维护中的板子 | PX4 官方标注 6C 由维护与测试团队支持 |

### 已评估但未选的备选

| 备选 | 优点 | 未选原因 |
|---|---|---|
| v1.16.2 | 有 2 轮补丁，更保守 | AAS 的代码引用需做 msg 版本适配，得不偿失 |
| v1.18.0 | — | **它还不是 stable**，只到 beta1（见下方更正） |
| main | 有最新特性 | 毕设期间追 main 是自找麻烦。明文禁止 |

> ⚠ **2026-07-27 更正**：本表原先写「v1.18.0 = 最新 stable」，**这是错的**。
> 该说法源自误读 PX4 文档 `releases/release_process.md` 里的流程示例表格（那是模板，不是实际发布状态）。
>
> 经 GitHub API 核实的实际状态：
>
> | 事实 | 核实方式 |
> |---|---|
> | `releases/latest` = **v1.17.0**（2026-05-13） | `gh api repos/PX4/PX4-Autopilot/releases/latest` |
> | `stable` 分支指向的 tag = **v1.17.0** | `gh api .../git/ref/heads/stable` + tag 比对 |
> | v1.18.0 最新只到 **v1.18.0-beta1**（2026-07-08，prerelease） | releases 列表 |
>
> **有利的后果**：v1.17.0 既是我们锁定的版本，又正好是当前 stable。
> 所以 QGroundControl 里默认的「PX4 Pro Stable Release」刷的就是它 ——
> 刷固件不需要手动下载文件，也不需要动 Advanced settings。见 `docs/FLASH_AND_CALIBRATE_6C.md`。

---

## 3. 毕设期间的版本冻结纪律

**PX4 约 6 个月发一个大版本。毕设周期内一定会有新版本发布。不要升级。**

允许升级的唯一情形：
1. 当前版本有影响飞行安全的已知缺陷，且新版本修复了它
2. 升级后必须回到 S2 地面联调重新验证全部检查项

升级时要同步改的东西（一处漏掉就会出诡异问题）：
- [ ] 本文件 §1 表格
- [ ] 本文件 §4 变更记录
- [ ] `flight/sitl/bootstrap_wsl2.sh` 里的版本变量
- [ ] 重新 `colcon build` 整个工作区（px4_msgs 变了，所有依赖它的包都要重编）
- [ ] 重刷飞控固件
- [ ] 重新导出 `.params` 基线（参数在版本间可能改名或改默认值）
- [ ] 检查 `dds_topics.yaml` 的自定义裁剪是否需要重做（见 `docs/SERIAL_BUDGET.md` §5）

---

## 4. 变更记录

| 日期 | 变更 | 原因 | 验证状态 |
|---|---|---|---|
| 2026-07-27 | 初次锁定：PX4 v1.17.0 / px4_msgs release/1.17 / ROS 2 Humble / Ubuntu 22.04 / Gazebo Harmonic | 项目启动，与 AAS 对齐 | ⏳ 未验证（WSL2 环境尚未搭建） |

---

## 5. 已知的版本相关注意事项

| 事项 | 说明 |
|---|---|
| **本地参考库的 px4_msgs 是 main 分支** | `PX4/02_ros2_bridge/px4_msgs` 是 `--depth 1` 的 main 快照，**不是** release/1.17。它只用于阅读参考。实际工作区要 clone `release/1.17`。`docs/SERIAL_BUDGET.md` 的带宽估算用的是 main，需在正确分支上重跑校准 |
| **本地参考库的 PX4-Autopilot 也是 main** | 同上。且是 `--depth 1`，没有 tag，`git describe` 会报错。要编译请另行 `git clone --recursive -b v1.17.0` |
| ROS 2 Humble 官方配对 Gazebo Fortress | 本项目用 Harmonic。基础闭环不需要 `ros_gz`（PX4 直连 Gazebo 走 gz transport，ROS 2 经 uXRCE-DDS 连 PX4），所以配对问题不影响。仅相机取流需要桥，届时按 AAS 的 GStreamer 方案处理 |
| Jetson 侧版本被 JetPack 锁死 | Orin 最高支持 JetPack 6 = L4T 36 = Ubuntu 22 = Python 3.10 → **强制 ROS 2 Humble**。这与本文件的选择一致，不是巧合 |
