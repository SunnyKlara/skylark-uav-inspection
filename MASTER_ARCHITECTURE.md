# 项目主架构与年度路线图 — MASTER ARCHITECTURE

> 写于 2026-05-27（项目锚定方向后第一份正式架构文档）。
> 上承 `PROJECT_NORTH_STAR.md`，下指导所有具体执行。
> **方向自此锁定**，后续不再做大方向变更。

---

## 0. 文档地位

| 文档 | 作用 | 修改频率 |
|---|---|---|
| `PROJECT_NORTH_STAR.md` | 北极星：为什么做、衡量标准、决策原则 | 几乎不改 |
| `MASTER_ARCHITECTURE.md`（本文） | 怎么做：系统架构、模块划分、季度路线图 | 每季度 review 一次 |
| `STATE.md` | 当前在哪：进度快照、下件事 | 每周更新 |

---

## 1. 项目身份重定义

### 1.1 项目正式名称

**Skylark — 通用无人机航拍 AI 巡检平台**
*Skylark — General-Purpose UAV Aerial AI Inspection Platform*

> 名字由来：云雀（Skylark）— 起飞、自主、轻盈、能感知。
> Logo 与命名是真实产品的第一步，不是装饰。

### 1.2 一句话定义

> 一个面向**中小型基础设施巡检场景**（光伏 / 输电 / 道路 / 屋顶 / 桥梁）的轻量化 AI 复核平台。
> 用户以图片包或实时图传上传航拍数据，平台跑预训练或定制模型，输出可视化报告 + 缺陷台账 + GIS 地图。
> 模型既能在云端 GPU 跑，也能下沉到 Jetson 边缘端做机载推理。

### 1.3 与本科毕设的关系

| 项 | 内容 |
|---|---|
| 本科毕设论文（中文） | 以 Skylark 中"光伏检测算法"模块为研究对象，撰写 35000-50000 字优秀级毕设 |
| 期刊投稿（英文） | 选 Skylark 中**最有学术价值**的一块（候选：CBAM 位置消融 / 训练预算与迁移率规律 / 多场景模型路由）投 IEEE TII / Sensors |
| 工程产品 | Skylark 完整平台，开源在 GitHub，部署在自有 VPS，作为"作品级别"项目 |

**论文是 Skylark 的副产物，不是终点。**

---

## 2. 五维完美验收标准（项目终态）

按你确认的五维：

| 维度 | 验收标准 |
|---|---|
| **论文（理论）** | 中文毕设优秀（35000+ 字、8 章）+ 1 篇 SCI 投出 + 论文里有 ≥ 1 处第一手实验发现 + 0 注水 |
| **产品（实践主轴）** | Web 平台真实在线（域名 + HTTPS + 注册登录）+ ≥ 3 个检测场景 + ≥ 1 次真实演示 + 完整 GitHub 开源 |
| **软硬协同** | Jetson Orin 真机部署 + INT8 + TensorRT + 真实 FPS/功耗实测 + 1 个 5-10 分钟完整演示视频 + **+ 仿真**（详见 §6） |
| **工程质量** | 后端 pytest ≥ 60% + CI/CD + Docker + OpenAPI + 架构文档 + 错误监控 |
| **个人能力** | Web 全栈 + 边缘 AI 部署 + ML 工程 + 产品思维 + 学术写作 |

**+ 你新增的"仿真"维度**：

✅ 在 AirSim / Gazebo / Webots 任一仿真环境中演示无人机航拍 → 模型推理 → 决策反馈的完整闭环。
> 仿真的好处：不依赖真实无人机起飞条件，全套流程可在 PC 上演示，且作为**产品扩展性证据**。

---

## 3. 系统架构（C4 模型）

### 3.1 Level 1 — 系统语境图

