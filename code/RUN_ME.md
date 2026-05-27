# 🚀 RUN ME —— 操作手册（5060 Ti / Blackwell 适配）

> 第一次跑：从头到尾按顺序走。
> 想跑某一步：直接跳到对应章节。

---

## 前置条件（自检）

| 项目             | 怎么验证                          | 期望              |
|-----------------|----------------------------------|-------------------|
| NVIDIA 驱动     | `nvidia-smi`                     | 看到 5060 Ti，驱动 ≥ 570 |
| E 盘空间        | 资源管理器看 E 盘                 | 剩余 ≥ 40 GB       |
| Miniconda       | 在 cmd 跑 `conda --version`      | 有版本号即可       |

如果没装 Miniconda：

1. 下载：https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
2. 安装时点 **Customize Install**
3. 路径选 **`E:\Miniconda3`**
4. 勾 **Add Miniconda3 to my PATH**
5. 装完**重启电脑**

---

## 🔧 Step 1：装环境（一次性，20–40 分钟）

打开 **Anaconda Prompt**（开始菜单搜），cd 到项目：

```cmd
cd E:\Users\Administrator\Desktop\gp\graduation_project\code
00_一键装环境.bat
```

或者更省事：在文件资源管理器里**双击** `00_一键装环境.bat`。

脚本自动做的事：

1. 检查驱动 + nvidia-smi
2. 创建 conda 环境 `E:\conda_envs\yolo`（Python 3.11）
3. 缓存全部钉到 E 盘（`E:\pip_cache`、`E:\torch_cache`、`E:\hf_cache`）
4. 装 **PyTorch 2.7.1 + CUDA 12.8（cu128 wheel）**
   —— 这是 5060 Ti 唯一稳定能跑的组合
5. 装 ultralytics + 所有依赖
6. 跑 `verify_gpu.py`（实跑卷积，不是空 import）
7. 跑 `diagnose_5060ti.py`（5 项兼容性体检）
8. 生成 `_activate.bat` 给后续脚本用

**期望最后看到**（关键行）：

```
[OK] Python 版本：3.11.x
[OK] PyTorch 版本：2.7.1+cu128
[OK] GPU 名称：NVIDIA GeForce RTX 5060 Ti
[OK] Compute Capability：sm_120
[OK] CUDA kernel 测试通过
[OK] 半精度 (FP16 / AMP) 测试通过
==> 环境就绪，可以开始训练
```

如果有 `[!!]` 标记，**截图发我**，我给你修复指令。

> 日后激活环境：`conda activate E:\conda_envs\yolo` 或者跑 `_activate.bat`

---

## 🗂️ Step 2：下数据集（10–60 分钟，看渠道）

**详细放置规范 + 真实下载渠道**：[`setup/dataset_layout.md`](setup/dataset_layout.md)

**快速版**：

