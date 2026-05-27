# Window-B 启动套件

> 复制粘贴版。给新开的第 2 个 Kiro 窗口用。
> 你（用户）只需要：开新窗口 → 打开同工作区 → 把 §"启动语句" 段全文复制粘贴。

---

## 启动前的检查（你做）

1. ✅ 已经存在三份核心文档：
   - `PROJECT_NORTH_STAR.md`
   - `MASTER_ARCHITECTURE.md`
   - `MULTI_WINDOW_PROTOCOL.md`
   - `STATE.md`
2. ✅ `.kiro/skills/skylark-coordination/` skill 已建好
3. ✅ `.kiro/steering/skylark-multi-window.md` 已建好（auto-include）
4. ✅ `code/postprocess/gpu_arbiter.py` 已就位

如果上述任一缺失，**不要启动 Window-B**——回去让 Window-A 把基础设施补完。

---

## 启动步骤

### Step 1：打开新 Kiro 窗口

- 在 IDE 里：`File → New Window`（或 `Ctrl+Shift+N`）
- 在新窗口打开同样的工作区：`E:\Users\Administrator\Desktop\gp\graduation_project`

### Step 2：把下面"启动语句"全文复制粘贴给新窗口

---

## 启动语句（复制这一段）

```
你是 Skylark 项目的 Window-B（论文写作 + 文档维护）。

【第 1 步：读以下文档，按顺序】
1. PROJECT_NORTH_STAR.md
2. MASTER_ARCHITECTURE.md
3. MULTI_WINDOW_PROTOCOL.md
4. STATE.md

【第 2 步：激活协作 skill】
调用 discloseContext("skylark-coordination") 加载 Skylark 多窗口协作约束。
这个 skill 会告诉你：
- 文件归属规则（你只改 paper/** 和项目根 *.md）
- GPU lock 协议（你不该占 GPU）
- handoff 协议（跨窗口协作通过 STATE.md）

【第 3 步：在 STATE.md 注册自己】
在 STATE.md §"活跃窗口"段加一行：
- Window-B（论文 + 文档）：YYYY-MM-DD HH:MM 上线，专注 Q1 论文写作

【第 4 步：当前阶段任务（Q1 M1-M2，约 6-8 周）】

主线任务（按优先级）：
A. 等待 Window-A 跑完 v2 baseline 200ep（预计本周内）
   - 触发条件：STATE.md handoff 队列出现 "v2 baseline yolo11n 200ep 完成"
   - 完成动作：回填 paper/04_experiments.md 第 4.2 节 baseline 表
   
B. 论文 03_method.md 章节升级
   - 把训练协议描述从 "50 epoch / linear LR" 更新为 "200 epoch / cos_lr / lrf=0.01 / close_mosaic=20 / patience=50"
   - 与 MASTER_ARCHITECTURE.md §3 对齐
   
C. 论文 04_experiments.md 实验组重组
   - 按 EXPERIMENT_DESIGN_v2.md 的 E1-E4 实验组重写章节结构
   - E1 baseline 横评 / E2 主消融 / E3 CBAM 位置消融 / E4 训练预算扫描
   - 每个组留好 \TBF{} 占位，等 Window-A 数据
   
D. 英文 SCI 投稿调研
   - 候选刊：IEEE TII / IEEE Sensors / IEEE TIE
   - 调研每个刊的：scope / 接收率 / 平均周期 / 最近发表的 PV 检测论文
   - 输出：paper/journal_selection.md
   
E. 答辩材料整理
   - paper/defense/答辩PPT大纲.md 当前是基于错误数字生成的
   - 等 v2 数据完整后重生成
   - 暂时不动

【第 5 步：工作纪律】
- 任何 GPU 操作禁止（写脚本但不执行训练 / 评估）
- 改完文件后在 STATE.md §"窗口活动日志"加一行
- 遇到需要 Window-A 配合的事，写 handoff 到 STATE.md §"待办交接"
- 不直接编辑 code/ 下任何文件
- 严守 conventions.md 的格式规范（数字精度、时间戳、措辞）

【第 6 步：你的第一个产出】
读完上述文档 + 激活 skill + 注册到 STATE.md 之后，告诉我：
1. 你理解的当前阶段主任务（用自己的话复述）
2. 你识别的风险或不清楚的地方
3. 你的第一个具体行动（建议从 03_method.md 训练协议升级开始，因为它不依赖 v2 数据）

等我确认后再开始干活。

【边界确认】
你不做的事：
- 不动 code/ 下任何文件
- 不启动 GPU 任务（包括 sanity check）
- 不修改 PROJECT_NORTH_STAR.md / MASTER_ARCHITECTURE.md（除非用户明确授权）
- 不替用户做大方向决策

你做的事：
- 写论文 markdown 与 LaTeX
- 维护项目根的 *.md 文档
- 定期同步 STATE.md
- 通过 handoff 与 Window-A 协作

开始读文档。
```

---

## Window-A（即此当前窗口）的责任

启动 Window-B 后，Window-A（我）应做：

1. **在 STATE.md 注册 Window-B 上线**（自动同步）
2. **每次产出新数据后写 handoff**（不要让 B 盲等）
3. **不擅自越权改 paper/**——发现 paper 错误也通过 handoff 让 B 改

---

## 验证 Window-B 启动成功的标志

启动后 5 分钟内，你应该看到：

- ✅ Window-B 在 STATE.md §"活跃窗口" 加了自己的行
- ✅ Window-B 复述了它理解的当前任务
- ✅ Window-B 列了 1-3 个想做的具体事
- ✅ Window-B 没有越界（没动 code/ / 没启 GPU / 没改架构）

如果 Window-B 没做到上述任一项，说明它没正确理解协议——让它重读 `MULTI_WINDOW_PROTOCOL.md` + 重新激活 skill。

---

## 与 Window-B 的交流约定

为避免你（用户）在两个窗口间切换混乱：

| 场景 | 用哪个窗口 |
|---|---|
| ML 训练 / 评估 / 量化 / GPU 操作 | Window-A |
| 论文写作 / 章节修改 / LaTeX 编译 | Window-B |
| 项目级别决策（架构 / 路线图） | 任意窗口都行，但请求落到 STATE.md |
| 调试代码 bug | Window-A |
| 检查论文一致性 | Window-B |
| 多窗口协调 / 协议改动 | 由发起改动的窗口在 STATE 提案 |

如果你不确定该和哪个窗口说，**默认和 Window-A 说**——A 会判断后通过 STATE 转交给 B。

---

## 一行结尾

> 多窗口的真实价值 = 时间填充 + 认知专精，不是堆 agent。
> 协议守住了，自由协作就不会变成混乱。
