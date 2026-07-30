"""Land action 的执行逻辑。

实现取向：**委托给飞控自带的 AUTO_LAND / AUTO_RTL，而不是在 offboard 里自己压高度。**

理由是触地检测与落地上锁属于安全关键逻辑：PX4 的 land detector 综合了推力、
垂速、加速度与地形估计，经过大量真机验证。自己在 offboard 里往下给 z 目标，
既拿不到这套判据，还要自己处理"压到地面却检测不到触地"的情况 —— 只会更差。

代价与如实告知
--------------
委托的代价是 Goal 里两个字段无法逐次生效，它们由飞控参数决定：
    descent_rate_mps       -> MPC_LAND_SPEED / MPC_Z_VEL_MAX_DN
    transit_altitude_agl_m -> RTL_RETURN_ALT
本实现不去改飞控参数（一个动作调用偷偷改飞控配置是危险的副作用，
而且会影响之后所有飞行），而是在 Result.message 里明确告知实际由参数决定。
需要按任务调这两个值的话，应该在任务开始前统一设参数，而不是塞进单次动作。

取消语义（契约原文）
--------------------
「本动作被取消时，飞机停止下降并悬停在当前位置。但若飞控自身的失效保护已触发
（低电量等），取消请求会被忽略 —— 飞控优先级高于 ROS 2 层。」
所以取消分两条路：failsafe 未触发时移交 AUTO_LOITER；已触发时**不干预**，
让飞控把降落做完，并在 message 里说明取消被忽略。
"""

from __future__ import annotations

import time

from skylark_flight_msgs.action import Land

from .px4_link import NAV_AUTO_LAND, NAV_AUTO_RTL, PX4Link


def preflight_reject(link: PX4Link) -> tuple[int, str] | None:
    """返回 (result_code, message) 表示该拒；None 表示可继续。"""
    if not link.connected:
        return (Land.Result.RESULT_AUTOPILOT_ERROR,
                f"与飞控无连接（上次收到状态 {link.link_age_ms} ms 前）")
    if not link.armed:
        return (Land.Result.RESULT_REJECTED_NOT_FLYING, "飞机未解锁")
    # 已在地面：契约里 NOT_FLYING 就是给这种情况的。用飞控的 land detector 判，
    # 不用"高度接近 0"（斜坡与气压漂移会误判）
    if link.landed:
        return (Land.Result.RESULT_REJECTED_NOT_FLYING,
                f"飞控报告已在地面（land_detected=true），当前模式 {link.nav_state_name}")
    return None


