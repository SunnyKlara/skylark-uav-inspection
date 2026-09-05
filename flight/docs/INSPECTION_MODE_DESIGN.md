# `skylark_inspection_mode` 设计

> 状态：设计已定，实现未开始（2026-07-30）
> 依据：`skylark_flight_msgs` 的 `InspectSweep.action` / `Revisit.action` 契约，
> 以及 `OFFBOARD_CONSTRAINTS.md` 里实测到的 offboard 约束。
> 这份文档存在的目的是把「必须先定的判断」定下来，避免边写边改。

---

## 1. 它和 `skylark_autopilot_iface` 的分界

| | `autopilot_iface` | `inspection_mode` |
|---|---|---|
| 抽象层级 | 单个飞行动作 | 任务级编排 |
| 提供 | Takeoff / Land / Orbit + FlightHealth + VehicleState | InspectSweep / Revisit |
| 知道飞控细节 | 是（唯一一层） | **不知道** |
| 谁独占 setpoint | 是 | 通过 iface，不自己发 |

**关键决定：`inspection_mode` 不直接发 setpoint，也不订阅 `px4_msgs`。**

理由是实测约束：offboard 的 setpoint 流必须只有一个发布者，两个节点同时发会互相
打断，而且这种打断在日志里看不出来（两边都在正常发命令）。`autopilot_iface`
已经用一把「忙」标志把三个动作串行化了；再来一个进程发 setpoint 就绕过了那把锁。

**代价与取舍**：扫掠需要航点跟随，而 iface 现在没有这个动作。所以要在 iface 里
**新增一个内部动作**（暂名 `FollowPath`，不进契约包，只给 `inspection_mode` 用），
由 `inspection_mode` 把割草机航线算好后交给它执行。

替代方案是让 `inspection_mode` 自己发 setpoint —— 更省事，但会引入
「两个进程都能动飞机」的结构，这类问题一旦在真机上出现，代价远高于现在多写一个动作。
所以选前者。

---

## 2. 覆盖率校验：这是契约点名的硬要求

契约原文：「若 `row_spacing_m` 与相机视场、高度算出的重叠率低于 `min_overlap`，
服务端拒绝该 goal 并返回 `RESULT_REJECTED_COVERAGE`，而不是默默地漏拍。」

```
幅宽  swath_m   = 2 · altitude_agl_m · tan(camera_hfov_deg / 2)
重叠率 overlap  = 1 − row_spacing_m / swath_m
拒绝条件         overlap < min_overlap
```

### 真值：`mono_cam` 的水平视场是 1.74 rad = 99.7°

实测自 `Tools/simulation/gz/models/mono_cam/model.sdf:54`
（`<horizontal_fov>1.74</horizontal_fov>`，配 1280×960、30 Hz）。
核实脚本 `99_notes/_probe_hfov.sh`。

代入契约的默认参数看一下这道校验有多紧：

| 高度 | 幅宽 | 行距 6 m 时的重叠率 |
|---:|---:|---:|
| 10 m | 23.71 m | 74.7% |
| **15 m（契约默认）** | **35.56 m** | **83.1%** |
| 20 m | 47.41 m | 87.3% |
| 30 m | 71.12 m | 91.6% |

**结论要说清：这是个 99.7° 的超广角相机，默认参数下重叠率 83%，
远超 `min_overlap=0.25`。所以覆盖率校验在当前配置下几乎不会触发。**

不要因此以为这道校验没用 —— 它防的是两类真实错误：
把行距按真机窄视场相机（典型 60~70°）的经验值填、以及低空高分辨率作业
（3 m 高时幅宽仅 7.1 m，行距稍大就漏拍）。但也不要把它当成主要的质量保证，
真正的覆盖率风险在**航线跟踪误差**（Feedback 的 `cross_track_error_m`），
不在参数校验。

三个实现细节：

- `camera_hfov_deg = 0` 表示「由服务端从配置读」。**配置值必须可追溯到实际相机**，
  不能写死一个数。节点参数默认值取自上面那个 SDF 并在参数描述里注明出处；
  换相机（真机）时必须同步更新，否则覆盖率保证是假的。
- `swath_m` 用的是 `altitude_agl_m`，而 AGL 有两个来源（测距仪 / 起飞点推算，
  见 `VehicleState.agl_source`）。**起飞点推算在地形起伏时不可靠**，
  此时算出的覆盖率也不可靠。设计上：拒绝判据照算，但 Feedback 里如实带上
  `agl_source`，让调用方知道这个覆盖率保证有多硬。
