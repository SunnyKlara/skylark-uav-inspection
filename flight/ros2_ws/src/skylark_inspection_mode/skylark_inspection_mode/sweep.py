"""InspectSweep 的执行逻辑：算航线 -> 交给 iface 的 FollowPath 飞 -> 记账。

为什么不自己发 setpoint
----------------------
offboard 的 setpoint 流必须只有一个发布者。两个进程都能动飞机时，
它们会互相打断，而且**日志里看不出是谁打断了谁**（两边都在正常发命令）。
所以本模块只做三件事：把矩形区域算成航点、调 FollowPath、把进度翻译成契约字段。
运动全部由 skylark_autopilot_iface 执行。

为什么整条航线一次交给 FollowPath，而不是逐行调用
------------------------------------------------
FollowPath 每次完成都会移交 AUTO_LOITER，下次调用再切回 OFFBOARD。
逐行调用 = 每行两次模式切换，5 行就是 10 次，既拖时间又平白多出失败面。
行进度改从 FollowPath 的 feedback.current_index 换算（一行两个端点），
这样一次调用就能拿到逐行进度。

将来插入 Revisit 也用同一套：取消 FollowPath -> 执行 Revisit ->
用 start_index 从断点重启。这正是 FollowPath 留 start_index 的原因。
"""

from __future__ import annotations

import time

from geometry_msgs.msg import Point
from skylark_flight_internal_msgs.action import FollowPath
from skylark_flight_msgs.action import InspectSweep

from . import geometry as geo

# FollowPath 的结果码 -> InspectSweep 的结果码。
#
# 刻意写成显式表而不是数值相加：两套结果码的编号**不一样**
# （FollowPath 的 TIMEOUT=3、InspectSweep 的 TIMEOUT=4），
# 靠记忆对应必然出错，而错了的表现是调用方拿到一个语义完全不同的码。
_FP_TO_SWEEP = {
    FollowPath.Result.RESULT_OK: InspectSweep.Result.RESULT_OK,
    FollowPath.Result.RESULT_REJECTED_NOT_READY:
        InspectSweep.Result.RESULT_REJECTED_NOT_READY,
    # 我们自己已经做过几何校验，FollowPath 再报 BAD_PATH 说明两边判据不一致，
    # 那是实现 bug 而不是调用方的错 —— 仍按几何拒绝上报，但消息里要点明。
    FollowPath.Result.RESULT_REJECTED_BAD_PATH:
        InspectSweep.Result.RESULT_REJECTED_BAD_GEOMETRY,
    FollowPath.Result.RESULT_TIMEOUT: InspectSweep.Result.RESULT_TIMEOUT,
    FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE:
        InspectSweep.Result.RESULT_ABORTED_BY_FAILSAFE,
    FollowPath.Result.RESULT_CANCELED: InspectSweep.Result.RESULT_CANCELED,
}


def _ref_from_state(state) -> tuple[float, float]:
    """从一帧 VehicleState 反解 EKF 的经纬度参考点。

    VehicleState 同时给了 position_ned 和 latitude/longitude，
    两者之差就是参考点 —— 于是 inspection_mode 不必订阅 px4_msgs
    就能做经纬度 <-> NED 换算。这正是契约让 VehicleState 同时带两套坐标的用处。
    """
    return geo.ned_to_latlon(-float(state.position_ned.x),
                             -float(state.position_ned.y),
                             float(state.latitude_deg),
                             float(state.longitude_deg))


