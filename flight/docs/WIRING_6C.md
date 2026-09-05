# Pixhawk 6C 分体式接线

> 硬件：Holybro Pixhawk 6C（非 PAB 形态，插不进 Jetson Baseboard，必须分体式）
> 依据：PX4 官方文档 `flight_controller/pixhawk6c.md` 与 `assembly/quick_start_pixhawk6c.md`，
> 本地副本在 `PX4/01_px4_core/PX4-user_guide/`。所有引脚与限流数据均出自官方文档，非记忆。
> 最后更新：2026-07-27

---

## 0. 三条会烧硬件的红线

先看这三条，再看别的。

### 红线 1：机载电脑绝对不能从飞控取电

6C 的电流限制（官方规格）：

| 端口 | 限流 |
|---|---|
| TELEM1 | 独立 1.5 A |
| **其余所有端口合计** | **1.5 A** |

Jetson Orin Nano 峰值功耗 15-25 W，按 5 V 算是 3-5 A。**远超 6C 全部端口的总预算。**

→ 机载电脑必须由独立 BEC / 电源模块供电（如 Matek PM12S-4A 之类提供 5 V/12 V 的模块）。
→ 6C 与机载电脑之间的串口线**只接 TX / RX / GND 三根，不接 VCC**。

### 红线 2：最大输入电压 6 V

6C 是模拟电源模块方案（不是 6X 的数字/CAN 电源模块）。

| 输入 | 正常范围 | 绝对上限（不损坏但不工作） |
|---|---|---|
| POWER1 / POWER2 | 4.9 – 5.5 V | 0 – 10 V |
| USB | 4.75 – 5.25 V | 0 – 6 V |
| FMU/IO PWM 的 VDD_SERVO 引脚 | — | 0 – 42 V |

→ 电池**绝不能**直接接 POWER 口。必须经 PM02 / PM06 / PM07 之类电源模块降压。

### 红线 3：GND 必须共地，但不能形成地环路

6C、机载电脑、电源模块共用同一电池负极。串口线的 GND 是信号地参考，不是供电回流路径。

→ 若机载电脑用独立电池（不推荐），必须只接一根 GND 做信号参考，且注意共模电压。

---

## 1. 6C 端口总览

| 端口 | 用途 | 本项目分配 |
|---|---|---|
| POWER1 | 电源模块输入（含电压/电流采样） | ✅ PM02/PM06 |
| POWER2 | 第二路电源（冗余） | 预留 |
| GPS1 | 10 针，GNSS + 罗盘 + 安全开关 + 蜂鸣器 + LED | ✅ M8N/M9N |
| GPS2 | 6 针，基础 GNSS | 预留（RTK 时用） |
| TELEM1 | 数传（独立 1.5 A 限流） | ✅ 地面站链路 |
| **TELEM2** | 通用串口 | ✅ **机载电脑 uXRCE-DDS** |
| TELEM3 | 通用串口 | 预留（测距仪 / 调试） |
| I/O PWM OUT | 8 路，PX4 的 **MAIN** 输出 | ✅ 四个电机 |
| FMU PWM OUT | 8 路，PX4 的 **AUX** 输出 | 预留（云台 / 相机触发） |
| DSM | Spektrum / DSM 接收机专用输入 | 视接收机型号 |
| PPM/SBUS | PPM 或 S.BUS 接收机输入 | ✅ 视接收机型号 |
| I2C | 外部 I2C 设备 | 预留 |
| CAN1 / CAN2 | UAVCAN/DroneCAN | 预留 |
| FMU Debug | 系统控制台 + SWD（JST SM10B） | 调试用 |
| SD 卡槽 | 飞行日志 | ✅ **必装**，否则没有 `.ulg` 日志 |

### 关键映射（极易搞错）

PX4 固件里的输出编号与 6C 物理端口的对应关系：

| PX4 输出 | 6C 物理端口 |
|---|---|
| **MAIN**1..8 | **I/O PWM OUT** 的 IO_CH1..8 |
| **AUX**1..8 | **FMU PWM OUT** 的 FMU_CH1..8 |

多旋翼的电机默认走 **MAIN**，也就是 **I/O PWM OUT**。

