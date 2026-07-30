"""Orbit action 的执行逻辑：绕指定点定圆巡视。

为什么用 offboard 自己算圆，而不是飞控的 VEHICLE_CMD_DO_ORBIT
--------------------------------------------------------------
PX4 有 DO_ORBIT 命令，但契约要求的反馈是 revolutions_completed / bearing_deg /
radius_error_m，也就是**任务进度与跟踪质量**。这些量飞控不回传，只能自己算；
而一旦要自己算，setpoint 也就顺手自己给了，还能顺带支持三种 yaw 模式
（朝圆心 / 沿切向 / 保持），这三种里"朝圆心"是拍摄目标最常用的，
DO_ORBIT 的 yaw 行为枚举不一定覆盖得这么直接。

与 Land 的取向刚好相反 —— Land 委托飞控是因为触地检测是安全关键；
Orbit 自己实现是因为任务语义在我们这边。这个区别是有意的。

几何校验（RESULT_REJECTED_BAD_GEOMETRY）
---------------------------------------
宁可在起飞前拒绝，也不要飞出一个荒谬的圆。校验三件事：半径下限、圆心距离上限、
以及经纬度输入时 EKF 是否真的有全局参考（xy_global 为假时任何经纬度都无法解释，
必须拒绝而不是当成 0,0）。
"""

from __future__ import annotations

import math
import time

from skylark_flight_msgs.action import Orbit

from .px4_link import PX4Link

MIN_RADIUS_M = 2.0          # 小于这个半径，姿态环跟不上，圆会变成原地打转
MAX_CENTER_DIST_M = 500.0   # 圆心离当前位置太远，说明调用方大概传错了坐标系
MIN_ALTITUDE_M = 1.0


def _resolve_center(link: PX4Link, g) -> tuple[tuple[float, float] | None, str]:
    """把 Goal 里的圆心解析成局部 NED 的 (north, east)。"""
    if g.use_global_center:
        ned = link.global_to_ned(float(g.center_latitude_deg), float(g.center_longitude_deg))
        if ned is None:
            return (None, "use_global_center=true 但 EKF 无全局参考（xy_global=false），"
                          "无法把经纬度换算到局部坐标")
        return (ned, f"圆心来自经纬度 ({g.center_latitude_deg:.7f}, {g.center_longitude_deg:.7f})")
    return ((float(g.center_north_m), float(g.center_east_m)),
            f"圆心来自 NED 偏移 (N={g.center_north_m:.1f}, E={g.center_east_m:.1f})")


def preflight_reject(link: PX4Link, g) -> tuple[int, str] | None:
    if not link.connected:
        return (Orbit.Result.RESULT_REJECTED_NOT_READY,
                f"与飞控无连接（上次收到状态 {link.link_age_ms} ms 前）")
    if not link.position_valid:
        return (Orbit.Result.RESULT_REJECTED_NOT_READY, "位置估计无效")
    if not link.armed:
        return (Orbit.Result.RESULT_REJECTED_NOT_READY,
                "飞机未解锁。Orbit 是飞行中动作，需先 Takeoff")
    if link.landed:
        return (Orbit.Result.RESULT_REJECTED_NOT_READY, "飞控报告仍在地面")
    if link.failsafe_active:
        return (Orbit.Result.RESULT_ABORTED_BY_FAILSAFE,
                f"飞控处于失效保护：{', '.join(link.failsafe_reasons()) or '原因未知'}")

    if g.radius_m < MIN_RADIUS_M:
        return (Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                f"半径 {g.radius_m:.1f} m 小于下限 {MIN_RADIUS_M} m")
    if g.altitude_agl_m < MIN_ALTITUDE_M:
        return (Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                f"高度 {g.altitude_agl_m:.1f} m 小于下限 {MIN_ALTITUDE_M} m")
    if g.speed_mps <= 0.0:
        return (Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                f"切向速度 {g.speed_mps:.1f} m/s 无意义")
    if g.revolutions <= 0.0:
        return (Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                f"圈数 {g.revolutions:.2f} 无意义")

    center, _ = _resolve_center(link, g)
    if center is None:
        return (Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                _resolve_center(link, g)[1])
    x, y, _ = link.current_ned()
    dist = math.hypot(center[0] - x, center[1] - y)
    if dist > MAX_CENTER_DIST_M:
        return (Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                f"圆心距当前位置 {dist:.0f} m，超过上限 {MAX_CENTER_DIST_M:.0f} m，"
                f"疑似坐标系或单位传错")
    return None


