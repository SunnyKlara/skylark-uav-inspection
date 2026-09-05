# 窗口角色与文件归属

## 4 个窗口

| 窗口 | 角色 | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|
| **Window-A** | ML 主线 | ✅ 活跃 | ✅ | ✅ | ✅ |
| **Window-B** | 论文 + 文档 | ✅ 活跃 | ✅ | ✅ | ✅ |
| **Window-C** | 后端 + 边缘 | — | ✅ 启动 | ✅ | ✅ |
| **Window-D** | 前端 | — | — | ✅ 启动 | ✅ |
| **Window-E** | 飞控 + 仿真 | ✅ 已启动<br>（低强度并行） | ✅ | ✅ | ✅ |

> **2026-07-27 变更**：新增 Window-E（飞控 + 仿真）。原属 Window-D 的 `simulation/` 并入
> Window-E 的 `flight/sitl/`（Gazebo 世界与 PX4 SITL 是一件事）。Window-D 收缩为纯前端。
> 完整理由见 `HARDWARE_FLIGHT_LAYER.md` §2.3。
>
> Window-E 在 Q1 即启动，但**低强度并行**（每周 3-5 小时，优先安排在 v2 训练等待时段）。
> 允许 Q1 启动的前提是：它跑在**另一台机器**上（AMD GPU，无 CUDA），不与 v2 训练抢 GPU。

## 文件归属表（精确版）

### Window-A（ML 主线）独占

```
code/configs/**            # YAML 模型配置
code/data/**               # 数据集准备脚本
code/eval/**               # 评估脚本
code/models/**             # 自定义模块（CBAM/EMA/BiFPN + register patch）
code/postprocess/**        # 实验后处理（除 gpu_arbiter 外）
code/runs/**               # 训练输出（除 .gpu_lock.json 外）
code/setup/**              # 环境验证
code/train/**              # 训练脚本
code/visualize/**          # 可视化脚本
code/yolo*.pt              # 预训练权重文件
code/run_pipeline*.py      # 流水线编排
code/_daemon_run*.bat      # daemon 启动脚本
code/0*.bat                # 一键脚本
ml/deploy/export_*.py      # ONNX 导出（Q2 起）
edge/inference/**          # Jetson 推理服务（Q2 起，与 Window-C 共管）
```

### Window-B（论文 + 文档）独占

```
paper/**                   # 中文 markdown + LaTeX
paper/tex/**
paper/defense/**
paper/figures/**

# 项目根的所有顶层文档
PROJECT_NORTH_STAR.md
MASTER_ARCHITECTURE.md
MULTI_WINDOW_PROTOCOL.md
STATE.md                   # 共写但 B 主导
EXPERIMENT_DESIGN_v2.md
FINALIZE_README.md
README.md                  # 项目主入口
01_课题立项.md
02_M1_第一个月作战图.md
03_数据集与代码资源.md
04_本周行动清单.md

# 后续可能新增
WINDOW_B_KICKOFF.md
WINDOW_C_KICKOFF.md
WINDOW_D_KICKOFF.md
docs/architecture/**       # Q2 起架构文档
docs/api/**                # Q2 起 OpenAPI 文档
docs/deployment/**         # Q3 起部署手册
docs/user-manual/**        # Q3 起用户手册
```

### Window-C（后端 + 边缘）独占（Q2 起）

```
platform/backend/**        # FastAPI 后端
edge/**                    # Jetson 部署（除 inference 外，与 A 共管）
ml/deploy/build_trt.py     # TensorRT 编译
ml/deploy/quantize.py      # INT8 量化
.github/workflows/**       # CI/CD
docker-compose.yml         # platform 目录下
```

### Window-D（前端）独占（Q3 起）

```
platform/frontend/**       # Vue 3 前端
docs/demo/**               # 演示视频脚本
```

> 原列的 `simulation/**` 已移交 Window-E（并入 `flight/sitl/`）。

### Window-E（飞控 + 仿真）独占（2026-07-27 起）

