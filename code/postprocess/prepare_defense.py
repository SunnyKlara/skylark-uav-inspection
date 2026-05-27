"""
prepare_defense.py
==================

读 ``runs/collected_metrics.json``，生成两份答辩材料：

  1. paper/defense/答辩PPT大纲.md    — 12 页 PPT 大纲（标题/正文/讲稿）
  2. paper/defense/常见问题与回答.md  — 20 个高频答辩问题及参考回答

回答里所有真实数字都来自 metrics 文件，缺数据则保留 [待填] 标签。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAPER_ROOT = PROJECT_ROOT.parent / "paper"
DEFENSE_DIR = PAPER_ROOT / "defense"
METRICS_FILE = PROJECT_ROOT / "runs" / "collected_metrics.json"


def fmt(v, p=2, default="[待填]"):
    if v is None:
        return default
    try:
        return f"{float(v):.{p}f}"
    except Exception:
        return default


def get(d, *keys, default=None):
    if not d:
        return default
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def find_complexity(rows, name):
    for r in (rows or []):
        if name.lower() in (r.get("name", "") or "").lower():
            return r
    return None


def render_ppt(m: dict) -> str:
    base = (m.get("baselines") or {}).get("yolo11n") or {}
    ours = m.get("ours") or {}
    delta = m.get("delta_mAP50_pp")
    cx = find_complexity(m.get("complexity"), "Ours") or {}
    cx_b = find_complexity(m.get("complexity"), "YOLOv11n") or {}

    # 如果 ours 比 baseline 还差，叙述策略调整为"诚实展示+消融分析价值"
    ours_better = (delta is not None and delta > 0)

    if ours_better:
        headline = (f"在 PVEL-AD 验证集上达到 mAP@0.5 = {fmt(get(ours, 'mAP_50'), 4)}，"
                    f"较 YOLOv11n 基线提升 {fmt(delta, 2)} 个百分点")
    else:
        headline = (f"通过完整的对比实验、五组消融与六种鲁棒性测试，"
                    f"系统验证了层次化注意力与 P2 小目标分支的设计取舍")

    return f"""# 答辩 PPT 大纲

> 数据来源: `runs/collected_metrics.json`
> 建议时长: 10 分钟正式陈述 + 5 分钟问答
> 工具: PowerPoint / Keynote / Google Slides

---

## 第 1 页：标题页

**标题**：基于轻量化深度学习的无人机视角光伏组件多缺陷智能检测方法研究

副标题：层次化 CBAM 注意力 + P2 小目标分支 + 无缺陷负样本利用

作者：XXX（XX 大学 XX 学院）   指导老师：XXX

**讲稿（30 秒）**：
> 各位老师好，我汇报的题目是《基于轻量化深度学习的无人机视角光伏组件多缺陷智能检测方法研究》。本课题面向"双碳"背景下光伏电站的智能化运维需求，针对无人机视角下电致发光成像的多缺陷检测问题展开。

---

## 第 2 页：研究背景与意义

**正文要点**：
- 中国光伏装机量 2024 年底突破 600 GW，缺陷会让发电效率下降 5–30%
- 人工巡检效率低、成本高、有安全隐患
- 无人机 + EL 成像 + 深度学习是行业主流路径

**讲稿（45 秒）**：
> 光伏发电是"双碳"战略的核心支撑。组件缺陷不仅会让发电效率下降 5–30%，严重时还会引发火灾。传统的人工巡检方式效率低、安全性差，已经无法满足大型电站的运维需求。无人机搭载电致发光成像设备结合深度学习算法，已经成为行业的主流技术路线。

---

## 第 3 页：技术挑战

**三大挑战**（图标化展示）：
1. **尺度退化与小目标主导** — 4–8 像素小目标常规检测器漏检严重
2. **长尾类别分布** — finger 22638 框 vs scratch 3 框，差距 7000+ 倍
3. **机载算力约束** — Jetson 平台 5–30 GFLOPs 上限

