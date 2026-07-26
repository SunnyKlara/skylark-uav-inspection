# Pixhawk 6C 刷固件与校准 — 逐步操作指导

> 目标：产出一份「已知良好」的基线配置 `flight/params/pixhawk6c_bench_v1.params`。
> 之后任何参数改动都能 diff，出问题能回退。
>
> **本文只需要飞控 + USB 线**（阶段 A）。机架、电机、电调、电池、遥控器都不需要。
>
> 依据：PX4 官方文档 `config/firmware.md`、`config/index.md`、`config/accelerometer.md`
> 等，本地副本在 `PX4/01_px4_core/PX4-user_guide/en/`。版本信息经 GitHub API 核实。
> 最后更新：2026-07-27

---

## 0. 开始前

### 0.1 需要准备的东西

| 项 | 阶段 A（今天） | 说明 |
|---|---|---|
| Pixhawk 6C | ✅ 必需 | — |
| USB 数据线（Type-C） | ✅ 必需 | 必须是**数据线**，不是只能充电的线 |
| Windows 电脑 | ✅ 必需 | 本机 `METAMECHBOOK01` 即可 |
| 机架 / 电机 / 电调 | ❌ 不需要 | 阶段 B 才用 |
| 电池 / 电源模块 | ❌ 不需要 | 阶段 B 才用 |
| 遥控器 / 接收机 | ❌ 不需要 | 阶段 B 才用 |
| GPS 模块 | ❌ 不需要 | 阶段 B 才用（含罗盘与安全开关） |

### 0.2 三条安全前提（官方硬性要求）

PX4 官方文档 `config/firmware.md` 的原文警告，逐条照做：

1. **刷固件前，所有 USB 连接必须断开** —— 包括直连和经数传模块的连接
2. **刷固件时不得用电池供电** —— 只能 USB 供电
3. **USB 必须直连电脑上的供电 USB 口，不要经 USB hub** —— hub 供电不稳会导致刷写中断

补充两条我的建议：

4. **桨叶不装。** 阶段 A 根本没装电机，但这个习惯要从第一天养成
5. **刷写过程中不要拔线、不要关电脑、不要让电脑睡眠** —— 中断可能需要重新进 bootloader 恢复

### 0.3 版本说明（已核实，不用你操心）

| 项 | 值 | 核实方式 |
|---|---|---|
| PX4 当前 stable | **v1.17.0**（2026-05-13 发布） | GitHub `releases/latest` + `stable` 分支指向的 tag |
| 我们锁定的版本 | **v1.17.0** | `flight/VERSIONS.md` |
| v1.18.0 状态 | 只到 **beta1**（预发布），**不要用** | GitHub releases 列表 |
| QGroundControl 当前 stable | **v5.0.8**（安装包 161.6 MB） | GitHub `releases/latest` |

**好消息**：因为 v1.17.0 正好就是当前 stable，QGC 里默认那个「PX4 Pro Stable Release」
刷的就是我们要的版本，**不需要手动下载固件文件，也不需要动 Advanced settings**。

---

## 第 1 步：装 QGroundControl

1. 下载 Windows 安装包（161.6 MB）：

   https://github.com/mavlink/qgroundcontrol/releases/download/v5.0.8/QGroundControl-installer.exe

   或从官网入口进：https://qgroundcontrol.com/downloads/

2. 双击安装，一路默认。装完先**不要**插飞控。

3. Windows 10/11 会自动为 Pixhawk 装 USB 串口驱动（CDC ACM），一般不需要手动装驱动。

---

## 第 2 步：第一次连接，确认电脑认得这块板子

**先不开 QGC**，用 USB 线把 6C 直连电脑（不经 hub）。

