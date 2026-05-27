# Skylark 多窗口协作协议 — MULTI WINDOW PROTOCOL

> 写于 2026-05-27。Skylark 项目专属的多 Kiro 窗口协作约束。
> 本文档解释**为什么这么设计 + 怎么用**。机器可读的协议见 `.kiro/skills/skylark-coordination/`。

---

## 0. 速读

如果你只看 30 秒：

| 窗口 | 角色 | 何时开 | 占 GPU |
|---|---|---|---|
| **Window-A** | ML 主线（训练 / 评估 / 量化） | 项目第 1 天起 | **唯一占用** |
| **Window-B** | 论文写作 + 文档维护 | 项目第 1 天起 | 不占 |
| **Window-C** | 后端 + 边缘部署 | Q2 起（M4 9 月） | 偶尔占（推理 benchmark） |
| **Window-D** | 前端 + 仿真 | Q3 起（M7 12 月） | 不占 |

**协作铁律**：
1. 文件归属不重叠 — 每个文件有明确的窗口主人
2. GPU lock 唯一 — 训练前必须 claim，做完必须 release
3. STATE.md 是真相 — 任何跨窗口决策必须落到 STATE，口头不算
4. 每模块自带 MODULE_STATE.md — 主 STATE 只汇总不细写

---

## 1. 为什么需要这套协议

### 1.1 单窗口的局限

我们已经经历过：一个会话里来回讨论"训练协议 / 论文叙事 / 平台架构 / 数据集事实"，结果上下文炸开、反复跳方向。原因不是我笨，是**一个 LLM 上下文窗口塞不下整个项目的所有维度**。

### 1.2 多窗口的真实价值

不是"多个 AI 并行干活"——Kiro 仍然是单线程助手。多窗口的真实价值是：

- **认知专精**：A 窗口专心 ML，不会被前端代码污染思考路径
- **时间填充**：A 训练时 GPU 跑着，B 同步在写论文，时间利用率从 50% → 90%
- **故障隔离**：B 窗口的论文写作出错不会让 A 窗口的训练中断
- **接管简化**：每个窗口的会话历史更短，新会话接管成本低

### 1.3 业界共识与 Skylark 特化

调研了 CCPM、MACP、Anthropic Worktrees 等业界方案，**业界共识三件套**：
- **Claim/Lock**：声明"我在改 X"
- **Handoff**：交接给下一个 agent
- **State Sync**：所有 agent 看到一致状态

Skylark 在此基础上**加一件事**：**GPU Arbiter** —— 单 GPU 资源仲裁。这是 ML 项目特有的，业界方案没解决（因为它们假设无限算力）。

---

## 2. 窗口角色详解

### 2.1 Window-A — ML 主线

**职责**：
- 模型训练（baseline / ablation / ours / 多场景）
- 模型评估（complexity / robustness / per-class AP）
- 模型量化（FP16 / INT8 QAT / TensorRT 导出）
- 推理 benchmark（5060 Ti / Jetson 跨平台对比）
- 实验流水线脚本（run_pipeline_v2 等）
- 数据集分析与统计

**文件归属**（独占）：
```
code/train/**
code/eval/**
code/visualize/**
code/configs/**
code/models/**
code/postprocess/**
code/runs/**
code/setup/**
code/data/**            # 数据集脚本
ml/deploy/**            # Q2 起：ONNX/TRT 导出
edge/inference/**       # Q2 起：Jetson 推理
```

**GPU 优先级**：**唯一**。Window-A 默认拥有 GPU 使用权。

**典型工作流**：
```
1. claim GPU                    → 写 .gpu_lock.json
2. 启动训练（v2 daemon 等）
3. 监控进度，更新 code/runs/STATE_ML.md
4. 训练结束 → release GPU lock
5. 用 postprocess/ 处理结果
6. 把"实验产生的事实"汇报到主 STATE.md
```

### 2.2 Window-B — 论文写作 + 文档维护

**职责**：
- 中文毕设论文 5-8 章（markdown + LaTeX）
- 英文 SCI 投稿稿
- 顶层文档维护（NORTH_STAR / ARCHITECTURE / STATE / MULTI_WINDOW_PROTOCOL）
- 答辩材料（PPT 大纲、Q&A、演示视频脚本）
- 实验结果可视化的"叙事化"——把 Window-A 产出的数字讲成故事