```
        ┌──────────────┐                              ┌─────────────────┐
        │  巡检员      │                              │  管理员         │
        │ (Field Op)   │                              │  (Admin)        │
        └──────┬───────┘                              └────────┬────────┘
               │                                                │
               │ 上传图片包 / 实时图传                           │ 配置场景/审核结果
               ▼                                                ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                                                             │
        │              Skylark 巡检平台                                │
        │   (Web 前端 + API 后端 + 模型服务 + 边缘节点)                │
        │                                                             │
        └─────────────────────────────────────────────────────────────┘
               │ 推理结果                              ▲
               │                                       │ RTMP/WebRTC 流
               ▼                                       │
        ┌──────────────┐                       ┌───────┴────────┐
        │  GIS 地图    │                       │  无人机        │
        │  (Mapbox)    │                       │  (大疆/PX4/    │
        │              │                       │   AirSim 仿真) │
        └──────────────┘                       └────────────────┘
```

### 3.2 Level 2 — 容器图

```
┌────────────────────────────────────────────────────────────────────┐
│                    Skylark Platform                                │
│                                                                    │
│  ┌──────────────────┐    ┌──────────────────┐   ┌──────────────┐  │
│  │  Web Frontend    │◄──►│  API Gateway     │◄─►│  PostgreSQL  │  │
│  │  (Vue3 + Element)│    │  (FastAPI)       │   │  (Tasks/Defe-│  │
│  │                  │    │                  │   │   cts/Users) │  │
│  └────────┬─────────┘    └────────┬─────────┘   └──────────────┘  │
│           │                       │                               │
│           │ WebSocket             │                               │
│           ▼                       ▼                               │
│  ┌──────────────────┐    ┌──────────────────┐   ┌──────────────┐  │
│  │  Live Stream     │    │  Inference       │   │  MinIO       │  │
│  │  (RTMP/WebRTC)   │    │  Worker          │   │  (Images/    │  │
│  │  Receiver        │    │  (Celery)        │   │   Reports)   │  │
│  └──────────────────┘    └────────┬─────────┘   └──────────────┘  │
│                                   │                               │
│                                   ▼                               │
│                          ┌────────────────────┐                   │
│                          │  Model Registry    │                   │
│                          │  - PV / Power /    │                   │
│                          │    Road / Roof     │                   │
│                          │  - ONNX/TensorRT   │                   │
│                          └────────────────────┘                   │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                          ┌────────────────────┐
                          │ Edge Node          │
                          │ (Jetson Orin Nano) │
                          │ - INT8 TRT engine  │
                          │ - 现场推理         │
                          └────────────────────┘
```

### 3.3 技术栈定义

| 层 | 技术 | 选型理由 |
|---|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia | 学习曲线友好、组件库成熟、中文文档好 |
| 地图 | Leaflet（开源免费）+ GeoJSON | 不绑定 Mapbox token、自部署友好 |
| 图表 | ECharts | 国产、文档全、对接复杂表方便 |
| 后端 | Python 3.11 + FastAPI + Pydantic | 与 ML 生态无缝、类型注解原生支持 |
| 任务队列 | Celery + Redis | 标准选型、成熟稳定 |
| 数据库 | PostgreSQL + SQLAlchemy + Alembic | GIS 扩展（PostGIS） + 迁移管理 |
| 对象存储 | MinIO（自建 S3） | 不绑定云厂商、部署简单 |
| 流媒体 | nginx-rtmp + ffmpeg + WebSocket | 开源、轻量、可定制 |
| 推理 | ONNX Runtime（云）+ TensorRT（Jetson） | 跨平台 + 边缘优化 |
| 仿真 | AirSim（Unreal Engine）或 Gazebo + ArduPilot SITL | AirSim 视觉好但重；Gazebo 工业标准 — **见 §6** |
| 容器 | Docker + Docker Compose | 一键部署 |
| CI/CD | GitHub Actions | 免费、生态完整 |
| 部署 | 阿里云轻量级 VPS + Nginx + Let's Encrypt | 100 元/月，足够 |
| 监控 | Sentry（错误）+ Prometheus（指标）+ Grafana（看板） | 全套开源 |

### 3.4 仓库未来组织

