# 接管交接：daemon 跑完后该怎么做

> 给"睡醒回来 / 忙完回来"的你看的。
> Kiro 已经把"daemon 跑完后要做的事"全部代码化，你只需要跑一个 bat。

---

## 0. 先看 daemon 跑完了没

```cmd
schtasks /query /tn "GP_Pipeline_Daemon"
```

- 显示"正在运行"：还在跑，先去看看进度
- 显示"就绪"或"未运行"：跑完了，可以收尾

```powershell
# 看一眼现在在哪一步、当前 epoch
Get-Content E:\Users\Administrator\Desktop\gp\graduation_project\code\runs\daemon.log -Tail 30
Get-Content E:\Users\Administrator\Desktop\gp\graduation_project\code\runs\current.log -Tail 5
```

---

## 1. 跑完后怎么收尾（就一条命令）

```cmd
cd E:\Users\Administrator\Desktop\gp\graduation_project\code
05_最终交付.bat
```

或者直接：

```cmd
E:\conda_envs\yolo\python.exe E:\Users\Administrator\Desktop\gp\graduation_project\code\postprocess\finalize_all.py
```

会**按顺序**跑这 5 步（每步独立 try/except，某步失败不阻塞后续）：

| 步 | 脚本 | 干什么 |
|---|---|---|
| 1 | `collect_metrics.py` | 扫所有 metrics.json + results.csv，汇总到 `runs/collected_metrics.json` |
| 2 | `fill_paper.py` | 回填 LaTeX `\TBF{...}` 宏 + Markdown `[待填]` |
| 3 | `copy_figures.py` | `code/paper/figures/*` → `paper/{tex/,}figures/` |
| 4 | `build_pdfs.py` | xelatex 中文 + pdflatex 英文 PDF（× 2 编译跑 cite） |
| 5 | `prepare_defense.py` | 答辩 PPT 大纲 + 20 问答 |

总耗时约 1–2 分钟（不训练，纯 IO + LaTeX 编译）。

---

## 2. 产出在哪

```
graduation_project/
├── code/runs/
│   ├── collected_metrics.json     # 所有数字一份汇总
│   ├── fill_report.md             # 哪些被填、哪些缺数据
│   └── finalize_status.md         # 5 步状态
├── paper/
│   ├── tex/main.pdf               # 英文 IEEE TII 风格 PDF
│   ├── tex/main_zh.pdf            # 中文版 PDF
│   ├── 04_experiments.md          # 实验章节（数字已填）
│   ├── 00_meta.md                 # 摘要（数字已填）
│   └── defense/
│       ├── 答辩PPT大纲.md          # 12 页 PPT 大纲 + 讲稿
│       └── 常见问题与回答.md        # 20 个 Q&A
└── FINALIZE_README.md              # 你正在看的这份
```

---

## 3. ⚠️ 一个必须告诉你的事实

我看了一下 ours 的 80 epoch 训练结果：

| 指标 | YOLOv11n baseline (50ep) | ours (80ep) | 差值 |
|---|---|---|---|
| mAP@0.5 | **0.7518** | **0.5747** | **−17.7 pp** |
| mAP@0.5:0.95 | 0.4923 | 0.3970 | −9.5 pp |
| Precision | 0.7334 | 0.6147 | −11.9 pp |
| Recall | 0.7099 | 0.4515 | −25.8 pp |

**ours 比 baseline 低**。这件事 STATE.md 里其实已经预警过——CBAM+P2 改了网络结构，预训练权重迁移率只有 89/602，80 epoch 还没收敛到 baseline 水平。

这不是 fill_paper 的问题，是**训练事实**。我把数字诚实回填进了论文，回填报告里能看到现在论文写的就是 ours = 0.5747。

### 你回来后有 3 个选择

#### 选择 A：诚实展示，调整论文叙事（推荐）

把"本文方法 mAP 提升 X pp"改成"对各改进组件做了完整消融，揭示了在受限算力预算下的设计取舍"。卖点变成"工程严谨性 + 系统消融分析"，弱化"绝对 mAP 数字"。

我已经在 `paper/defense/答辩PPT大纲.md` 第 8 页和 `常见问题与回答.md` Q11 里给了这个备用叙事。直接用就行。

#### 选择 B：续训到 200 epoch

把 ours 从 80 epoch 续训到 200 epoch（约再花 20 小时）。直接：

```cmd
E:\conda_envs\yolo\python.exe E:\Users\Administrator\Desktop\gp\graduation_project\code\train\train_ours.py --epochs 200
```

需要先看 `code/runs/ours/yolo11n_full/results.csv` 的 mAP 曲线判断有没有继续上升空间。如果 80 epoch 已经平台了，续训意义不大。