**文件归属**（独占）：
```
paper/**
*.md（项目根的所有文档：NORTH_STAR / ARCHITECTURE / STATE / MULTI_WINDOW_PROTOCOL / FINALIZE / EXPERIMENT_DESIGN_v2 等）
docs/**                # Q2 起：架构文档、API 文档、部署手册
01_课题立项.md          # 立项相关，归 B
02_M1_第一个月作战图.md
03_数据集与代码资源.md
04_本周行动清单.md
```

**GPU**：完全不占。

**典型工作流**：
```
1. 读 STATE.md → 知道 Window-A 跑出了什么数字
2. 把 paper/04_experiments.md 的对应表格回填
3. 写第 4 章配套叙事
4. 编译 PDF（pdflatex / xelatex）
5. 更新主 STATE.md "论文进度" 段
```

### 2.3 Window-C — 后端 + 边缘部署（Q2 起）

**职责**：
- FastAPI 后端骨架
- PostgreSQL schema + SQLAlchemy ORM + Alembic 迁移
- Celery 推理 worker
- MinIO 对接
- Jetson Orin 真机部署
- TensorRT engine 编译
- 边缘推理服务（Python + ZMQ/HTTP）

**文件归属**（独占）：
```
platform/backend/**
edge/**
ml/deploy/**           # 与 Window-A 共管（边界详见 §4.2）
.github/workflows/**
docker-compose.yml（platform 目录下）
```

**GPU**：**偶尔占用**。
- Jetson 真机部署：Jetson 自带 GPU，与 5060 Ti 不冲突
- 5060 Ti 上跑 benchmark：必须 claim GPU lock
- ONNX 导出：CPU 即可，不需要 GPU

**典型工作流**：
```
情境 1：纯后端开发（不冲突 GPU）
  自由写代码 → pytest → 启动 docker-compose

情境 2：需要在 5060 Ti 跑 benchmark
  → 检查 .gpu_lock.json 是否被 Window-A 占用
  → 占用：等 / 找 Window-A 协商
  → 空闲：claim → 跑 → release
```

### 2.4 Window-D — 前端 + 仿真（Q3 起）

**职责**：
- Vue 3 前端代码
- Element Plus + Leaflet + ECharts 集成
- AirSim 仿真集成
- 演示视频脚本与录制
- 多场景模型路由的前端表现层

**文件归属**（独占）：
```
platform/frontend/**
simulation/**
docs/demo/**
```

**GPU**：完全不占。

---

## 3. 三大铁律

### 铁律 1：文件归属不重叠

每个文件路径**有且仅有一个窗口主人**。任何窗口想改不属于自己的文件，必须：
- 第一选择：在归属窗口里改
- 第二选择：通过 STATE.md 显式 handoff（写明"Window-A 请求 Window-B 在 paper/04_experiments.md 第 132 行回填 X"）

**冲突检测**：每个目录顶层 README 写明 `WINDOW_OWNER: A/B/C/D`。

**例外清单**（共享文件，需要谨慎）：
| 文件 | 共享窗口 | 协议 |
|---|---|---|
| `STATE.md` | A/B/C/D | 任何窗口都能改，但每次改前后写 timestamp |
| `code/runs/.gpu_lock.json` | A（写）+ C（写）+ B/D（读） | 见 §3.2 |
| `README.md`（项目根） | B（主写）+ 其他（review） | B 主导 |
| `requirements.txt` | A（主）+ C（追加） | 协商 |

### 铁律 2：GPU Lock 唯一

任何窗口想跑 GPU 任务前必须读 `code/runs/.gpu_lock.json`。

**Lock 文件格式**：
```json
{
  "owner": "Window-A",
  "task": "v2 baseline yolo11n 200ep",
  "started_at": "2026-05-27T15:00:00",
  "estimated_end": "2026-05-27T19:00:00",
  "pid": 12345,
  "can_be_preempted": false,
  "released_at": null
}
```

**协议**：
1. **Claim 前先读**：如果 `released_at == null` 且 `owner != self`，**禁止启动 GPU 任务**
2. **Claim 后立即写**：写完 lock 文件再开始训练
3. **Release 必须执行**：训练结束（成功或失败）必须把 `released_at` 设为时间戳
4. **Stale lock**（owner 进程死了但 lock 还在）：通过 `pid` 字段判断；任何窗口可以用 `gpu-status.sh --force-clear` 强制清理过期 lock，但要在 STATE.md 记录原因

**Window-A 的优先权**：
- 默认拥有 GPU
- 长时间训练任务（>1h）期间，其他窗口必须等
- 但 Window-A 不能 24/7 锁住 GPU——每完成一个训练后必须 release，让其他窗口有机会用