```
graduation_project/                    ← 项目根
│
├── docs/                              ← 文档（架构/部署/API）
├── paper/                             ← 论文（中文 md + 中英 tex）
├── ml/                                ← ML 训练 / 评估 / 量化（沿用现有 code/）
│   ├── configs/
│   ├── data/
│   ├── eval/
│   ├── models/
│   ├── train/
│   ├── visualize/
│   ├── postprocess/
│   ├── deploy/                        ← 新：ONNX 导出、TRT 编译、Jetson 推理
│   └── runs/
│
├── platform/                          ← 新：Skylark 平台代码
│   ├── backend/                       ← FastAPI 后端
│   │   ├── api/
│   │   ├── workers/                   ← Celery 推理 worker
│   │   ├── models/                    ← 数据库 ORM
│   │   ├── services/
│   │   ├── tests/
│   │   └── Dockerfile
│   ├── frontend/                      ← Vue3 前端
│   │   ├── src/
│   │   ├── public/
│   │   └── Dockerfile
│   ├── docker-compose.yml             ← 一键启动
│   └── README.md
│
├── edge/                              ← 新:Jetson 边缘端代码
│   ├── inference/                     ← TRT engine + Python 服务
│   ├── streaming/                     ← RTMP 推流客户端
│   └── README.md
│
├── simulation/                        ← 新：仿真环境
│   ├── airsim/                        ← AirSim 集成
│   │   ├── settings.json
│   │   └── client.py                  ← Python API 控制无人机 + 抓帧
│   ├── scenarios/                     ← 巡检场景脚本（光伏屋顶 / 输电线路）
│   └── README.md
│
├── .github/workflows/                 ← CI/CD
└── README.md                          ← 项目主入口
```

---

## 4. 季度路线图（4 个季度 × 3 个月）

### Q1（M1-M3）— 算法与论文季

**主目标**：完成论文全部实验 + 中文毕设初稿 + 英文期刊投稿

**M1（6 月）— v2 协议训练**

- [ ] 验证 v2 训练脚本端到端跑通（先跑 1 个 baseline 200ep 作为 sanity check）
- [ ] 启动 v2 全套训练（E1 baseline 横评 + E2 主消融）
- [ ] 跑评估三件套（complexity / robustness / deployment）
- [ ] 跑可视化三件套（plot / grad_cam / qualitative）
- [ ] daemon 化 v2 流水线，长时间无人值守

**M2（7 月）— 中文毕设写作**

- [ ] 重写第 4 章实验（基于 v2 真实数字）
- [ ] 完善第 3 章方法描述（加入实测尺度分布）
- [ ] 重写摘要 / 结论，与新数据吻合
- [ ] 第 5 章局限与展望（尤其注明"尚未在 Jetson / 跨数据集验证"作为 Q2-Q3 预告）
- [ ] 中文毕设初稿完成（35000+ 字）

**M3（8 月）— 英文 SCI 投稿**

- [ ] 选定投稿目标（IEEE TII / Sensors / TIE）
- [ ] 把第一手发现包装成英文论文（建议主线："训练预算 + 预训练迁移率 + CBAM 位置"三合一系统消融）
- [ ] 英文论文打磨 2-3 轮（Grammarly + DeepL Write + 自查）
- [ ] 投稿 + 进入 under review

**Q1 产出**：3 个 baseline + 5 组消融 + 3 组 CBAM 位置 + 2 组预算扫描，共 13 个 200ep 训练；中文毕设完整初稿；1 篇英文论文投出。

### Q2（M4-M6）— 边缘部署与 ML 服务化

**主目标**：模型量化 + Jetson 真机部署 + 推理服务 API 化

**M4（9 月）— 量化与 ONNX 化**

- [ ] 把 ours 模型导出 ONNX（FP32 + FP16 + 静态 INT8 + QAT INT8）
- [ ] 在 5060 Ti 上对比四种精度的 mAP / FPS
- [ ] 写 `ml/deploy/onnx_export.py` + `quantize.py` + `benchmark.py`
- [ ] 论文 5 章局限补一段量化结果（如已发表则作为下一轮 minor revision）

