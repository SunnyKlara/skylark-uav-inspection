# 跨窗口交接（Handoff）

## Handoff 是什么

一个窗口完成阶段性产出后，把"接下来该谁做什么"显式传递给另一个窗口。

**核心**：交接必须落到 STATE.md，口头不算。

## Handoff 标准格式

在 STATE.md §"待办交接（pending handoffs）"加条目：

```markdown
- [YYYY-MM-DD HH:MM] Window-X → Window-Y
  事项：[一句话描述]
  上下文：[相关文件 / 数据位置 / 依赖]
  期望产出：[具体的输出文件或决策]
  紧急度：[紧急 / 本周 / Q1 内 / 长期]
  发起人备注：[可选 — 给接收方的提示]
```

接收方完成后**不删除**，改成：

```markdown
- [YYYY-MM-DD HH:MM] Window-X → Window-Y
  ...（原内容保留）
  ✅ YYYY-MM-DD HH:MM 已完成 by Window-Y
  实际产出：[实际产出文件]
  备注：[可选 — 完成情况说明]
```

完成的 handoff 保留在 STATE 里作为审计轨迹。每月归档一次到 `docs/handoff_archive/`。

## 双向 Handoff 模板

### 单向交接（最常见）

A 给 B 提供数据，B 用数据写论文：

```markdown
- [2026-06-01 10:30] Window-A → Window-B
  事项：v2 baseline yolo11n 200ep 训完
  上下文：
    - metrics: code/runs/v2/baseline/yolo11n/yolo11n_metrics.json
    - 训练曲线: code/runs/v2/baseline/yolo11n/results.csv
    - 权重: code/runs/v2/baseline/yolo11n/weights/best.pt
  期望产出：
    - paper/04_experiments.md 第 4.2 节 baseline 表第 4 行更新
    - paper/00_meta.md 中文 / 英文摘要 mAP 数字更新
  紧急度：本周
  备注：注意这是单 seed 数据，未来还会跑 seed 142 / 242 取均值
```

### 双向交接（请求 + 反馈）

B 写论文时发现需要新图，请求 A 生成：

```markdown
- [2026-06-05 14:00] Window-B → Window-A
  事项：需要 per-class AP 柱状图
  上下文：
    - 第 4.3 节消融实验需要展示 finger / black_core / crack 三类 AP 变化
    - 现有 visualize/plot_results.py 不支持 per-class 拆分
  期望产出：
    - 新脚本 code/visualize/plot_per_class_ap.py
    - 输出图 code/paper/figures/fig_per_class_ap.png
  紧急度：本周（论文 4.3 节正在写）

- [2026-06-05 18:00] Window-A → Window-B
  ✅ 上面 handoff 已完成 by Window-A
  实际产出：
    - code/visualize/plot_per_class_ap.py
    - code/paper/figures/fig_per_class_ap.png（共 5 行 = 5 ablation 配置）
  备注：图横轴是类别（按训练框数排序），纵轴是 AP@0.5
       5 条线分别为 A0/A1/A2/A3/A4
       请 B 拷贝到 paper/figures/ 并在 4.3 节引用
```

## Handoff 优先级队列

STATE.md 末尾保留一个"按紧急度排序的 handoff 列表"：

```markdown
### 紧急 Handoffs（< 24h 内必须处理）
（无）

### 本周 Handoffs
1. [2026-06-01] A → B: v2 baseline 数字回填论文 4.2 节
2. [2026-06-03] B → A: 需要 per-class AP 图

### Q1 内 Handoffs
1. [2026-05-27] A → B: 5 处理论硬伤已修，B 校对一遍

### 长期 Handoffs
1. [2026-05-27] A → C: Q2 时需要把 ours best.pt 导出 ONNX
```

## 常见 Handoff 场景速查

### Window-A → Window-B

| 场景 | 触发条件 |
|---|---|
| 训完一个模型 | 写 metrics.json 后 |
| 跑完一组 eval | complexity / robustness / deployment 任一脚本完成 |
| 出了一组图 | plot_results / grad_cam / make_qualitative 任一完成 |
| 实验中发现意外事实 | 例如"ablation A2 EMA 比 A1 CBAM 更好"——这影响论文叙事 |
| 训练失败 | failure mode 也是论文写作的素材（局限性章节） |

### Window-B → Window-A

| 场景 | 触发条件 |
|---|---|
| 写论文发现需要新实验 | 例如审稿意见反馈"应补充 v2 协议下 ours 与文献 SOTA 对比" |
| 写论文发现需要新图表 | 现有图无法支撑某个论点 |
| 写论文发现现有数据有误 | 例如校对时发现 metrics.json 字段写错 |

### Window-C → Window-A（Q2 起）

| 场景 | 触发条件 |
|---|---|
| INT8 量化精度回退超阈值 | 需要 A 重训或调超参 |
| 模型在 Jetson 上 OOM | 需要 A 减小输入或通道 |
| 部署后某层数值不稳 | 需要 A 在训练时加约束 |

### Window-D → Window-C（Q3 起）

| 场景 | 触发条件 |
|---|---|
| 前端需要新的后端 API | 例如"任务进度推送" |
| 仿真 / 飞控集成需要后端配合 | 例如 Gazebo 或真机抓帧后调用推理 API（Window-E ↔ Window-C） |

## 注意事项

**1. 不要嵌套 Handoff**
错误：A → B → C → A（环形）
正确：把每一步都写成独立 handoff，每个有自己的完成标记

**2. 不要 Handoff 不属于自己的事**
错误：A 替 B 决定"论文该怎么写第 4 章" ❌
正确：A 提供数据 + 提示，B 自己写

**3. Handoff 完成后必须有产出文件**
不能只是"我写了一段话给 B" → 必须落到具体文件