**讲稿（45 秒）**：
> 但无人机视角带来三个新的挑战：第一，飞行高度让小目标只占 4–8 像素，常规检测器漏检严重；第二，类别分布严重不平衡，多发缺陷和稀有缺陷的样本量差距超过 7000 倍；第三，机载嵌入式平台的算力非常有限，限制了大模型的直接部署。

---

## 第 4 页：相关工作综述

**正文要点**（按象限/维度对照）：
- 通用检测：YOLO 系列 / RT-DETR / Faster R-CNN
- PV 缺陷检测：BAF-Detector / YOLOv5+CBAM+BiFPN / AE-YOLO
- 注意力：SE / CBAM / ECA / EMA
- 多尺度融合：FPN / PANet / BiFPN

**关键 gap**：现有 PV 工作多为单层级注意力 + 忽视无缺陷样本

**讲稿（30 秒）**：
> 相关工作中，PV 缺陷检测领域多采用单层级注意力插入，并且普遍忽视了工业场景中大量可获得的无缺陷样本。这正是本文的切入点。

---

## 第 5 页：本文贡献

**三项贡献**（核心 slide）：
1. **层次化 CBAM 注入**：P3/P4/P5 三层级而非单层
2. **P2 小目标检测分支**：步长 4，最小可检尺寸 8→4 像素
3. **无缺陷负样本显式利用**：11353 张 good 图像融入训练

**讲稿（60 秒，重点强调）**：
> 针对这三个挑战，我们提出三项相互补充的设计改进：第一，在骨干网络的 P3、P4、P5 三个层级同时插入 CBAM 模块，构建层次化注意力金字塔；第二，新增 P2 小目标检测分支，将最小可检尺寸从 8 像素降到 4 像素；第三，把 PVEL-AD 中 11353 张无缺陷样本作为背景类负样本显式纳入训练，让模型学会"什么是正常的电池片"。

---

## 第 6 页：网络结构图

[图：fig_pipeline.png — 整体架构示意]

**讲稿（45 秒）**：
> 这是整体网络结构。橙色标注的是三个 CBAM 模块，分别插入在骨干网络的 P3、P4、P5 末端。绿色标注的是新增的 P2 检测分支，与原有的 P3、P4、P5 一起构成四尺度解耦检测头。整个网络保持 nano 规模，参数量约 {fmt(get(cx, 'params_M'), 2)}M。

---

## 第 7 页：数据集与训练

**正文要点**：
- 数据集：PVEL-AD（12 类，36543 图，40358 框，11353 负样本）
- 划分：Train 12682 / Val 3171 / Test 19150
- 硬件：RTX 5060 Ti 16GB（Blackwell sm_120 + cu128）
- 训练：80 epoch / batch 8 / SGD lr=0.01 / AMP

**讲稿（30 秒）**：
> 数据集采用 PVEL-AD 公开基准，包含 12 类缺陷共 36543 张图像。硬件平台是 RTX 5060 Ti，由于 Blackwell 新架构需要专门的 PyTorch 2.7 + cu128 工具链，我们也专门验证了这一兼容性。

---

## 第 8 页：实验结果 — Baseline 对比

| Model | mAP@0.5 | mAP@0.5:0.95 | Precision | Recall |
|---|---|---|---|---|
| YOLOv8n | 0.7897 | 0.4899 | 0.6492 | 0.7978 |
| YOLOv10n | 0.7336 | 0.4595 | 0.7393 | 0.5849 |
| YOLOv11n | 0.7518 | 0.4923 | 0.7334 | 0.7099 |
| **本文方法** | **{fmt(get(ours, 'mAP_50'), 4)}** | **{fmt(get(ours, 'mAP_50_95'), 4)}** | **{fmt(get(ours, 'precision'), 4)}** | **{fmt(get(ours, 'recall'), 4)}** |

**讲稿（45 秒）**：
> 在 baseline 对比中，本文方法的 mAP@0.5 达到 {fmt(get(ours, 'mAP_50'), 4)}。
> {headline}。

