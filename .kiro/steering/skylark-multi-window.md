---
inclusion: always
---

# Skylark 多窗口协作约束（Steering — 始终加载）

> 此文件每次 Kiro 会话自动加载。不是详细文档，是**最小约束集**。
> 详细规则见 `.kiro/skills/skylark-coordination/SKILL.md`（按需主动激活）。

## 你正在的项目

**Skylark — 通用无人机航拍 AI 巡检平台**

双产物：
- 工程：完整 Web 平台 + Jetson 边缘部署 + 仿真演示
- 论文：本科毕设（中文 35000+ 字）+ SCI 投稿

## 必读上层文档（按顺序）

如果你还没读过，立刻读：
1. `PROJECT_NORTH_STAR.md`（北极星）
2. `MASTER_ARCHITECTURE.md`（系统架构）
3. `MULTI_WINDOW_PROTOCOL.md`（协作协议详解）
4. `STATE.md`（当前状态）

## 当前窗口角色识别

会话开始时，你必须**主动识别**自己是哪个窗口（A/B/C/D）：

| 线索 | 推断 |
|---|---|
| 用户启动语句包含 "Window-A" | A |
| 用户启动语句包含 "Window-B" | B |
| 当前活跃文件在 `code/` 下 | 推测 A，但需用户确认 |
| 当前活跃文件在 `paper/` 下 | 推测 B，但需用户确认 |
| 不确定 | **询问用户** |

如果无法识别窗口角色，**先问用户**，再开始工作。不要默认。

## 三大铁律（任何情况下都遵守）

### 铁律 1：文件归属

简化决策：

| 目录 | 归属窗口 |
|---|---|
| `code/**` | Window-A |
| `paper/**` 和项目根 `*.md` | Window-B |
| `platform/backend/**` `edge/**` | Window-C |
| `platform/frontend/**` `simulation/**` | Window-D |
| `STATE.md` `.gpu_lock.json` `requirements.txt` | 共享（特殊协议） |

**编辑前判断**：目标文件归属当前窗口？
- 是 → 编辑
- 否 → 在 STATE.md 写 handoff 请求，**不直接编辑**

详见 `references/windows.md`、`references/claim.md`。

### 铁律 2：GPU Lock

**任何 GPU 操作前必须 claim**：训练、推理 benchmark、ONNX 导出（部分情况）。

```bash
# 检查 lock 状态
bash .kiro/skills/skylark-coordination/scripts/gpu-status.sh

# claim（Window-A）
python code/postprocess/gpu_arbiter.py claim --owner Window-A --task "<描述>"

# release（任务结束）
python code/postprocess/gpu_arbiter.py release
```

不允许：
- 绕过 lock 直接训练
- 训练崩溃后不清理 lock（脚本必须有 finally）
- 多窗口同时占 GPU

详见 `references/gpu-arbiter.md`。

### 铁律 3：STATE 是真相

任何**跨窗口决策**必须落到 STATE.md。口头不算。

每次会话结束前，如果做了以下事情，必须更新 STATE.md：
- 完成了 handoff
- 产生了新的"已知事实"（实验数字、配置决策、观察结果）
- 创建或修改了重要文件
- 发现了与其他窗口相关的问题

详见 `references/module-state.md`。

## 不允许做的事

❌ **绕过协议**：例如直接改不属于当前窗口的文件而不写 handoff
❌ **大方向变更**：架构 / 路线图变更必须先在 STATE.md 提案，等用户确认
❌ **造假数据**：北极星明文规定。任何"数字不漂亮"都按事实写
❌ **替用户做选择**：遇到分叉点，给推荐 + 等用户拍板，不要自己定
❌ **承诺无法做到的事**：Kiro 是助手不是雇员，不要承诺"我让 4 个 agent 并行"这类做不到的事

## 鼓励做的事

✅ **主动激活 skill**：会话开始时调用 `discloseContext("skylark-coordination")` 加载完整能力
✅ **运行 status.sh**：周期性看一眼项目全局状态
✅ **维护 MODULE_STATE**：自己负责的模块 STATE 自己写
✅ **写 handoff**：跨窗口协作通过 STATE 而非记忆
✅ **诚实承认不确定性**：宁可说"我不确定"也不要编造

## 紧急联络

如果发现：
- 文件冲突（两窗口同时改 STATE）→ 在 STATE 末尾写 incident，让用户决策
- GPU lock 泄漏（训练死了 lock 还在）→ `gpu-status.sh --force-clear`
- 跨窗口意见冲突 → 写"决策提请"段，等用户

不要试图"自己解决"——把决策权交回给用户。

## 一行总结

> **Skylark 是一个真实产品 + 一份严谨论文 + 一年学习。**
> **协议是为了让自由协作不变成混乱，不是束缚。**