- 重叠率是**相邻行之间**的横向重叠，与航向重叠（帧率 × 速度）是两件事。
  本动作只保证前者；航向重叠由 `speed_mps` 与相机帧率决定，
  实测帧率 25 fps @ 3 m/s 时帧间位移 0.12 m，远小于幅宽，不构成约束。

---

## 3. 航线生成

区域由两个 WGS84 对角点给出，`heading_deg` 指定扫掠行方向（应与光伏阵列长边对齐）。

```
1. 两个角点 -> 局部 NED（用 VehicleLocalPosition 的 ref_lat/ref_lon，
   等距圆柱近似；作业半径百米量级，误差远小于 GPS 自身误差）
2. 把矩形旋转到「行方向 = x 轴」的坐标系
3. 按 row_spacing_m 切行，行数 = ceil(横向跨度 / row_spacing) + 1
4. 逐行生成端点，偶数行正向、奇数行反向（割草机式）
5. 旋转回 NED，作为 FollowPath 的航点序列
```

`resume_from_row` 直接切掉前 N 行，用于断点续飞。
`rows_total` / `last_completed_row` 按此定义，保证 `resume_from_row = last_completed_row + 1`
能无缝接上 —— 这个闭合关系要有单测。

**几何拒绝条件**（`RESULT_REJECTED_BAD_GEOMETRY`）：
- 任一边长 < 2 × `row_spacing_m`（区域太小，连两行都排不下）
- 区域对角线 > 1000 m（疑似坐标或单位传错，与 Orbit 的 `MAX_CENTER_DIST_M` 同源思路）
- `xy_global == false`（EKF 无全局参考，经纬度无法解释，必须拒绝而不是当成 0,0）

---

## 4. Revisit 的两个延迟字段：先定测量点，别事后补

契约注释写明 `latency_goal_to_motion_ms` 与 `latency_goal_to_onstation_ms`
是论文「AI 反馈闭环延迟」实验的原始素材。这类字段一旦先随便填，后面很难回头做准。

```
t0  收到 goal            = action server 的 execute 回调入口第一行
t1  开始动作             = 第一条**改变目标位置**的 setpoint 发出的时刻
                          （不是心跳起来的时刻 —— 心跳可能早就在发了）
t2  到位且稳定           = 高度进入 ±阈值 **且** 水平速度 < 0.3 m/s
                          **且** 上述条件连续保持 1.0 s
latency_goal_to_motion_ms     = t1 − t0
latency_goal_to_onstation_ms  = t2 − t0
```

`t2` 刻意要求「连续保持」而不是单帧命中：单帧到位在超调过程中会误触发，
测出来的延迟会系统性偏小 —— 而这个数字是要写进论文的。

### 4.1 实现时对上面定义的两处刻意偏离（2026-07-31）

**`t1` 改为实测运动，而不是「第一条改变目标位置的 setpoint 发出的时刻」。**
两个理由：

- `inspection_mode` **看不到** setpoint 流 —— 那是 `autopilot_iface` 的内部行为，
  而「inspection_mode 不碰 setpoint」正是这套分层的前提（§1）。
  要观测它就得给 iface 加一条专门的埋点话题，为一个字段引入跨包耦合不值得。
- 契约的字段名就是 `latency_goal_to_motion_ms`（motion = 运动）。
  实测运动更贴字段的字面含义，也更贴论文要回答的问题
  （AI 决策到飞机真的动，中间有多久）。

判据：`VehicleState.velocity_ned` 的模超过 `motion_speed_mps`（默认 0.3 m/s）。
差别是可界定的：实测运动比「setpoint 发出」晚一个控制器响应时间。
⚠ 若飞机收到 goal 时**本来就在动**（扫掠途中插入复拍），这个数失去意义，
此时回报 0 并在 `Result.message` 里写明，不假装测到了。

**`t2` 取「开始满足判据的时刻」，而不是「保持够 1 秒的时刻」。**
后者是原文的字面读法，但它会给每次测量硬加 1000 ms 的确认延迟 ——
那是我们的滤波开销，不是飞机的性能。「保持 1 秒」的作用是**排除误触发**，
不该被算进结果。

### 4.2 一条会静默出错的参数耦合（实测踩过）

`revisit_accept_radius_m` 必须**小于** `onstation_alt_tol_m`。

`FollowPath` 一进到达半径就宣布到达并移交 `AUTO_LOITER`，而 LOITER 保持的是
当时的高度、不会再向指令高度收敛。所以到达半径比高度容差还宽时，
飞机会停在容差**之外**，「到位」判据永远不成立 ——
表现是 `latency_goal_to_onstation_ms` 全程为 0，而动作照常返回 OK。