> 官方警告原文含义：机架之间的输出映射**不一致**（例如不能假设所有固定翼的油门都在同一路输出）。
> 务必对照 [Airframe Reference](https://docs.px4.io/v1.17/en/airframes/airframe_reference.html) 确认你的机架。

---

## 2. POWER 端口引脚（6 针）

| 针 | 线色 | 信号 | 电平 |
|---|---|---|---|
| 1 | 红 | VDD | +5 V |
| 2 | 黑 | VDD | +5 V |
| 3 | 黑 | CURRENT | +3.3 V（模拟量） |
| 4 | 黑 | VOLTAGE | +3.3 V（模拟量） |
| 5 | 黑 | GND | GND |
| 6 | 黑 | GND | GND |

CURRENT / VOLTAGE 是电源模块回传的模拟采样，用于电量估计。**不接这两针的话电池监控不工作**，低电量失效保护也就失效了。

---

## 3. 分体式拓扑

```
                    ┌─────────────┐
                    │  LiPo 电池   │
                    └──────┬──────┘
                           │ 主电源
                    ┌──────┴───────────────────┐
                    │  电源模块 PM02 / PM06     │
                    │  （降压 + 电压电流采样）    │
                    └───┬──────────────────┬───┘
                        │ 5V + 采样        │ 电池直出
                        │ (6 线)           │
                  ┌─────┴─────┐      ┌────┴─────────┐
                  │  POWER1   │      │  四个电调 ESC │
              ┌───┴───────────┴──┐   └────┬─────────┘
              │                  │        │ 三相
              │   Pixhawk 6C     │   ┌────┴────┐
              │                  ├───┤  电机 ×4 │
              │  I/O PWM OUT ────┼───┘         │
              │  (MAIN 1-4)      │   └─────────┘
              │                  │
              │  GPS1 ───────────┼──── M8N/M9N（罗盘+安全开关+蜂鸣器+LED）
              │  TELEM1 ─────────┼──── 数传 ────► 地面站 QGC
              │  PPM/SBUS ───────┼──── 接收机 ◄── 遥控器
              │                  │
              │  TELEM2 ─────────┼─┐
              └──────────────────┘ │ 仅 TX/RX/GND 三根
                                   │ 不接 VCC ！
                            ┌──────┴──────────┐
                            │  机载电脑 Jetson │
                            │  uXRCE-DDS Agent │
                            └──┬────────────┬──┘
                               │ USB/MIPI   │ 独立供电
                          ┌────┴────┐  ┌────┴──────────┐
                          │  相机    │  │ 独立 BEC 5V   │◄── 电池
                          └─────────┘  └───────────────┘
```

**图像数据流向注意**：相机直接接机载电脑，**不经过飞控**。原因见 `SERIAL_BUDGET.md` —— 6C 无以太网，串口带宽根本不够传图。

---

## 4. TELEM2 ↔ 机载电脑 接线

### 4.1 方案 A：直连 UART（推荐）

6C 的 TELEM 口是 JST-GH 6 针。TELEM2 → 机载电脑的 UART：

| 6C TELEM2 | 机载电脑 | 说明 |
|---|---|---|
| TX | RX | **交叉** |
| RX | TX | **交叉** |
| GND | GND | 共地 |
| VCC | ✗ 不接 | 红线 1 |
| CTS / RTS | 可不接 | 921600 下建议不用流控，简化调试 |

⚠ TX/RX 必须交叉。接成 TX-TX 不会烧板但完全通不了，这是最常见的浪费半天的错误。

### 4.2 方案 B：USB 转串口（更省事，PX4 官方推荐给新手）

用一个 FTDI USB-TTL 模块（**必须选 3.3 V 电平版本**，5 V 会损伤 6C 的 UART）：

```
6C TELEM2 ──(TX/RX/GND)── FTDI 3.3V 模块 ──USB── 机载电脑
```

好处：不占用机载电脑的板载 UART，插拔方便，电平隔离更安全。
代价：多一个 USB 设备，设备名可能变化（用 udev 规则固定，见 §6）。

**S2 阶段（地面联调）建议先用方案 B**，把软件链路调通；确认无误后再换方案 A 上机减重。

---

## 5. 对应的 PX4 参数

在 QGC 里设置（依据 PX4 官方串口配置文档）：

```
UXRCE_DDS_CFG = 102        # 102 = TELEM2，启用 uXRCE-DDS 客户端
SER_TEL2_BAUD = 921600     # 与机载电脑侧 agent 的波特率必须一致
MAV_1_CONFIG  = 0          # 关闭 TELEM2 上的 MAVLink 实例，避免抢串口
```

改完**必须重启飞控**（`UXRCE_DDS_CFG` 与 `MAV_*_CONFIG` 都是重启生效参数）。

6C 的 TELEM2 在 PX4 内部映射到 `/dev/ttyS3`（UART5）。完整串口映射：

| UART | 设备节点 | 端口 |
|---|---|---|
| USART1 | `/dev/ttyS0` | GPS1 |
| USART2 | `/dev/ttyS1` | TELEM3 |
| USART3 | `/dev/ttyS2` | Debug Console |
| UART5 | `/dev/ttyS3` | **TELEM2** |
| USART6 | `/dev/ttyS4` | PX4IO |
| UART7 | `/dev/ttyS5` | TELEM1 |
| UART8 | `/dev/ttyS6` | GPS2 |

机载电脑侧启动 agent：

```bash
# 方案 A（板载 UART，设备名视机载电脑而定）
MicroXRCEAgent serial --dev /dev/ttyTHS0 -b 921600

# 方案 B（USB 转串口）
MicroXRCEAgent serial --dev /dev/ttyUSB0 -b 921600
```

---

## 6. 固定串口设备名（避免重启后设备名漂移）

USB 转串口的 `/dev/ttyUSB0` 会随插拔顺序变化。用 udev 规则钉死：

```bash
# 先查 FTDI 的 idVendor / idProduct / serial
udevadm info -a -n /dev/ttyUSB0 | grep -E 'idVendor|idProduct|serial' | head -5

# 写规则（把 XXXX 换成实际值）
sudo tee /etc/udev/rules.d/99-skylark-fcu.rules >/dev/null <<'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="skylark_fcu"
EOF

sudo udevadm control --reload-rules && sudo udevadm trigger
# 之后固定用 /dev/skylark_fcu
```

---

## 7. 安装与减振

- **位置**：尽可能靠近机架重心
- **朝向**：正面朝上，箭头指向机头。若因空间限制无法按默认朝向安装，必须在固件里配置实际朝向（`Flight Controller Orientation`）
- **固定**：6C 板内已有集成减振系统 + IMU 加热电阻温控，一般用套件里的双面胶直接贴即可，**不要再加软性减振垫** —— 双层减振反而可能引入低频谐振
- **罗盘**：GPS/罗盘模块要尽量远离电源线、电调和大电流走线。装在支架上抬高是标准做法
- **走线**：信号线（串口、PWM 信号）与动力线（电池、三相）分开走，避免平行长距离并行

---

## 8. 安全开关

GPS1 模块集成的安全开关**默认启用**。启用状态下 PX4 拒绝解锁。

- 长按 1 秒 → 解除安全锁定（此时才能解锁电机）
- 再按一次 → 重新锁定并上锁电机

这个开关是最后一道物理防线。**调试期间不要用参数禁用它。**

---

## 9. 固定翼 / 车辆的额外注意（本项目暂不涉及，登记备查）

6C 板上**没有内置舵机供电排针**。做固定翼或车时，FMU PWM OUT 的 8 针电源正极轨需要外接 BEC 才能驱动舵机（带 BEC 的电调、独立 5 V BEC、或 2S 锂电）。

⚠ 供电电压必须匹配舵机规格。

Holybro 的 **PM07** 就是专为 6C / Pixhawk 4 这类无内置舵机排针的板子设计的，自带舵机分电。

---

## 10. 接线自检清单

按顺序逐项打勾，**每一项都做完再上电**：

- [ ] 电池经电源模块降压后接 POWER1，**没有**直连
- [ ] POWER 线 6 根全接（含 CURRENT / VOLTAGE 采样）
- [ ] TELEM2 到机载电脑：TX/RX **已交叉**，GND 已接，**VCC 未接**
- [ ] 机载电脑由独立 BEC 供电，**未**从飞控任何端口取电
- [ ] GPS 接 GPS1（10 针口），箭头朝机头
- [ ] 接收机接对了口（DSM 接收机 → DSM 口；S.BUS/PPM → PPM/SBUS 口）
- [ ] 数传接 TELEM1
- [ ] 电机信号线接 **I/O PWM OUT**（= MAIN），不是 FMU PWM OUT
- [ ] SD 卡已插入（没有卡就没有飞行日志，等于白飞）
- [ ] **桨叶已全部拆除**
- [ ] 信号线与动力线分离走线
- [ ] 万用表确认：POWER1 输入电压在 4.9–5.5 V 之间

上电后立刻做的事：见 `SAFETY_CHECKLIST.md`。

---

## 11. 官方参考

| 内容 | 位置 |
|---|---|
| 6C 硬件规格与引脚 | 本地 `PX4/01_px4_core/PX4-user_guide/en/flight_controller/pixhawk6c.md` |
| 6C 接线快速指南 | 本地 `PX4/01_px4_core/PX4-user_guide/en/assembly/quick_start_pixhawk6c.md` |
| 中文版 | 同路径把 `en` 换成 `zh`（翻译滞后，建议中英对照） |
| 厂家引脚图 | https://docs.holybro.com/autopilot/pixhawk-6c/pixhawk-6c-pinout |
| 机架输出映射 | https://docs.px4.io/v1.17/en/airframes/airframe_reference.html |
| Pixhawk 连接器标准 | Pixhawk-Standards 仓库 DS-009 |
