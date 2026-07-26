# 已完成地理配准的检出结果 —— 这是最终进入缺陷台账的记录。
#
# 发布者：flight/ 的 skylark_bridge（它同时持有 DetectionArray 与 VehicleState，
#         做时间对齐后完成投影）
# 订阅者：platform/ 后端（经图传上行）
#
# 为什么放在 flight/ 而不是 edge/：地理配准需要精确的载具位姿与时间同步，
# 这是 flight/ 层的职责。edge/ 只负责"看"，不负责"我在哪"。
#
# 参考实现：07_domain_pv/PV-Hawk（视频 -> 组件提取 -> 地理配准 -> 电站映射的完整管线）

Detection detection                      # 原始图像坐标系的检出

# ---- 地理位置（缺陷在地面的估计位置）----
float64 latitude_deg                     # [deg] WGS84
float64 longitude_deg                    # [deg] WGS84
float32 altitude_amsl_m                  # [m] 地面点海拔估计

# ---- 配准质量与方法（论文里必须交代清楚，不能只给一个坐标）----
uint8 GEOREF_METHOD_NONE=0
uint8 GEOREF_METHOD_NADIR_FLAT=1         # 假设正下视 + 地面水平，最简单，误差最大
uint8 GEOREF_METHOD_PINHOLE_AGL=2        # 针孔模型 + AGL 高度反投影
uint8 GEOREF_METHOD_DEM=3                # 结合数字高程模型
uint8 georef_method

float32 georef_uncertainty_m             # [m] 估计的水平定位不确定度
bool georef_valid                        # false 表示位姿或高度不可信，此记录仅供参考

# ---- 溯源快照（保证每条台账记录可完全复现）----
VehicleState vehicle_state_at_capture    # 曝光时刻的载具状态
string source_image_uri                  # 原图存储位置，如 "minio://skylark/task-42/frame-001837.jpg"
uint32 time_sync_error_us                # [us] 图像时间戳与飞控时间戳的对齐残差
