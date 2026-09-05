"""FollowPath action 的执行逻辑：沿航点序列飞行。

这是 flight 层的内部动作，给 skylark_inspection_mode 的扫掠用。
它存在的理由是结构性的：扫掠需要航点跟随，但 inspection_mode 不能自己发 setpoint
—— offboard 的 setpoint 流必须只有一个发布者（实测约束，两个发布者会互相打断
且日志里看不出来）。所以航线由 inspection_mode 算，执行放在 iface 内。

跟踪方式：**沿航段推进目标点**，不是"把下一个航点直接当 setpoint"。
后者在长航段上会让飞机一开始就朝远处全速冲，姿态与高度都不好收，
而且横向偏差无从谈起（目标就在远处，没有"航线"这个概念）。
本实现让目标点以 speed_mps 沿当前航段匀速前移，飞机跟着走 ——
这和 Orbit 里目标点沿圆周前移是同一个模式，实测半径误差能压到 0.4 m 量级。
"""

from __future__ import annotations

import math
import time

from skylark_flight_internal_msgs.action import FollowPath

from .px4_link import PX4Link

MAX_WAYPOINT_DIST_M = 2000.0     # 单个航点离原点过远，基本是坐标系或单位传错
MIN_SEGMENT_M = 0.05             # 短于此的航段直接跳过，避免除零与目标点抖动


def _cross_track_error(p: tuple[float, float], a: tuple[float, float],
                       b: tuple[float, float]) -> float:
    """点 p 到有向线段 a->b 所在直线的垂直距离（米）。

    用直线而不是线段：横向偏差的语义是"离航线多远"，
    在航段端点附近也应该按航线延长线算，否则数值会在切换航点时跳变。
    """
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg = math.hypot(dx, dy)
    if seg < MIN_SEGMENT_M:
        return math.hypot(p[0] - ax, p[1] - ay)
    # 二维叉积除以段长 = 点到直线距离
    return abs(dx * (p[1] - ay) - dy * (p[0] - ax)) / seg


def preflight_reject(link: PX4Link, g) -> tuple[int, str] | None:
    if not link.connected:
        return (FollowPath.Result.RESULT_REJECTED_NOT_READY,
                f"与飞控无连接（上次收到状态 {link.link_age_ms} ms 前）")
    if not link.position_valid:
        return (FollowPath.Result.RESULT_REJECTED_NOT_READY, "位置估计无效")
    if not link.armed:
        return (FollowPath.Result.RESULT_REJECTED_NOT_READY,
                "飞机未解锁。FollowPath 是飞行中动作，需先 Takeoff")
    if link.landed:
        return (FollowPath.Result.RESULT_REJECTED_NOT_READY, "飞控报告仍在地面")

    wps = list(g.waypoints_ned)
    if len(wps) < 2:
        return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                f"航点数 {len(wps)} < 2，构不成航线")
    if g.start_index >= len(wps):
        return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                f"start_index={g.start_index} 超出航点数 {len(wps)}")
    if g.speed_mps <= 0.0:
        return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                f"速度 {g.speed_mps} m/s 无意义")
    if g.accept_radius_m <= 0.0:
        return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                f"到达半径 {g.accept_radius_m} m 无意义")
    for i, w in enumerate(wps):
        for name, v in (("x", w.x), ("y", w.y), ("z", w.z)):
            if math.isnan(v) or math.isinf(v):
                return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                        f"航点 {i} 的 {name} 非法（NaN/Inf）")
        if math.hypot(w.x, w.y) > MAX_WAYPOINT_DIST_M:
            return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                    f"航点 {i} 距原点 {math.hypot(w.x, w.y):.0f} m，"
                    f"超过上限 {MAX_WAYPOINT_DIST_M:.0f} m，疑似坐标系或单位传错")
        if w.z > 0.0:
            # NED 下 z 向下为正，正值意味着"地面以下"
            return (FollowPath.Result.RESULT_REJECTED_BAD_PATH,
                    f"航点 {i} 的 z={w.z:.1f} > 0（NED 向下为正，等于地面以下）")
    return None


