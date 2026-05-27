# GPU 资源仲裁（GPU Arbiter）

## 为什么需要这个

Skylark 在单 GPU（RTX 5060 Ti 16GB）环境下做 ML 训练。

**特殊约束**：
- 业界多 agent 协调框架（CCPM/MACP/Anthropic Worktree）都假设无限算力
- Skylark 单 GPU + 长训练（200 epoch ≈ 15 小时）+ 多窗口 → **必须仲裁**

## Lock 文件

路径：`code/runs/.gpu_lock.json`

Schema：
```json
{
  "owner": "Window-A",
  "task": "v2 baseline yolo11n 200ep",
  "started_at": "2026-05-27T15:00:00",
  "estimated_end": "2026-05-27T19:00:00",
  "pid": 12345,
  "can_be_preempted": false,
  "released_at": null,
  "history": [
    {
      "owner": "Window-A",
      "task": "v1 daemon ablation",
      "started_at": "2026-05-26T23:35:43",
      "released_at": "2026-05-27T22:00:00",
      "duration_hours": 22.4
    }
  ]
}
```

字段说明：
- `owner`：当前持有者（Window-A/B/C/D 之一）
- `task`：人类可读的任务描述
- `started_at`：claim 时间
- `estimated_end`：预计释放时间（不是硬上限）
- `pid`：进程号，用于检测 stale lock
- `can_be_preempted`：是否允许被高优任务抢占
- `released_at`：实际释放时间。**null = lock 未释放**
- `history`：历史 claim 记录（用于 review GPU 利用率）

## 标准操作

### Claim（占用）

```bash
python code/postprocess/gpu_arbiter.py claim \
    --owner Window-A \
    --task "v2 baseline yolo11n 200ep" \
    --estimated-hours 15
```

行为：
1. 读取当前 `.gpu_lock.json`
2. 如果 `released_at == null`：报错退出（已被占用）
3. 如果 `released_at != null` 或文件不存在：写新 lock
4. 在 history 追加上一次的释放记录

### Release（释放）

```bash
python code/postprocess/gpu_arbiter.py release
```

行为：
1. 读 lock，把 `released_at` 设为当前时间
2. 把当前 owner / task / started_at / released_at 移到 history
3. 主字段全部清空（next claimer 用）

### Status（查看）

```bash
python code/postprocess/gpu_arbiter.py status
```

输出：
```
=== GPU Lock Status ===
Owner:        Window-A
Task:         v2 baseline yolo11n 200ep
Started:      2026-05-27 15:00:00 (3h 45m ago)
Est. release: 2026-05-27 19:00:00 (in 11h 15m)
PID:          12345 (alive: yes)
Status:       ACTIVE

GPU usage:    72% / 8.4 GB / 14.2 GB
```

### Force-clear（强制清理过期 lock）

```bash
python code/postprocess/gpu_arbiter.py force-clear --reason "PID 12345 dead since 2h"
```

行为：
1. 检查当前 owner 的 PID 是否还活着
2. 如果死了：清空 lock，在 history 追加"force-cleared by Window-X with reason"
3. 在 STATE.md 写一条 incident report

## 协议规则

### 规则 1：Window-A 的默认优先权

- Window-A 是 ML 主线，长时间训练任务的天然 owner
- 其他窗口需要 GPU 时**默认必须等**
- 但 A 不能 24/7 锁住——每个训练完成必须 release

### 规则 2：协商场景

**场景**：Window-C 要在 5060 Ti 上做 ONNX/TRT INT8 benchmark（约 30 分钟），但 A 在跑 200 ep 训练。

**协议**：
1. C 在 STATE.md §"GPU 借用请求"写：
   ```
   [2026-MM-DD HH:MM] Window-C 请求借用 GPU
   任务：INT8 benchmark on ours best.pt
   预计耗时：30 分钟
   紧急度：本周
   建议时机：A 完成下一个训练任务后的间隙
   ```
2. A 在下一个训练间隙看到请求 → 不立刻 claim 下一个 → 让出 30 分钟
3. C claim → 30 分钟跑完 → release
4. A 继续

### 规则 3：Stale Lock 处理

**定义 stale**：lock 主字段不空，但 `pid` 对应进程已死（用 `tasklist /fi "pid eq XXX"` 检测）。

**处理**：
- 任何窗口都可以 `force-clear`
- 必须在 STATE.md 写 incident
- 如果 stale 连续发生 ≥ 2 次，主张更新 train_v2.py 的 finally 块

### 规则 4：不允许的操作

❌ 多个进程同时占 GPU（即使 lock 文件被绕过）
❌ 训练脚本不主动 release lock（必须有 finally）
❌ 训练脚本崩溃后不清理 lock（依赖 force-clear 救场）

## 集成到训练脚本

`code/train/train_v2.py` 应包含：

```python
import sys
from pathlib import Path

# 路径硬编码：脚本相对项目根
ARBITER = Path(__file__).resolve().parent.parent / "postprocess" / "gpu_arbiter.py"

import subprocess
import os
import atexit

def claim_gpu(task_desc: str, est_hours: float = 1.0):
    rc = subprocess.run([
        sys.executable, str(ARBITER), "claim",
        "--owner", "Window-A",
        "--task", task_desc,
        "--estimated-hours", str(est_hours),
    ])
    if rc.returncode != 0:
        raise RuntimeError("GPU lock 获取失败 — 检查是否已被占用")

def release_gpu():
    subprocess.run([sys.executable, str(ARBITER), "release"])

# 在 main() 入口
def main():
    args = parse_args()
    claim_gpu(f"{args.group}/{args.name} {args.epochs}ep", est_hours=args.epochs * 4.5 / 60)
    atexit.register(release_gpu)  # 任何退出方式都释放
    
    # ... 训练代码 ...
```

## 一年期内的演进

| 时机 | 演进 |
|---|---|
| 现在（M1） | Lock 仅 Window-A 用（C/D 还没开） |
| Q2（M5 Jetson 接入） | Jetson GPU 不冲突 5060 Ti，但 5060 Ti 上的 benchmark 进入 Lock 队列 |
| Q3（仿真上线） | AirSim 占 GPU 渲染，但用 iGPU 不影响 NV 卡（如有） |
| Q4 | 评估是否升级到 Redis-based lock（如果出现真并行需求） |
