# 项目状态快照（接管协议）

> 给新 Kiro 会话用的"上下文压缩包"。读完这一份就知道现在在哪、要干什么。
>
> **最后更新：2026-05-27 16:30 by Window-B**
> **重大变更：项目从"本科毕设论文"升级为"Skylark 通用无人机航拍 AI 巡检平台 + 论文双产物"。**
> **新增：多窗口协作协议（详见 `MULTI_WINDOW_PROTOCOL.md`）+ skill `.kiro/skills/skylark-coordination/`**

---

## 一句话总结

正在做 **Skylark 平台 + 论文** 双产物项目。当前 v1 daemon 跑着旧协议消融（仅作短预算对照），新架构已锁定，多窗口协作协议已落地，下一步启动 Window-B + v2 协议正式实验。

---

## 0. 必读 — 上层文档

按顺序读完才能开始干活：

1. `PROJECT_NORTH_STAR.md` — 北极星（为什么做、怎么决策）
2. `MASTER_ARCHITECTURE.md` — 主架构（怎么做、季度路线图）
3. `MULTI_WINDOW_PROTOCOL.md` — 多窗口协作协议（详细规则）
4. `STATE.md`（本文）— 当前在哪
5. 新窗口启动 → 读 `WINDOW_<X>_KICKOFF.md`

> 严禁不读上述文档就动手。

---

## 0.1 活跃窗口（Active Windows）

| 窗口 | 上线时间 | 机器 | 当前焦点 |
|---|---|---|---|
| **Window-A**（ML 主线）| 2026-05-26 23:35（v1 daemon 上线） | ML 训练机 | 监控 v1 daemon、准备 v2 启动、维护协议 |
| **Window-B**（论文 + 文档）| ⏳ 待启动 | ML 训练机 | — |
| **Window-C**（后端 + 边缘）| ⏳ Q2 起（约 9 月）| ML 训练机 + Jetson | — |
| **Window-D**（前端）| ⏳ Q3 起（约 12 月）| 任意 | — |
| **Window-E**（飞控 + 仿真）| **2026-07-27 上线** | **METAMECHBOOK01**（AMD） | S0 骨架已完成，等硬件上电与 WSL2 安装 |

### 机器分工（2026-07-27 新增事实）

本项目跨**两台物理机器**，通过 GitHub 同步。这是之前文档未记录的重要事实。

| 机器 | 硬件 | 角色 | 窗口 |
|---|---|---|---|
| ML 训练机 | RTX 5060 Ti 16 GB（Blackwell sm_120）、32 GB RAM、E 盘 conda | 训练 / 量化 / TensorRT / 论文实验 | A / B / C |
| `METAMECHBOOK01` | **AMD RX 7600M XT + 780M 核显**、C 盘 1907 GB、**无 CUDA** | PX4 固件 / SITL / QGC 刷参 / 真机联调 | **E** |

**三个推论**：

1. **GPU 抢卡问题不存在**。Window-E 与 v2 训练在物理隔离的两台机器上。此前「装 Gazebo 会抢卡拖慢训练」的担忧**作废**。这也是允许 Window-E 在 Q1 就低强度启动的前提
2. **飞控开发机没有 CUDA**。Isaac Sim / Pegasus / AAS 的 CUDA Docker 栈在这台机器上都跑不了 → 仿真只能用 Gazebo（见下方决策）
3. **`STATE.md` 冲突走正常 git merge**。两台机器各自 clone，比原「同一 workspace 多窗口」假设更干净 —— 有 git 做仲裁

判断自己在哪台机器：`Get-PSDrive`（有无 E 盘）或 `nvidia-smi`（有无 NVIDIA GPU）。

---

## 1. 项目身份

**项目名**：Skylark — 通用无人机航拍 AI 巡检平台
**双产物**：
- 工程：完整 Web 平台 + Jetson 边缘部署 + 仿真演示
- 论文：本科毕设（中文 35000+ 字）+ SCI 投稿（IEEE TII / Sensors 任一）