def execute(node, goal_handle):
    link: PX4Link = node.link
    log = node.get_logger()
    g = goal_handle.request
    t_start = time.time()
    settle = getattr(node, "mode_settle", 2.0)

    revolutions_done = 0.0

    def result(code: int, msg: str):
        r = Orbit.Result()
        r.result_code = code
        r.success = (code == Orbit.Result.RESULT_OK)
        r.revolutions_completed = float(revolutions_done)
        r.elapsed_sec = float(time.time() - t_start)
        r.message = msg
        return r

    rej = preflight_reject(link, g)
    if rej:
        code, msg = rej
        log.warn(f"Orbit 前置校验未过：{msg}")
        goal_handle.abort()
        return result(code, msg)

    center, center_note = _resolve_center(link, g)
    cn, ce = center
    radius = float(g.radius_m)
    alt = float(g.altitude_agl_m)
    omega = float(g.speed_mps) / radius          # rad/s，切向速度换成角速度
    direction = 1.0 if g.clockwise else -1.0
    total_angle = 2.0 * math.pi * float(g.revolutions)
    timeout = float(g.timeout_sec) if g.timeout_sec > 0 else 300.0

    x0, y0, _ = link.current_ned()
    # 从当前位置所在的方位角起圈，避免一上来就横向跳一大步
    bearing0 = math.atan2(y0 - ce, x0 - cn)

    log.info(f"Orbit 开始：{center_note}，半径 {radius:.1f} m，高度 {alt:.1f} m，"
             f"切向 {g.speed_mps:.1f} m/s（角速度 {math.degrees(omega):.1f} deg/s），"
             f"{'顺' if g.clockwise else '逆'}时针 {g.revolutions:.2f} 圈，"
             f"预计 {total_angle / omega:.0f}s")
    if total_angle / omega > timeout:
        goal_handle.abort()
        return result(Orbit.Result.RESULT_REJECTED_BAD_GEOMETRY,
                      f"按给定速度需 {total_angle / omega:.0f}s，超过 timeout_sec="
                      f"{timeout:.0f}s，参数自相矛盾")

    def target_at(angle_from_start: float) -> tuple[float, float, float, float]:
        """返回该角度处的 (north, east, down, yaw)。"""
        b = bearing0 + direction * angle_from_start
        n = cn + radius * math.cos(b)
        e = ce + radius * math.sin(b)
        if g.yaw_mode == Orbit.Goal.YAW_FACE_CENTER:
            yaw = math.atan2(ce - e, cn - n)          # 由机体指向圆心
        elif g.yaw_mode == Orbit.Goal.YAW_FACE_TANGENT:
            yaw = b + direction * math.pi / 2.0
        else:
            yaw = link.current_heading()
        return (n, e, -alt, yaw)

    n, e, d, yaw = target_at(0.0)
    link.start_heartbeat((n, e, d), yaw)

    # 攒够 setpoint 再切模式：切 OFFBOARD 前必须已有 setpoint 流，否则会被拒
    preheat = getattr(node, "preheat", 15)
    deadline = time.time() + 5.0
    while link.heartbeat_count < preheat and time.time() < deadline:
        time.sleep(0.05)

    def guard() -> tuple[int, str] | None:
        """入圈与绕圈两个阶段共用的中止判据。None 表示可继续。"""
        if link.failsafe_active and not link.in_offboard:
            reasons = ", ".join(link.failsafe_reasons()) or "原因未知"
            return (Orbit.Result.RESULT_ABORTED_BY_FAILSAFE,
                    f"飞控接管（模式 {link.nav_state_name}），原因: {reasons}")
        if not link.armed:
            return (Orbit.Result.RESULT_ABORTED_BY_FAILSAFE,
                    f"飞行中被解除解锁，模式 {link.nav_state_name}")
        if link.offboard_signal_really_lost:
            return (Orbit.Result.RESULT_ABORTED_BY_FAILSAFE,
                    f"offboard 信号持续丢失 {link.offboard_signal_lost_for():.1f}s")
        return None

    if not link.in_offboard:
        res = link.set_mode_offboard()
        if not res.accepted:
            link.handover_to_loiter("Orbit 切 OFFBOARD 失败", settle)
            goal_handle.abort()
            return result(Orbit.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"切 OFFBOARD 被拒：{res.describe()}")
        deadline = time.time() + settle
        while not link.in_offboard and time.time() < deadline:
            time.sleep(0.05)
        if not link.in_offboard:
            link.handover_to_loiter("Orbit 模式未切换", settle)
            goal_handle.abort()
            return result(Orbit.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"命令已接受但模式仍是 {link.nav_state_name}")

    fb_period = 1.0 / max(getattr(node, "feedback_hz", 5.0), 0.5)
    next_fb = time.time()

    # ---- 入圈阶段 ----
    #
    # 必须先飞到圆上再开始计圈。第一版没有这一步，直接从当前位置开始算角度，
    # 后果是：起飞点若在圆心附近，setpoint 一上来就跳到半径外，
    # 于是 radius_error_m 的第一帧是 -7.75 m（实测），
    # revolutions_completed 也在飞机还没到圆上时就开始涨。
    # 这两个量是契约里用来评估**跟踪质量与任务进度**的，
    # 把"飞向圆"的过程混进去，读数就失去意义了。
    entry_tol = max(1.5, radius * 0.15)
    entry_timeout = min(60.0, timeout * 0.5)
    log.info(f"入圈：飞往圆上最近点，容差 {entry_tol:.1f} m，限时 {entry_timeout:.0f}s")
    t_entry0 = time.time()
    while True:
        now = time.time()
        if goal_handle.is_cancel_requested:
            link.handover_to_loiter("Orbit 入圈阶段被取消", settle)
            goal_handle.canceled()
            return result(Orbit.Result.RESULT_CANCELED, "入圈阶段被取消，悬停在当前位置")
        g_ = guard()
        if g_:
            code, msg = g_
            if code == Orbit.Result.RESULT_ABORTED_BY_FAILSAFE and link.in_offboard:
                link.handover_to_loiter("入圈阶段中止", settle)
            goal_handle.abort()
            return result(code, f"入圈阶段：{msg}")
        if now - t_entry0 > entry_timeout:
            link.handover_to_loiter("入圈超时", settle)
            goal_handle.abort()
            return result(Orbit.Result.RESULT_TIMEOUT,
                          f"{entry_timeout:.0f}s 内未飞到圆上（容差 {entry_tol:.1f} m）")

        x, y, _ = link.current_ned()
        dist_to_entry = math.hypot(x - n, y - e)
        if dist_to_entry <= entry_tol:
            log.info(f"已入圈（距入圈点 {dist_to_entry:.2f} m，用时 {now - t_entry0:.1f}s）")
            break

        if now >= next_fb:
            actual_r = math.hypot(x - cn, y - ce)
            fb = Orbit.Feedback()
            fb.revolutions_completed = 0.0        # 入圈期间进度恒为 0，不虚报
            fb.bearing_deg = float(math.degrees(math.atan2(y - ce, x - cn)))
            fb.radius_error_m = float(actual_r - radius)
            fb.elapsed_sec = float(now - t_start)
            goal_handle.publish_feedback(fb)
            next_fb = now + fb_period
        time.sleep(0.05)

    # 入圈点可能与 bearing0 有偏差，从实际所在方位重新起算，避免起圈瞬间横跳
    x, y, _ = link.current_ned()
    bearing0 = math.atan2(y - ce, x - cn)
    t_orbit0 = time.time()

    while True:
        now = time.time()
        elapsed = now - t_start
        angle = omega * (now - t_orbit0)
        revolutions_done = angle / (2.0 * math.pi)

        if goal_handle.is_cancel_requested:
            link.handover_to_loiter("Orbit 被取消", settle)
            goal_handle.canceled()
            return result(Orbit.Result.RESULT_CANCELED,
                          f"已取消，完成 {revolutions_done:.2f} 圈，悬停在当前位置")

        # 与入圈阶段共用同一套中止判据，避免两处逻辑各自漂移
        g_ = guard()
        if g_:
            code, msg = g_
            if link.in_offboard:
                link.handover_to_loiter("绕圈中止", settle)
            goal_handle.abort()
            return result(code, msg)

        if elapsed > timeout:
            link.handover_to_loiter("Orbit 超时", settle)
            goal_handle.abort()
            return result(Orbit.Result.RESULT_TIMEOUT,
                          f"{timeout:.0f}s 内只完成 {revolutions_done:.2f}/"
                          f"{g.revolutions:.2f} 圈")

        if angle >= total_angle:
            link.handover_to_loiter("Orbit 完成", settle)
            goal_handle.succeed()
            return result(Orbit.Result.RESULT_OK,
                          f"完成 {revolutions_done:.2f} 圈（目标 {g.revolutions:.2f}）")

        n, e, d, yaw = target_at(angle)
        link.update_heartbeat_target((n, e, d), yaw)

        if now >= next_fb:
            x, y, _ = link.current_ned()
            actual_r = math.hypot(x - cn, y - ce)
            fb = Orbit.Feedback()
            fb.revolutions_completed = float(revolutions_done)
            fb.bearing_deg = float(math.degrees(math.atan2(y - ce, x - cn)))
            fb.radius_error_m = float(actual_r - radius)
            fb.elapsed_sec = float(elapsed)
            goal_handle.publish_feedback(fb)
            next_fb = now + fb_period

        time.sleep(0.05)
