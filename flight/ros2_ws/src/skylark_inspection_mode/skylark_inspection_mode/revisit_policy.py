"""Revisit 的安全策略：参数夹紧与频率限制。纯函数，不 import rclpy。

契约原文（Revisit.action 头部）：
「本动作的所有参数都会被服务端夹紧到安全范围内（最低高度、最大偏移、
地理围栏、剩余电量余量）。调用方给出的值是『请求』而非『命令』，
实际执行值见 Result.actual_* 字段。」

把这部分单独拎成纯函数的理由和 geometry 一样：夹紧规则是**安全边界**，
它必须能被秒级单测覆盖，而不是只能在一次 5 分钟的 SITL 里碰运气验到。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# 夹紧规则的默认值。依据见 INSPECTION_MODE_DESIGN.md §5。
DEFAULT_MIN_AGL_M = 3.0        # 再低地效与测距噪声都显著，且留不出改出余量
DEFAULT_MAX_HOVER_SEC = 30.0   # 防止误检导致长时间占用
DEFAULT_MAX_BURST = 20         # 同上
DEFAULT_MAX_OFFSET_M = 50.0    # 复拍是"就近降高"，偏移过大说明该发别的动作

# 频率限制：同一目标点短时间内重复请求直接拒。
# 判据刻意用"距离 + 时间"两条而不是全局冷却 —— 全局冷却会把相邻两个
# **真实**缺陷误拒，而那正是巡检最不该漏的情况。
DEFAULT_RATE_LIMIT_SEC = 30.0
DEFAULT_RATE_LIMIT_RADIUS_M = 5.0


class UnsafeRequest(ValueError):
    """请求无法通过夹紧变安全。调用方应转成 RESULT_REJECTED_UNSAFE。"""


@dataclass
class ClampedRevisit:
    agl_m: float
    hover_sec: float
    capture_burst: int
    offset_m: float
    # 每条被改动的参数都要留下痕迹：调用方只看 actual_* 数字看不出
    # "为什么变了"，而这类静默改动最容易被误当成自己算错。
    notes: list[str] = field(default_factory=list)

    @property
    def was_clamped(self) -> bool:
        return bool(self.notes)


def clamp_revisit(*, requested_agl_m: float, requested_hover_sec: float,
                  requested_burst: int, offset_m: float,
                  min_agl_m: float = DEFAULT_MIN_AGL_M,
                  max_hover_sec: float = DEFAULT_MAX_HOVER_SEC,
                  max_burst: int = DEFAULT_MAX_BURST,
                  max_offset_m: float = DEFAULT_MAX_OFFSET_M) -> ClampedRevisit:
    """把请求夹紧到安全范围。夹不动的情况抛 UnsafeRequest。

    水平偏移**超限就拒，不夹紧**。这一条与设计文档 §5 表格里写的"夹紧"
    不一致，是有意的偏离，理由在同一张表的"依据"列里：
    「复拍是就近降高，偏移过大说明调用方该发别的动作」。
    把 60 m 的偏移夹到 50 m，等于飞到一个**调用方没要求的位置**去复拍，
    然后回报 success —— 那比直接拒更糟：调用方会拿着错位置的图像下结论。
    夹紧只适用于"同一件事做得更保守"（降得没那么低、悬停没那么久），
    不适用于"换个地方做"。
    """
    notes: list[str] = []

    if not math.isfinite(requested_agl_m) or not math.isfinite(offset_m):
        raise UnsafeRequest("请求含 NaN/Inf")

    if offset_m > max_offset_m:
        raise UnsafeRequest(
            f"目标点距当前位置 {offset_m:.1f} m，超过复拍偏移上限 "
            f"{max_offset_m:.0f} m。复拍是「就近降高」；这么远应该先用扫掠或"
            f"重定位动作过去，而不是把偏移夹到 {max_offset_m:.0f} m "
            f"去拍一个你没要求的位置")

    agl = float(requested_agl_m)
    if agl < min_agl_m:
        notes.append(f"复拍高度 {agl:.1f} m 抬到安全下限 {min_agl_m:.1f} m")
        agl = float(min_agl_m)

    hover = float(requested_hover_sec)
    if hover < 0.0:
        notes.append(f"悬停时长 {hover:.1f} s 无意义，取 0")
        hover = 0.0
    elif hover > max_hover_sec:
        notes.append(f"悬停时长 {hover:.1f} s 压到上限 {max_hover_sec:.0f} s")
        hover = float(max_hover_sec)

    burst = int(requested_burst)
    if burst < 0:
        notes.append(f"连拍张数 {burst} 无意义，取 0")
        burst = 0
    elif burst > max_burst:
        notes.append(f"连拍张数 {burst} 压到上限 {max_burst}")
        burst = int(max_burst)

    return ClampedRevisit(agl_m=agl, hover_sec=hover, capture_burst=burst,
                          offset_m=float(offset_m), notes=notes)


def rate_limited(last: tuple[float, float, float] | None, now: float,
                 x: float, y: float,
                 window_sec: float = DEFAULT_RATE_LIMIT_SEC,
                 radius_m: float = DEFAULT_RATE_LIMIT_RADIUS_M) -> tuple[bool, str]:
    """判断这次复拍请求是否该按 RESULT_REJECTED_RATE_LIMITED 拒掉。

    last = (上次复拍点 x, y, 时刻)，None 表示没有历史。
    返回 (要不要拒, 说明)。

    两个条件**都**满足才拒：离上次复拍点近（< radius_m）且间隔短（< window_sec）。
    只看时间会把相邻两个真实缺陷误拒；只看距离会让同一个误检无限重试。
    """
    if last is None:
        return False, ""
    lx, ly, lt = last
    dt = now - lt
    dist = math.hypot(x - lx, y - ly)
    if dt < window_sec and dist < radius_m:
        return True, (f"{dt:.1f} s 前刚在 {dist:.1f} m 内复拍过"
                      f"（限制：{radius_m:.0f} m 内 {window_sec:.0f} s 一次）。"
                      f"这条限制防的是误检导致飞机在同一点反复下降")
    return False, ""


def onstation(*, agl_m: float, target_agl_m: float, speed_mps: float,
              alt_tol_m: float, max_speed_mps: float) -> bool:
    """单帧是否满足"到位"。**连续保持**由调用方计时，见设计文档 §4。

    刻意不在这里做"保持 1 秒"的判断：把计时和单帧判据分开，
    单帧判据才能被纯函数单测覆盖。
    """
    return abs(agl_m - target_agl_m) <= alt_tol_m and speed_mps <= max_speed_mps