**时间预算**：1 年（2026-05 至 2027-05）
**硬件预算**：~8800 元（Jetson + 大疆 + VPS + 域名 + 杂）
**当前进度**：约 10-15%（地基稳，主体未建）

---

## 2. 五维完美验收（终态）

| 维度 | 当前 | 终态 |
|---|---|---|
| 论文（理论） | 30% | 中文优秀 + SCI 投出 + ≥1 处第一手发现 + 0 注水 |
| 产品（实践） | 0% | Web 平台真在线 + **≥2 场景（光伏 + 输电）** + **视频→缺陷台账管线** + GitHub 开源 |
| 软硬协同 | 5% | Jetson 真机 + INT8/TRT + 仿真 + 演示视频 |
| 工程质量 | 20% | pytest 60%+ + CI/CD + Docker + 文档 |
| 个人能力 | ML 已掌握 | + Web 全栈 + 边缘 AI + 产品思维 |

**用户已确认这就是验收标准。**

---

## 3. 当前后台进程（不要碰）

- Windows 计划任务 `GP_Pipeline_Daemon` 在跑（svchost 父进程，关 IDE 不影响）
- 当前阶段：消融 A1 yolo11n_cbam（v1 协议：80ep / linear LR / yolo11n.pt 预训练）
- ETA：今晚 22:00 前后跑完所有 ablation + dataset_stats + eval + viz
- **v1 数据 = 短预算 linear-LR 对照组**，论文里**只作为协议敏感性分析的对比**，不是主结果
- 红线：不要 `schtasks /end` 或 `/delete`（除非用户明确要求）

---

## 4. 硬件 / 软件环境（已搭好，别动）

- Windows 11 / 32 GB RAM / RTX 5060 Ti 16 GB（Blackwell sm_120）
- Conda 环境：`E:\conda_envs\yolo`（Python 3.11.15）
- PyTorch 2.7.1 + CUDA 12.8（cu128 — 5060 Ti 唯一可用组合）
- Ultralytics 8.4.54
- TeX Live 2024：`E:\Program Files\texlive\2024\bin\windows\`
- Windows 虚拟内存：E 盘 32 GB（避免 dataloader WinError 1455）
- 关键 ENV：`TORCH_HOME=E:\torch_cache`、`PIP_CACHE_DIR=E:\pip_cache`

---

## 5. 数据集（已落盘，别动）

```
E:\Users\Administrator\Desktop\gp\graduation_project\code\data\
└── processed\pvel_yolo\
    ├── images\{train,val,test}\
    ├── labels\{train,val,test}\
    └── data.yaml      # nc=12
