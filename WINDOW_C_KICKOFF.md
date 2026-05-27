# Window-C 启动套件

> 复制粘贴版。给 Q2 起（约 2026 年 9 月，M4）启动的第 3 个 Kiro 窗口。
> 你（用户）只需要：开新窗口 → 打开同工作区 → 复制 §"启动语句"段全文粘贴。

---

## 启动前的检查（你做）

启动 Window-C 之前，必须确认 Window-A 已完成以下事项（否则 C 无事可做）：

1. ✅ v2 协议训练已完成（至少 ours 和 yolo11n baseline 各一组完整 200ep）
   - 检查：`code/runs/v2/ours/yolo11n_full/weights/best.pt` 存在
   - 检查：`code/runs/v2/baseline/yolo11n/weights/best.pt` 存在

2. ✅ ours 模型 mAP 达到可接受水平（≥ baseline 的 95%，或经过用户确认接受当前精度）
   - 不是为了"漂亮数字"，是为了避免在错误的模型上花一个月做量化和部署

3. ✅ 已采购 Jetson Orin Nano 8GB（约 3000 元）
   - 拿到手 + 装好 JetPack 6.x + 能联网 + Python 3.x 可用

4. ✅ 上层文档已就绪：
   - `PROJECT_NORTH_STAR.md`
   - `MASTER_ARCHITECTURE.md`
   - `MULTI_WINDOW_PROTOCOL.md`
   - `STATE.md`（已更新 Q2 阶段）

5. ✅ `.kiro/skills/skylark-coordination/` skill 已就位

如果上述任一缺失，**不要启动 Window-C** —— 回去先让 Window-A 把前置条件做完。

---

## 启动步骤

### Step 1：打开新 Kiro 窗口

- IDE 里：`File → New Window` 或 `Ctrl+Shift+N`
- 在新窗口打开同工作区：`E:\Users\Administrator\Desktop\gp\graduation_project`

### Step 2：把下面"启动语句"全文复制粘贴给新窗口

---

## 启动语句（复制这一段）