**M5（10 月）— Jetson 真机**

- [ ] 采购 Jetson Orin Nano 8GB（约 3000 元，2 周到货）
- [ ] Jetson 上装 JetPack 6.x + TensorRT
- [ ] 把 ONNX 模型转成 TRT engine
- [ ] 真机 benchmark：FPS / 功耗 / 温度 / 长时间稳定性
- [ ] 写 `edge/inference/` 完整推理服务（Python + ZMQ/HTTP）

**M6（11 月）— 推理 API 化**

- [ ] FastAPI 后端骨架（用户 / 项目 / 任务三表）
- [ ] Celery worker 调用模型推理
- [ ] MinIO 接图片上传
- [ ] PostgreSQL 存任务状态 / 缺陷记录
- [ ] 一个 `/health` + `/predict` 接口能 curl 跑通

**Q2 产出**：完整边缘部署链路；后端骨架 + 一个真实可用的 `/predict` API；Jetson FPS/功耗实测数据。

### Q3（M7-M9）— Web 平台与多场景

**主目标**：Web 平台前端 + 多场景模型 + 仿真集成

**M7（12 月）— 前端 + 多场景模型训练**

- [ ] Vue 3 项目初始化 + Element Plus + 路由 / 状态管理
- [ ] 5 个核心页面骨架：登录 / 项目列表 / 任务详情 / 缺陷地图 / 设置
- [ ] 训练第 2 个场景模型：输电线路缺陷检测（CPLID / Insulator Detection 公开集）
- [ ] 训练第 3 个场景模型：道路病害检测（RDD2022 公开集）

**M8（1 月）— 平台集成**

- [ ] 模型注册系统（多场景路由）
- [ ] 文件上传 + 异步推理 + 结果可视化（带检测框图 + 地图标注）
- [ ] PDF 报告生成（reportlab / WeasyPrint）
- [ ] 用户认证 + 简单权限
- [ ] Docker Compose 一键部署
- [ ] 部署到阿里云 VPS + 域名 + HTTPS

**M9（2 月）— 仿真 + 实时图传**

- [ ] AirSim 集成：在虚拟光伏屋顶环境飞 + 抓帧推理
- [ ] 真实大疆无人机 RTMP 推流（如果买了无人机）/ 否则用仿真完整顶替
- [ ] 实时图传 → 后端 ffmpeg 抽帧 → 推理 → WebSocket 推前端
- [ ] 录制 5-10 分钟完整演示视频

**Q3 产出**：Skylark Web 平台真实在线、能注册登录；3 个检测场景；仿真演示视频 + 真机演示视频（如有无人机）。

### Q4（M10-M12）— 工程化、答辩、收尾

**主目标**：工程级别 polish + 毕设答辩 + 期刊返修

**M10（3 月）— 工程化收尾**

- [ ] 后端 pytest 覆盖率到 60%+
- [ ] GitHub Actions：自动测试 + Docker 镜像构建 + 部署
- [ ] OpenAPI 文档自动生成 + 在线 Swagger UI
- [ ] Sentry 错误监控接入
- [ ] 完整 README + 架构文档（C4）+ 部署手册 + 用户手册

**M11（4 月）— 答辩准备 + 真实演示**

- [ ] 中文毕设最终稿（已经 8 个月在迭代了，应该非常成熟）
- [ ] 答辩 PPT + 演示视频 + 现场 demo 演练
- [ ] 找 1-2 个本地用户真实试用平台（同学 / 同行 / 实习公司）
- [ ] 收集反馈 + 迭代

**M12（5 月）— 答辩 + 期刊返修 + 收尾**

- [ ] 毕设答辩
- [ ] 英文期刊返修（如有 minor / major revision）
- [ ] 项目主页 + 演示视频上传 B 站 / YouTube
- [ ] GitHub README 终稿（含演示截图 + 架构图 + 引用论文）
- [ ] 写一篇个人技术 blog 总结全程

**Q4 产出**：毕业 + 期刊投出（理想已 accept）+ 真实有人用过的产品 + 完整作品集。

