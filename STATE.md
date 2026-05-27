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

| 窗口 | 上线时间 | 当前焦点 |
|---|---|---|
| **Window-A**（ML 主线）| 2026-05-26 23:35（v1 daemon 上线） | 监控 v1 daemon、准备 v2 启动、维护协议 |
| **Window-B**（论文 + 文档）| ⏳ 待启动 | — |
| **Window-C**（后端 + 边缘）| ⏳ Q2 起（约 9 月）| — |
| **Window-D**（前端 + 仿真）| ⏳ Q3 起（约 12 月）| — |

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
| 产品（实践） | 0% | Web 平台真在线 + ≥3 场景 + GitHub 开源 |
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
- AirSim（Unreal）— 视觉真实、文献多、可在 Q3 末做演示

### 论文叙事
- **不寻求绝对 SOTA**
- 三个核心贡献：CBAM 层次化注入位置消融 / P2 分支对 finger 类的针对性贡献 / 预训练迁移率与训练预算量化分析
- 无论实验数字好坏，6 条结论都站得住（详见 `MASTER_ARCHITECTURE.md` §2 + `EXPERIMENT_DESIGN_v2.md`）

### 平台路径
- 不做飞控层（用大疆 SDK 或仿真替代）
- 不追求工业级可商用，做"作品级"
- 多场景 ≥ 3（光伏 + 输电 + 道路 / 屋顶 / 桥梁任二）

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

### 紧急 Handoffs（< 24h 内必须处理）

（无）

### 本周 Handoffs

（无 — Window-B 尚未上线）

### Q1 内 Handoffs

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

- 2026-05-27 15:25 Window-A: 完成多窗口协作基础设施（MULTI_WINDOW_PROTOCOL.md + skill + steering + gpu_arbiter.py + Window-B 启动套件）
- 2026-05-27 14:53 Window-A: 完成 MASTER_ARCHITECTURE.md 写作
- 2026-05-27 12:39 Window-A: 完成 PROJECT_NORTH_STAR.md 写作
- 2026-05-27 12:30 Window-A: 修 5 处理论硬伤（基于 6254 个 box 实测）
- 2026-05-27 11:00 Window-A: 项目方向锚定为 Skylark 平台 + 论文双产物