```

**真实划分**：

| Split | 含缺陷 | 无缺陷负样本 | 标注框 |
|---|---|---|---|
| train | 3,600 | 9,082 | 6,254 |
| val   | 900   | 2,271 | 1,588 |
| test  | 19,150 | 0    | 34,116 |

**真实尺度分布（基于 6254 个训练 box 实测）**：

- 中位边长（imgsz=640）= 40.6 px
- 最小 14.5 px、p10 = 24 px、p90 = 570 px
- ≤ 8 px 占比 **0%**、≤ 16 px 占比 **0.2%**
- finger 类（37.7% 训练框，最多发）：中位 28.9 px、最小 14.5 px

**真实长尾比例（按划分尺度差异显著）**：

- 全集（41,958 框）：finger 25,596 / scratch 8 → **3,200×**
- train+val（7,842 框）：finger 2,958 / scratch 5 → **591×**
- test 单独（34,116 框）：finger 22,638 / scratch 3 → **7,546×**

> 注：之前论文里写的"7000+×"实为测试集层面的统计，文献中常被误用为训练分布。本文已显式区分这三个比例。

类别（PVEL_CLASSES）：crack, finger, black_core, thick_line, star_crack, corner, fragment, scratch, horizontal_dislocation, vertical_dislocation, printing_error, short_circuit

---

## 6. 已完成实验（保留作 v1 短预算对照）

3 个 baseline + ours 80ep + 部分 ablation 已训完（v1 协议：80ep / linear LR / 默认 ultralytics）：

| 配置 | mAP@0.5 | 备注 |
|---|---|---|
| YOLOv8n（50ep）| 0.7897 | baseline |
| YOLOv10n（50ep）| 0.7336 | baseline |
| YOLOv11n（50ep）| 0.7518 | baseline |
| ours yolo11n_full（80ep）| 0.5747 | **预训练迁移率仅 14.8%, 80ep linear-LR 未收敛** |
| ablation A0 yolo11n（80ep, daemon 重训）| 0.6628 | 协议变化对 baseline 都不利 |
| A1 / A2 / A3 / A4 | daemon 跑着 | 估计今晚出 |

**结论**：v1 协议产生的 ours / ablation 数字 **不进论文主表**。它们只作为 §"训练协议敏感性分析" 的对比证据。论文主表来自 v2 协议。

---

## 7. 已完成的代码（按角色）

### ML 训练 / 评估 / 可视化（沿用现有）

```
code/
├── train/{train_baseline,train_ours,train_ablation,train_v2}.py
├── eval/{eval_complexity,eval_robustness,eval_deployment}.py
├── visualize/{plot_results,grad_cam,make_qualitative}.py
├── configs/yolo11n_*.yaml（含新建的 3 个 cbam 位置消融）
├── models/register_modules.py（关键 patch，别动）
├── postprocess/
│   ├── collect_metrics.py     ✅ 已端到端跑通
│   ├── fill_paper.py          ✅ 已端到端跑通
│   ├── copy_figures.py        ✅
│   ├── build_pdfs.py          ✅
│   ├── prepare_defense.py     ✅
│   ├── finalize_all.py        ✅ 一键串
│   ├── sanity_check_configs.py ✅ 验证 8 个 yaml + 迁移率
│   └── count_classes.py       ✅ 统计实测尺度/长尾
├── run_pipeline_v2.py         ⚠️ 已写未跑
├── _daemon_run_v2.bat         ⚠️ 已写未启
└── 05_最终交付.bat            ✅ 一键收尾
```

### 平台 / 边缘 / 仿真（**未开始**）

按 `MASTER_ARCHITECTURE.md` §3.4 规划：

```
graduation_project/
├── platform/   # Q3 开建（M7 12 月）
├── edge/       # Q2 开建（M5 10 月）
└── simulation/ # Q3 末（M9 2 月）
```

---

## 8. 已完成论文（待 v2 实验回填）

```
paper/                      # 中文 markdown 5 章 ✅ 已修硬伤
├── 00_meta.md             # 已撤回伪数字、改为公平叙事
├── 01_introduction.md     # ✅
├── 02_related_work.md     # ✅
├── 03_method.md           # ✅ 加入实测尺度分布
├── 04_experiments.md      # 待 v2 跑完回填
├── 05_conclusion.md       # ✅ 已修
└── tex/
    ├── main.tex           # 英文 IEEE TII ✅ 已修
    ├── main_zh.tex        # 中文 ✅ 已修
    └── refs.bib
