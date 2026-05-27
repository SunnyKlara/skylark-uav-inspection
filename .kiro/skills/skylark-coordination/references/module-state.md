# MODULE_STATE.md 协议

## 主 STATE vs 模块 STATE

| 文件 | 位置 | 内容 | 维护者 |
|---|---|---|---|
| 主 STATE.md | 项目根 | 项目级别快照（所有窗口共享） | 所有窗口共写，B 主导 |
| MODULE_STATE.md | 各模块根目录 | 该模块的细节状态 | 该模块归属窗口 |

**原则**：主 STATE 只汇总不细写。详情去模块 STATE。

## 当前已存在的 MODULE_STATE

```
code/runs/MODULE_STATE_ML.md          ← Window-A 维护（待建）
paper/MODULE_STATE_PAPER.md           ← Window-B 维护（待建）
platform/backend/MODULE_STATE.md      ← Q2 起 Window-C 维护
platform/frontend/MODULE_STATE.md     ← Q3 起 Window-D 维护
edge/MODULE_STATE.md                  ← Q2 起 Window-C 维护
simulation/MODULE_STATE.md            ← Q3 起 Window-D 维护
```

## MODULE_STATE.md 标准 Schema

每份 MODULE_STATE.md 必须包含以下 7 个部分：

```markdown
# <模块名> MODULE STATE

> 上次更新：YYYY-MM-DD HH:MM by Window-<X>
> 上次同步主 STATE 时间：YYYY-MM-DD HH:MM
> 下次同步预计：YYYY-MM-DD（建议每周日）

## 1. 模块身份

- 模块名：<例如：ML 训练流水线>
- 归属窗口：Window-<X>
- 所在目录：<例如：code/{train,eval,visualize,configs,models,postprocess,runs}>
- 一句话职责：<例如：实验设计、训练、评估、可视化>

## 2. 当前进度（当下在做什么）

- 当前活跃任务：<例如：v2 baseline yolo11n 200ep 训练中，72/200 epoch>
- 启动时间：YYYY-MM-DD HH:MM
- 预计完成：YYYY-MM-DD HH:MM
- 阻塞情况：<无 / 等 X / 等 Y>

## 3. 已完成（最近 1-2 周）

- [x] YYYY-MM-DD：<完成的事>
- [x] YYYY-MM-DD：<完成的事>

## 4. 待办（按优先级）

- [ ] [紧急] <事项>
- [ ] [本周] <事项>
- [ ] [Q1 内] <事项>
- [ ] [长期] <事项>

## 5. 已知事实（关键产出）

> 这部分是给其他窗口看的——他们最需要知道你这边产出了什么。

| 事实 | 数值 / 位置 | 时间 | 来源脚本 |
|---|---|---|---|
| baseline yolov8n 50ep mAP@0.5 | 0.7897 | 2026-05-25 | train_baseline.py |
| ours 80ep mAP@0.5 | 0.5747 | 2026-05-27 | train_ours.py |
| 训练集 finger 类中位边长 | 28.9 px | 2026-05-27 | postprocess/count_classes.py |

## 6. 与其他窗口的依赖

- 我提供给：<谁需要我的产出>
- 我依赖于：<我需要谁的产出>

## 7. 风险与决策记录

- [YYYY-MM-DD] <发现的问题 / 做的决策>
- [YYYY-MM-DD] <如果发生 X，应对方案 Y>
```

## 主 STATE.md 中的 "汇总" 段

主 STATE.md 应包含一个"模块 STATE 汇总"段，自动从各 MODULE_STATE 抓取关键信息：

```markdown
## 6. 各模块状态汇总（每周日同步）

### ML 主线（Window-A，详见 code/runs/MODULE_STATE_ML.md）
- 当前活跃：v2 baseline yolo11n 200ep, 72/200 epoch
- 本周完成：v1 daemon ablation 全部跑完
- 阻塞：无

### 论文（Window-B，详见 paper/MODULE_STATE_PAPER.md）
- 当前活跃：等 Window-A v2 baseline 数据回填 4.2 节
- 本周完成：5 处理论硬伤已修，PDF 重编通过
- 阻塞：等 v2 数据
```

## 同步协议（每周日做一次）

**触发**：每周日 / 每次有重大变更 / 任何窗口主动调用

**步骤**（用 sync.sh 脚本）：

1. 扫描所有 MODULE_STATE.md
2. 抽取每份的 §2「当前进度」+ §5「已知事实」最新条目
3. 比对主 STATE.md §6「各模块状态汇总」
4. 生成 diff 报告
5. 用户决策合并方向

**执行**：
```bash
bash .kiro/skills/skylark-coordination/scripts/sync.sh
```

输出：
```
=== Skylark Sync Report ===
Generated: 2026-MM-DD HH:MM

ML 主线（Window-A）:
  ✅ MODULE_STATE last updated: 2026-MM-DD (1d ago)
  ✅ 主 STATE 汇总段 last updated: 2026-MM-DD (1d ago)
  ⚠️ 偏差：MODULE_STATE 提到了 "v2 sanity check 通过"，主 STATE 未反映

论文（Window-B）:
  ✅ 同步

平台后端（Window-C）:
  ⏳ 模块未启用

平台前端（Window-D）:
  ⏳ 模块未启用

建议合并：
  1. 把 ML 模块"v2 sanity check 通过"加到主 STATE.md §6
  2. ...
```

## 规则细节

### 规则 1：MODULE_STATE 是窗口的"出门简历"

任何陌生窗口（包括接管的新 Kiro 会话）打开模块时第一件事：读 MODULE_STATE。

如果 MODULE_STATE 已过时（与目录实际状态不符），归属窗口必须立刻修。

### 规则 2：「已知事实」不容许偏差

§5 的事实必须可追溯到具体文件 / 命令 / 实验。不允许"我觉得是 X"。

每条事实附带 `来源脚本`：
- 实验数字 → 来自哪个脚本输出
- 配置决策 → 来自哪份决策文档
- 测量值 → 来自哪个测量命令

### 规则 3：跨模块依赖必须双向写

如果 Window-A 的产出被 Window-B 依赖：
- A 的 MODULE_STATE §6 写"提供给：Window-B"
- B 的 MODULE_STATE §6 写"依赖于：Window-A"

任何一边没写 = 协议违反。

### 规则 4：风险记录不删除，只追加

§7 是审计轨迹。已经过时的风险也保留（用 ~~删除线~~ 标记）。

### 规则 5：MODULE_STATE 文件命名

为了避免冲突（多个 MODULE_STATE.md 在不同目录），命名约定：
- 简单情况：`MODULE_STATE.md`（目录唯一时）
- 多模块在同一上层目录：`MODULE_STATE_<NAME>.md`，例如 `MODULE_STATE_ML.md`、`MODULE_STATE_PAPER.md`
