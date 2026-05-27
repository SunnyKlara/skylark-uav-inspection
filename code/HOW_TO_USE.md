# 操作手册

> 这个文档是 [`RUN_ME.md`](RUN_ME.md) 的"为什么"补充。
> 只想动手不想看原理的，直接去 RUN_ME。

---

## 一句话流程

1. 双击 `00_一键装环境.bat` → 装好截图发我
2. 按 [`setup/dataset_layout.md`](setup/dataset_layout.md) 准备数据 → 跑 `python data\prepare_pvel_ad.py` → 把统计输出发我
3. 双击 `01_一键跑实验.bat` → 挂机 24–36 小时
4. 把 `paper/` 整个发我 → 进入"写论文"

---

## 全部装到 E 盘

| 路径                          | 用途                          |
|-------------------------------|-------------------------------|
| `E:\Miniconda3\`              | Miniconda 本体（你手动装时选这）  |
| `E:\conda_envs\yolo\`         | 项目的 Python 环境              |
| `E:\pip_cache\`               | pip 包缓存                     |
| `E:\torch_cache\`             | PyTorch 模型 / ultralytics 权重缓存 |
| `E:\hf_cache\`                | HuggingFace 模型缓存            |
| `E:\Users\...\code\data\raw\` | 原始数据集（你放这）             |
| `E:\Users\...\code\runs\`     | 训练输出（自动）                |
| `E:\Users\...\code\paper\`    | 论文图表（自动）                |

C 盘不会被污染。

---

## 5060 Ti 的两个坑（已经预埋自动处理）

### 坑 1：`no kernel image is available for execution on the device`

**原因**：5060 Ti 是 Blackwell（sm_120），需要 PyTorch 2.7.1 + CUDA 12.8 wheel。
旧版 PyTorch（含 cu121 / cu124）的预编译 kernel **没包含 sm_120**，会在第一次 conv2d 调用时炸。

**自动处理**：`00_一键装环境.bat` 钉死 cu128 安装，失败后会回退 nightly cu128。

**手动验证**：
```cmd
python setup\verify_gpu.py
python setup\diagnose_5060ti.py
```
看到 `[OK] sm_120` + `[OK] CUDA kernel 测试通过` 就稳了。

### 坑 2：训练 OOM（显存爆 16G）

**原因**：消融某些配置 + `batch=16` 可能撑爆 16G。

**手动处理**：所有 train 脚本支持 `--batch` 参数：
```cmd
python train\train_ours.py --batch 8        :: 显存还吃紧再试 4
python train\train_ablation.py --batch 8
```

---

## 我（Kiro）那边的诚实交代

仓库里有几个之前文档夸大的部分，下面列出真实状态，别再被旧描述误导：

| 仓库以前说有     | 真实状况                       |
|----------------|-------------------------------|
| `eval_main.py`  | 没有；实际由 `eval_*.py` 三个脚本 + `train_*.py` 写的表格替代 |
| `models/ours_yolo11.py` | 没有；改进通过 yaml 配置（`yolo11n_full.yaml`）实现，由 ultralytics 直接构图 |
| `small_object_head.py` | 没有；P2 小目标头同样用 yaml 加层，不需要单独 .py |
| `data/visualize_samples.py` | 没有；`dataset_stats.py` 已包含可视化 |
| `plot_pr_curve.py` | 没有；ultralytics 训练时自动出 PR 曲线在 `runs/<name>/PR_curve.png` |
| LaTeX 模板 / 章节模板 / `refs.bib` | 没有；跑完实验再做这部分 |
| `fig_pipeline.png` | 没有；这个是论文方法总框图，需要画图工具人工做（建议 draw.io） |

下面这些**真的有**而且能跑：

- 4 个 baseline 训练 + 5 组消融 + 完整 eval 管线
- CBAM / EMA / BiFPN 模块代码（BiFPN 暂未挂入主方法的 yaml）
- 训练曲线 / Grad-CAM / 定性对比 / 鲁棒性曲线 / 复杂度对比 / 部署对比

---

## 卡住了

```
卡在 Step X
报错截图：[贴图]
我尝试了：xxx 或 啥都没动
```

把截图甩过来，给具体修复指令。