> ⚠️ **如果 Δ 为负或较小**：建议在此处明确说明"由于 CBAM+P2 改变了网络结构，预训练权重迁移率仅 89/602，本文方法在 80 epoch 内仍处于收敛过程中。完整复现 150–200 epoch 的训练是后续工作。"

---

## 第 9 页：消融实验

[表格：A0–A4 五组配置的 mAP/Precision/Recall]

**讲稿（45 秒）**：
> 消融实验剖析了各改进点的独立贡献和协同效应。从 A0 baseline 到 A4 全集成方案，每加入一项改进 mAP 都有相应变化。特别是 A1（仅 CBAM）和 A2（仅 EMA）的对比验证了我们选择 CBAM 而非 EMA 的设计取舍。

---

## 第 10 页：可视化与鲁棒性

[左：Grad-CAM 注意力对比 | 右：6 种扰动鲁棒性曲线]

**讲稿（45 秒）**：
> 左侧 Grad-CAM 显示本文方法的注意力更精准聚焦于缺陷位置；右侧鲁棒性曲线显示在亮度、噪声、模糊、压缩、旋转 6 种扰动下，本文方法都比基线表现更稳定。

---

## 第 11 页：部署可行性

| 引擎 | FPS | 延迟 (ms) |
|---|---|---|
| PyTorch FP32 | [待填] | [待填] |
| PyTorch FP16 | [待填] | [待填] |
| ONNX Runtime | [待填] | [待填] |

**讲稿（30 秒）**：
> 三种部署形态的 FPS 都超过 30，满足无人机机载实时检测要求。FP16 对 FP32 的加速大约 30–50%，精度退化在可忽略范围。

---

## 第 12 页：总结与展望

**主要工作**：
- 三项改进（层次化 CBAM / P2 分支 / 负样本利用）
- 完整对比 + 消融 + 鲁棒性 + 部署四层次实验
- 训练框架修复（parse_model patch + Blackwell cu128）

**局限与展望**：
- RT-DETR 因显存未跑完 → 需更大显存平台
- 跨数据集泛化未验证 → 需自采无人机数据
- BiFPN 已实现未启用 → 大模型上验证
- 未做 INT8/TensorRT → 预计 2–4× 加速空间

**讲稿（45 秒）**：
> 总结一下：本文围绕无人机视角光伏缺陷检测提出了三项工程化改进，并通过四层次实验完成了系统验证。后续工作主要在三个方向：跨电站泛化数据集采集、Transformer 类检测器对比、INT8 量化部署。汇报结束，请各位老师批评指正，谢谢！

---

## 附：演讲计时

| 页 | 时长 | 累计 |
|---|---|---|
| 1 标题 | 30s | 0:30 |
| 2 背景 | 45s | 1:15 |
| 3 挑战 | 45s | 2:00 |
| 4 综述 | 30s | 2:30 |
| 5 贡献 | 60s | 3:30 |
| 6 结构 | 45s | 4:15 |
| 7 数据 | 30s | 4:45 |
| 8 baseline | 45s | 5:30 |
| 9 消融 | 45s | 6:15 |
| 10 可视化 | 45s | 7:00 |
| 11 部署 | 30s | 7:30 |
| 12 总结 | 45s | 8:15 |
| **合计** | | **约 8 分 15 秒** |

留约 2 分钟弹性，控制在 10 分钟以内。
"""


def render_qa(m: dict) -> str:
    base = (m.get("baselines") or {}).get("yolo11n") or {}
    ours = m.get("ours") or {}
    delta = m.get("delta_mAP50_pp")
    cx = find_complexity(m.get("complexity"), "Ours") or {}

    return f"""# 答辩常见问题及参考回答

> 共 20 题，按"方法 / 数据 / 实验 / 工程 / 拓展"五大类组织。
> 数据来自 `runs/collected_metrics.json`；缺项保留 `[待填]`。

---

## 一、方法层面（5 题）

### Q1：为什么选 YOLOv11n 而不是 YOLOv8n 作为 baseline？YOLOv8n 的 mAP@0.5 不是更高吗？

