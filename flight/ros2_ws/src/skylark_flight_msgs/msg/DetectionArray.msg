# 一帧图像的全部检出结果。
#
# 话题：/skylark/detections
# 发布者：edge/ 推理节点
# 订阅者：flight/ 的 skylark_inspection_mode（决定是否触发 Revisit）
#
# 铁律：本消息只描述"看到了什么"。它不包含任何飞行指令。
# 视觉节点若想改变飞机行为，必须调用 flight/ 提供的 action，不得发布 setpoint。

std_msgs/Header header                   # stamp = 图像曝光时刻（不是推理完成时刻！）
                                         # frame_id = 相机坐标系，如 "cam_down"

Detection[] detections

# ---- 图像元信息 ----
uint16 image_width                       # [px]
uint16 image_height                      # [px]

# ---- 推理性能埋点（照抄 PX4 NeuralControl 的做法：把耗时做进消息里）----
uint32 preprocess_us                     # [us] 预处理耗时
uint32 inference_us                      # [us] 纯推理耗时
uint32 postprocess_us                    # [us] 后处理 + NMS 耗时
builtin_interfaces/Time capture_stamp    # 图像曝光时刻（冗余保留，便于跨机核对时间同步）

# ---- 模型溯源（保证任何一帧检出都能追溯到具体模型版本）----
string model_name                        # 如 "yolo11n_full"
string model_version                     # 如 "v2-200ep-a1b2c3d"
string model_precision                   # "fp32" / "fp16" / "int8"