```

**5 处理论硬伤已修**（基于实测）：
- ❌ 4-8 px 小目标 → ✅ finger 类中位 29 px、最小 14.5 px
- ❌ 90% box < 0.05 → ✅ 训练 32% / 验证 47%
- ❌ 7000× 长尾 → ✅ 三层级 (3200× / 591× / 7546×) 显式区分
- ❌ P2 为绝对小目标设计 → ✅ P2 为 finger 类边界目标设计
- ❌ "提升 -16.43 pp"等伪数字 → ✅ 撤回为 "v2 协议训练完成后回填"

PDF 重编：✅ main.pdf 202KB / main_zh.pdf 312KB

---

## 9. 关键决策记录

### 训练协议
- **v2 协议**（所有正式实验）：200 epoch / cosine LR (lrf=0.01) / close_mosaic=20 / patience=50 / 同样的预训练源 / 相同 augment
- **v1 协议**（已有数据）：50/80 epoch / linear LR / 默认 ultralytics — **只作为协议敏感性对照**

### 实验组（v2）
- E1: 3 baseline 横评（yolov8n / 10n / 11n）
- E2: 5 组主消融（A0 / A1 cbam / A2 ema / A3 p2 / A4 full）
- E3: 3 组 CBAM 位置消融（P3only / P3+P4 / P5only）
- E4: 训练预算扫描（ours @ 100ep / 300ep）

### 仿真选型
- ~~AirSim（Unreal）— 视觉真实、文献多、可在 Q3 末做演示~~
- **2026-07-27 变更为 Gazebo Harmonic LTS**。AirSim 及其主要 fork Colosseum 均已归档；且飞控开发机是 AMD GPU，AirSim/Isaac Sim 都跑不了。详见 `HARDWARE_FLIGHT_LAYER.md` §2.2

### 论文叙事
- **不寻求绝对 SOTA**
- 三个核心贡献：CBAM 层次化注入位置消融 / P2 分支对 finger 类的针对性贡献 / 预训练迁移率与训练预算量化分析
- 无论实验数字好坏，6 条结论都站得住（详见 `MASTER_ARCHITECTURE.md` §2 + `EXPERIMENT_DESIGN_v2.md`）

### 平台路径
- ~~不做飞控层（用大疆 SDK 或仿真替代）~~ → **2026-07-27 变更**：已购入 Pixhawk 6C，新增 `flight/` 层。见下方「2026-07-27 决策批次」
- 不追求工业级可商用，做"作品级"
- ~~多场景 ≥ 3（光伏 + 输电 + 道路 / 屋顶 / 桥梁任二）~~ → **2026-07-27 变更为 ≥2 场景（光伏 + 输电）+ 视频→缺陷台账管线 + 真机闭环**。依据北极星「广 vs 深优先深」原则，见 `HARDWARE_FLIGHT_LAYER.md` §12

---

## 9.1 决策批次 — 2026-07-27（飞控层落地）

完整依据见 `HARDWARE_FLIGHT_LAYER.md`。以下为已执行的决策。

| # | 决策 | 内容 | 状态 |
|---|---|---|---|
| 1 | **仓库许可证** | **AGPL-3.0**。根因：`ultralytics` 是 AGPL-3.0（网络传染），而本项目要对外提供 Web 服务。变更前仓库**没有 LICENSE 文件**，法律上等于保留所有权利，与「完整开源」目标矛盾 | ✅ 已执行 |
| 2 | **仿真器** | AirSim → **Gazebo Harmonic LTS**。AirSim 已被微软归档，主要 fork Colosseum 亦已归档；且飞控开发机是 AMD GPU，Isaac Sim / AirSim 都跑不了，Gazebo 是唯一解 | ✅ 已执行 |
| 3 | **新窗口 Window-E** | `flight/**` 归属 Window-E（飞控 + 仿真）。不并入 Window-C —— 知识域不重叠。原属 Window-D 的 `simulation/` 并入 `flight/sitl/` | ✅ 已执行 |
| 4 | **版本锁定** | PX4 **v1.17.0** / px4_msgs **release/1.17** / ROS 2 **Humble** / Ubuntu **22.04** / Gazebo **Harmonic**。与主要代码参考 `aerial-autonomy-stack` 对齐，零适配摩擦。单一来源 `flight/VERSIONS.md` | ✅ 已执行 |

### 本批次的关键量化发现

| 发现 | 数值 | 影响 |
|---|---|---|
| **PX4 默认 DDS 话题集占满 6C 串口预算** | **60,060 B/s = 921600 bps 链路的 100.3%** | 不裁剪直接联调必然丢包。已给出裁剪方案 B（65.7%）。这是低成本平台特有的工程约束，可写进论文 |
| 带宽第一大户 | `/fmu/out/vehicle_odometry` 100 Hz = 12,400 B/s（占默认总量 20.6%） | GPS 巡检不做 VIO 融合可整条裁掉；但若后续做 GNSS 拒止环境巡检必须加回，届时只能换 6X |
| 6C 不是 PAB 形态 | 插不进 Holybro Jetson Baseboard | 必须分体式（6C + 独立机载电脑，TELEM2 串口互联）。AAS 算法层可全抄，硬件部署层不可抄 |
| PX4 自带端到端神经控制器 | `mc_nn_control` + **fmu-v6c 专用编译目标** `make px4_fmu-v6c_neural`，15 KB TFLite 模型编进固件；uORB `NeuralControl` 内置 `inference_time` 埋点自动进 `.ulg` | 已登记为 Q3/Q4 加分机会，**本期明确不做**（`Kconfig` 里 `default n`，稳定性未验证） |

### 本批次的工程加固

- **行尾规范**：新增 `.gitattributes`，声明 `*.sh` / `*.msg` / `*.srv` / `*.action` / `*.params` 为 `eol=lf`，`*.bat` / `*.ps1` 为 `eol=crlf`。
  起因是在本机工作区发现 4 个协作脚本 `.sh` 为 CRLF；用 `git ls-files --eol` 核实后确认**仓库内一直是 LF**，CRLF 由本机 `core.autocrlf=true` 在 checkout 时产生 —— 仓库内容无缺陷。
  但风险真实存在：Window-E 要从 WSL 访问 Windows 工作区（`bash /mnt/c/...`），会拿到 CRLF 并报 `bad interpreter: /usr/bin/env bash^M`。`.gitattributes` 强制任何平台都得到 LF，已用 `git check-attr` 验证生效。
  有意**不写** `* text=auto` —— 那会让现有 33 个 CRLF 的 Python 文件在下次 checkout 时全部重写，产生数千行无意义 diff

### 本批次的事故记录

- Kiro 重构工作副本目录时，`Move` 失败后紧随的 `Remove-Item -Recurse` 无条件执行，误删了本仓库的本地 clone。因是零本地修改的干净 clone，重新 clone 完全恢复，**无数据损失**。教训：不把清理动作链在可能失败的操作之后

---

## 10. 当下要做的事（按 NORTH_STAR 原则：只做下一件）

### 立刻可做（不冲突 GPU）

- [x] 修 5 处论文硬伤（已完成）
- [x] 写 `PROJECT_NORTH_STAR.md`（已完成）
- [x] 写 `MASTER_ARCHITECTURE.md`（已完成）
- [x] 重写本 `STATE.md`（已完成）
- [ ] 准备 v2 训练 sanity check 脚本（不启动训练，仅准备）

### daemon 跑完后（明天）

- [ ] 用 v1 数据生成"短预算对照报告"，作为 v2 启动前的 baseline reference
- [ ] 启动 v2 第一个训练（baseline yolo11n 200ep）作为 sanity check
- [ ] sanity 通过后启动 v2 daemon（13 个训练串行 ≈ 200 小时）

### 本周内

- [ ] v2 daemon 跑起来后定期 review
- [ ] 同时不冲突的事：开始读 FastAPI 文档（M4 之前必备）

---

## 11. 用户偏好（性格 / 沟通方式）

- **中文回复**
- **直接、不绕弯**："你直接运行，我只看结果"
- 信任 Kiro 做技术决策（"听你的"），但要求事先说清楚"做什么 + 为什么 + 多久"
- 对"假承诺"零容忍——绝对不能编不存在的文件 / 链接 / 命令
- "时间不打紧、精力充足"——不要为了赶时间砍掉重要事
- "学到东西就是赢"——做不出来不算失败，路上学到的全是真本事
- "实践和理论都达到完美"——平台是真东西，论文也要严谨
- "论文不能注水也不能造假"——这是底线

---

## 12. 危险动作（禁止）

- ❌ 不要关 v1 `GP_Pipeline_Daemon`（除非用户明确要求停训）
- ❌ 不要删 `code/runs/baseline/` 等已有训练结果（v1 数据是协议对照证据）
- ❌ 不要碰 `code/data/processed/pvel_yolo/`（数据集准备好了）
- ❌ 不要改 `code/configs/yolo11n_full.yaml` 等核心 yaml（消融对比依赖）
- ❌ 不要改 `code/models/register_modules.py`（含关键 parse_model patch）
- ❌ 不要追求"漂亮数字"调实验（北极星明文规定）
- ❌ 不要在没和用户对齐前做大方向变更

---

## 13. 状态快照命令

```powershell
# daemon 状态
schtasks /query /tn "GP_Pipeline_Daemon"

# 当前训练 epoch
Get-Content E:\Users\Administrator\Desktop\gp\graduation_project\code\runs\current.log -Tail 1

# GPU
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader

# v1 daemon 进度
Get-Content E:\Users\Administrator\Desktop\gp\graduation_project\code\runs\daemon.log -Tail 30

# 已完成的 best.pt
Get-ChildItem E:\Users\Administrator\Desktop\gp\graduation_project\code\runs -Recurse -Filter best.pt | Select-Object FullName, LastWriteTime
```

---

## 14. 给接管 Kiro 会话的第一句话

复制粘贴：

> 接管 Skylark 平台项目。先读 `PROJECT_NORTH_STAR.md` + `MASTER_ARCHITECTURE.md` + `MULTI_WINDOW_PROTOCOL.md` + 本 `STATE.md`。当前 v1 daemon 跑着短预算 ablation 作为对照，跑完后启动 v2 协议正式实验（13 个训练 × 200ep），然后开始 Q1 论文季 → Q2 边缘部署 → Q3 平台 → Q4 答辩。底线：诚实、不注水。北极星：学到东西就是赢。如果你不知道自己是哪个窗口，先识别（默认 Window-A）。

---

## 15. 待办交接（Pending Handoffs）

> 按 `MULTI_WINDOW_PROTOCOL.md` §4.1 的标准格式。
> 完成的 handoff **不删除**，加 ✅ 标记保留作审计轨迹。

### ✅ 已拍板的决策（2026-07-27 批次二）

**[2026-07-27] ✅ 范围取舍：第三个检测场景 → 真机闭环 + 视频→台账管线**

`PROJECT_NORTH_STAR.md` 决策原则写着「广 vs 深取舍时**优先深**，但保证至少一个广度示例」。

加入 `flight/` 后，两件事在时间上直接竞争：

| 事项 | 类型 | 成本 |
|---|---|---|
| 「≥3 场景」的第三个场景（道路 / 屋顶） | 广 | 3-4 周（数据清洗 + 标注转换 + 训练） |
| 真机飞行闭环 + 「视频→缺陷台账」管线 | 深 | 8-10 周 |

**决定**：第三个场景换成「真机闭环 + 视频→台账管线」。场景数 **3 → 2**（光伏 + 输电，仍满足「至少一个广度示例」）。

**理由**：现有 `code/` 只做到「单张图检测出框」。从「出框」到「电站缺陷台账」之间的**组件跟踪、多帧关联、地理配准**才是「巡检平台」与「检测模型」的本质区别，也是论文里最容易做出第一手贡献的地方 —— 第三个场景给不了这个。参考实现 `PV-Hawk`（MIT，博士项目，完整管线）。

**⚠ 必须说清的一点**：这次取舍换的是**深度，不是工期**。腾出的 3-4 周被真机 + 台账管线（合计 8-10 周）吸收，**Q3 的实际压力没有减小**。不要误以为"少做一个场景就轻松了"。

**已同步修改的文件**（8 处，清单见 `HARDWARE_FLIGHT_LAYER.md` §12）：
`PROJECT_NORTH_STAR.md` 五条标准 / `MASTER_ARCHITECTURE.md` §2 §4(Q3-M7, Q3-M9, Q3产出) / `STATE.md` §2 §9 / `WINDOW_D_KICKOFF.md` / `flight/MODULE_STATE.md`

**[2026-07-27] ✅ 商业化路径：不做**

用户明确决定不做商业化。**AGPL-3.0 永久确定，不替换 Ultralytics。**

这条决定的实际效果是把许可证问题彻底关掉：

| 事项 | 变更前 | 变更后 |
|---|---|---|
| 评估替换 Ultralytics | Q2 前必须决定，替换预计数周 | **取消该任务** |
| GPL 组件能否进构建 | 需谨慎，怕堵死商业路径 | **可以**（且经实测全部兼容） |
| 许可证的后续跟踪开销 | 需持续关注 | **归零** |

**顺带纠正了一个我此前的错误判断**：原先写「GPL-2.0（FAST_LIO）与 AGPL-3.0 不兼容」，
并据此建立了 copyleft 隔离策略。逐个读 LICENSE 正文核实后该判断**不成立** ——
关键是遗漏了 "any later version"（or-later）条款。实测结果：

| 组件 | 实测许可证 | 与 AGPL-3.0 兼容 |
|---|---|---|
| FAST_LIO | GPL-2.0-**or-later** | ✅ 可升级到 GPL-3.0 |
| VINS-Fusion | GPL-3.0-or-later | ✅ GPL-3.0 §13 允许与 AGPL-3.0 组合 |
| ego-planner-swarm | GPL-3.0-or-later | ✅ |
| kiss-icp / PV-Hawk | MIT | ✅ |

**没有任何候选组件因许可证被排除。** 核实工具 `99_notes/_check_licenses.py`（在参考资料库，不在本仓库）。

隔离策略未删除，但**理由已改写**为「构建体量与可复现性」（对应北极星「任何人 clone
都能在 30 分钟内跑起来」），并改名为「重型依赖隔离策略」。详见 `THIRD_PARTY_LICENSES.md` §3。

**对「事业起点」定位的影响**：依然成立，只是路径明确为**开源作品集 / 技术能力 / 行业影响力**，
而非闭源变现。这与北极星「学到的东西 > 做出来的产品 > 论文叙事」的优先级一致 —— 开源更利于前两项。

### ⏸ 仍待拍板的决策提请

（无。截至 2026-07-27 全部已决。）

### 紧急 Handoffs（< 24h 内必须处理）

**[2026-07-27] Window-E → 用户（硬件操作，Kiro 无法代做）**

事项 1：**6C 首次上电与基线导出**（约 1 小时，不需要任何配件）
1. 6C 插 USB，QGC 刷 **v1.17.0** 固件
2. 选机架类型
3. 全套校准：加速度计、水平、罗盘、遥控器
4. 配失效保护参数（清单见 `flight/params/CHANGELOG.md` §本项目已规划的参数改动）
5. 导出 `flight/params/pixhawk6c_bench_v1.params`
6. 在 `flight/params/CHANGELOG.md` 登记

价值：产出一份「已知良好」基线配置，之后任何改动都能 diff。硬件放着会积灰，配置基线做出来就是永久资产。

事项 2：**WSL2 安装**（约 20 分钟，大部分是等待）
```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default Ubuntu-22.04
# 建 C:\Users\Klara\.wslconfig，模板见 flight/sitl/bootstrap_wsl2.sh 附录
wsl --shutdown
```
之后即可跑 `bash flight/sitl/bootstrap_wsl2.sh --check`。

### 本周 Handoffs

（无 — Window-B 尚未上线）

### Q1 内 Handoffs

- [2026-07-27] **Window-E → Window-B**（Q3 启动 Window-D 之前必须处理）
  事项：**重写 `WINDOW_D_KICKOFF.md`**
  原因：该文档写于 2026-05-27，2026-07-27 的架构变更使其正文过时 —— 正文（含要复制粘贴给新窗口的「启动语句」段）仍有约 19 处 AirSim / `simulation/` / 「前端 + 仿真」/「3 个场景」的表述
  已做的：头部加了「⚠ 2026-07-27 变更说明（启动前必读）」权威对照表；修了 3 处最会误导的角色定义（自我注册行、文件归属清单、M9-E 段作废标记）
  未做的：正文其余部分未逐处改写。判断是届时必然整体重写，逐处修补是浪费
  **风险**：在重写完成前，启动 Window-D 时**必须把头部变更说明一并粘贴**，否则新窗口会按过时职责范围干活（去装 AirSim、去训第三个场景模型、去改 `simulation/`）
  期望产出：Q3 启动前一份与当时架构一致的 Window-D 启动套件
  紧急度：Q3 前（约 12 月），不紧急但不可遗漏

- [2026-07-27] **Window-E → Window-B**（本周内）
  事项：追认 `HARDWARE_FLIGHT_LAYER.md`，并校对本次对 `PROJECT_NORTH_STAR.md` / `MASTER_ARCHITECTURE.md` / `MULTI_WINDOW_PROTOCOL.md` 的修改
  文件：`HARDWARE_FLIGHT_LAYER.md`、`THIRD_PARTY_LICENSES.md`、`PROJECT_NORTH_STAR.md`、`MASTER_ARCHITECTURE.md`、`MULTI_WINDOW_PROTOCOL.md`
  说明：项目根 `*.md` 归 Window-B，本次由 Window-E 越权修改（用户已授权执行）。按协议在此留痕
  期望产出：B 通读后在本条末尾标 ✅，或指出需修正处
  紧急度：本周

- [2026-05-27 15:00] Window-A → Window-B（待 B 上线后处理）
  事项：5 处理论硬伤已修，请校对一遍
  文件：paper/{01_introduction.md, 03_method.md, 05_conclusion.md, 00_meta.md, tex/main.tex, tex/main_zh.tex}
  期望产出：B 通读后在 handoff 末尾标 ✅ 或写出仍需修正的地方
  紧急度：B 上线后第一周内

### 长期 Handoffs

- [2026-05-27 15:00] Window-A → Window-C（Q2 启动时处理）
  事项：把 ours best.pt 导出 ONNX + INT8 QAT，部署到 Jetson
  依赖：Window-A 先完成 v2 协议的 ours 训练
  时机：Q2 M4 9 月

### 已完成 Handoffs（审计轨迹）

（暂无）

---

## 16. 修改日志

- 2026-07-27 Window-E: **飞控层落地**。新增 Window-E；4 项决策（AGPL-3.0 许可 / Gazebo 取代 AirSim / flight 归属 / 版本锁 v1.17.0）；接口契约包 `skylark_flight_msgs`（14 个接口，静态校验通过）；`dds_bandwidth.py` 算出默认 DDS 话题集占满 6C 串口 100.3%；三份实操文档 + WSL2 引导脚本；修复 4 个 `.sh` 的 CRLF 缺陷 + 新增 `.gitattributes`。详见 §9.1 与 `HARDWARE_FLIGHT_LAYER.md`
- 2026-05-27 15:25 Window-A: 完成多窗口协作基础设施（MULTI_WINDOW_PROTOCOL.md + skill + steering + gpu_arbiter.py + Window-B 启动套件）
- 2026-05-27 14:53 Window-A: 完成 MASTER_ARCHITECTURE.md 写作
- 2026-05-27 12:39 Window-A: 完成 PROJECT_NORTH_STAR.md 写作
- 2026-05-27 12:30 Window-A: 修 5 处理论硬伤（基于 6254 个 box 实测）
- 2026-05-27 11:00 Window-A: 项目方向锚定为 Skylark 平台 + 论文双产物
