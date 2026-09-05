# 飞行健康状态。
#
# 用途：edge/ 在请求任何飞行动作前必须先确认 ready_for_offboard 为 true；
#       platform/ 用它做地面站告警显示。
# 发布者：skylark_autopilot_iface（flight 层）
# 频率：建议 2 Hz
#
# 设计说明：这是"AI 能不能指挥飞机"的唯一判据。视觉节点不得自行推断飞行状态。

std_msgs/Header header

# ---- 解锁与模式 ----
bool armed
string flight_mode                      # 人类可读，如 "OFFBOARD" / "POSCTL" / "AUTO.RTL"

uint8 NAV_STATE_UNKNOWN=0
uint8 NAV_STATE_MANUAL=1
uint8 NAV_STATE_POSITION=2
uint8 NAV_STATE_MISSION=3
uint8 NAV_STATE_OFFBOARD=4
uint8 NAV_STATE_RTL=5
uint8 NAV_STATE_LAND=6
uint8 nav_state

# ---- Offboard 就绪判据（edge/ 必须检查这一位）----
bool ready_for_offboard                 # true 表示：已解锁 + 位置有效 + 无 failsafe + 链路健康

# ---- 失效保护 ----
bool failsafe_active
string[] failsafe_reasons               # 如 ["battery_low", "rc_signal_lost"]

# ---- 关键资源 ----
float32 battery_remaining               # 0.0 .. 1.0
float32 battery_voltage_v               # [V]

uint8 GPS_FIX_NONE=0
uint8 GPS_FIX_2D=2
uint8 GPS_FIX_3D=3
uint8 GPS_FIX_RTK_FLOAT=5
uint8 GPS_FIX_RTK_FIXED=6
uint8 gps_fix_type
uint8 gps_satellites_used

# ---- 链路 ----
bool rc_link_ok
bool gcs_link_ok
bool companion_link_ok                  # 机载电脑 <-> 飞控 的 uXRCE-DDS 链路
uint32 companion_link_age_ms            # 距上次收到飞控数据的毫秒数
