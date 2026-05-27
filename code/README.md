# 毕设代码仓库

> YOLOv11 改进 + 光伏缺陷检测，按 [`RUN_ME.md`](RUN_ME.md) 走即可。
> 5060 Ti（Blackwell sm_120）适配版，全部装到 E 盘。

---

## 📂 目录结构（实际存在的）

```
code/
├── RUN_ME.md                     ← 第一份要看的，按它走
├── HOW_TO_USE.md                 ← 老版操作手册（与 RUN_ME 内容重叠，可忽略）
├── requirements.txt              ← Python 依赖（torch 由装环境脚本单独装 cu128）
│
├── 00_一键装环境.bat              ← 双击装环境（PyTorch 2.7.1 + cu128）
├── 01_一键跑实验.bat              ← 双击从数据准备跑到出图
├── 02_检查进度.bat                ← 看哪些步骤已完成
├── 03_只跑评估.bat                ← 已训完后只重跑 eval / visualize
│
├── setup/
│   ├── verify_gpu.py             ← 实跑卷积验证 GPU
│   ├── diagnose_5060ti.py        ← 5060 Ti 兼容性诊断
│   ├── check_progress.py         ← 进度扫描
│   └── dataset_layout.md         ← 数据集放哪 / 真实下载渠道
│
├── data/
│   ├── prepare_pvel_ad.py        ← PVEL-AD VOC→YOLO 转换 + 划分
│   ├── prepare_roboflow.py       ← Roboflow 备选数据准备
│   └── dataset_stats.py          ← 数据集统计 + 论文图（4.1 节）
│
├── configs/
│   ├── yolo11n_cbam.yaml         ← + CBAM
│   ├── yolo11n_ema.yaml          ← + EMA
│   ├── yolo11n_p2.yaml           ← + P2 小目标检测头
│   └── yolo11n_full.yaml         ← CBAM + P2（最终方法）
│
├── models/
│   ├── register_modules.py       ← 把自定义模块注入 ultralytics
│   └── modules/
│       ├── cbam.py               ← CBAM 注意力
│       ├── ema.py                ← EMA 注意力
│       └── bifpn.py              ← BiFPN（已实现，当前 yaml 未启用）
│
├── train/
│   ├── train_baseline.py         ← 4 个 baseline（YOLOv8/10/11n + RT-DETR-l）
│   ├── train_ours.py             ← 训最终方法
│   └── train_ablation.py         ← 5 组消融
│
├── eval/
│   ├── eval_complexity.py        ← Params / FLOPs / FPS / 模型大小
│   ├── eval_robustness.py        ← 6 种扰动 × 3 强度
│   └── eval_deployment.py        ← PyTorch FP32/FP16 + ONNX
│
├── visualize/
│   ├── plot_results.py           ← 训练曲线
│   ├── grad_cam.py               ← Grad-CAM 注意力图
│   └── make_qualitative.py       ← 检测结果对比图
│
├── paper/                        ← 由评估脚本自动填
│   ├── tables/
│   └── figures/
│
└── runs/                         ← 训练输出（gitignore）
```

> 注意：真实仓库里**没有** LaTeX 模板、章节模板、`refs.bib`、`fig_pipeline.png`、`fig_pr_curves.png`、`eval_main.py` 这些。如果以前看到过类似清单，那是夸大。论文写作模板按需现做。

---

## ⏱ 操作流程（详见 RUN_ME.md）

```cmd
:: 1. 装环境（一次性，20-40 分钟）
00_一键装环境.bat

:: 2. 准备数据（看 setup\dataset_layout.md 拿真实下载渠道）
python data\prepare_pvel_ad.py

:: 3-6. 一键跑全套实验（24-36 小时，挂机过夜）
01_一键跑实验.bat

:: 随时看进度
02_检查进度.bat
```

---

## ⚠️ 5060 Ti 必读

- 必须 **PyTorch 2.7.1 + CUDA 12.8 (cu128)**，cu121 / cu124 跑训练会炸 `no kernel image`
- 装环境脚本已经钉死正确版本
- 如果碰到这个报错，直接跑 `python setup\diagnose_5060ti.py` 看哪一步坏了

---

## 已知未实现 / 留作后续

| 项目                | 状态        | 说明                                  |
|---------------------|------------|--------------------------------------|
| BiFPN 在最终方法中启用 | 模块已写，yaml 未用 | 当前 `yolo11n_full.yaml` 用 CBAM+P2，BiFPN 是可选消融拓展 |
| 完整 LaTeX 模板      | 没有        | 跑完实验再决定模板路线                  |
| PR 曲线脚本          | 没有        | ultralytics 训练时已自动出，需要再单独写 |
