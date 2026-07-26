# 单个视觉检出结果（图像坐标系）。
#
# 发布者：edge/ 的推理节点（对应 AAS 的 yolo_py）
#
# 设计说明：为什么不用 vision_msgs/Detection2D —— 那会引入 ros-humble-vision-msgs
# 依赖，且它的 ObjectHypothesisWithPose 结构对本项目冗余。这里用最小自定义结构，
# 代价是与通用视觉工具链不兼容，收益是接口契约完全自洽、无外部版本耦合。
# 若后续需要接入 ROS 2 视觉生态，再加一个转换节点即可。

uint16 class_id                          # 类别索引，与训练时 data.yaml 的 names 顺序一致
string class_name                        # 类别名，如 "crack" / "finger" / "black_core"
float32 confidence                       # 0.0 .. 1.0

# ---- 边界框（像素坐标，原点左上角）----
uint16 bbox_x                            # 左上角 x
uint16 bbox_y                            # 左上角 y
uint16 bbox_w                            # 宽
uint16 bbox_h                            # 高

# ---- 严重等级（由业务规则从 class_id + 面积 + 置信度推导，非模型直接输出）----
uint8 SEVERITY_UNKNOWN=0
uint8 SEVERITY_INFO=1
uint8 SEVERITY_MINOR=2
uint8 SEVERITY_MAJOR=3
uint8 SEVERITY_CRITICAL=4
uint8 severity
