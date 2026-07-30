"""扫掠的几何计算：覆盖率校验与割草机航线生成。

为什么单独成一个**不 import rclpy** 的模块
------------------------------------------
两个理由，第二个更重要：

1. 单测不需要拉起 ROS。覆盖率与航线是纯函数，`pytest` 秒级跑完，
   碎片时间就能推进；混进节点里就得拖着 rclpy 和 DDS 一起跑。
2. 论文的离线分析脚本要复用**同一份**公式。如果分析脚本自己再抄一遍幅宽公式，
   就会出现「论文里算的覆盖率和飞机实际飞的不是同一个东西」——
   这类错一旦发现，实验得重跑，而且它极难被察觉（两边看着都对）。
   所以公式只允许存在于这里。

坐标约定
--------
- NED：x 北、y 东、z 向下为正（与 PX4 `VehicleLocalPosition` 一致）。
- `heading_deg`：扫掠行的方向，0 = 正北，90 = 正东（航空惯例，顺时针为正）。
  注意这与数学上的极角方向相反，转换见 `_rotate_*`。

设计依据：`flight/docs/INSPECTION_MODE_DESIGN.md` §2、§3。
契约：`skylark_flight_msgs/action/InspectSweep.action`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# mono_cam 的水平视场，实测自 PX4 v1.17.0 的
# Tools/simulation/gz/models/mono_cam/model.sdf:54 <horizontal_fov>1.74</horizontal_fov>
# （配 1280x960、30 Hz）。核实脚本 99_notes/_probe_hfov.sh。
#
# ⚠ 这个常量是**仿真相机**的真值。换真机相机必须同步更新，
# 否则覆盖率保证是假的 —— 契约把覆盖率列为硬要求，这里写错等于整条保证失效。
MONO_CAM_HFOV_RAD = 1.74
MONO_CAM_HFOV_DEG = math.degrees(MONO_CAM_HFOV_RAD)   # 99.6949...

# 几何拒绝的两个阈值，理由见 §3。
MIN_SIDE_ROWS = 2.0          # 任一边长必须 >= 该倍数 x 行距，否则连两行都排不下
MAX_DIAGONAL_M = 1000.0      # 对角线上限，超了基本是坐标或单位传错
MIN_SPAN_M = 0.5             # 退化判据：边长小于这个数就当区域不成立


class GeometryError(ValueError):
    """几何不成立。调用方应转成 RESULT_REJECTED_BAD_GEOMETRY。"""


class CoverageError(ValueError):
    """覆盖率不达标。调用方应转成 RESULT_REJECTED_COVERAGE。"""


# ---------------------------------------------------------------- 覆盖率

def swath_width_m(altitude_agl_m: float, hfov_deg: float) -> float:
    """相机在给定高度下的地面幅宽（米）。

        swath = 2 * altitude * tan(hfov / 2)

    只算**横向**幅宽。航向重叠是帧率与速度的事（实测 25 fps @ 3 m/s
    帧间位移 0.12 m，远小于幅宽，不构成约束），不在这里管。
    """
    if altitude_agl_m <= 0.0:
        raise GeometryError(f"高度 {altitude_agl_m} m 无意义")
    if not 0.0 < hfov_deg < 180.0:
        raise GeometryError(f"水平视场 {hfov_deg}° 超出 (0, 180) 开区间")
    return 2.0 * altitude_agl_m * math.tan(math.radians(hfov_deg) / 2.0)


def overlap_ratio(row_spacing_m: float, swath_m: float) -> float:
    """相邻行的图像重叠率 = 1 - 行距 / 幅宽。

    行距大于幅宽时返回**负值**而不是夹到 0：负值的含义是「两行之间有条没拍到的带」，
    夹到 0 会把「刚好接上」和「漏了 10 米」混为一谈，而后者正是这道校验要拦的。
    """
    if row_spacing_m <= 0.0:
        raise GeometryError(f"行距 {row_spacing_m} m 无意义")
    if swath_m <= 0.0:
        raise GeometryError(f"幅宽 {swath_m} m 无意义")
    return 1.0 - row_spacing_m / swath_m


def check_coverage(altitude_agl_m: float, row_spacing_m: float,
                   min_overlap: float, hfov_deg: float) -> tuple[float, float]:
    """覆盖率校验。返回 (幅宽, 重叠率)；不达标抛 CoverageError。

    契约原文：「若 row_spacing_m 与相机视场、高度算出的重叠率低于 min_overlap，
    服务端拒绝该 goal 并返回 RESULT_REJECTED_COVERAGE，而不是默默地漏拍。」

    ⚠ 别把这道校验当成主要的质量保证。mono_cam 是 99.7° 超广角，
    契约默认（15 m / 6 m）下重叠率 83.1%，远超 min_overlap=0.25，几乎不会触发。
    真正的覆盖率风险在**航线跟踪误差**（Feedback 的 cross_track_error_m）。
    它防的是两类真实错误：行距按真机窄视场相机（典型 60~70°）的经验值填、
    以及低空高分辨率作业（3 m 高时幅宽仅 7.1 m，行距稍大就漏拍）。
    """
    if not 0.0 <= min_overlap < 1.0:
        raise GeometryError(f"min_overlap {min_overlap} 超出 [0, 1) 区间")
    swath = swath_width_m(altitude_agl_m, hfov_deg)
    ov = overlap_ratio(row_spacing_m, swath)
    if ov < min_overlap:
        raise CoverageError(
            f"行距 {row_spacing_m:.2f} m 在高度 {altitude_agl_m:.1f} m、"
            f"视场 {hfov_deg:.1f}° 下只有 {ov * 100:.1f}% 重叠，"
            f"低于要求的 {min_overlap * 100:.1f}%（幅宽 {swath:.2f} m）")
    return swath, ov


def max_row_spacing_m(altitude_agl_m: float, min_overlap: float,
                      hfov_deg: float) -> float:
    """满足 min_overlap 的最大行距。用于把拒绝消息写成可操作的建议值。"""
    return swath_width_m(altitude_agl_m, hfov_deg) * (1.0 - min_overlap)


# ---------------------------------------------------------------- 经纬度 <-> NED

# 等距圆柱（equirectangular）近似。作业半径百米量级时误差远小于 GPS 自身误差，
# 没必要上 UTM/Mercator。地球半径取 WGS84 长半轴。
EARTH_RADIUS_M = 6378137.0


def latlon_to_ned(lat_deg: float, lon_deg: float,
                  ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float]:
    """WGS84 -> 本地 NED 的 (北, 东)，单位米。参考点取 EKF 的 ref_lat/ref_lon。"""
    lat = math.radians(lat_deg - ref_lat_deg)
    lon = math.radians(lon_deg - ref_lon_deg)
    north = lat * EARTH_RADIUS_M
    # 经度方向要乘 cos(纬度)：同样的经度差在高纬度对应更短的地面距离。
    # 用参考点纬度而不是目标点纬度 —— 百米量级两者差异可忽略，但用参考点
    # 能保证正反变换严格互逆，否则往返一趟会有残差。
    east = lon * EARTH_RADIUS_M * math.cos(math.radians(ref_lat_deg))
    return north, east


def ned_to_latlon(north_m: float, east_m: float,
                  ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float]:
    """latlon_to_ned 的逆变换。"""
    lat = ref_lat_deg + math.degrees(north_m / EARTH_RADIUS_M)
    lon = ref_lon_deg + math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(math.radians(ref_lat_deg))))
    return lat, lon


# ---------------------------------------------------------------- 航线生成

def _rotate_to_row_frame(north: float, east: float, heading_deg: float
                         ) -> tuple[float, float]:
    """把 NED 的 (北, 东) 转到「行方向 = u 轴」的坐标系，返回 (u, v)。

    heading 是航空角（0=北，顺时针为正），行方向单位向量在 NED 里是
    (cos h, sin h)，与之垂直的是 (-sin h, cos h)。
    """
    h = math.radians(heading_deg)
    ch, sh = math.cos(h), math.sin(h)
    return north * ch + east * sh, -north * sh + east * ch


def _rotate_from_row_frame(u: float, v: float, heading_deg: float
                           ) -> tuple[float, float]:
    h = math.radians(heading_deg)
    ch, sh = math.cos(h), math.sin(h)
    return u * ch - v * sh, u * sh + v * ch


@dataclass(frozen=True)
class SweepPlan:
    """扫掠航线。waypoints_ned 直接喂给 FollowPath。

    z 一律取 -altitude_agl_m（NED 向下为正），高度基准是**起飞点**所在平面。
    """
    waypoints_ned: tuple[tuple[float, float, float], ...]
    rows_total: int
    row_length_m: float
    swath_m: float
    overlap: float
    area_m2: float
    path_length_m: float

    @property
    def waypoints_per_row(self) -> int:
        return 2


def plan_sweep(corner_a: tuple[float, float], corner_b: tuple[float, float],
               ref: tuple[float, float], *,
               heading_deg: float, altitude_agl_m: float,
               row_spacing_m: float, min_overlap: float,
               hfov_deg: float, resume_from_row: int = 0) -> SweepPlan:
    """生成割草机式扫掠航线。

    corner_a / corner_b / ref 都是 (纬度, 经度)，度。

    步骤（对应设计文档 §3）：
      1. 角点 -> NED
      2. 旋到「行方向 = u 轴」
      3. 按 row_spacing 切行
      4. 逐行生成端点，偶数行正向、奇数行反向
      5. 旋回 NED

    `resume_from_row` 直接切掉前 N 行，用于断点续飞。**每行的方向按它在完整
    航线里的原始序号决定**，不按切完之后的位置 —— 否则续飞后蛇形的相位会翻，
    接缝处会多飞一整行的长度。
    """
    if resume_from_row < 0:
        raise GeometryError(f"resume_from_row={resume_from_row} 不能为负")

    an, ae = latlon_to_ned(corner_a[0], corner_a[1], ref[0], ref[1])
    bn, be = latlon_to_ned(corner_b[0], corner_b[1], ref[0], ref[1])

    au, av = _rotate_to_row_frame(an, ae, heading_deg)
    bu, bv = _rotate_to_row_frame(bn, be, heading_deg)
    u_lo, u_hi = min(au, bu), max(au, bu)
    v_lo, v_hi = min(av, bv), max(av, bv)
    span_u, span_v = u_hi - u_lo, v_hi - v_lo

    if span_u < MIN_SPAN_M or span_v < MIN_SPAN_M:
        raise GeometryError(
            f"区域退化：行方向跨度 {span_u:.2f} m、横向跨度 {span_v:.2f} m，"
            f"至少要 {MIN_SPAN_M} m")
    diag = math.hypot(span_u, span_v)
    if diag > MAX_DIAGONAL_M:
        raise GeometryError(
            f"区域对角线 {diag:.0f} m 超过上限 {MAX_DIAGONAL_M:.0f} m，"
            f"疑似坐标或单位传错")
    # 「连两行都排不下」的判据落在**横向**跨度上：行方向短只是每行短，
    # 不影响能不能扫；横向短才会导致排不下行。
    if span_v < MIN_SIDE_ROWS * row_spacing_m:
        raise GeometryError(
            f"横向跨度 {span_v:.2f} m 不足 {MIN_SIDE_ROWS:.0f} × 行距 "
            f"{row_spacing_m:.2f} m，区域太小排不下两行")

    swath, ov = check_coverage(altitude_agl_m, row_spacing_m,
                              min_overlap, hfov_deg)

    # 行数：跨度切成 ceil(span/spacing) 段，端点数比段数多 1。
    # 这样首行贴 v_lo、末行贴 v_hi，两条边界都被覆盖 —— 用 floor 会漏掉末行。
    rows_total = int(math.ceil(span_v / row_spacing_m)) + 1
    if resume_from_row >= rows_total:
        raise GeometryError(
            f"resume_from_row={resume_from_row} 超出总行数 {rows_total}")

    z = -abs(altitude_agl_m)
    wps: list[tuple[float, float, float]] = []
    for row in range(resume_from_row, rows_total):
        # 末行夹到 v_hi：span_v 通常不是 spacing 的整数倍，
        # 不夹的话末行会飞到区域外面去
        v = min(v_lo + row * row_spacing_m, v_hi)
        # 方向按**原始行号**的奇偶，见 docstring
        u_first, u_second = (u_lo, u_hi) if row % 2 == 0 else (u_hi, u_lo)
        for u in (u_first, u_second):
            n, e = _rotate_from_row_frame(u, v, heading_deg)
            wps.append((n, e, z))

    path_len = sum(math.dist(wps[i][:2], wps[i + 1][:2])
                   for i in range(len(wps) - 1))
    return SweepPlan(
        waypoints_ned=tuple(wps),
        rows_total=rows_total,
        row_length_m=span_u,
        swath_m=swath,
        overlap=ov,
        area_m2=span_u * span_v,
        path_length_m=path_len,
    )