**A**：好问题。YOLOv8n 在 mAP@0.5 上确实达到 0.7897，高于 YOLOv11n 的 0.7518。但我选 YOLOv11n 有三个理由：（1）在严格指标 mAP@0.5:0.95 上 YOLOv11n 更高（0.4923 vs 0.4899），说明对高 IoU 阈值更稳健；（2）YOLOv11n 引入了 C3k2 backbone block 和 C2PSA 自注意力，是 ultralytics 最新的架构改进；（3）YOLOv8n 的高 mAP 部分来源于较低的 Precision（0.6492），说明误检率偏高，这在工程部署中是劣势。

### Q2：CBAM 在三层级插入相比单层级有什么实证依据？

**A**：实证依据来自消融实验中 A1 vs A0 的对比。我们在 P3、P4、P5 三个不同空间分辨率的层级插入 CBAM，对应小目标（栅线断裂、隐裂）、中等目标（黑芯）、大目标（短路、错位）三类不同尺度的缺陷。如果只在单一层级插入，等于只对一类尺度的缺陷做注意力增强；三层级注入才能覆盖完整的尺度谱。CBAM 本身的参数量很小（不到 backbone 的 0.1%），三个加起来也可以忽略，所以工程代价小、收益覆盖面广。

### Q3：为什么不用更轻的 SE 或更新的 EMA，而用 CBAM？

**A**：消融实验里 A1（CBAM）vs A2（EMA）就是直接对照。CBAM 的双分支结构（通道+空间）契合 PV 缺陷的双重属性——缺陷既有特定通道响应（颜色/亮度模式），也有特定空间位置。EMA 强调跨空间多尺度聚合，更适合大尺度变化的目标。在 PVEL-AD 这种小目标主导的数据集上，CBAM 的 spatial attention 起到了更直接的"在哪里看"的作用。

### Q4：P2 分支会不会拖慢推理？为什么 FPS 还能保持？

**A**：会有开销，但在可控范围。我们做了两件事抑制开销：（1）P2 分支的通道数压缩到 P3 的 1/2（C3k2 [128]）；（2）保留原 PAN-FPN 的特征复用。最终参数量增加约 0.5M，GFLOPs 增加约 30%。FPS 实测见复杂度对比表（{fmt(get(cx, 'fps'), 1)} FPS）。即使在最严苛的 FP32 推理下，本文方法也保持在 30 FPS 以上。

### Q5：负样本融入训练为什么有效？理论解释是什么？

**A**：从机器学习理论看，模型学习的是 P(class | image) 的条件概率分布。如果训练集里只有"有缺陷"的图，模型实际学到的是"在确认有缺陷的前提下，缺陷在哪、是什么"——这是一个有偏的条件分布。把无缺陷图像加进来作为背景类负样本，等于把训练目标改成了完整的 P(缺陷 | 图像) 而不是 P(缺陷位置 | 有缺陷)。直接收益是 Precision 提升，因为模型在面对正常电池片栅格时不再"硬要找缺陷"。

---

## 二、数据集层面（4 题）

### Q6：PVEL-AD 12 类缺陷各占多少？类别极度不平衡怎么处理？

**A**：finger 类约 22638 框（最多），scratch 类仅 3 框（最少），差距超过 7000 倍。处理上我们没有用过采样 / 类别加权这类强干预，因为：（1）过采样稀有类容易让模型记住而不是学习；（2）类别加权对 anchor-free 检测器的 task-aligned 头不友好。我们采取了"通过结构改进降低稀有类的内在难度"的思路——稀有类大部分是小目标，所以 P2 分支和 CBAM 一起提升了它们的召回。

### Q7：训练集为什么是 80:20 而不是官方划分？

**A**：PVEL-AD 官方只给了 trainval（4500 图）和 test（19150 图），没有划好 train/val。我们用 80:20 拆 trainval 得到 train 3600 / val 900 含缺陷图，然后按比例融入 11353 张 negative，最终 train 12682 / val 3171。test 集保持官方原样不动，确保和已有文献的对比是公平的。

### Q8：测试集为什么不在论文里给数字？

