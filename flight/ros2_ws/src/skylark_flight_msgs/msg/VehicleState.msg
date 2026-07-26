# 载具状态快照。
#
# 用途：edge/ 的视觉节点用它给检出结果打地理标签；platform/ 用它画航迹。
# 发布者：skylark_autopilot_iface（flight 层）
# 频率：建议 10 Hz（受 6C TELEM2 串口带宽限制，见 flight/docs/SERIAL_BUDGET.md）
#
# 设计说明：本消息是飞控无关的。它由 skylark_autopilot_iface 从
# px4_msgs/VehicleLocalPosition + VehicleGlobalPosition + VehicleAttitude 聚合而来。
# edge/ 不允许直接订阅 px4_msgs 话题 —— 那会把飞控类型泄漏到感知层。

std_msgs/Header header          # stamp = 飞控采样时刻（已做时间同步），frame_id = "map"

# ---- 本地坐标（NED，原点为 EKF 起飞点）----
geometry_msgs/Point position_ned        # [m] north, east, down
geometry_msgs/Vector3 velocity_ned      # [m/s]

# ---- 全球坐标 ----
float64 latitude_deg                    # [deg] WGS84
float64 longitude_deg                   # [deg] WGS84
float32 altitude_amsl_m                 # [m] 平均海平面高度
float32 altitude_agl_m                  # [m] 相对地面高度（来自测距仪或起飞点，见 agl_source）

uint8 AGL_SOURCE_UNKNOWN=0
uint8 AGL_SOURCE_TAKEOFF_REF=1          # 用起飞点气压高度推算，地形起伏时不可靠
uint8 AGL_SOURCE_RANGEFINDER=2          # 测距仪实测
uint8 agl_source

# ---- 姿态 ----
geometry_msgs/Quaternion attitude       # 机体系 FRD 相对 NED
float32 heading_deg                     # [deg] 0..360，正北为 0，顺时针为正

# ---- 数据质量 ----
bool position_valid                     # EKF 水平位置有效
bool altitude_valid                     # EKF 高度有效
float32 eph_m                           # [m] 水平位置标准差
float32 epv_m                           # [m] 垂直位置标准差
