# 元信息

## 题目

**中文**：基于轻量化深度学习的无人机视角光伏组件多缺陷智能检测方法研究

**英文**：A Lightweight Deep Learning Method for Multi-Defect Detection of Photovoltaic Modules from UAV Perspective

## 关键词

**中文关键词**：光伏缺陷检测；目标检测；YOLOv11；注意力机制；小目标检测；轻量化

**Keywords**: photovoltaic defect detection; object detection; YOLOv11; attention mechanism; small object detection; lightweight model

## 中文摘要

光伏发电是实现"双碳"目标的核心可再生能源，而组件缺陷会显著降低发电效率甚至引发安全事故。无人机搭载电致发光（Electroluminescence, EL）成像设备进行自主巡检，结合深度学习算法实现缺陷智能识别，已成为光伏运维领域的重要技术路线。然而无人机视角下的光伏组件缺陷检测面临三大挑战：第一，缺陷目标尺度差异显著且小目标占比高，传统检测器漏检严重；第二，类间样本分布严重不平衡，长尾类别召回率低；第三，机载嵌入式平台算力受限，制约了高精度大模型的应用。

针对上述问题，本文以 YOLOv11n 为基线，提出一种轻量化的多缺陷智能检测方法。主要工作包括：第一，构建了基于 PVEL-AD 数据集的无人机视角光伏缺陷检测基准，涵盖 12 类典型缺陷与 11353 张无缺陷负样本，共 36543 张图像、40358 个标注框；第二，在骨干网络中引入卷积块注意力模块（CBAM），通过通道-空间双分支注意力增强对小目标缺陷的特征响应；第三，新增 P2 小目标检测分支（步长 4，分辨率 160×160），构建四尺度检测头以提升小目标召回率；第四，完成了与 YOLOv8n、YOLOv10n、YOLOv11n 的系统对比与三组消融实验，并在 6 种鲁棒性扰动条件下验证模型可靠性。

实验设计采用公平协议（200 epoch、cos_lr、所有配置等同 yolo11n.pt 预训练源）系统报告：（1）3 个 nano 级 baseline（YOLOv8n/v10n/v11n）的横评，确立基线选择依据；（2）5 组消融配置（A0–A4）在公平协议下逐一拆解 CBAM、EMA、P2 各改进点的独立与组合贡献；（3）CBAM 注入位置消融（仅 P3 / 仅 P5 / P3+P4 / 全层级）验证"层次化"叙事的真实必要性；（4）训练预算扫描揭示自定义 yaml 改造导致的 14.8% 预训练迁移率衰减及其对训练 epoch 预算的量化要求。本研究不寻求绝对 SOTA，而是在算力受限的工业部署场景下系统验证三类改进的真实贡献边界，为后续在 ultralytics 框架上做结构改造的研究者提供经验参考。具体数字详见正文实验章节。

> **数字占位说明**：本文当前为方法/实验设计正稿；最终量化数字（mAP / Params / FLOPs / FPS）将在 v2 协议训练完成后回填，回填脚本与流程已在 `code/postprocess/` 中实现。

## English Abstract

Photovoltaic (PV) power generation is a cornerstone of carbon neutrality goals, yet defects in PV modules significantly reduce energy efficiency and may pose safety hazards. Autonomous inspection using unmanned aerial vehicles (UAVs) equipped with electroluminescence (EL) imaging, combined with deep-learning-based defect detection, has become a key direction for PV operations and maintenance. However, defect detection from UAV perspective faces three major challenges: large scale variation with high small-object ratio, severe class imbalance with long-tailed distribution, and the resource constraints of airborne embedded platforms.

To address these challenges, this work proposes a lightweight multi-defect detection method built on YOLOv11n. The main contributions are: (1) a benchmark on PVEL-AD with 12 defect categories and 11353 negative (defect-free) samples, totaling 36543 images and 40358 annotations; (2) integration of Convolutional Block Attention Module (CBAM) into the backbone, providing channel-spatial dual attention to enhance small-defect feature response; (3) addition of a P2 small-object detection head (stride 4, 160×160 resolution), forming a four-scale detection head that improves small-object recall; (4) systematic comparison against YOLOv8n / YOLOv10n / YOLOv11n with ablation studies and a six-perturbation robustness evaluation.

Following a fair training protocol (200 epochs, cosine LR schedule, identical yolo11n.pt pretrained source across all configurations), this work systematically reports: (1) a horizontal comparison among three nano-scale baselines (YOLOv8n/v10n/v11n) to justify the baseline choice; (2) a five-configuration ablation (A0–A4) that decomposes the independent and combined contributions of CBAM, EMA, and the P2 branch; (3) a CBAM placement ablation (P3-only / P5-only / P3+P4 / full hierarchy) that interrogates the real necessity of the ``hierarchical injection'' narrative; (4) a training-budget sweep that quantifies the 14.8% pretrained-weight transfer rate caused by custom-YAML structural modifications and its impact on epoch budget. We do not pursue absolute SOTA; rather, under compute-constrained industrial deployment scenarios, we delineate the genuine contribution boundaries of these improvements and offer empirical guidance for subsequent practitioners modifying the ultralytics framework. Concrete numerical results are reported in the experiments section.

## 论文图表清单（产物追踪）

| 编号 | 标题 | 章节 | 状态 |
|---|---|---|---|
| 表 3.1 | PVEL-AD 数据集类别分布与训练划分 | 3.1 | ✅ 已生成 |
| 图 3.1 | 数据集类别频次柱状图 | 3.1 | 🟡 待 dataset_stats.py 完工 |
| 图 3.2 | 标注框尺寸归一化散点图 | 3.1 | 🟡 待 dataset_stats.py 完工 |
| 图 3.3 | 本文方法整体网络结构图 | 3.2 | 🔴 需手画（draw.io） |
| 图 3.4 | CBAM 注意力模块结构图 | 3.3 | 🔴 需手画 |
| 图 3.5 | 四尺度检测头网络拓扑 | 3.4 | 🔴 需手画 |
| 表 4.1 | 实验环境与超参数配置 | 4.1 | ✅ 已写 |
| 表 4.2 | Baseline 模型对比 | 4.2 | 🟡 3/4 baseline 已得 |
| 表 4.3 | 消融实验结果 | 4.3 | 🟡 待 ablation 完工 |
| 表 4.4 | 模型复杂度对比（Params/FLOPs/FPS） | 4.4 | 🟡 待 eval 完工 |
| 图 4.1 | 训练曲线（mAP/loss） | 4.2 | 🟡 待 plot_results.py |
| 图 4.2 | PR 曲线（ultralytics 自动产出） | 4.2 | 🟡 |
| 图 4.3 | Grad-CAM 注意力可视化（baseline vs ours） | 4.5 | 🟡 待 grad_cam.py |
| 图 4.4 | 检测结果定性对比 | 4.5 | 🟡 待 make_qualitative.py |
| 图 4.5 | 鲁棒性曲线（6 种扰动） | 4.6 | 🟡 待 eval_robustness.py |
| 表 4.5 | 部署可行性对比（FP32/FP16/ONNX） | 4.7 | 🟡 待 eval_deployment.py |
