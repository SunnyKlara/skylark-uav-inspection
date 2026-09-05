# 参数变更记录

> **规则：每一次参数改动，这里加一行。没有例外。**
>
> 为什么必须有这份文件：飞控参数有 1000+ 个，改了三个月后没人记得为什么。
> 出问题时如果不能 diff，只能整体恢复默认从头调 —— 那意味着丢掉几十小时的调参成果。

---

## 使用方法

### 导出基线快照

```
QGC → Vehicle Setup → Parameters → 右上角 Tools → Save to file
命名：pixhawk6c_<机架>_v<序号>.params
例如：pixhawk6c_x500_v1.params
```

### 记录改动

改任何参数后，在 §变更记录 表格加一行。**四列都要填**：

| 列 | 要求 |
|---|---|
| 参数 | 完整参数名，如 `UXRCE_DDS_CFG` |
| 旧值 → 新值 | 两个都写，只写新值等于没写 |
| 为什么 | 一句话说明动机。写"调一下试试"等于没写 |
| 飞行验证 | 未验证 / SITL 通过 / 地面通过 / 飞行通过 + 日志文件名 |

### 关键区分：参数 vs 固件

| 类型 | 存在哪 | 换板/重刷后 |
|---|---|---|
| **参数**（QGC 里能改的） | 飞控 EEPROM | 可从 `.params` 文件恢复 |
| **固件级改动**（如裁剪 `dds_topics.yaml`） | 编译进固件 | **丢失，必须重新编译** |

⚠ 固件级改动也要记在这里，并在「为什么」里明确标注 `[固件级]`。
这是最容易踩的坑：调好的话题裁剪，重刷官方固件后全部复原，然后"莫名其妙又丢包了"。

---

## 快照清单

| 文件 | 日期 | 固件版本 | 机架 | 状态 |
|---|---|---|---|---|
| _（尚无）_ | — | — | — | 等待首次导出 |

**首次导出的前置动作**（约 1 小时，不需要任何配件）：

1. 6C 插 USB，QGC 刷 v1.17.0 固件
2. 选机架类型
3. 完成全套校准：加速度计、水平校准、罗盘、遥控器
4. 配置失效保护参数（`BAT_LOW_THR` / `COM_LOW_BAT_ACT` / `NAV_RCL_ACT` / `GF_MAX_HOR_DIST`）
5. 配置机载电脑串口（`UXRCE_DDS_CFG=102` / `SER_TEL2_BAUD=921600` / `MAV_1_CONFIG=0`）
6. 导出为 `pixhawk6c_bench_v1.params`（bench = 台面基线，还没上机架）
7. 在下方表格登记

> 这一步的价值：产出一份「已知良好」的基线配置。之后任何改动都能 diff。
> 硬件放着会积灰，配置基线做出来就是永久资产。

---

## 变更记录

| 日期 | 参数 | 旧值 → 新值 | 为什么 | 飞行验证 |
|---|---|---|---|---|
| _（尚无）_ | | | | |

---

## 本项目已规划的参数改动（尚未执行，等硬件上电）

以下改动的依据均已在文档中说明，执行时逐条搬到上方变更记录表：

| 参数 | 目标值 | 为什么 | 依据文档 |
|---|---|---|---|
| `UXRCE_DDS_CFG` | `102`（TELEM2） | 在 TELEM2 上启用 uXRCE-DDS 客户端，连接机载电脑 | `docs/WIRING_6C.md` §5 |
| `SER_TEL2_BAUD` | `921600` | 与机载电脑侧 agent 波特率一致 | `docs/SERIAL_BUDGET.md` §2 |
| `MAV_1_CONFIG` | `0` | 关闭 TELEM2 上的 MAVLink 实例，避免与 DDS 抢串口 | `docs/WIRING_6C.md` §5 |
| `COM_OBL_RC_ACT` | 待定 | Offboard 信号丢失时的处置动作。首飞前必须明确设定 | `SAFETY_CHECKLIST.md` §I |
| `GF_MAX_HOR_DIST` | 按场地设 | 地理围栏水平半径，必须小于场地边界 | `SAFETY_CHECKLIST.md` §C2 |
| `GF_MAX_VER_DIST` | 按场地设 | 地理围栏高度上限 | `SAFETY_CHECKLIST.md` §C2 |
| `BAT_LOW_THR` / `BAT_CRIT_THR` | 按电池设 | 低电量 / 危险电量阈值 | `SAFETY_CHECKLIST.md` §C2 |
| `COM_LOW_BAT_ACT` | 待定 | 低电量处置动作 | `SAFETY_CHECKLIST.md` §C2 |
| `NAV_RCL_ACT` | 待定 | 遥控链路丢失处置动作 | `SAFETY_CHECKLIST.md` §C2 |
| `dds_topics.yaml` 裁剪（方案 B） | 见文档 | **[固件级]** 默认配置占满串口预算 100.3%，必须裁剪 | `docs/SERIAL_BUDGET.md` §3-4 |

---

## 目录里应该有什么

```
flight/params/
├── CHANGELOG.md                      本文件
├── pixhawk6c_bench_v1.params         台面基线（无机架）
├── pixhawk6c_<机架>_v1.params        整机基线
└── pixhawk6c_<机架>_v2.params        调参后的版本
```

`.params` 是纯文本，git diff 直接可读。**不要用 `.gz` 或二进制备份格式** —— 那会让版本控制失去意义。