```
flight/**                  # 飞控层全部内容
├── ros2_ws/src/skylark_*/ # 接口契约与 ROS 2 节点
├── params/**              # QGC 参数基线快照 + CHANGELOG
├── sitl/**                # PX4 SITL + Gazebo（原 simulation/）
├── tools/**               # dds_bandwidth.py 等
├── docs/**                # WIRING_6C / SERIAL_BUDGET / SAFETY_CHECKLIST
├── VERSIONS.md            # 版本锁定单一来源
└── MODULE_STATE.md

HARDWARE_FLIGHT_LAYER.md   # 飞控层架构提案（E 主写，B 追认）
```

**Window-E 的特殊约定**：

1. **不参与 GPU lock 协议**。它在另一台机器（AMD GPU，无 CUDA）上，与 ML 训练物理隔离
2. **版本号只在 `flight/VERSIONS.md` 一处定义**。其他文件引用它，不各自硬编
3. **`flight/params/` 下的 `.params` 必须是纯文本**，不用 `.gz` 或二进制格式 —— 否则 git diff 失去意义
4. **涉及硬件的操作必须由用户执行**（接线、上电、刷固件、飞行）。Window-E 只能写代码、写文档、做静态校验
5. **安全相关改动（失效保护参数、地理围栏、`Revisit` 的高度夹紧逻辑）必须在 `params/CHANGELOG.md` 留痕**

## 共享文件（特殊规则）

| 文件 | 共享窗口 | 协议 |
|---|---|---|
| `STATE.md` | A/B/C/D | 任意可改，编辑前后写时间戳；编辑窗口 < 30 秒 |
| `code/runs/.gpu_lock.json` | A 写 + C 写 + B/D 读 | 见 `gpu-arbiter.md` |
| `requirements.txt` | A 主 + C 追加 | 通过 STATE.md 协商，避免直接覆盖 |
| `code/postprocess/gpu_arbiter.py` | 所有窗口读，A 主写 | A 维护，但保持 API 稳定 |
| `.kiro/skills/skylark-coordination/**` | 所有窗口读，少改 | 改之前先在 STATE 提案，等用户确认 |
| `.kiro/steering/skylark-multi-window.md` | 所有窗口读，少改 | 同上 |

## 决策树：编辑前

```
我要编辑文件 X
   │
   ├── X 在我归属范围 → 直接改
   │
   ├── X 是共享文件 → 走对应特殊协议
   │
   └── X 在别人归属范围
         │
         ├── 我能直接联系归属窗口的人 → 让他改
         │
         └── 异步协作（最常见）
              │
              └── 在 STATE.md §"待办交接" 写 handoff 请求
                  + 等他完成
                  + 不要绕过去自己改
```

## 例外情况

**例外 1：紧急修复**

如果归属窗口当前不在线，且某个 bug 必须立刻修：
- 可以暂时越权改
- 改完立刻在 STATE.md 写"越权修复记录"+ 原因 + 修改详情
- 通知归属窗口（在 STATE 里 @）

**例外 2：跨模块影响的小改动**

例如 Window-C 改 platform/backend/ 时需要更新 README.md（B 归属）：
- 小改动（< 5 行）：直接改 + STATE 通知
- 大改动（> 5 行）：写 handoff

## Window-A 当前激活的具体目录

截至 2026-05-27，Skylark 处于 Q1 起步阶段。Window-A 实际活跃在：

```
✅ code/configs/           # 已有 8 个 yaml
✅ code/train/             # 已有 train_v2.py 等
✅ code/eval/              # 已有评估三件套
✅ code/visualize/         # 已有可视化三件套
✅ code/postprocess/       # 已有 collect/fill/build/finalize 等
✅ code/runs/              # daemon 在写 v1 数据
⏳ code/runs/v2/           # 待启动
⏳ ml/deploy/              # Q2 启动
⏳ edge/inference/         # Q2 启动
```

## Window-B 当前激活的具体目录

```
✅ paper/                  # 5 章 md 已有，5 处硬伤已修
✅ paper/tex/              # 中英 tex 已修
✅ paper/defense/          # 答辩材料（基于错误数字，需重做）
✅ 项目根 *.md             # NORTH_STAR / ARCHITECTURE / STATE 等
⏳ paper/04_experiments.md # 等 Window-A v2 数据回填
⏳ docs/                   # Q2 启动
```