实测（`99_notes/rv1`）：半径 0.8 m > 容差 0.5 m，请求 6 m 停在 6.74 m，
延迟字段全程测不到。现在默认半径 0.35 m，且节点启动时会检查这个关系并告警
—— 两个值单看都合理，只有放在一起才矛盾，这种错必须由代码自己喊出来。

顺带修掉同一处暴露的另一个问题：`Result.actual_agl_m` 原本回报的是**夹紧后的
指令值**，而契约写的是「实际到达的复拍高度」。请求 6 m、实际停在 6.74 m、
回报 6.00 —— 12% 的 GSD 偏差被静默吞掉，而 GSD 正是复拍这个动作存在的全部理由。
现在回报悬停开始那一刻的实测 AGL，并在超出容差时在 message 里点明。

## 5. 参数夹紧：调用方给的是「请求」不是「命令」

契约原文：「本动作的所有参数都会被服务端夹紧到安全范围内……
调用方给出的值是『请求』而非『命令』，实际执行值见 `Result.actual_*` 字段。」

| 请求 | 夹紧规则 | 依据 |
|---|---|---|
| `descend_to_agl_m` | 下限 3.0 m | 低于此高度地效与测距噪声都显著，且留不出改出余量 |
| `hover_sec` | 上限 30 s | 防止误检导致长时间占用 |
| `capture_burst` | 上限 20 张 | 同上 |
| 目标水平偏移 | 上限 50 m | 复拍是「就近降高」，偏移过大说明调用方该发别的动作 |

`RESULT_REJECTED_RATE_LIMITED`：同一目标点 30 s 内重复请求直接拒。
理由写在契约里 —— 防止误检导致飞机反复下降。判据用「与上次复拍点的距离 < 5 m
且间隔 < 30 s」，而不是简单的全局冷却，否则相邻两个真实缺陷会被误拒。

**「间隔」从上次复拍的结束时刻起算，不是开始时刻。**
实测（`99_notes/rv1` 场景 B）：一次复拍本身要飞 30 秒上下（下降 + 悬停 + 爬回），
从开始时刻起算的话，动作刚结束 30 s 窗口就已经过期 —— 限流等于不存在，
而它要防的正是「刚拍完又被同一个误检拽下去」。

**水平偏移超限是「拒」，不是「夹紧」。** 上表把它列在夹紧规则里，
但依据列写的是「偏移过大说明调用方该发别的动作」—— 那是拒绝的语义。
把 60 m 的偏移夹到 50 m，等于飞到一个调用方**没要求**的位置去复拍，
然后回报 `success` —— 调用方会拿着错位置的图像下结论，比直接拒更糟。
夹紧只适用于「同一件事做得更保守」（降得没那么低、悬停没那么久），
不适用于「换个地方做」。实现按拒绝处理，返回 `RESULT_REJECTED_UNSAFE`。

## 6. 低电量主动中止

`RESULT_ABORTED_LOW_BATTERY` 是**状态机主动**中止，不是飞控失效保护。
判据：`FlightHealth.battery_remaining` 低于阈值 + 返航余量估算。

⚠ 这里有个已知的坑：SITL 电池约 1.5 分钟就会掉到告警区（实测），
而扫掠动作的 `timeout_sec` 默认 1800 s。**SITL 下必须把电池告警动作关掉
（`COM_LOW_BAT_ACT=0`）才能跑完整扫掠**，否则测的是电池而不是扫掠。
真机上这个判据是真实需要的，不要因为 SITL 麻烦就把它删掉。

## 7. 实现顺序

1. iface 侧新增 `FollowPath` 内部动作 + 单测（航点跟随，复用 Orbit 的 setpoint 步进）
2. 航线生成 + 覆盖率校验的**纯函数单测**（不启仿真，秒级反馈，
   含 `resume_from_row` 闭合关系与三个几何拒绝条件）
3. `InspectSweep` 串起来，最小世界里跑通（不需要精细光伏模型）
4. `Revisit` + 延迟测量
5. 扫掠中自动插入 Revisit（`auto_revisit_on_detection`）—— 这一步依赖 `DetectionArray`，
   在 Window-A 的模型到位前用假检出注入验证

**先不做精细光伏世界**：它的形态取决于要检测的缺陷类别，而模型在 Window-A 手里。
验证扫掠几何与覆盖率只需要地面 + 几排板，先精雕有返工风险。