---

## 5. 关键路径分析（哪些事情阻塞哪些事情）

```
v2 训练协议验证 ──► v2 全套实验 ──► 中文毕设实验章 ──► 中文毕设初稿
                                                        │
                                                        ▼
                                                    英文 SCI 投稿
                                                        │
ONNX 导出+量化 ────► Jetson 部署 ─► 边缘推理服务 ─► 平台后端 API
                                                        │
                                                        ▼
                                                    平台前端
                                                        │
                                                        ▼
                                                    多场景 + 仿真演示
                                                        │
                                                        ▼
                                                    答辩 + 收尾
```

**关键依赖**：
- v2 训练协议验证 = 整个项目地基。**必须先验证 1 个 baseline 200ep 跑得通**
- ONNX 导出 = Jetson 部署前提。这件事是 Q2 第一周的事
- Jetson 真机 = "软硬协同"维度的核心。**必须采购**

**风险点**：
- v2 训练 200ep 单 baseline 约 15 小时，13 个配置 ≈ 200 小时。期间任何 GPU 异常都需要 resume 机制 — 已在 train_v2.py 实现
- Jetson 采购 + 调试可能踩坑（JetPack 版本 / Python 兼容性）— 预留 1 周 buffer
- 多场景数据集质量参差 — 预留 2 周做数据清洗 / 标注转换

---

## 6. 仿真维度详细设计

### 6.1 选型决策

**最终选 AirSim**。理由：

| 选项 | 优势 | 劣势 | 选择 |
|---|---|---|---|
| AirSim | 视觉真实 / Unreal 引擎 / 直接出图 / 微软维护 | 重（30GB+） | ✅ |
| Gazebo + ArduPilot | 工业标准 / ROS 生态 | 视觉差、装机难 | ❌ |
| Webots | 轻量、跨平台 | 视觉一般 | 备选 |
| Isaac Sim | NVIDIA 出品、视觉顶级 | 商用许可 / 显存高 | ❌ |

> AirSim 已被微软停更，但仓库 stable，社区活跃，文献用得最多。学界引用率高，写论文自动加分。

### 6.2 仿真三个用途

**用途 1：航拍视角生成与训练数据增强**
- 在 Unreal 虚拟光伏屋顶 / 输电线路场景中，按预定航线飞行
- 抓取多视角、多光照、多高度的合成图像
- 配合 Domain Randomization → 提升模型对真实视角的泛化能力
- **这本身就是论文里一个独立 contribution**

**用途 2：算法闭环验证**
- 仿真无人机搭载本文模型实时推理
- 检测到缺陷时调用 callback（标注、降低高度复拍、记录 GPS）
- 演示"AI 反馈控制飞行决策"——这是真正的"软硬协同"

**用途 3：演示视频替代品**
- 不依赖真实无人机起飞条件
- 录制完整任务流程：起飞 → 巡航 → 检出 → 报告生成
- 答辩 / 投稿 / 找工作时通用

### 6.3 实施时机

放在 Q3 M9（2 月）。**不放 Q1 / Q2** 的原因：
- AirSim 装机调试约 3-5 天，不能挤算法主线
- 仿真最有价值的时机是平台已经能跑后，仿真数据能直接接进平台演示

---

## 7. 硬件预算确认

| 项 | 价格 | 必要性 |
|---|---|---|
| Jetson Orin Nano 8GB | 3000 | 核心 |
| 二手大疆 Mini 3 Pro / Air 3 | 4000 | 推荐（仿真做主，真机加分） |
| 阿里云轻量 VPS（2C4G） | 100/月 × 12 = 1200 | 平台部署 |
| .com 域名 | 70/年 | 品牌 |
| 备用件 / 充电管家 / SD 卡 | 500 | 杂项 |
| **合计** | **8770 元** | 接受 |

> 说明：Jetson 在 Q2 中段（10 月）采购，无人机在 Q3 末（2 月）采购。前期不需要立刻投入。
> 如果不买无人机：完全用仿真替代演示，整体成本降到 4770 元，且不损失论文 / 答辩效果（仿真 + 公开数据集足以支撑五维验收）。