**协商场景**：
- Window-C 要做 5060 Ti 上的 INT8 benchmark（约 30 分钟）
- Window-A 当时正在跑 200 epoch 训练（约 15 小时）
- 协议：C 通过 STATE.md 提交"GPU 借用请求"，A 在下一个训练间隙安排 30 分钟空闲让 C 用

### 铁律 3：STATE 是唯一真相

**主 STATE.md** 在项目根，是所有窗口的"一站式接管协议"。

**MODULE_STATE.md** 在每个模块根，是该模块的细节快照。

**约定**：
- 任何跨窗口的决策必须写到 STATE.md
- 口头/对话决策不算数
- 每个窗口工作开始前读相关 STATE，结束前写相关 STATE
- 每周日做一次主 STATE 大同步（汇总所有 MODULE_STATE 变化）

---

## 4. 协议细节

### 4.1 跨窗口 Handoff（交接）

当 Window-A 产出的东西需要 Window-B 用时：

```markdown
## 主 STATE.md 末尾

### 待办交接（pending handoffs）

- [2026-06-01 08:00] Window-A → Window-B
  事项：v2 协议 baseline yolo11n 200ep 已训完，metrics.json 在
  `code/runs/v2/baseline/yolo11n/yolo11n_metrics.json`
  请回填 `paper/04_experiments.md` 第 4.2 节 baseline 表
  完成标记：在本条目末尾写 ✅ + 时间戳

- [2026-06-02 14:30] Window-A → Window-B
  事项：...
```

Window-B 完成后改成：
```markdown
- [2026-06-01 08:00] Window-A → Window-B
  ...
  ✅ 2026-06-01 09:15 已完成，paper/04_experiments.md 第 132/138/145 行已更新
```

### 4.2 共享代码区（ml/deploy）

`ml/deploy/` 既被 Window-A 用（导出 ONNX）也被 Window-C 用（部署到 Jetson）。规则：

- **ONNX 导出脚本**（`ml/deploy/export_onnx.py`）— Window-A 主写
- **TensorRT 编译脚本**（`ml/deploy/build_trt.py`）— Window-C 主写
- **基准测试脚本**（`ml/deploy/benchmark.py`）— **协议**：先到先写、PR 到 STATE 里 review

### 4.3 文档变更

任何窗口修改 `STATE.md` 后必须：
1. 在文件顶部更新 "最后更新：YYYY-MM-DD HH:MM by Window-X"
2. 在末尾的"修改日志"添加一行简述

任何窗口修改 `MASTER_ARCHITECTURE.md` 必须：
1. 先在 STATE.md 里发一条 "请求 Architecture 变更：理由 / 影响范围"
2. 等待用户（人类）确认后才能改
3. 改完后通知所有活跃窗口（在 STATE.md 写）

### 4.4 紧急情况

**情境 A**：训练崩了
1. Window-A 立刻 release GPU lock
2. 在 STATE.md 写 incident report
3. 不抢救 → 等用户决策（按 NORTH_STAR 原则：超过 3 天没进展就停下重审）

**情境 B**：跨窗口意见冲突
1. 不要让两个窗口"在 STATE 里吵架"
2. 把分歧总结成"决策提请"，写在 STATE.md 末尾
3. 等用户拍板

---

## 5. 各窗口启动协议

### 5.1 Window-A 启动（已经在跑）

当前会话即 Window-A。无需重启。

### 5.2 Window-B 启动（推荐：今天 daemon 跑完后）

**用户操作**：
1. 在 IDE 打开新 Kiro 窗口（`Ctrl+Shift+N` 或 `File → New Window`）
2. 打开同一工作区 `E:\Users\Administrator\Desktop\gp\graduation_project`
3. 给新窗口的第一句话发：

```
你是 Skylark 项目的 Window-B（论文写作 + 文档维护）。

1. 先读以下三份文档：
   - PROJECT_NORTH_STAR.md
   - MASTER_ARCHITECTURE.md
   - MULTI_WINDOW_PROTOCOL.md
   - STATE.md

2. 严格遵守 MULTI_WINDOW_PROTOCOL.md §2.2 的文件归属：
   你只改 paper/** 和项目根的 *.md 文档，不碰 code/。

3. 你的当前任务（Q1 M1-M2）：
   - 等 Window-A 跑完 v2 baseline 200ep 第一个 sanity check
   - 然后回填 paper/04_experiments.md 的 baseline 表
   - 同时把 paper/03_method.md 的实验环境章节按 v2 协议（200ep / cos_lr）更新
   - 准备英文 SCI 投稿的初步选刊调研

4. 工作模式：
   - 任何 GPU 操作禁止
   - 改完文件后在 STATE.md 末尾"窗口活动日志"加一行
   - 遇到需要 Window-A 配合的事，写 handoff 到 STATE.md §"待办交接"

第一件事：读完上述四份文档后，告诉我你理解的当前阶段任务，等我确认。
```