def execute(node, goal_handle):
    link: PX4Link = node.link
    log = node.get_logger()
    g = goal_handle.request
    t_start = time.time()
    settle = getattr(node, "mode_settle", 2.0)

    wps = [(float(w.x), float(w.y), float(w.z)) for w in g.waypoints_ned]
    idx = int(g.start_index)
    reached = 0
    dist_flown = 0.0
    max_xte = 0.0

    def result(code: int, msg: str):
        r = FollowPath.Result()
        r.result_code = code
        r.success = (code == FollowPath.Result.RESULT_OK)
        r.waypoints_total = len(wps)
        r.waypoints_reached = reached
        # 闭合关系：下次传 start_index = last_reached_index + 1 应能无缝接上。
        # 一个都没到达时给 start_index 本身，让调用方原样重试而不是从头再来。
        r.last_reached_index = (idx - 1) if reached else int(g.start_index)
        r.distance_flown_m = float(dist_flown)
        r.max_cross_track_error_m = float(max_xte)
        r.elapsed_sec = float(time.time() - t_start)
        r.message = msg
        return r

    rej = preflight_reject(link, g)
    if rej:
        code, msg = rej
        log.warn(f"FollowPath 前置校验未过：{msg}")
        goal_handle.abort()
        return result(code, msg)

    speed = float(g.speed_mps)
    accept = float(g.accept_radius_m)
    timeout = float(g.timeout_sec) if g.timeout_sec > 0 else 600.0
    # 三维总长，与 seg_len 同口径（progress 是按已飞距离占总航程算的，
    # 两边口径不一致会让纯垂直航段的进度算出 >1 或恒 0）
    total_len = sum(math.dist(wps[i], wps[i + 1]) for i in range(len(wps) - 1))

    log.info(f"FollowPath 开始：{len(wps)} 个航点（从 {idx} 起），"
             f"速度 {speed:.1f} m/s，到达半径 {accept:.1f} m，总航程 {total_len:.0f} m")

    # 起点取当前位置，这样第一段是"从我在的地方到第一个航点"，
    # 不会因为飞机不在航线起点而算出巨大的横向偏差
    cur = link.current_ned()
    seg_a = (cur[0], cur[1], wps[idx][2])
    seg_b = wps[idx]
    travelled_on_seg = 0.0

    def yaw_for(a, b) -> float | None:
        if g.yaw_mode == FollowPath.Goal.YAW_FIXED:
            return math.radians(float(g.yaw_fixed_deg))
        if g.yaw_mode == FollowPath.Goal.YAW_HOLD:
            return link.current_heading()
        dx, dy = b[0] - a[0], b[1] - a[1]
        if math.hypot(dx, dy) < MIN_SEGMENT_M:
            return link.current_heading()
        return math.atan2(dy, dx)      # NED：x 北 y 东，atan2(东, 北) 即航向

    yaw = yaw_for(seg_a, seg_b)
    link.reset_hb_stats()
    link.start_heartbeat(seg_a, yaw)

    preheat = getattr(node, "preheat", 15)
    deadline = time.time() + 5.0
    while link.heartbeat_count < preheat and time.time() < deadline:
        time.sleep(0.05)

    if not link.in_offboard:
        # 已解锁飞行中切 OFFBOARD 是有时机要求的：飞控若此刻仍认为 offboard 信号
        # 陈旧，切过去会立刻失效保护转 AUTO_RTL（实测踩过）。等飞控自己确认。
        sig_ok, sig_msg = link.wait_offboard_signal_ready()
        if not sig_ok:
            link.stop_heartbeat()
            goal_handle.abort()
            return result(FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE, sig_msg)
        res = link.set_mode_offboard()
        if not res.accepted:
            link.handover_to_loiter("FollowPath 切 OFFBOARD 失败", settle)
            goal_handle.abort()
            return result(FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"切 OFFBOARD 被拒：{res.describe()}")
        d2 = time.time() + settle
        while not link.in_offboard and time.time() < d2:
            time.sleep(0.05)
        if not link.in_offboard:
            link.handover_to_loiter("FollowPath 模式未切换", settle)
            goal_handle.abort()
            return result(FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"命令已接受但模式仍是 {link.nav_state_name}")

    fb_period = 1.0 / max(getattr(node, "feedback_hz", 5.0), 0.5)
    next_fb = time.time()
    last_t = time.time()
    last_pos = link.current_ned()

    while True:
        now = time.time()
        dt = now - last_t
        last_t = now
        elapsed = now - t_start

        if goal_handle.is_cancel_requested:
            link.handover_to_loiter("FollowPath 被取消", settle)
            goal_handle.canceled()
            return result(FollowPath.Result.RESULT_CANCELED,
                          f"已取消，到达 {reached}/{len(wps)} 个航点，悬停在当前位置")

        # 与 Takeoff/Orbit 同一套判据：飞控接管就别再假装我们还在控
        if link.failsafe_active and not link.in_offboard:
            reasons = ", ".join(link.failsafe_reasons()) or "原因未知"
            goal_handle.abort()
            # 带上时序自证用于定因：心跳间隔远小于 COM_OF_LOSS_T(默认 1.0s)
            # 却仍被判丢失，说明不是我们发布卡了，问题在飞控侧的新鲜度判定。
            trace = link.dump_timing_trace()
            return result(FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"飞控接管（模式 {link.nav_state_name}），原因: {reasons}；"
                          f"{link.timing_summary()}"
                          + (f"；时序 trace: {trace}" if trace else ""))
        if not link.armed:
            goal_handle.abort()
            return result(FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"飞行中被解除解锁，模式 {link.nav_state_name}")
        if link.offboard_signal_really_lost:
            link.handover_to_loiter("offboard 信号持续丢失", settle)
            goal_handle.abort()
            return result(FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"offboard 信号持续丢失 {link.offboard_signal_lost_for():.1f}s")
        if elapsed > timeout:
            link.handover_to_loiter("FollowPath 超时", settle)
            goal_handle.abort()
            return result(FollowPath.Result.RESULT_TIMEOUT,
                          f"{timeout:.0f}s 内只到达 {reached}/{len(wps)} 个航点")

        pos = link.current_ned()
        # distance_flown_m 刻意保持**二维**（地面航迹长度）：
        # 它的消费者是覆盖率与航程核算，那里关心的是走过多少地面，
        # 不是上下起伏累加了多少。与 seg_len 的三维口径不同是有意的。
        dist_flown += math.dist(pos[:2], last_pos[:2])
        last_pos = pos

        # 航段长度与到达判定都用**三维**距离，横向偏差仍是二维（那是它的定义）。
        #
        # 为什么必须三维：Revisit 的"原地降高"就是一条纯垂直航段
        # （XY 不变、只降 z）。二维口径下这条航段长度为 0、飞机到航点的
        # 二维距离也为 0，于是会被判"立即到达"——目标点一步跳到底，
        # 飞机以最大速率俯冲，而动作立刻报完成。
        # 对水平扫掠没有影响：那里 z 恒定，三维等于二维。
        seg_len = math.dist(seg_a, seg_b)
        xte = _cross_track_error(pos[:2], seg_a[:2], seg_b[:2])
        max_xte = max(max_xte, xte)

        # 到达判定用**飞机到航点的实际距离**，不是"目标点走到头了"。
        # 目标点是我们自己推的，它到达不代表飞机到达。
        dist_to_wp = math.dist(pos, seg_b)
        if dist_to_wp <= accept:
            reached += 1
            idx += 1
            if idx >= len(wps):
                link.handover_to_loiter("FollowPath 完成", settle)
                goal_handle.succeed()
                # 成功路径也带时序自证：只有"没被接管"不足以说明时序健康，
                # 得看飞控这一路有没有短暂判过丢失（有就是余量不够，只是没触发）。
                return result(FollowPath.Result.RESULT_OK,
                              f"到达全部 {len(wps)} 个航点，航程 {dist_flown:.0f} m，"
                              f"最大横向偏差 {max_xte:.2f} m；{link.timing_summary()}")
            seg_a = seg_b
            seg_b = wps[idx]
            travelled_on_seg = 0.0
            yaw = yaw_for(seg_a, seg_b)
            log.info(f"到达航点 {idx - 1}，转向下一段（剩 {len(wps) - idx} 个）")
            continue

        # 目标点沿当前航段前移。封顶在航段终点，避免冲过头。
        travelled_on_seg = min(travelled_on_seg + speed * dt, seg_len)
        if seg_len < MIN_SEGMENT_M:
            tgt = seg_b
        else:
            r = travelled_on_seg / seg_len
            tgt = (seg_a[0] + (seg_b[0] - seg_a[0]) * r,
                   seg_a[1] + (seg_b[1] - seg_a[1]) * r,
                   seg_a[2] + (seg_b[2] - seg_a[2]) * r)
        link.update_heartbeat_target(tgt, yaw)

        if now >= next_fb:
            fb = FollowPath.Feedback()
            fb.waypoints_total = len(wps)
            fb.current_index = idx
            fb.progress = float(min(dist_flown / total_len, 1.0)) if total_len > 0 else 0.0
            fb.cross_track_error_m = float(xte)
            fb.distance_to_next_m = float(dist_to_wp)
            fb.elapsed_sec = float(elapsed)
            goal_handle.publish_feedback(fb)
            next_fb = now + fb_period

        time.sleep(0.05)