def execute(node, goal_handle):
    """InspectSweep 的 execute 回调。node 需提供：
    state / health / fp_client / hfov_deg / accept_radius_m /
    battery_abort_threshold / feedback_hz。
    """
    log = node.get_logger()
    g = goal_handle.request
    t_start = time.time()

    rows_total = 0
    rows_done_global = 0
    plan = None

    def result(code: int, msg: str, dist: float = 0.0):
        r = InspectSweep.Result()
        r.result_code = code
        r.success = (code == InspectSweep.Result.RESULT_OK)
        r.rows_total = int(rows_total)
        r.rows_completed = int(rows_done_global - int(g.resume_from_row)) \
            if rows_done_global else 0
        # 闭合关系：下次传 resume_from_row = last_completed_row + 1 应能接上。
        # 一行都没完成时给 resume_from_row - 1，这样 +1 回到原点、原样重试，
        # 而不是从头再来。resume_from_row=0 时给 0 会让调用方以为第 0 行已完成，
        # 所以这里用 -1 表达"什么都没完成"，并在 message 里写明。
        r.last_completed_row = int(rows_done_global - 1) if rows_done_global \
            else max(int(g.resume_from_row) - 1, 0)
        if plan is not None:
            r.area_covered_m2 = float(geo.area_covered_m2(
                r.rows_completed, float(g.row_spacing_m),
                plan.row_length_m, plan.area_m2))
        r.distance_flown_m = float(dist)
        r.revisits_triggered = 0      # auto_revisit 还没接，见 message
        r.elapsed_sec = float(time.time() - t_start)
        r.message = msg
        return r

    # ---------------- 前置：得有一帧新鲜的 VehicleState ----------------
    state = node.latest_state()
    if state is None:
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_NOT_READY,
                      f"收不到 {node.iface_ns}/vehicle_state，"
                      f"skylark_autopilot_iface 在跑吗？")
    if not state.position_valid:
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_NOT_READY,
                      "位置估计无效，经纬度无法解释为局部坐标")
    # 经纬度必须真的有全局参考。EKF 没有全局参考时 lat/lon 会是 0 ——
    # 那时把 0,0 当参考点会算出一条飞到几内亚湾的航线，必须拒而不是照算。
    if abs(float(state.latitude_deg)) < 1e-6 and abs(float(state.longitude_deg)) < 1e-6:
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_BAD_GEOMETRY,
                      "飞控未提供全局位置（lat/lon 均为 0），无法把经纬度区域"
                      "换算成局部航线")

    health = node.latest_health()
    if health is None or not health.ready_for_offboard:
        why = "收不到 flight_health" if health is None else \
              (f"ready_for_offboard=false（模式 {health.flight_mode}，"
               f"failsafe={health.failsafe_active}）")
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_NOT_READY,
                      f"飞控未就绪：{why}。扫掠是飞行中动作，需先 Takeoff")
    # 低电量是**状态机主动**中止，不是飞控失效保护（设计文档 §6）。
    # ⚠ SITL 电池约 1.5 分钟就掉进告警区，所以测试脚本必须设 COM_LOW_BAT_ACT=0；
    #   但这条判据在真机上是真实需要的，不能因为 SITL 麻烦就删掉。
    if float(health.battery_remaining) < node.battery_abort_threshold:
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_ABORTED_LOW_BATTERY,
                      f"剩余电量 {health.battery_remaining * 100:.0f}% 低于阈值 "
                      f"{node.battery_abort_threshold * 100:.0f}%，不开始扫掠")

    # ---------------- 算航线 ----------------
    hfov = float(g.camera_hfov_deg) if g.camera_hfov_deg > 0.0 else node.hfov_deg
    hfov_src = "goal 指定" if g.camera_hfov_deg > 0.0 else \
               f"节点参数 camera_hfov_deg={node.hfov_deg:.2f}"
    ref = _ref_from_state(state)
    try:
        plan = geo.plan_sweep(
            (float(g.corner_a_latitude_deg), float(g.corner_a_longitude_deg)),
            (float(g.corner_b_latitude_deg), float(g.corner_b_longitude_deg)),
            ref,
            heading_deg=float(g.heading_deg),
            altitude_agl_m=float(g.altitude_agl_m),
            row_spacing_m=float(g.row_spacing_m),
            min_overlap=float(g.min_overlap),
            hfov_deg=hfov,
            resume_from_row=int(g.resume_from_row),
        )
    except geo.CoverageError as exc:
        # 覆盖率不达标要用**专门的**结果码，不能混进 BAD_GEOMETRY ——
        # 前者调用方改行距就能过，后者是区域本身有问题，处置完全不同。
        suggest = geo.max_row_spacing_m(float(g.altitude_agl_m),
                                        float(g.min_overlap), hfov)
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_COVERAGE,
                      f"{exc}（视场来自{hfov_src}）。"
                      f"把 row_spacing_m 降到 {suggest:.2f} m 及以下即可满足")
    except geo.GeometryError as exc:
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_BAD_GEOMETRY, str(exc))

    rows_total = plan.rows_total
    rows_done_global = 0
    log.info(f"扫掠计划：{rows_total} 行（从第 {g.resume_from_row} 行起），"
             f"行长 {plan.row_length_m:.0f} m、行距 {g.row_spacing_m:.1f} m、"
             f"高度 {g.altitude_agl_m:.0f} m，"
             f"幅宽 {plan.swath_m:.2f} m、重叠率 {plan.overlap * 100:.1f}%，"
             f"航程 {plan.path_length_m:.0f} m，{len(plan.waypoints_ned)} 个航点")

    # ---------------- 交给 FollowPath ----------------
    if not node.fp_client.wait_for_server(timeout_sec=5.0):
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_NOT_READY,
                      f"{node.iface_ns}/follow_path 动作服务器不在线")

    fp_goal = FollowPath.Goal()
    fp_goal.waypoints_ned = [_point(w) for w in plan.waypoints_ned]
    fp_goal.speed_mps = float(g.speed_mps)
    fp_goal.accept_radius_m = float(node.accept_radius_m)
    fp_goal.yaw_mode = FollowPath.Goal.YAW_ALONG_PATH
    fp_goal.start_index = 0        # 航线已按 resume_from_row 切过片，见模块 docstring
    timeout = float(g.timeout_sec) if g.timeout_sec > 0 else 1800.0
    fp_goal.timeout_sec = timeout

    # 进度由 FollowPath 的 feedback 驱动。用可变容器而不是 nonlocal 赋值，
    # 因为回调在别的线程里跑。
    live = {"index": 0, "xte": 0.0, "reached": 0, "dist": 0.0}

    def on_fp_feedback(msg) -> None:
        fb = msg.feedback
        live["index"] = int(fb.current_index)
        live["xte"] = float(fb.cross_track_error_m)

    send_fut = node.fp_client.send_goal_async(fp_goal, feedback_callback=on_fp_feedback)
    if not _await(send_fut, 10.0):
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_NOT_READY,
                      "FollowPath 未在 10s 内受理 goal")
    fp_handle = send_fut.result()
    if not fp_handle.accepted:
        goal_handle.abort()
        return result(InspectSweep.Result.RESULT_REJECTED_NOT_READY,
                      "FollowPath 拒绝了 goal（iface 可能正忙于别的动作）")

    res_fut = fp_handle.get_result_async()
    fb_period = 1.0 / max(node.feedback_hz, 0.5)
    next_fb = time.time()
    cancel_sent = False
    abort_reason: tuple[int, str] | None = None

    while not res_fut.done():
        now = time.time()

        if not cancel_sent:
            if goal_handle.is_cancel_requested:
                log.info("收到取消，转发给 FollowPath")
                fp_handle.cancel_goal_async()
                cancel_sent = True
            elif now - t_start > timeout:
                log.warn(f"扫掠超时 {timeout:.0f}s，取消 FollowPath")
                fp_handle.cancel_goal_async()
                cancel_sent = True
                abort_reason = (InspectSweep.Result.RESULT_TIMEOUT,
                                f"{timeout:.0f}s 内未扫完")
            else:
                h = node.latest_health()
                if h is not None and \
                        float(h.battery_remaining) < node.battery_abort_threshold:
                    log.warn("剩余电量低于阈值，主动中止扫掠")
                    fp_handle.cancel_goal_async()
                    cancel_sent = True
                    abort_reason = (
                        InspectSweep.Result.RESULT_ABORTED_LOW_BATTERY,
                        f"剩余电量 {h.battery_remaining * 100:.0f}% 低于阈值，"
                        f"主动中止以保留返航余量")

        if now >= next_fb:
            local_row = live["index"] // geo.WAYPOINTS_PER_ROW
            fb = InspectSweep.Feedback()
            fb.rows_total = rows_total
            fb.current_row = geo.global_row(int(g.resume_from_row), local_row)
            span = max(rows_total - int(g.resume_from_row), 1)
            fb.progress = float(min(local_row / span, 1.0))
            fb.cross_track_error_m = float(live["xte"])
            h = node.latest_health()
            fb.battery_remaining = float(h.battery_remaining) if h else 0.0
            fb.detections_so_far = 0        # DetectionArray 未接，见 Result.message
            fb.revisit_in_progress = False
            fb.elapsed_sec = float(now - t_start)
            goal_handle.publish_feedback(fb)
            next_fb = now + fb_period

        time.sleep(0.05)

    fp_res = res_fut.result().result
    live["reached"] = int(fp_res.waypoints_reached)
    live["dist"] = float(fp_res.distance_flown_m)
    rows_done_global = geo.global_row(int(g.resume_from_row),
                                      geo.rows_done(live["reached"]))

    # 主动中止（超时 / 低电量）优先于 FollowPath 自己报的 CANCELED ——
    # 取消是我们发的，真实原因是我们知道的那个。
    if abort_reason is not None:
        code, why = abort_reason
        goal_handle.abort()
        return result(code, f"{why}。已完成 {rows_done_global - int(g.resume_from_row)}"
                            f"/{rows_total - int(g.resume_from_row)} 行；"
                            f"FollowPath: {fp_res.message}", live["dist"])

    code = _FP_TO_SWEEP.get(int(fp_res.result_code),
                            InspectSweep.Result.RESULT_ABORTED_BY_FAILSAFE)
    note = (f"覆盖面积为估算值（完成行数 x 行距 x 行长），"
            f"真实覆盖受航线跟踪误差影响，见 max_cross_track_error_m="
            f"{fp_res.max_cross_track_error_m:.2f} m。"
            f"auto_revisit_on_detection 尚未接入（DetectionArray 由 Window-A 提供），"
            f"revisits_triggered 恒为 0")

    if code == InspectSweep.Result.RESULT_OK:
        goal_handle.succeed()
        return result(code,
                      f"扫掠完成：{rows_total - int(g.resume_from_row)} 行、"
                      f"航程 {live['dist']:.0f} m、"
                      f"重叠率 {plan.overlap * 100:.1f}%（视场来自{hfov_src}）。{note}",
                      live["dist"])

    if code == InspectSweep.Result.RESULT_CANCELED:
        goal_handle.canceled()
    else:
        goal_handle.abort()
    return result(code, f"FollowPath 未完成（{fp_res.message}）。{note}", live["dist"])


def _await(fut, timeout_sec: float) -> bool:
    """等一个 future，但**不占用 executor**。

    不能用 rclpy.spin_until_future_complete：我们此刻正跑在
    MultiThreadedExecutor 的一个回调里，再去 spin 同一个 executor 会死锁。
    轮询 + sleep 让别的线程去处理这个 future 才是安全的做法。
    """
    deadline = time.time() + timeout_sec
    while not fut.done() and time.time() < deadline:
        time.sleep(0.02)
    return fut.done()


def _point(w: tuple[float, float, float]) -> Point:
    p = Point()
    p.x, p.y, p.z = float(w[0]), float(w[1]), float(w[2])
    return p