def execute(node, goal_handle):
    """node 需要提供 .link 与 .get_logger()。"""
    link: PX4Link = node.link
    log = node.get_logger()
    g = goal_handle.request
    t_start = time.time()
    settle = getattr(node, "mode_settle", 2.0)

    def result(code: int, msg: str):
        r = Land.Result()
        r.result_code = code
        r.success = (code == Land.Result.RESULT_OK)
        r.disarmed = not link.armed
        r.elapsed_sec = float(time.time() - t_start)
        r.message = msg
        return r

    mode_name = ("返航后降落" if g.mode == Land.Goal.MODE_RETURN_TO_LAUNCH else "原地降落")
    log.info(f"Land 开始：{mode_name}，超时 {g.timeout_sec:.0f}s")

    rej = preflight_reject(link)
    if rej:
        code, msg = rej
        log.warn(f"前置校验未过：{msg}")
        goal_handle.abort()
        return result(code, msg)

    # 若此前有 offboard 动作在跑，先停掉心跳：接下来交给飞控自主模式，
    # 继续发 setpoint 只会和飞控的降落逻辑打架
    link.stop_heartbeat()

    if g.mode == Land.Goal.MODE_RETURN_TO_LAUNCH:
        res = link.set_mode_auto_rtl()
        expect_modes = (NAV_AUTO_RTL, NAV_AUTO_LAND)
        param_note = ("返航高度由 RTL_RETURN_ALT 决定，"
                      f"Goal.transit_altitude_agl_m={g.transit_altitude_agl_m:.0f} 未逐次生效")
    else:
        res = link.set_mode_auto_land()
        expect_modes = (NAV_AUTO_LAND,)
        param_note = ("下降率由 MPC_LAND_SPEED 决定，"
                      f"Goal.descent_rate_mps={g.descent_rate_mps:.1f} 未逐次生效")

    if not res.accepted:
        goal_handle.abort()
        return result(Land.Result.RESULT_AUTOPILOT_ERROR,
                      f"切降落模式被拒：{res.describe()}")

    deadline = time.time() + settle
    while link.nav_state not in expect_modes and time.time() < deadline:
        time.sleep(0.05)
    if link.nav_state not in expect_modes:
        goal_handle.abort()
        return result(Land.Result.RESULT_AUTOPILOT_ERROR,
                      f"命令已接受但 {settle}s 后模式仍是 {link.nav_state_name}")
    log.info(f"已进入 {link.nav_state_name}")

    timeout = float(g.timeout_sec) if g.timeout_sec > 0 else 300.0
    fb_period = 1.0 / max(getattr(node, "feedback_hz", 5.0), 0.5)
    next_fb = time.time()
    x0, y0, _ = link.current_ned()
    cancel_ignored = False

    while True:
        now = time.time()
        elapsed = now - t_start

        # 成功判据：飞控报告触地。上锁与否单独放进 Result.disarmed，
        # 因为 COM_DISARM_LAND 可能配成不自动上锁，那时"没上锁"不等于"没降落成功"
        if link.landed:
            # 给飞控一点时间完成自动上锁再读 disarmed
            time.sleep(2.0)
            msg = f"已降落（{mode_name}），{'已上锁' if not link.armed else '仍解锁'}。{param_note}"
            if cancel_ignored:
                msg += "。取消请求因飞控失效保护已触发而被忽略（飞控优先）"
            log.info(msg)
            goal_handle.succeed()
            return result(Land.Result.RESULT_OK, msg)

        if goal_handle.is_cancel_requested:
            if link.failsafe_active:
                # 契约明确：飞控自主保护不可被外部软件否决
                if not cancel_ignored:
                    log.warn("收到取消，但飞控处于失效保护中，按契约忽略取消，继续降落")
                    cancel_ignored = True
            else:
                ok, hmsg = link.handover_to_loiter("Land 被取消", settle)
                goal_handle.canceled()
                return result(Land.Result.RESULT_CANCELED,
                              f"已取消，停止下降并悬停（{hmsg}）")

        if not link.armed and not link.landed:
            # 空中失去解锁：不是正常降落，要如实报错而不是当成成功
            goal_handle.abort()
            return result(Land.Result.RESULT_AUTOPILOT_ERROR,
                          "降落过程中飞机在未触地的情况下上锁，状态异常")

        if elapsed > timeout:
            alt = link.altitude_agl_m
            goal_handle.abort()
            return result(Land.Result.RESULT_TIMEOUT,
                          f"{timeout:.0f}s 内未触地，当前高度 "
                          f"{alt if alt is not None else float('nan'):.2f} m，"
                          f"模式 {link.nav_state_name}")

        if now >= next_fb:
            alt = link.altitude_agl_m or 0.0
            x, y, _ = link.current_ned()
            fb = Land.Feedback()
            # 阶段按**实际运动**判，不按 nav_state。
            #
            # PX4 的 RTL 自己把降落做完，全程 nav_state 都是 AUTO_RTL，
            # 从不切到 AUTO_LAND。第一版按 nav_state 判，结果整个下降过程
            # 都上报 PHASE_TRANSIT（实测反馈里高度从 8.4 m 掉到 -0.04 m
            # 却一直显示"返航"），调用方据此无法知道飞机已经在下降。
            vz = link.lpos.vz if link.lpos else 0.0     # NED，向下为正
            if alt < 0.5:
                fb.phase = Land.Feedback.PHASE_TOUCHDOWN
            elif vz > 0.3:
                fb.phase = Land.Feedback.PHASE_DESCENDING
            else:
                fb.phase = Land.Feedback.PHASE_TRANSIT
            fb.current_altitude_agl_m = float(alt)
            # 返航时"目标"是起飞点（局部原点），原地降落时水平距离恒为 0
            fb.distance_to_target_m = float((x * x + y * y) ** 0.5) \
                if g.mode == Land.Goal.MODE_RETURN_TO_LAUNCH else 0.0
            fb.elapsed_sec = float(elapsed)
            goal_handle.publish_feedback(fb)
            next_fb = now + fb_period

        time.sleep(0.05)
