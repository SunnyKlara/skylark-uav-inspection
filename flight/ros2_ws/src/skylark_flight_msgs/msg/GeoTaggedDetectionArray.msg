# 一批已配准的检出结果。
#
# 话题：/skylark/geo_detections
# 这是 flight/edge 与 platform/ 之间的上行数据单元。
# 按批打包而非逐条发送，是为了在 4G/图传链路上减少往返开销。

std_msgs/Header header

GeoTaggedDetection[] detections

# ---- 任务上下文 ----
string task_id                           # platform/ 侧的巡检任务 ID
string mission_name                      # 如 "PV_Array_Inspection"
uint32 sweep_row_index                   # 当前扫掠到第几行（InspectSweep 提供），无则 0