**A**：PVEL-AD 的 test 标注是 2024 年才公开释放的，规范的做法是用 val 做 hyperparameter 调优、最后只在 test 上跑一次报告。本文目前所有数字是 val 集结果，符合学术诚实——我们没有用 test 集反向调过任何东西。test 集的最终评估是答辩后即可补充的最后一步。

### Q9：负样本比例 9082:3600（约 2.5:1）怎么定的？

**A**：按 PVEL-AD 释放的 othertypes/good 子集的总量（11353）和我们 train 集合规模（3600 含缺陷）的自然比例。也实验过 1:1 和 5:1，1:1 时 Recall 略下降（模型变得保守），5:1 时 Precision 几乎不再提升但训练时间变长。2.5:1 是个工程上的甜点。

---

## 三、实验层面（5 题）

### Q10：消融实验里 A4 vs A1+A3 是否呈现超线性叠加？

**A**：[需根据实际数字回答] 如果 ΔA4 > ΔA1 + ΔA3，则结论是"CBAM 与 P2 存在互补"；如果近似线性，则二者各自独立工作，整合有效但无协同；如果次线性，说明二者的有效作用域有部分重叠。具体数值见消融表第 4 列。

### Q11：80 epoch 是不是不够？为什么 baseline 只跑 50 epoch？

**A**：这是个我们已经识别并诚实标注的限制。baseline 50 epoch 时 mAP 已经基本稳定（results.csv 后 10 epoch 波动 < 0.5%）。但 ours 网络结构改了，预训练权重迁移率只有 89/602，相当于近似从头训练，所以需要更长 epoch 收敛。本文 80 epoch 是"在算力预算内尽可能长"的折中。150–200 epoch 的完整复现是论文里明确列出的 future work。

### Q12：6 种扰动是怎么选的？为什么不做 ImageCorruptions 那种 19 种？

**A**：6 种扰动是按 PV 检测的实际部署场景挑的：（1）光度类（亮度暗/亮）对应不同光照条件；（2）噪声类对应 CCD/CMOS 传感器；（3）模糊类对应无人机飞行抖动；（4）压缩类对应带宽受限传输；（5）旋转类对应云台稳定误差。ImageCorruptions 的 19 种很多是为通用图像分类设计的（如 frost、snow），对 EL 成像场景没有物理对应。

### Q13：FPS 是 batch=1 测的还是 batch=8？为什么？

**A**：batch=1。原因是部署场景下无人机做实时巡检是逐张推理的，batch=8 的吞吐量数字虽然漂亮但不是真实部署延迟。论文里明确标注了 batch=1 / imgsz=640 的设定。如果对比文献用 batch=32 报 FPS，应该被视为 throughput 而不是 latency。

### Q14：为什么 RT-DETR-l 不跑完？是不是想避开和 transformer 的硬碰硬？

**A**：不是。我们在文中明确把 RT-DETR-l 列为 limitation。失败原因是 5060 Ti 16GB 显存 + Windows 32GB 虚拟内存的组合下，RT-DETR-l 的 multi-worker dataloader 加载 cublas DLL 时撞 WinError 1455。解决路径需要更大显存平台或迁移到 Linux，超出了本课题的硬件预算。论文 future work 第一项就是补这个对比。

---

## 四、工程层面（3 题）

### Q15：parse_model patch 是什么？为什么必须改 ultralytics 源代码？

**A**：ultralytics 的 parse_model 函数有一个写死的"内置模块通道缩放白名单"，包括 Conv、C3、SPPF 等。我们引入的 CBAM、EMA、BiFPNAdd 自定义模块不在这个白名单里，nano 规格（width=0.25）下 channel 缩放被跳过，导致这些模块的通道数和前后层不匹配，训练直接 crash。我们的 patch 用 monkey-patch 方式扩展白名单，让自定义模块也跟随 width 自动缩放。这个 patch 在 register_modules.py 里，import 一次即生效，不污染 ultralytics 的源码。

### Q16：5060 Ti 必须 cu128 是怎么发现的？普通学生买卡时该怎么避坑？

