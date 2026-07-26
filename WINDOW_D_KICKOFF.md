# Window-D 启动套件

> 复制粘贴版。给 Q3 起（约 2026 年 12 月，M7）启动的第 4 个 Kiro 窗口。
> 你（用户）只需要：开新窗口 → 打开同工作区 → 复制 §"启动语句"段全文粘贴。

---

## ⚠ 2026-07-27 变更说明（启动前必读）

本文档写于 2026-05-27，之后项目做了两次调整，**下文尚有部分内容过时**。启动 Window-D 时按本节修正：

| 原文内容 | 现状 |
|---|---|
| Window-D = **前端 + 仿真** | Window-D = **纯前端**。`simulation/**` 已移交 **Window-E**（飞控 + 仿真），并入 `flight/sitl/` |
| 仿真用 **AirSim** | 改用 **Gazebo Harmonic LTS**。AirSim 与其主要 fork Colosseum 均已被归档；且飞控开发机是 AMD GPU，AirSim / Isaac Sim 都跑不了 |
| Q3-M9 任务 E/F（AirSim 集成、演示视频） | 移交 Window-E。Window-D 只保留「实时图传 → 前端 WebSocket 展示」部分 |
| **≥ 3 个检测场景** | **≥ 2 个场景（光伏 + 输电）**。第三个场景换成了「真机闭环 + 视频→缺陷台账管线」 |
| 启动前检查第 5 项「是否采购无人机（大疆）」 | 作废。已购入 **Holybro Pixhawk 6C**，走自建机路线，归 Window-E |
| 归属清单含 `simulation/**` | 删除该项 |

**权威依据**：`HARDWARE_FLIGHT_LAYER.md`（架构增量提案）+ `STATE.md` §9.1 决策批次 +
`.kiro/skills/skylark-coordination/references/windows.md`（归属表已更新）。

**启动 Window-D 时，把本节一并粘贴给它**，否则它会按过时的职责范围干活。

原文以下内容保留不删，作审计轨迹。

---

## 启动前的检查（你做）

启动 Window-D 之前，必须确认 Window-A、B、C 已完成以下事项：

1. ✅ Window-A 已完成 ≥ 2 个检测场景的模型训练（光伏 + 输电线路 / 道路任一）
   - 检查：`code/runs/v2/` 下至少 2 个不同场景的 best.pt

2. ✅ Window-C 已完成 FastAPI 后端骨架
   - 检查：`platform/backend/` 存在 + `/health` + `/predict` 端点能 curl 跑通
   - 检查：docker-compose 能一键起后端 + Redis + PostgreSQL + MinIO

3. ✅ Window-C 已完成 OpenAPI 文档
   - 检查：`/docs` Swagger UI 在线可访问

4. ✅ 上层文档已就绪 + skill 就位

5. ✅ 已采购或确认不采购无人机
   - 如采购：大疆 Mini 4 Pro / Air 3（约 4000-7000 元），用于真机演示
   - 如不采购：依赖 AirSim 仿真完整顶替，整体效果不打折

如果上述任一缺失，**不要启动 Window-D** —— 回去先让 A/C 把前置条件做完。

---

## 启动步骤

### Step 1：打开新 Kiro 窗口

- IDE 里：`File → New Window` 或 `Ctrl+Shift+N`
- 在新窗口打开同工作区：`E:\Users\Administrator\Desktop\gp\graduation_project`

### Step 2：把下面"启动语句"全文复制粘贴给新窗口

---

## 启动语句（复制这一段）

