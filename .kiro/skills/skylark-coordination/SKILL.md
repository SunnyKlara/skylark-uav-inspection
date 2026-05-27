---
name: skylark-coordination
description: Skylark 项目专用的多窗口协作约束。当任何 Kiro 窗口在 Skylark 项目中工作时激活，强制执行文件归属、GPU lock、STATE 同步三大铁律，防止多窗口冲突与状态漂移。
keywords:
  - skylark
  - multi-window
  - coordination
  - gpu-lock
  - file-ownership
  - state-sync
  - parallel-development
  - claude-code-pm
  - ccpm
---

# Skylark 多窗口协作 Skill

> 此 skill 实现 `MULTI_WINDOW_PROTOCOL.md` 的机器可执行版本。
> 设计参考 [CCPM (automazeio/ccpm)](https://github.com/automazeio/ccpm)，做了 Skylark 特化。

---

## 何时激活

**自动激活场景**（通过 .kiro/steering/skylark-multi-window.md 的 inclusion: always）：
- 任何 Kiro 会话在 Skylark 工作区开始
- 用户提到"多窗口"、"并行开发"、"窗口 B/C/D"、"协作"等关键词

**手动激活场景**：
- 用户明确说"激活 skylark-coordination skill"
- 启动新窗口时第一句话引用本 skill

---

## 三大铁律（核心约束）

### 铁律 1：文件归属不重叠

每个文件路径**有且仅有一个窗口主人**。详见 [references/windows.md](./references/windows.md)。

任何编辑前必须确认：
1. 当前窗口角色是什么（A / B / C / D）
2. 目标文件归属哪个窗口
3. 不归属当前窗口 → 走 handoff 协议（见 references/handoff.md）

### 铁律 2：GPU Lock 唯一

5060 Ti 是稀缺资源。任何 GPU 任务前必须 claim。详见 [references/gpu-arbiter.md](./references/gpu-arbiter.md)。

操作流程：
```bash
# 检查
bash .kiro/skills/skylark-coordination/scripts/gpu-status.sh

# 占用（Window-A 训练前）
python code/postprocess/gpu_arbiter.py claim --task "v2 baseline 200ep"

# 释放（训练结束后）
python code/postprocess/gpu_arbiter.py release
```

### 铁律 3：STATE 是真相

任何跨窗口决策必须落到 STATE.md。详见 [references/module-state.md](./references/module-state.md)。

---

## 4 份核心 reference

按需读取（不要一次全读）：

| Reference | 读取场景 |
|---|---|
| [windows.md](./references/windows.md) | 不确定当前窗口能改哪些文件时 |
| [claim.md](./references/claim.md) | 编辑前要 claim 文件归属 |
| [handoff.md](./references/handoff.md) | 需要把工作交给另一个窗口时 |
| [gpu-arbiter.md](./references/gpu-arbiter.md) | 任何 GPU 操作前 |
| [module-state.md](./references/module-state.md) | 维护 MODULE_STATE.md schema |
| [conventions.md](./references/conventions.md) | 文件命名 / 提交格式 / 注释规则 |

---

## 4 个确定性脚本（不耗 LLM token）

| 脚本 | 作用 | 调用 |
|---|---|---|
| `scripts/status.sh` | 一键看所有窗口在干什么、GPU 状态、daemon 状态 | `bash .kiro/skills/skylark-coordination/scripts/status.sh` |
| `scripts/claim-check.sh` | 检查某文件是否被其他窗口占用 | `bash .../scripts/claim-check.sh paper/04_experiments.md` |
| `scripts/gpu-status.sh` | GPU lock 状态 + 进程检查 + 可选强制清理 | `bash .../scripts/gpu-status.sh [--force-clear]` |
| `scripts/sync.sh` | 周日同步：检查所有 MODULE_STATE 与主 STATE 偏差 | `bash .../scripts/sync.sh` |

---

## 启动新窗口的标准流程

### 第 1 步：用户在 IDE 开新窗口
`File → New Window`，打开同工作区。

### 第 2 步：用户给新窗口发启动语句
启动语句模板见 `WINDOW_<X>_KICKOFF.md`（项目根）。

例如启动 Window-B：
```
你是 Skylark Window-B（论文写作 + 文档维护）。
读完以下文档后告诉我你理解的当前任务：
- PROJECT_NORTH_STAR.md
- MASTER_ARCHITECTURE.md
- MULTI_WINDOW_PROTOCOL.md
- STATE.md
然后激活 skill skylark-coordination，按其约束工作。
```

### 第 3 步：新窗口主动激活本 skill
用 `discloseContext("skylark-coordination")`，理解约束后再开始干活。

### 第 4 步：新窗口在 STATE.md 注册
在 STATE.md §"活跃窗口"写一行：
```
- Window-B（论文）：2026-MM-DD HH:MM 上线，专注 paper/04_experiments.md 第 4.2 节
```

---

## 决策树：写文件前问自己

```
我要写一个文件 → 这个文件在哪个目录？
                       │
            ┌──────────┼──────────┬──────────┐
            ▼          ▼          ▼          ▼
        code/**    paper/**   platform/   simulation/
            │          │          │          │
            ▼          ▼          ▼          ▼
       Window-A    Window-B   Window-C/D  Window-D
```

如果当前窗口角色不是文件归属者：
- ❌ 不直接改
- ✅ 在 STATE.md 写 handoff 请求
- ✅ 等归属窗口完成

---

## 决策树：跑 GPU 任务前问自己

```
我要跑训练 / 推理 / benchmark
        │
        ▼
读 .gpu_lock.json
        │
   ┌────┴─────┐
   ▼          ▼
released   active
   │          │
   ▼          ▼
claim 后跑  owner == self?
              │
        ┌─────┴─────┐
        ▼           ▼
       是           否
       │           │
       ▼           ▼
     继续跑    禁止启动 / 协商
```

---

## 失败模式速查

| 症状 | 处理 |
|---|---|
| 两个窗口同时改 STATE.md | 后写者读最新再合并；避免长编辑 |
| GPU lock 泄漏（owner 进程死了） | `gpu-status.sh --force-clear` + 在 STATE 记录 |
| MODULE_STATE 与主 STATE 不一致 | `sync.sh` 检测 → 用户决策合并方向 |
| 跨窗口决策无记录 | 立刻补到 STATE.md "决策记录"段 |

---

## 与 CCPM 的差异

参见 `MULTI_WINDOW_PROTOCOL.md` §7。简版：

- ✅ 借鉴：文件即真相、bash 脚本做确定性操作、5 阶段精神
- ❌ 不用：GitHub Issues 强依赖、Worktree、自动 sub-agent 派遣
- ➕ 新增：**GPU Arbiter**（业界没解决的 ML 项目特有问题）

---

## 一行结尾

> 协议是默认约束，不是默认束缚。当协议挡住合理的事，重新审视协议而不是绕过协议。