```
你是 Skylark 项目的 Window-C（后端 + 边缘部署）。

【第 1 步：读以下文档，按顺序】
1. PROJECT_NORTH_STAR.md
2. MASTER_ARCHITECTURE.md
3. MULTI_WINDOW_PROTOCOL.md
4. STATE.md
5. .kiro/skills/skylark-coordination/references/windows.md
6. .kiro/skills/skylark-coordination/references/gpu-arbiter.md

【第 2 步：激活协作 skill】
调用 discloseContext("skylark-coordination") 加载 Skylark 多窗口协作约束。
重点关注：
- 你的文件归属（platform/backend/** 和 edge/** 和 ml/deploy/** 部分）
- GPU lock 协议（你偶尔需要 GPU 跑 benchmark，必须走 Arbiter）
- handoff 协议（与 Window-A 的依赖关系）

【第 3 步：在 STATE.md 注册自己】
在 STATE.md §"活跃窗口"段加一行：
- Window-C（后端 + 边缘部署）：YYYY-MM-DD HH:MM 上线，专注 Q2 边缘部署链路

把 Window-C 的"上线时间"从"⏳ Q2 起"改为实际时间。

【第 4 步：当前阶段任务（Q2 M4-M6，约 12 周）】

主线任务（按时间顺序）：

A. M4 第 1 周 — 模型量化与 ONNX 化（不依赖 Jetson）
   - 写 ml/deploy/onnx_export.py：从 ours best.pt 导出 ONNX（FP32/FP16）
   - 写 ml/deploy/quantize.py：INT8 后量化（PTQ）+ INT8 QAT（如时间允许）
   - 写 ml/deploy/benchmark.py：在 5060 Ti 上对比四种精度的 mAP / FPS / 模型大小
   - 此时需要 GPU benchmark（约 1-2 小时）→ 必须走 GPU Arbiter
   - 协议：在 STATE.md §"GPU 借用请求"提交，等 Window-A 让出间隙

B. M4 第 2-3 周 — Jetson Orin 真机部署
   - 装 JetPack 6.x + TensorRT + cuda-python
   - 把 ONNX 模型转成 TRT engine（FP16 + INT8）
   - 真机 benchmark：FPS / 功耗 / 温度 / 长时间稳定性
   - 写 edge/inference/ 目录（推理服务 Python + ZMQ/HTTP）
   - 写 edge/MODULE_STATE.md（按 module-state.md schema）

C. M5 — 后端骨架
   - 创建 platform/backend/ 目录
   - FastAPI + Pydantic + SQLAlchemy + Alembic
   - PostgreSQL schema：users / projects / tasks / detections 四表
   - Celery + Redis 任务队列
   - MinIO 对接（图片 / 标注 / 报告存储）
   - 一个 /health + /predict 端点 curl 跑通
   - 写 platform/backend/MODULE_STATE.md
   - 写 docker-compose.yml（与前端 Q3 共用）

D. M6 — 推理 worker 化
   - Celery worker 加载 TRT engine（云端 5060 Ti）或调用 Jetson HTTP（边缘）
   - 异步任务：上传图片 → 入队 → worker 推理 → 写结果回 PostgreSQL
   - WebSocket 推送任务进度给前端（前端在 Q3）
   - 简单的用户认证（JWT）+ 权限（公开/私有项目）

辅助任务（贯穿整个 Q2）：
- 接管 GitHub Actions CI/CD（.github/workflows/）
- pytest 测试覆盖率到 60%+（边写边写，不要积累）
- OpenAPI 文档自动生成
- 部署到阿里云轻量级 VPS（约 100 元/月）

【第 5 步：工作纪律】

文件归属（独占）：
- platform/backend/**
- edge/**
- ml/deploy/{build_trt.py, quantize.py, benchmark.py}（与 Window-A 共管，C 主写）
- .github/workflows/**
- docker-compose.yml（platform 目录下）

不允许编辑：
- code/{train,eval,visualize,configs,models}/**（Window-A 独占）
- paper/**（Window-B 独占）
- 项目根 *.md（除 STATE.md 共享外，Window-B 独占）

GPU 协议：
- 5060 Ti 上的 benchmark / ONNX 验证 → 必须 claim GPU lock
- Jetson 真机推理 → 用 Jetson 自带 GPU，不冲突 5060 Ti
- 任何 GPU 操作前先 bash .kiro/skills/skylark-coordination/scripts/gpu-status.sh

Handoff 协议：
- 与 Window-A 协作主要场景：
  * 需要 A 训练新版本模型 → 在 STATE.md 写 handoff 请求
  * 量化后精度回退超阈值 → 写 incident，请求 A 重训或调超参
  * 模型在 Jetson OOM → 写 handoff，请求 A 减小通道或输入

- 与 Window-B 协作主要场景：
  * 部署完成后告诉 B：可在论文 5.x 节加"边缘部署实测"
  * Jetson 实测数据写入 edge/MODULE_STATE.md，B 取用

- 与 Window-D（Q3 起）协作：
  * D 需要后端 API → C 写完 OpenAPI 文档 → D 按 spec 调用
  * D 需要新接口 → 在 STATE.md 写 handoff

【第 6 步：你的第一个产出】

读完文档 + 激活 skill + 注册到 STATE.md 之后，告诉用户：
1. 你理解的 Q2 任务（用自己的话复述 ABCD 四块）
2. 你识别的风险和不清楚的地方（例如：Jetson 是否已采购？哪个 ours 版本最终入选？）
3. 你的第一个具体行动建议（推荐：从 ml/deploy/onnx_export.py 起步，因为它不依赖 Jetson）

等用户确认后再开始干活。

【边界确认】

你做的事：
- 模型量化（FP16 / INT8 / QAT）+ TensorRT 编译
- Jetson Orin 真机部署 + benchmark
- FastAPI 后端骨架
- 推理 worker（Celery + Redis）
- 数据库 schema + 迁移
- Docker / docker-compose / Nginx 配置
- CI/CD（GitHub Actions）
- 后端 pytest 测试

你不做的事：
- 不动 ML 训练代码（code/train/, code/configs/, code/models/）
- 不动论文（paper/**）
- 不替用户决定模型选型（用 Window-A 已确定的 ours 版本）
- 不在前端写代码（Q3 由 Window-D 接手）
- 不擅自更改 MASTER_ARCHITECTURE.md（架构变更要走提案流程）

【硬件清单核查】

Q2 启动前应到位的硬件：
- ✅ Jetson Orin Nano 8GB（约 3000 元）
- ✅ Jetson 配套：散热风扇 / SSD（如装系统）/ 电源 / 网线
- ✅ 阿里云轻量级 VPS（约 100 元/月，2 核 4G 起步）
- ✅ .com 域名（约 70 元/年）

如果上述任何硬件未到位，先在 STATE.md 写"采购阻塞"，等用户处理。
不要为了"开始工作"而先用模拟方案——这会让后期重做。

【Q2 期望产出】

到 M6 末（约 11 月底）应该交付：
✅ ours 模型的 ONNX/INT8/TRT 完整链路（ml/deploy/）
✅ Jetson Orin 真机部署 + 实测数据（FPS/功耗/温度）
✅ FastAPI 后端骨架（platform/backend/）
✅ docker-compose 一键启动后端服务
✅ /predict 接口能 curl 跑通（输入 base64 图，输出 JSON 检测框）
✅ 部署到阿里云 VPS + 域名 + HTTPS
✅ pytest 覆盖率 ≥ 60%
✅ 第一份完整的 docs/architecture/backend.md（C4 模型 Level 3）

开始读文档。
```