### 5.3 Window-C 启动（Q2 起，M4 9 月）

到时再写启动协议。模板待 Q2 开始时填充。

### 5.4 Window-D 启动（Q3 起，M7 12 月）

到时再写。

---

## 6. 失败模式与防御

### 6.1 文件冲突

**症状**：两个窗口同时改 STATE.md 导致 merge conflict

**防御**：
- 任何编辑 STATE.md 前先读最新版（不依赖窗口的本地缓存）
- 编辑后立即写回
- 编辑窗口尽量短（< 30 秒）
- 长篇大段更新写到模块 STATE.md，主 STATE 只汇总

### 6.2 GPU lock 泄漏

**症状**：训练崩了，lock 没释放

**防御**：
- `train_v2.py` 加 finally 块强制 release
- `gpu-status.sh --check-stale` 检测过期 lock（pid 不存在但 lock 存在）
- 用户级别紧急：`gpu-status.sh --force-clear` 强制清

### 6.3 STATE 漂移

**症状**：各窗口的 MODULE_STATE 不一致，主 STATE 已过时

**防御**：
- 周日 review 模板（`scripts/sync.sh` 自动生成检查表）
- 每个 MODULE_STATE 顶部有 "上次同步主 STATE 时间"
- 偏差 > 1 周强制 sync

### 6.4 上下文跨窗口流失

**症状**：Window-A 知道某个事实但 Window-B 不知道

**防御**：
- 任何"实验产生的事实"必须写到 STATE.md（不只是写到 results.csv）
- Window-A 每次产出新数字必须摘录到 STATE 的 "已知事实" 段
- Window-B 在写论文前必读 "已知事实" 段

---

## 7. 简化版 vs 完整版 CCPM 的区别

我们采用**简化版**。差异：

| 维度 | 完整 CCPM | Skylark 简化版 |
|---|---|---|
| 阶段纪律 | 5 阶段强制（Brainstorm / Document / Plan / Execute / Track） | 进入大模块前简化 SPEC，不为每个 feature 写 |
| 协调中心 | GitHub Issues + Worktrees | 文件 + STATE.md（无 GitHub 依赖） |
| Worktree | 每个 epic 独立 worktree | 不用，直接共享工作目录 |
| Standup | bash 脚本生成 | scripts/status.sh（同名同语义） |
| 任务追踪 | issues + 子 issues + comments | MODULE_STATE.md + handoff 队列 |
| 验收 | 自动测试 + PR review | 手动 review + 部分 CI |
| GPU 仲裁 | 不存在 | **Skylark 特有，新增** |

**简化的代价**：
- 不能多人协作（单用户单仓库假设）
- 没有自动化任务路由（CCPM 的 sub-agent 可以自动分派）
- 没有自动化进度报告（CCPM 有 standup script）

**为什么这个代价可接受**：
- Skylark 是单人项目，不需要多人协作
- 你不需要"AI 自动分派"，你需要"AI 不打架"
- 进度报告：`scripts/status.sh` 一键看（我们会做）

---

## 8. 接下来的实施步骤

按 5 步顺序：

### ✅ 步骤 1：本协议文档（你正在看）

### ⏳ 步骤 2：建 `.kiro/skills/skylark-coordination/` skill
6 份 reference markdown + 4 个 bash 脚本

### ⏳ 步骤 3：建 `.kiro/steering/skylark-multi-window.md`（auto-include）
每次 Kiro 会话自动加载，不依赖手动激活

### ⏳ 步骤 4：建 GPU lock 机制
`code/runs/.gpu_lock.json` schema + `code/postprocess/gpu_arbiter.py` 工具

### ⏳ 步骤 5：建 Window-B 启动套件
`WINDOW_B_KICKOFF.md`（用户复制粘贴用）

---

## 9. 一行结尾

> 多窗口不是堆人，是把同一颗大脑的不同思维流物理隔离。
> 协议不是束缚，是让自由协作不变成混乱。
