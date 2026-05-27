# 约定（Conventions）

文件命名 / 提交格式 / 注释规则 / 时间戳格式 — 全项目统一。

## 1. 时间戳

**格式**：ISO 8601 不带时区
```
2026-05-27T15:00:00
```

**简化版**（人类可读）：
```
2026-05-27 15:00
```

不允许：
- `5/27/2026`（美式）
- `27 May 2026`（口语）
- 没有日期（"今天"、"刚才"）

## 2. 文件命名

### Markdown 文档

| 类型 | 命名 | 例子 |
|---|---|---|
| 项目根级 | `UPPER_SNAKE.md` | `STATE.md`、`PROJECT_NORTH_STAR.md` |
| 模块级 | `MODULE_STATE.md` 或 `MODULE_STATE_<NAME>.md` | `MODULE_STATE_ML.md` |
| 论文章节 | `<编号>_<内容>.md` | `04_experiments.md` |
| 临时文档 | `_<scope>.md` 前缀下划线 | `_test_notes.md`（不进 git） |

### Python 模块

| 类型 | 命名 |
|---|---|
| 训练脚本 | `train_<scope>.py` |
| 评估脚本 | `eval_<metric>.py` |
| 可视化 | `plot_<what>.py` 或 `make_<what>.py` |
| 后处理 | `<verb>_<noun>.py`（动词在前） |
| 工具脚本 | snake_case |

### YAML 配置

| 类型 | 命名 |
|---|---|
| 模型配置 | `<base>_<改动>.yaml`，例如 `yolo11n_cbam_p3only.yaml` |
| 数据配置 | `data.yaml`（标准） |
| 部署配置 | `deploy_<env>.yaml`，例如 `deploy_jetson.yaml` |

## 3. 文件头部约定

### Python 文件头

```python
"""
<一句话模块功能>
=================================
<2-5 行详细描述>

用法：
  python xxx.py --arg1 val1 ...

输出：
  - <产出文件 1>
  - <产出文件 2>

WINDOW_OWNER: A   # 此文件归属 Window-A
"""
```

### Markdown 文件头

```markdown
# <标题>

> 写于 YYYY-MM-DD by Window-<X>
> 上次更新：YYYY-MM-DD HH:MM by Window-<X>

<内容>
```

### YAML 文件头

```yaml
# <一句话配置说明>
# WINDOW_OWNER: A
nc: 80
...
```

## 4. STATE.md 编辑约定

### 编辑前

1. 读最新版（可能其他窗口刚改过）
2. 找到要改的段落
3. 准备好要写的内容

### 编辑中

- 编辑窗口尽量短（< 30 秒）
- 不要在编辑期间被中断（不要边改边查资料）

### 编辑后

1. 在文件顶部更新"最后更新"行：
   ```markdown
   > 最后更新：YYYY-MM-DD HH:MM by Window-<X>
   ```
2. 在末尾"修改日志"加一行：
   ```markdown
   - YYYY-MM-DD HH:MM Window-<X>: <一句话改了什么>
   ```

### 长内容写到 MODULE_STATE

主 STATE.md 单条目超过 5 行 → 写到 MODULE_STATE，主 STATE 只放摘要。

## 5. 提交信息（如未来用 Git）

格式：
```
<类型>(<窗口>): <摘要>

<详细描述>

WINDOW: <X>
HANDOFF: <如有，关联 STATE.md handoff 编号>
```

类型：
- `train`: 训练相关
- `eval`: 评估相关
- `paper`: 论文写作
- `platform`: 平台开发
- `edge`: 边缘部署
- `sim`: 仿真
- `docs`: 文档
- `chore`: 杂项

例：
```
train(A): v2 baseline yolo11n 200ep 完成

mAP@0.5 = 0.X，与 v1 50ep 对比 +Y pp。
metrics 写入 code/runs/v2/baseline/yolo11n/。

WINDOW: A
HANDOFF: STATE.md "Handoff #3"
```

## 6. 数字与精度

### 实验数字

| 指标 | 精度 |
|---|---|
| mAP@0.5 / mAP@0.5:0.95 | 4 位小数（例：0.7518） |
| Precision / Recall | 4 位小数 |
| FPS | 1 位小数（例：142.3） |
| Latency (ms) | 2 位小数（例：7.04） |
| Params (M) | 2 位小数（例：2.62） |
| GFLOPs | 2 位小数（例：6.48） |
| 训练时间 (h) | 2 位小数（例：6.05） |

### 百分比

带"%"或"pp（百分点）"明确含义。
```
mAP@0.5 提升 5.2 个百分点 (pp)
不写：mAP@0.5 提升 5.2%（歧义：是 abs 还是 rel？）
```

### 比例

| 形式 | 适用 |
|---|---|
| `1158×` | 长尾比例（最大类与最小类） |
| `2:1` | 简单比例（含缺陷:无缺陷） |
| `47.1%` | 占比（小数 1 位即可） |

## 7. 不允许的措辞

❌ "应该可以..."（不确定的承诺）
❌ "估计 / 大约 / 可能"（除非有数据支撑）
❌ "完美 / 最优 / 最先进"（绝对化形容词）
❌ "超过 SOTA"（除非真的复现且对比过）
❌ "约 7000+ 倍"（不精确数字）

✅ "实测 X"、"基于 Y 计算 Z"、"在 N 个样本上测得"

## 8. 文件大小约束

| 类型 | 软上限 | 处理 |
|---|---|---|
| Python 单文件 | 500 行 | 拆分到子模块 |
| Markdown 单文件 | 1000 行 | 拆分到子文件 |
| LaTeX tex | 2000 行 | 用 \input 拆分 |
| YAML 配置 | 100 行 | 拆分或简化 |

## 9. 编码

所有文本文件 UTF-8（不含 BOM）。
LaTeX 中文用 ctex + xelatex，不用 pdflatex。