#### 选择 C：换基线策略

ours 的网络结构没问题，但预训练权重浪费严重。可以试：

1. 不挂预训练，从头训（让所有层都从随机起步公平比较）
2. 或者只在 backbone 用预训练（CBAM 后的 head 重训）

这条路风险最大，时间 + 不确定性双叠加，**只在 A 走不通时考虑**。

---

## 4. 答辩前你还得自己做的事

`finalize_all.py` 跑完后还有一些"机器搞不定"的事：

| 项 | 说明 | 估时 |
|---|---|---|
| 把 `paper/defense/答辩PPT大纲.md` 转成真 PPT | Marp / Slidev / 手动复制到 PowerPoint 都行 | 1–2h |
| 看一遍 `常见问题与回答.md` 并背熟 5 个最可能被问的 | Q1, Q2, Q11, Q14, Q20 是高危题 | 30min |
| 把 `paper/tex/main.tex` 第 31 行作者信息改成你自己的名字/学校 | 否则投稿会被拒 | 2min |
| 检查 `paper/tex/figures/` 里图齐不齐、清晰不清晰 | 占位 PNG 大小 < 30 KB，真图通常 > 200 KB | 5min |
| 把 PDF 试印一下看格式有没有炸 | IEEE TII 单栏 11pt 草稿 → 投稿前切双栏 10pt | 5min |

---

## 5. 排错速查

### 跑完 finalize 后某步显示 `✗`

1. 看 `runs/finalize_status.md` 哪一步失败
2. 直接跑那一步看 traceback：
   ```cmd
   E:\conda_envs\yolo\python.exe E:\Users\Administrator\Desktop\gp\graduation_project\code\postprocess\<那个脚本>.py
   ```
3. 95% 的失败是"上游脚本没产物"——例如 daemon 还没跑完 viz 阶段，`fig_robustness.png` 不存在；这种情况 fill_report 会标记 [待填]，PDF 里红色显示 [TBF: ...]，跑完后 viz 再做一次 finalize 就好

### LaTeX 编译失败

- `IEEEtran.cls not found` → 已修，是 `build_pdfs.py` 里 PATH 注入逻辑，跑 `pip` 之类的环境别动 `E:\Program Files\texlive\2024\bin\windows`
- 中文乱码 → 必须用 xelatex 编译，不是 pdflatex；`build_pdfs.py` 已经分别用了

### 数据看起来不对

```cmd
E:\conda_envs\yolo\python.exe E:\Users\Administrator\Desktop\gp\graduation_project\code\postprocess\collect_metrics.py --print
```

会把 `runs/collected_metrics.json` 整个 dump 到屏幕，肉眼检查。

---

## 6. 文件级别"我做了什么"清单

我**新建**的（可以删，不影响 daemon）：

```
code/postprocess/
├── __init__.py
├── collect_metrics.py
├── fill_paper.py
├── copy_figures.py
├── build_pdfs.py
├── prepare_defense.py
└── finalize_all.py
code/05_最终交付.bat
graduation_project/FINALIZE_README.md (本文件)
```

我**改过一次**的（已恢复 / 验证正常）：

```
paper/tex/main.tex     # 宏定义已修复，dryrun 不再多 }
paper/tex/main_zh.tex  # 同上
```

我**没动**的（按 STATE.md 红线）：

- ❌ `GP_Pipeline_Daemon` 计划任务（在跑）
- ❌ `code/runs/baseline/` 的 3 个真实 baseline 结果
- ❌ `code/data/processed/pvel_yolo/`（数据集）
- ❌ `code/configs/*.yaml`（消融在跑，改了会让消融对比无效）
- ❌ `code/models/register_modules.py`

---

## 7. 时间线推演（基于 daemon 当前进度）

> 截至 2026-05-27 10:30 的事实：
> - ours 已训完（用时 6h，比预估快）
> - ablation 在跑，已到 75/80 epoch（A0 yolo11n）
> - 后续还有 4 组 ablation × 80ep，约 16 小时
> - 然后 dataset_stats / eval × 3 / viz × 3，约 1 小时

**daemon 全部跑完预计：今晚 22:00 前后**（不是 STATE 里说的 48 小时，跑得比预估快）。

跑完后：
1. 你回来执行 `05_最终交付.bat` —— 1 分钟
2. 你看 `FINALIZE_README.md` 第 3 节（关于 ours mAP < baseline 的事实）—— 5 分钟
3. 走选择 A 调叙事 + 整 PPT —— 2-3 小时
4. 答辩前过一遍 Q&A —— 30 分钟

**总投入：3-4 小时**。
