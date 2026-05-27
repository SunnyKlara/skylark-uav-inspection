# 文件归属与冲突避免（Claim）

## 核心原则

**写之前先 claim，不要"先动手再说"。**

## 三步 Claim 流程

### Step 1：判断归属

参见 [windows.md](./windows.md) 的归属表。

简化判断：
- `code/**` → Window-A
- `paper/**` 或 项目根 `*.md` → Window-B
- `platform/backend/**` 或 `edge/**` → Window-C
- `platform/frontend/**` 或 `simulation/**` → Window-D

### Step 2：检查是否有进行中的工作

```bash
bash .kiro/skills/skylark-coordination/scripts/claim-check.sh <文件路径>
```

输出：
```
[claim-check] paper/04_experiments.md
- Owner: Window-B
- Last modified: 2026-05-27 14:55:36 (by Window-A: 2 hours ago)
- Active editor: none detected
- Recent STATE.md mentions: 1 (line 87)
```

### Step 3：如果你不是 Owner

不要改。两个选项：

**选项 1（推荐）：写 handoff 请求**
在 STATE.md §"待办交接"加一行：
```markdown
- [2026-MM-DD HH:MM] Window-X → Window-Y
  事项：[简述需要 Y 做什么]
  文件：[文件路径]
  期望完成时间：[紧急 / 本周 / Q1 内]
```

**选项 2（紧急例外）：越权修复**
仅在归属窗口不可达且事情紧急时使用。
改完立刻在 STATE.md 写"越权修复记录"。

## 常见冲突场景与解决

### 场景 1：Window-A 训完模型，论文要回填数字

错误做法：A 直接去改 paper/04_experiments.md ❌
正确做法：
1. A 把数字写到 `code/runs/v2/<run_name>/metrics.json` 或 `code/runs/collected_metrics.json`
2. A 在 STATE.md 写 handoff：
   ```
   [2026-MM-DD] Window-A → Window-B
   事项：v2 baseline yolo11n 200ep 已训完
   数据：code/runs/v2/baseline/yolo11n/yolo11n_metrics.json
   请求：回填 paper/04_experiments.md 第 4.2 节 baseline 表第 4 行
   ```
3. B 读 STATE → 读 metrics.json → 改 paper md

### 场景 2：Window-B 写论文需要某个图

错误做法：B 自己跑可视化脚本生成图 ❌（脚本属于 A）
正确做法：
1. B 在 STATE.md 写 handoff：
   ```
   [2026-MM-DD] Window-B → Window-A
   事项：需要训练曲线图（v2 协议下 baseline + ours 4 条曲线）
   原因：第 4.2.3 节训练曲线分析
   产出：paper/figures/fig_training_curves_v2.png
   ```
2. A 跑 `code/visualize/plot_results.py`（可能需要扩展支持 v2）
3. A 输出图到 `code/paper/figures/`
4. A 写 handoff back：
   ```
   [2026-MM-DD] Window-A → Window-B
   ✅ fig_training_curves_v2.png 已生成
   位置：code/paper/figures/fig_training_curves_v2.png
   请 B 拷贝到 paper/figures/
   ```
5. B 拷贝（拷贝目标在 paper/ 归属内 ✅）

### 场景 3：Window-C 要改一个 ML 训练参数

错误做法：C 直接改 code/configs/yolo11n_full.yaml ❌
正确做法：
- C 不应该直接改 ML 配置。如果需要，提议给 A：
   ```
   [2026-MM-DD] Window-C → Window-A
   建议：把 yolo11n_full.yaml 的 P2 channel 从 128 改成 96
   理由：在 Jetson 上 INT8 推理时 128 通道 latency 超 33ms
   影响：所有 v2 ours 实验需要重训
   决策：等用户拍板
   ```

## 紧急情况：归属窗口不可达

定义"不可达"：
- 用户已关闭该窗口
- 该窗口长时间无响应（超过当前任务的 SLA）
- 该窗口正在执行无法中断的长任务（如 200 ep 训练）

**步骤**：
1. 先尝试在 STATE.md 留 handoff（也许那边稍后会读）
2. 如果时间紧迫且事情风险低（< 5 行修改、不影响其他模块）：
   - 在 STATE.md 写 "**越权修复**" 记录
   - 改文件
   - 通知用户（写在 STATE 末尾的 "用户决策提请" 段）
3. 如果时间紧迫但事情风险高：**等用户**，不要冒险