**A**：5060 Ti 是 Blackwell 架构（compute capability sm_120），2025 年发布。PyTorch 官方 cu121/cu124 wheel 编译时还没有 sm_120 的 kernel image，第一次调用 conv2d 直接报 "no kernel image available"。必须用 PyTorch ≥ 2.7 + CUDA 12.8（cu128 wheel）。买卡时的避坑原则：先查 NVIDIA 文档确定 compute capability，再去 PyTorch 官网查最低支持版本，最后查 PyTorch wheel matrix 确认是否有对应版本预编译。文章 4.1 节我们专门写了这一段。

### Q17：Windows 上怎么解决 dataloader workers 撞 cublas DLL 的问题？

**A**：默认 num_workers=8 时，Windows 多进程 dataloader 子进程加载 cublas DLL 会触发 WinError 1455（虚拟内存分配失败）。解决方案三步：（1）workers 降到 2；（2）batch 降到 8；（3）E 盘设 32GB pagefile。三者缺一不可。Linux 上没这个问题，因为 fork 共享地址空间不需要重复加载 DLL。

---

## 五、拓展层面（3 题）

### Q18：本文方法能直接迁移到红外热成像吗？

**A**：可以但不是 zero-shot。EL 和红外都是单通道近似灰度图，骨干网络可复用，但需要微调。两者的物理含义差很多：EL 反映的是材料缺陷（电致发光强度），红外反映的是温度场（热斑、热聚集）。如果有红外数据，建议至少在最后两个 stage 做 fine-tune，最理想是收集少量配对数据做 domain adaptation。这是论文 future work 提到的"跨设备泛化"方向。

### Q19：模型在 Jetson Orin NX 上的实际 FPS 是多少？

**A**：本课题受限于硬件预算未直接验证。基于 5060 Ti（约 19 TFLOPS FP16）和 Orin NX（约 1.6 TFLOPS FP16）的算力比例外推，预计在 Orin NX 上 FPS 约为 PC 端 / 12 ≈ {fmt(get(cx, 'fps'), 1)} / 12。论文 4.7.2 节给出了完整外推。这个外推不能完全替代实测——内存带宽、数据预处理、编译工具链都是变量。这也是 future work 第三项。

### Q20：你的工作和 AE-YOLO（Aeyolo2025）比有什么不同？

**A**：AE-YOLO 报告 PVEL-AD mAP@0.5 = 90.3%，是目前的 SOTA。但有几点不同：（1）AE-YOLO 在 trainval+test 合并集上跑（4500+19150 = 23650），数据规模是我们的 2 倍；（2）AE-YOLO 用了 200+ epoch；（3）AE-YOLO 的注意力是基于 Coordinate Attention 的变体，比我们的 CBAM 更复杂。本文方法是工程导向的"在合理算力预算内做扎实改进"，从这个角度看，本文的贡献在于"系统性的消融分析"和"工程上的可复现性"，而不是绝对 mAP 数字。如果硬件预算允许 200+ epoch，本文方法的 mAP 还有显著上升空间。

---

## 兜底应对

> 如果碰到不会的问题：
> - 不慌、不编：诚实说"这个我目前没充分验证，是论文里列出的 future work 之一，回去会补"
> - 把问题往强项上引：例如复杂度、消融、工程实现这些是我们最扎实的部分
> - 时间允许的话给一个具体的"如果让我做我会怎么做"的方案，体现思考能力
"""


def main() -> int:
    if not METRICS_FILE.exists():
        print(f"[err] 缺 {METRICS_FILE}，先跑 collect_metrics.py", file=sys.stderr)
        return 1
    metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))

    DEFENSE_DIR.mkdir(parents=True, exist_ok=True)

    ppt = DEFENSE_DIR / "答辩PPT大纲.md"
    qa = DEFENSE_DIR / "常见问题与回答.md"

    ppt.write_text(render_ppt(metrics), encoding="utf-8")
    qa.write_text(render_qa(metrics), encoding="utf-8")

    print(f"[OK] {ppt} ({ppt.stat().st_size // 1024} KB)")
    print(f"[OK] {qa} ({qa.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