上电后 6C 会亮灯。然后在 PowerShell 里执行：

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Description, PNPDeviceID | Format-List
```

期望看到一个 COM 口，`Description` 里含 `PX4`、`Pixhawk` 或 `USB Serial Device` 之类。

**如果什么都没有**：

| 检查 | 说明 |
|---|---|
| 换根线 | 最常见原因。很多 Type-C 线只能充电不能传数据 |
| 换 USB 口 | 优先用机身上直接的 USB 口，不用扩展坞/hub |
| 看设备管理器 | `devmgmt.msc`，找有没有带黄色感叹号的未知设备 |
| 板子灯亮不亮 | 完全不亮说明供电或线有问题 |

记下这个 COM 口号，后面排查时有用。

---

## 第 3 步：刷固件 v1.17.0

### 3.1 关键顺序：先断开，再进入固件页，最后插线

这个顺序容易搞反，搞反了 QGC 会先连上飞控，然后固件页不显示刷写选项。

1. **把 USB 线拔掉**（第 2 步插的那根）
2. 打开 QGroundControl
3. 点左上角 **"Q" 图标 → Vehicle Setup → Firmware**（侧边栏）

   此时页面应显示等待连接的提示（英文界面是 *"Plug in your device via USB to start firmware upgrade"*）

4. **现在**把 USB 线插上（直连，不经 hub）

### 3.2 选版本并刷写

1. QGC 识别到板子后，会出现固件选项，**自动识别**你的板子型号
2. 选 **`PX4 Pro Stable Release v1.17.0`**（默认就选中它，不用改）
3. **不要勾 Advanced settings** —— 默认的 stable 就是我们要的版本
4. 点 **OK** 开始

刷写会依次经过若干阶段（下载新固件、擦除旧固件、写入、校验），每一步都会打印在屏幕上，
下方有进度条。**全程约 1-3 分钟，不要碰线。**

完成后设备会自动重启并重新连上。

### 3.3 验证刷对了

刷完在 QGC 里看 **Vehicle Setup → Summary**（或标题栏），确认：

- 固件版本显示 **v1.17.0**
- 板子型号显示 **Pixhawk 6C** 或 **PX4 FMU v6C**

⚠ **如果安装过程的控制台里出现 `FMUv2`**：那说明 bootloader 太旧，需要先更新 bootloader
才能用满 flash。6C 出厂 bootloader 一般没这个问题，但如果真出现了，按官方
`advanced_config/bootloader_update.md` 的 FMUv2 章节处理，**先别继续往下做**。

### 3.4 备查：以后怎么刷别的版本

现在不用做，记着就行。

| 需求 | 做法 |
|---|---|
| 刷 beta / main | 勾 **Advanced settings** → 下拉选 Beta Testing / Developer Build |
| 刷自己编译的固件 | 勾 **Advanced settings** → 选 **Custom Firmware file...** → 选 `.px4` 文件 |
| 刷裁剪过 `dds_topics.yaml` 的固件 | 同上。这是 S2 阶段会用到的（见 `SERIAL_BUDGET.md` §5） |

v1.17.0 的 6C 固件直链（备用，QGC 抽风时手动下）：

```
https://github.com/PX4/PX4-Autopilot/releases/download/v1.17.0/px4_fmu-v6c_default.px4
```

> 顺带一提：同一个 release 里还有 `px4_fmu-v6c_neural.px4`（1.75 MB，**预编译好的**
> 神经网络控制器固件，见 `HARDWARE_FLIGHT_LAYER.md` §13）。**现在不要刷它** ——
> 那是 Q3/Q4 的探索项，稳定性未验证。

---

## 第 4 步：选机架（必须做，且必须在校准之前）

官方文档明确：**固件 + 机架选择必须先做**，其他步骤大多可以乱序，但调参（tuning）必须最后。

1. **Vehicle Setup → Airframe**
2. 选 **Multirotor → Quadrotor X**
3. 具体型号：如果还没定机架，选 **Generic Quadrotor X**（通用四轴 X 型）
4. 点右上角 **Apply and Restart**

飞控会重启。

> 以后确定了具体机架（比如 Holybro X500 V2），回来改成对应型号。
> 改机架会重置一部分参数，**所以要在导出基线之前定下来**，或者在改完之后重新导出基线。

---

## 第 5 步：阶段 A 校准（只用飞控本体）

进 **Vehicle Setup → Sensors**。

这一步的关键认知：**你现在校准的是"飞控这块板子"，不是"飞机"**。所以：

| 校准项 | 现在能做吗 | 说明 |
|---|---|---|
| Autopilot Orientation（安装方向） | ✅ | 板子平放、箭头朝前 → 选 `ROTATION_NONE` |
| Gyroscope（陀螺仪） | ✅ | 板子静止放桌上即可 |
| Accelerometer（加速度计） | ✅ | 手持板子按提示翻转 |
| Level Horizon（水平校准） | ⚠ 可做但要重做 | 现在按"板子水平"校，装上机架后必须重校 |
| Compass（罗盘） | ❌ **不要现在做** | 见下方说明 |

### 5.1 设置安装方向

1. Sensors 页面找 **Set Orientations**（或在加计校准里一并设置）
2. 板子平放、箭头指向你的正前方 → 选 **ROTATION_NONE**

### 5.2 陀螺仪校准

1. 把板子平放在桌上，**完全不要碰**
2. 点 **Gyroscope** → **OK**
3. 等进度条走完（几秒到十几秒）

⚠ 6C 的 IMU 有加热电阻做温控。**冷启动后建议先通电等 1-2 分钟**让 IMU 温度稳定，再做校准。

### 5.3 加速度计校准

这一步要手持板子翻转 6 个方向。

1. 点 **Accelerometer** → **OK**
2. 屏幕会用图示提示当前要摆的方向：正放、倒放、左侧、右侧、机头朝下、机头朝上
3. 摆到位后**保持静止**，图示变黄表示正在采集，变绿表示这个方向完成
4. 依次完成 6 个方向

**官方说明（可以放心）**：算法用最小二乘拟合，**不要求精确 90 度**。只要每个轴在过程中
大致朝上/朝下过，且保持静止，精度就够。不用找水平仪。

全部变绿 + 进度条满 = *Calibration complete*。

### 5.4 水平校准（可选，装机架后必须重做）

1. 板子平放在**尽量水平**的桌面上
2. 点 **Level Horizon** → **OK**

现在做的意义只是让基线完整。**装上机架后必须重做** —— 那时校的是"飞机水平"，
飞控在机架上可能有安装倾角。

### 5.5 为什么现在不做罗盘校准

6C 板载有 IST8310 磁罗盘，技术上现在就能校。但**不要做**，原因：

- 罗盘校准的目的是补偿**周围磁干扰**（电源线、电调、电机、机架碳纤维）
- 现在裸板校准，采集到的是"桌面环境"的干扰特征
- 装上机架通电后，干扰完全不同 → 之前的校准数据全部作废，还可能误导 EKF

**正确时机**：整机装好、所有线接好、GPS 模块装到支架上之后，**在户外空旷处**做。
GPS 模块自带的罗盘也是那时才接上。

---

## 第 6 步：配机载电脑串口参数

这是给后面 Window-E 的 ROS 2 联调铺路，现在配好省得以后返工。

进 **Vehicle Setup → Parameters**，右上角搜索框逐个搜索并修改：

| 参数 | 设为 | 含义 |
|---|---|---|
| `UXRCE_DDS_CFG` | **TELEM 2**（值 102） | 在 TELEM2 上启用 uXRCE-DDS 客户端 |
| `SER_TEL2_BAUD` | **921600** | TELEM2 波特率，与机载电脑侧 agent 必须一致 |
| `MAV_1_CONFIG` | **Disabled**（值 0） | 关掉 TELEM2 上的 MAVLink 实例，避免和 DDS 抢串口 |

改法：搜到参数 → 双击 → 从下拉选或输入数值 → **Save**。

改完 QGC 会提示需要重启，点确认重启飞控。这三个参数都是重启生效。

> 依据见 `flight/docs/WIRING_6C.md` §5。TELEM2 在 PX4 内部映射到 `/dev/ttyS3`（UART5）。

---

## 第 7 步：导出基线 `.params` —— 本次的最终产出

1. **Vehicle Setup → Parameters**
2. 右上角 **Tools**（工具菜单）→ **Save to file...**
3. 存到：

   ```
   c:\Users\Klara\Desktop\PX4\skylark\flight\params\pixhawk6c_bench_v1.params
   ```

   文件名里 `bench` 表示"台面基线，还没上机架"。

4. 打开 `flight/params/CHANGELOG.md`，在「快照清单」表格里加一行：

   ```markdown
   | pixhawk6c_bench_v1.params | 2026-MM-DD | v1.17.0 | Generic Quadrotor X | 台面基线，未上机架 |
   ```

5. 在「变更记录」表格里补上第 6 步改的三个参数，每个一行（四列都要填）

`.params` 是纯文本，git diff 直接可读。**这就是本次操作的核心产出。**

---

## 第 8 步（阶段 B）—— 装上机架之后再做

现在只是登记，不要现在做。所需硬件到位后按此顺序：

| 顺序 | 项目 | 需要的硬件 | 文档 |
|---|---|---|---|
| 1 | 确定并重选机架型号 | 机架 | `config/airframe.md` |
| 2 | 重做水平校准 | 整机 | `config/level_horizon_calibration.md` |
| 3 | **罗盘校准（户外空旷处）** | 整机 + GPS 模块 | `config/compass.md` |
| 4 | 遥控器校准 | 遥控器 + 接收机 | `config/radio.md` |
| 5 | 飞行模式映射（**必须留一个 RTL 开关**） | 同上 | `config/flight_mode.md` |
| 6 | 电池参数（`BAT1_N_CELLS` 等） | 电源模块 + 电池 | `config/battery.md` |
| 7 | **执行器配置与测试（务必拆桨）** | 电调 + 电机 | `config/actuators.md` |
| 8 | 失效保护 + 地理围栏 | — | `config/safety.md` |
| 9 | 重新导出 `pixhawk6c_<机架>_v1.params` | — | — |
| 10 | 自动调参（**必须最后做**） | 能飞的整机 | `config/autotune_mc.md` |

官方明确：**tuning 必须最后做**。

文档本地路径：`PX4/01_px4_core/PX4-user_guide/en/config/<文件名>`，
把 `en` 换成 `zh` 是中文版（翻译滞后，建议中英对照）。

阶段 B 开始前**先读完** `flight/docs/SAFETY_CHECKLIST.md`。

---

## 第 9 步：故障排查

| 症状 | 原因 / 处置 |
|---|---|
| QGC 完全不认设备 | 换数据线（首要嫌疑）→ 换 USB 口 → 不用 hub → 看设备管理器有无未知设备 |
| 固件页不出现刷写选项 | 顺序错了。**先拔线 → 开 QGC → 进 Firmware 页 → 再插线** |
| 刷写中途失败 | 拔线、重启 QGC，重新按 3.1 顺序做。多数情况能直接重刷成功 |
| 刷完连不上 | 拔插一次 USB。若仍不行，重刷一遍 |
| 控制台出现 `FMUv2` | bootloader 太旧，需先更新 bootloader，**停下别继续** |
| 加计校准反复失败 | 保持静止；等 IMU 温度稳定（通电 1-2 分钟）；确认放在稳固桌面上不是手上抖 |
| QGC 报"高加速度计偏差"/一致性检查失败 | 加计校准没做好，重做 |
| 飞控无法解锁（arm） | 阶段 A 正常现象。没有 GPS、没有遥控器、安全开关未解除，都会拒绝解锁 |
| 参数改了没生效 | `UXRCE_DDS_CFG` / `MAV_*_CONFIG` / `SER_*_BAUD` 都需**重启飞控** |

---

## 第 10 步：完成检查表

阶段 A 全部做完后，逐项确认：

- [ ] QGroundControl v5.0.8 已安装
- [ ] 6C 能被电脑识别（有 COM 口）
- [ ] 固件已刷成 **v1.17.0**，Summary 页确认
- [ ] Summary 页板型显示 Pixhawk 6C / PX4 FMU v6C
- [ ] 安装过程**没有**出现 FMUv2 警告
- [ ] 机架已选（Generic Quadrotor X 或具体型号），已 Apply and Restart
- [ ] Autopilot Orientation 已设（`ROTATION_NONE`）
- [ ] 陀螺仪校准通过
- [ ] 加速度计校准通过（6 个方向全绿）
- [ ] 水平校准做过（知道装机架后要重做）
- [ ] **罗盘校准没做**（有意推迟到整机 + 户外）
- [ ] `UXRCE_DDS_CFG = 102 (TELEM 2)`
- [ ] `SER_TEL2_BAUD = 921600`
- [ ] `MAV_1_CONFIG = 0 (Disabled)`
- [ ] 三个参数改完已重启飞控
- [ ] **`flight/params/pixhawk6c_bench_v1.params` 已导出**
- [ ] `flight/params/CHANGELOG.md` 已登记快照 + 三条参数变更

全部打勾 = 阶段 A 完成，你手上有了一份可 diff 的基线配置。

---

## 一句话

> 这一步的产出不是"飞控能用了"，是**一份可回退的已知良好配置**。
> 三个月后你改坏了什么，靠的就是和这份 `.params` 做 diff。