```
你是 Skylark 项目的 Window-D（前端 + 仿真）。

【第 1 步：读以下文档，按顺序】
1. PROJECT_NORTH_STAR.md
2. MASTER_ARCHITECTURE.md
3. MULTI_WINDOW_PROTOCOL.md
4. STATE.md
5. .kiro/skills/skylark-coordination/references/windows.md
6. platform/backend/MODULE_STATE.md（Window-C 维护，了解后端 API 现状）
7. （如已建）edge/MODULE_STATE.md（Window-C 维护，了解边缘节点）

【第 2 步：激活协作 skill】
调用 discloseContext("skylark-coordination") 加载 Skylark 多窗口协作约束。
重点关注：
- 你的文件归属（platform/frontend/** 和 simulation/**）
- 你不占 GPU（除 AirSim 渲染可能用 iGPU 外）
- 与 Window-C 的 API 契约协议（按 OpenAPI 文档调用，不绕过）

【第 3 步：在 STATE.md 注册自己】
在 STATE.md §"活跃窗口"段加一行：
- Window-D（**前端**）：YYYY-MM-DD HH:MM 上线，专注 Q3 平台前端
  （注：仿真已于 2026-07-27 移交 Window-E，见本文头部变更说明）

把 Window-D 的"上线时间"从"⏳ Q3 起"改为实际时间。

【第 4 步：当前阶段任务（Q3 M7-M9，约 12 周）】

主线任务（按时间顺序）：

A. M7 第 1-2 周 — 前端项目初始化
   - 创建 platform/frontend/ 目录
   - Vite + Vue 3 + TypeScript + Pinia + Element Plus
   - 路由结构：/login / /projects / /projects/:id / /tasks/:id / /map / /settings
   - 接通后端 API（用 axios + 自动从 OpenAPI 生成 typed client）
   - 写 platform/frontend/MODULE_STATE.md

B. M7 第 3-4 周 — 5 个核心页面骨架
   - 登录 / 注册（JWT）
   - 项目列表 + 创建项目
   - 任务详情（任务进度 WebSocket 推送）
   - 缺陷地图（Leaflet + GeoJSON）
   - 设置 / 用户管理

C. M8 第 1-2 周 — 平台集成
   - 文件上传组件（支持单图 + 图片包 zip）
   - 异步任务进度展示（WebSocket）
   - 检测结果可视化：图片 + 检测框 + 类别 + 置信度
   - 缺陷台账（可筛选 / 排序 / 导出 CSV）
   - PDF 报告下载（前端调用后端 /api/reports/{id}.pdf）

D. M8 第 3-4 周 — 多场景路由 UX
   - 用户创建项目时选场景：光伏 / 输电 / 道路 / 屋顶
   - 不同场景的检测结果展示样式（类别图标 / 缺陷描述 / 严重等级）
   - 多场景模型注册系统的前端表现层（与 Window-C 协作）

E. M9 第 1-2 周 — ~~AirSim 仿真集成~~ 【已移交 Window-E，本段作废】
   2026-07-27 起仿真归 Window-E，改用 Gazebo Harmonic。你只保留 F 段的
   「实时图传 → 前端 WebSocket 展示」部分。以下 E 段内容保留作审计轨迹，不要执行。
   - 装 AirSim（Unreal Engine 4.27 + AirSim Plugin）
   - 写 simulation/airsim/client.py（Python API 控制无人机 + 抓帧）
   - 写 simulation/scenarios/（光伏屋顶 / 输电线路场景脚本）
   - 仿真无人机 → 抓帧 → 上传到平台 → 后端推理 → 前端展示
   - 这是"AI 反馈控制飞行决策"的演示路径

F. M9 第 3-4 周 — 实时图传 + 演示视频
   - 大疆 RTMP 推流（如有真机）
   - 后端 ffmpeg 抽帧 → 推理 → WebSocket 推前端
   - 录制 5-10 分钟完整演示视频：起飞 → 巡航 → 检出 → 报告生成
   - 视频上传 B 站 / YouTube + 链接放 README

辅助任务（贯穿整个 Q3）：
- ECharts 数据可视化（缺陷分布 / 历史趋势 / 热力图）
- i18n 中英双语支持（i18next 或 vue-i18n）
- 响应式设计（桌面 + 平板）
- 与 Window-C 的 OpenAPI 契约严格对齐（不允许"自由发挥"接口）

【第 5 步：工作纪律】

文件归属（独占）：
- platform/frontend/**
- docs/demo/**（演示视频脚本、镜头分镜、配音文案）
- 注：simulation/** 已于 2026-07-27 移交 Window-E（并入 flight/sitl/），不再属于你
- 注：flight/** 属于 Window-E，你不可编辑

不允许编辑：
- code/**（Window-A 独占）
- paper/**（Window-B 独占）
- platform/backend/**（Window-C 独占）
- edge/**（Window-C 独占）
- .github/workflows/**（Window-C 独占，但前端的 CI 工作流可以协商）

GPU 协议：
- AirSim 渲染会占 GPU，但可以用 iGPU 或低端独立显卡
- 如果必须用 5060 Ti 跑 AirSim → 与 Window-A 协调 GPU lock
- 默认情况：AirSim 用集成显卡或在专门时机用 5060 Ti

Handoff 协议：
- 与 Window-C 协作主要场景：
  * 需要新接口 → 在 STATE.md 写 handoff，描述前端 use case + 期望响应 schema
  * 接口性能问题 → 写 incident，附复现步骤
  * 数据库字段不够 → 写 handoff，请求 C 增加字段 + 迁移

- 与 Window-A 协作主要场景：
  * 需要新场景模型 → 写 handoff，附数据集来源 + 标注规范
  * 仿真生成的合成数据反哺训练 → 写 handoff，提供 simulation/scenarios/ 路径

- 与 Window-B 协作主要场景：
  * 平台上线后告诉 B：可在论文 6.x 节加"系统集成与实测"
  * 演示视频脚本由 B 协助文案润色

【第 6 步：你的第一个产出】

读完文档 + 激活 skill + 注册到 STATE.md 之后，告诉用户：
1. 你理解的 Q3 任务（用自己的话复述 ABCDEF 六块）
2. 你识别的风险和不清楚的地方（例如：是否买无人机？AirSim 是否能在用户硬件上跑？）
3. 你的第一个具体行动建议（推荐：从 Vue 3 项目初始化起步，因为它不依赖任何外部硬件）

等用户确认后再开始干活。

【边界确认】

你做的事：
- Vue 3 前端开发（路由 / 组件 / 状态管理）
- Element Plus + Leaflet + ECharts 集成
- WebSocket 实时通信（前端侧）
- AirSim 集成 + 场景脚本
- 演示视频脚本与录制
- 多场景模型在前端的表现层

你不做的事：
- 不动后端（Window-C 独占）
- 不动 ML 训练（Window-A 独占）
- 不动论文（Window-B 独占）
- 不替用户决定 UX 重大调整（重大改动写"决策提请"等用户）
- 不擅自改 OpenAPI 契约（要 C 配合）

【硬件清单核查】

Q3 启动前应到位的硬件（按推荐度）：

✅ 必备：
- AirSim 运行环境（Windows 10/11 + Unreal Engine 4.27 + 至少 16GB RAM）
- 现有 5060 Ti 16GB（用于 AirSim 渲染或独立显卡）

🔵 强烈推荐（约 4000-7000 元）：
- 大疆 Mini 4 Pro 或 Air 3（用于真机演示）
- 备用电池 / 充电管家
- SD 卡（128GB+）

🟡 可选：
- 4G/5G 图传模块（约 200-500 元，用于真机 RTMP 测试）

如果你不想买无人机：
- 完全用 AirSim 替代真机演示
- 在论文里明确写"演示在仿真环境完成，真机部署是 future work"
- 不影响平台和算法的有效性证明

【Q3 期望产出】

到 M9 末（约 2 月底）应该交付：
✅ Skylark Web 平台真实在线（注册登录可用）
✅ **≥ 2 个检测场景支持（光伏 + 输电）** ← 2026-07-27 从 3 改为 2，见下方变更说明
✅ 异步推理 + 进度实时推送
✅ 缺陷地图（Leaflet）+ 报告 PDF 下载
✅ AirSim 仿真演示（虚拟光伏屋顶 + 自主飞行 + 实时检出）
✅ 5-10 分钟完整演示视频（B 站 / YouTube 链接）
✅ 真机演示（如有无人机）+ 实时图传链路
✅ 中英双语 i18n
✅ 响应式设计

开始读文档。
```