1. 拿到 PVEL-AD 数据（4 条渠道任选，**Kaggle 没有公开数据集页**，常见 `qianbinghui/pvel-ad` 是错的）：
   - **Google Drive**（首选，需梯子）：[drive.google.com/drive/folders/1AMlo433v-torspIxynzx0wXGced8Eo3q](https://drive.google.com/drive/folders/1AMlo433v-torspIxynzx0wXGced8Eo3q)
   - **邮件申请**：仓库 [github.com/binyisu/PVEL-AD](https://github.com/binyisu/PVEL-AD)，下表填好寄给作者，2 周内回
   - **Kaggle 比赛**：[kaggle.com/competitions/pvelad](https://www.kaggle.com/competitions/pvelad)（注册比赛后才能下）
   - **Roboflow 备选**：[universe.roboflow.com](https://universe.roboflow.com/) 搜 photovoltaic defect

2. 把数据放到这里（任选其一，脚本都吃）：
   - 整个解压目录 → `code\data\raw\pvel_ad\`（里面有 .xml 和 .jpg）
   - 官方 zip 改名 → `code\data\raw\pvel_ad.zip`

3. 在 Anaconda Prompt（已激活 yolo 环境）里跑：

```cmd
python data\prepare_pvel_ad.py --dry-run
```

先确认数据找到了 + 格式正确，再去掉 `--dry-run` 正式跑。

脚本会自动：
- VOC（xml）→ YOLO 转换（**这一步是真转，不是占位**）
- 8 : 1 : 1 划分 train / val / test
- 写 `configs/pv_baseline.yaml`
- 输出每个 split 的图像数 / 标注框数

**完成后会看到**（数字以你拿到的子集为准）：

```
==> 数据集统计
  train: ~28000 images, ~32000 boxes
  val:   ~3500 images,  ~4000 boxes
  test:  ~3500 images,  ~4000 boxes
```

把这段输出发我。

---

## 🎯 Step 3：跑 4 个 baseline（6–10 小时，挂机过夜）

```cmd
python train\train_baseline.py
```

或者直接双击 `01_一键跑实验.bat`，它会从 Step 2 串到 Step 6。

按顺序训：
1. YOLOv8n
2. YOLOv10n
3. YOLOv11n
4. RT-DETR-l

每个 100 epochs。**挂机过夜**，早上起来 4 组结果。

**完成后**：

```
runs/baseline/
├── yolov8n/weights/best.pt
├── yolov10n/weights/best.pt
├── yolo11n/weights/best.pt
└── rtdetr/weights/best.pt

paper/tables/baseline_table.md   ← 论文 Table 1
```

把 `baseline_table.md` 内容发我。

---

## 🔬 Step 4：训我们的方法（3–4 小时）

```cmd
python train\train_ours.py
```

训最终方法 = **YOLOv11n + CBAM + P2 小目标头**（配置 `configs/yolo11n_full.yaml`）。

完成后产出 `runs/ours/yolo11n_full/weights/best.pt` + `paper/tables/main_comparison.md`。

> 注：BiFPN 模块代码已实现（`models/modules/bifpn.py`），但当前 `yolo11n_full.yaml` 没用它。论文里就按"CBAM + P2"两件套写，BiFPN 留作后续可选实验。

---

## 🧪 Step 5：消融实验（6–10 小时，挂机）

```cmd
python train\train_ablation.py
```

跑 5 组：

| Config              | 改动                |
|---------------------|---------------------|
| `yolo11n`           | Baseline            |
| `yolo11n_cbam`      | + CBAM              |
| `yolo11n_ema`       | + EMA               |
| `yolo11n_p2`        | + P2 head           |
| `yolo11n_full`      | + CBAM + P2 (Ours)  |

完成后写 `paper/tables/ablation_table.md`，论文 5.3 节直接搬。

赶时间可以 `python train\train_ablation.py --epochs 50` 减半。

---

## 📊 Step 6：评估 + 出图（30–90 分钟）

```cmd
python eval\eval_complexity.py        # Params / FLOPs / FPS / 模型大小
python eval\eval_robustness.py        # 6 种扰动 × 3 强度 的退化曲线
python eval\eval_deployment.py        # PyTorch FP32 / FP16 / ONNX 对比

python data\dataset_stats.py          # 数据集类别 + 框尺寸图

python visualize\plot_results.py      # 训练曲线
python visualize\grad_cam.py          # 注意力可视化
python visualize\make_qualitative.py  # 检测结果对比图
```

或者直接双击 `03_只跑评估.bat`。

**产物**（位于 `paper/`）：

```
paper/tables/
├── baseline_table.md
├── main_comparison.md
├── ablation_table.md
├── complexity_table.md
├── robustness_table.md
├── deployment_table.md
└── dataset_stats.md

paper/figures/
├── fig_dataset_dist.png       数据集类别分布
├── fig_box_size.png           标注框尺寸分布
├── fig_training_curves.png    训练曲线
├── fig_robustness.png         鲁棒性曲线
├── fig_grad_cam.png           Grad-CAM 注意力对比
└── fig_qualitative.png        检测结果对比
```

把这两个目录打包发我，进入"写论文"阶段。

---

## 🔍 随时检查进度

```cmd
python setup\check_progress.py
```

或者双击 `02_检查进度.bat`，列出每一步是否完成。

---

## 🆘 卡住了？

```
卡在 Step X
命令：xxx
报错截图：[贴图]
我尝试了：xxx 或 什么都没改
```

把截图甩给我，我给具体修复指令。

---

## 📋 跑完 Step 6 后还要做的事（论文那部分）

仓库**没有**预置 LaTeX / Word 模板。这块到 Step 6 跑完之后我们再细聊：
是用学校官方 LaTeX 模板，还是 Word 老老实实写。我不会再编不存在的模板路径。

---

## 📈 当前进度

```
Step 1  [ ]  装环境
Step 2  [ ]  下数据集
Step 3  [ ]  跑 4 baseline
Step 4  [ ]  训我们的方法
Step 5  [ ]  消融实验
Step 6  [ ]  评估 + 出图
Step 7  [ ]  写论文
```