---

## 8. 学习路径（你需要补的技能）

按时间顺序：

| 月 | 重点学习内容 | 推荐资源 |
|---|---|---|
| M1-M3 | 学术写作 / LaTeX / 论文投稿流程 | 《How to Write a Lot》/ 师兄师姐 |
| M4 | Python 异步、FastAPI、Pydantic | FastAPI 官方文档（半天即可） |
| M5 | TensorRT、Jetson 嵌入式 | NVIDIA 官方文档 + JetsonHacks YouTube |
| M6 | Docker、PostgreSQL、SQLAlchemy | 官方文档 |
| M7 | Vue 3 Composition API、TypeScript | Vue 3 Mastery / Element Plus 文档 |
| M8 | Celery、Redis、MinIO、Nginx | 官方文档 |
| M9 | AirSim、Unreal Engine 基础 | AirSim docs / 论文 implementations |
| M10 | pytest、GitHub Actions、监控 | 官方文档 |

> **每月 5-10 小时学习投入足以**。其余时间是动手做。**学了不立刻用 = 白学**——学习与做事必须交错。

---

## 9. 风险与应对

### 风险 1：v2 训练实验数字不漂亮（ours < baseline）

**应对**：北极星已经定好——不为数字漂亮调实验。如实写 + 把"为什么不漂亮"作为论文的独立学术贡献。论文方向已经从"性能 SOTA"改为"系统消融 + 工程经验"，不依赖具体数字。

### 风险 2：Jetson 调试踩坑超预期

**应对**：预留 1 周 buffer。失败后退路是"全用 5060 Ti 模拟边缘部署 + 论文里写"硬件采购延误"。仿真维度不依赖 Jetson。

### 风险 3：Web 全栈学习曲线陡

**应对**：Q2 末（M6）只要求一个 `/predict` 接口能 curl 跑通——这是 FastAPI 入门第一天能做到的。Vue 前端在 M7 才开始，前面留了 6 个月渐进准备。

### 风险 4：英文 SCI 投稿被拒

**应对**：投稿被拒不影响毕业。本文重点是过程中的学习。如果一审被拒，根据审稿意见改投下一档期刊（IEEE Sensors → IEEE Access → MDPI Sensors）。

### 风险 5：时间投入分散

**应对**：北极星说每周一件具体事。**严格执行周末 review**，不允许超过 3 天没产出。

---

## 10. 执行原则（与北极星呼应）

1. **永远只做下一件具体事**。本架构图是地图不是命令。
2. **季度 review 时可调整**，但不在季中变方向。
3. **学到的 > 做出的 > 写出的**。永远把"我学到什么"放第一位。
4. **诚实第一**。不注水、不造数据、不写没做过的事。
5. **完成 > 完美**。每一步先有丑陋的能跑版本，再迭代。

---

## 11. 当下立刻要做的三件事

不变更，沿用 `PROJECT_NORTH_STAR.md` 第 3 节：

### 事 A：等 daemon 跑完（今天-明天）
v1 daemon 还在跑，预计今晚-明天上午跑完所有 ablation + eval + viz。**不打扰**。

### 事 B：v2 协议 sanity check（今天剩余时间，不冲突 GPU）
**不能跑训练（GPU 占用中）**，但可以：
- 重写 `STATE.md`，更新到反映最新方向（Skylark 平台 + 双线产物）
- 检查 `train_v2.py` 静态语法 + 逻辑（已通过 sanity check 了，再做一次代码 review）
- 准备 v2 启动脚本

### 事 C：daemon 跑完后 → 启动 v2
明天 daemon 跑完，立刻启动 v2 全套（先 1 个 baseline 200ep 验证 4 小时，OK 后启动剩余 12 个）。

---

## 12. 一行结尾

> **Skylark — 一个真实的产品，一篇严谨的论文，一年的学习，全部装在你的兜里。**
> **从今天起，不再变方向。**