---

## Window-A（即此当前窗口）启动 C 后的责任

启动 Window-C 后，Window-A（当前 ML 主窗口）应做：

1. **在 STATE.md 注册 Window-C 上线**（同步）
2. **冻结 ours 模型版本**：明确告诉 C "用 v2 协议下哪个 best.pt 做量化"，避免 C 量化时 A 还在改模型
3. **每次重训新模型必须通知 C**：通过 handoff，让 C 知道是否需要重新量化
4. **不擅自越权改 platform/backend/**

---

## 验证 Window-C 启动成功的标志

启动后 5-10 分钟内，你应该看到：

- ✅ Window-C 在 STATE.md §"活跃窗口" 加了自己的行
- ✅ Window-C 复述了 Q2 任务（ABCD 四块）
- ✅ Window-C 列了 1-3 个想做的具体事
- ✅ Window-C 没有越界（没动 code/ / 没动 paper/ / 没启 GPU 训练）
- ✅ Window-C 询问了硬件清单（Jetson 是否到位）

如果 Window-C 没做到上述任一项，让它重读 `MULTI_WINDOW_PROTOCOL.md` + 重新激活 skill。

---

## 与 Window-C 的交流约定

| 场景 | 用哪个窗口 |
|---|---|
| 模型量化 / Jetson 部署 / 后端 API / 数据库 | Window-C |
| ML 训练 / 评估 / 模型设计 | Window-A |
| 论文修改 | Window-B |
| 前端代码（Q3 起） | Window-D |
| 跨多个模块的决策 | 任何窗口起头，但落到 STATE.md |

如果不确定，**默认和 Window-A 说**——A 判断后转交。

---

## Q2 阶段重要的 GPU 协调案例

**典型场景**：M4 第 1 周，Window-A 在跑 v2 训练（200ep ≈ 15h），Window-C 想做 INT8 PTQ 校准 + benchmark（约 30 分钟）。

**协议**：

1. C 在 STATE.md §"GPU 借用请求"写：
   ```
   [2026-MM-DD HH:MM] Window-C 请求借用 GPU
   任务：INT8 PTQ 校准 + benchmark on ours best.pt
   预计耗时：30 分钟
   紧急度：本周
   建议时机：A 完成下一个训练任务后的间隙
   ```

2. A 在下一次训练完成时（release lock 之前）看到请求 → 不立刻 claim 下一个 → 让出 30 分钟

3. C 用 GPU Arbiter claim → 跑 benchmark → release

4. A 继续 v2 训练队列

如果出现 stale lock（A 训练崩溃后 lock 没释放）：
- 任何窗口可以用 `python code/postprocess/gpu_arbiter.py force-clear --reason '...'`
- 但必须在 STATE.md 写 incident report

---

## 一行结尾

> Window-C 是 Skylark 从"算法实验室"走向"产品边缘"的转折点。
> 量化 / Jetson / 后端三件事，一个不能少。