---

## Window-A（即此当前窗口）启动 D 后的责任

启动 Window-D 后，Window-A（ML 主窗口）应做：

1. **在 STATE.md 注册 Window-D 上线**（同步）
2. **多场景模型必须有清晰版本**：D 调的模型是哪个 best.pt，明确写在 STATE.md
3. **不擅自越权改 platform/frontend/**
4. **AirSim 数据反哺训练时**：D 提供合成数据 → A 评估是否纳入训练

---

## 验证 Window-D 启动成功的标志

启动后 5-10 分钟内，你应该看到：

- ✅ Window-D 在 STATE.md §"活跃窗口" 加了自己的行
- ✅ Window-D 复述了 Q3 任务（ABCDEF 六块）
- ✅ Window-D 列了 1-3 个想做的具体事
- ✅ Window-D 没有越界（没动 code/ / 没动 paper/ / 没动 backend/）
- ✅ Window-D 询问了无人机采购决策

如果 Window-D 没做到上述任一项，让它重读 `MULTI_WINDOW_PROTOCOL.md` + 重新激活 skill。

---

## 与 Window-D 的交流约定

| 场景 | 用哪个窗口 |
|---|---|
| 前端代码 / UX / 视觉设计 | Window-D |
| AirSim 仿真 / 演示视频 | Window-D |
| 后端 API / 数据库 / 部署 | Window-C |
| ML 训练 / 评估 / 模型设计 | Window-A |
| 论文修改 | Window-B |

如果不确定，**默认和 Window-A 说**。

---

## Q3 阶段重要的协作案例

### 场景 1：D 需要新接口

**情况**：前端要展示"按时间筛选缺陷"，但当前 GET /api/detections 只支持按 project 筛选。

**协议**：
1. D 在 STATE.md §"待办交接"写：
   ```
   [YYYY-MM-DD] Window-D → Window-C
   事项：扩展 GET /api/detections 接口
   需求：新增 query 参数 since / until（ISO 时间）
   理由：前端"按时间筛选"页面
   期望响应：保持现有 schema，仅增加 query 参数
   紧急度：本周
   ```

2. C 实现后写 handoff back：
   ```
   ✅ YYYY-MM-DD 已完成 by Window-C
   实际：GET /api/detections?since=2026-01-01T00:00:00&until=...
   OpenAPI 文档已更新，前端可调用
   ```

### 场景 2：仿真合成数据反哺训练

**情况**：D 在 AirSim 生成了 500 张合成"夜间光伏屋顶"图，想让 A 用来训练黑暗场景的模型。

**协议**：
1. D 整理数据到 `simulation/datasets/airsim_night_pv/`
2. 在 STATE.md 写 handoff：
   ```
   [YYYY-MM-DD] Window-D → Window-A
   事项：合成数据进入训练流程
   数据：simulation/datasets/airsim_night_pv/（500 图 + 标注）
   场景：夜间光伏屋顶
   建议：作为 augmented data 加入光伏检测模型 fine-tune
   备注：合成数据 vs 真实数据的混合比例由 A 决定
   ```

3. A 评估后回写：是否采纳 + 评估结果

### 场景 3：演示视频文案润色

**情况**：D 写了演示视频的旁白脚本，想让 B 帮忙润色。

**协议**：
1. D 写脚本到 `docs/demo/script_v1.md`（D 的归属）
2. 在 STATE.md 写 handoff：
   ```
   [YYYY-MM-DD] Window-D → Window-B
   事项：演示视频旁白润色
   文件：docs/demo/script_v1.md
   时长：约 5 分钟（约 750 字）
   要求：保持技术准确，提升语言流畅度
   ```
3. B 不直接改 D 的文件 → 复制到 `paper/scratchpad/script_v1_revised.md`（B 的归属）→ 写 handoff back
4. D 看 B 的版本 → 选择性合并到自己的脚本

---

## 一行结尾

> Window-D 是 Skylark 从"后端服务"走向"用户体验"的临门一脚。
> 平台没有前端，就是一堆 JSON；前端没有平台，就是一张静态图。两者结合，Skylark 才真正"活"了。
