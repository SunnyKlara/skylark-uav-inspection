"""Revisit 的执行逻辑：降高复拍。

这个动作是整个项目「AI 反馈控制飞行决策」叙事的具体载体：
巡航高度检出可疑目标 -> 请求 Revisit -> 飞机降到更低高度悬停 ->
用更高 GSD 的图像复核。所以它的**延迟**本身就是论文数据，见下面的 §延迟。

运动同样全部通过 iface 的 FollowPath 执行（本包不发 setpoint）。
降高被表达成一条**纯垂直航段** —— 这就是 FollowPath 的到达判定与航段长度
必须改成三维的原因（二维口径下垂直航段长度为 0，会被判"立即到达"，
目标点一步跳到底，飞机俯冲）。

§延迟：两个字段的测量点（对应设计文档 §4，有一处刻意偏离）
------------------------------------------------------------
    t0  收到 goal   = 本函数第一行
    t1  开始动作    = **实测到飞机开始动**（速度超过 motion_speed_mps）
    t2  到位且稳定  = 高度进 ±阈值 且 水平速度 < 阈值，且**连续保持** hold 秒

设计文档原本把 t1 定义成"第一条改变目标位置的 setpoint 发出的时刻"。
这里改成实测运动，两个理由：
  1. 本节点**看不到** setpoint 流 —— 那是 iface 的内部行为，
     而"inspection_mode 不碰 setpoint"正是这套分层的前提。
     要观测它就得给 iface 加一条专门的埋点话题，为一个字段引入跨包耦合不值得。
  2. 契约的字段名就是 latency_goal_to_motion_ms（motion = 运动）。
     实测运动比"发出了一条 setpoint"更贴字段的字面含义，
     也更贴论文要回答的问题（AI 决策到飞机真的动，中间有多久）。
差别是可界定的：实测运动会比"setpoint 发出"晚一个控制器响应时间。
⚠ 若飞机在收到 goal 时**本来就在动**（例如扫掠途中插入复拍），
  这个数就失去意义，此时回报 0 并在 message 里写明，不假装测到了。

t2 刻意要求"连续保持"而不是单帧命中：单帧到位在超调过程中会误触发，
测出来的延迟会系统性偏小 —— 而这个数字是要写进论文的。
"""

from __future__ import annotations

import math
import time

from skylark_flight_internal_msgs.action import FollowPath
from skylark_flight_msgs.action import Revisit

from . import geometry as geo
from . import revisit_policy as rp
from .sweep import _await, _point, _ref_from_state

# 水平偏移小于这个值就当"就在当前位置"，不单独走一次转场
NO_TRANSIT_EPS_M = 1.0

_FP_TO_REVISIT = {
    FollowPath.Result.RESULT_OK: Revisit.Result.RESULT_OK,
    FollowPath.Result.RESULT_REJECTED_NOT_READY:
        Revisit.Result.RESULT_REJECTED_NOT_READY,
    # 航点是我们自己算的，FollowPath 还报 BAD_PATH 说明两边判据不一致 ——
    # 那是实现 bug，但对调用方而言结果就是"这个请求不安全"
    FollowPath.Result.RESULT_REJECTED_BAD_PATH: Revisit.Result.RESULT_REJECTED_UNSAFE,
    FollowPath.Result.RESULT_TIMEOUT: Revisit.Result.RESULT_TIMEOUT,
    FollowPath.Result.RESULT_ABORTED_BY_FAILSAFE:
        Revisit.Result.RESULT_ABORTED_BY_FAILSAFE,
    FollowPath.Result.RESULT_CANCELED: Revisit.Result.RESULT_CANCELED,
}


def _speed3(state) -> float:
    v = state.velocity_ned
    return math.sqrt(float(v.x) ** 2 + float(v.y) ** 2 + float(v.z) ** 2)


def _speed_h(state) -> float:
    v = state.velocity_ned
    return math.hypot(float(v.x), float(v.y))


class _Tracker:
    """在整个动作期间盯着两个延迟测量点。

    单独成类是因为它要跨多次 FollowPath 调用持续采样 ——
    写成散落在各阶段的局部变量必然漏掉某一段。
    """

    def __init__(self, node, t0: float, target_agl_m: float) -> None:
        self.node = node
        self.t0 = t0
        self.target_agl = target_agl_m
        self.motion_ms: int | None = None
        self.onstation_ms: int | None = None
        self._hold_since: float | None = None
        # 收到 goal 时本来就在动？那 t1 没有意义，如实记下来
        st = node.latest_state()
        self.moving_at_t0 = bool(st is not None and _speed3(st) > node.motion_speed_mps)
        if self.moving_at_t0:
            self.motion_ms = 0

    def sample(self, now: float) -> None:
        st = self.node.latest_state()
        if st is None:
            return
        if self.motion_ms is None and _speed3(st) > self.node.motion_speed_mps:
            self.motion_ms = int((now - self.t0) * 1000)
        if self.onstation_ms is None:
            ok = rp.onstation(
                agl_m=float(st.altitude_agl_m), target_agl_m=self.target_agl,
                speed_mps=_speed_h(st),
                alt_tol_m=self.node.onstation_alt_tol_m,
                max_speed_mps=self.node.onstation_speed_mps)
            if ok:
                if self._hold_since is None:
                    self._hold_since = now
                elif now - self._hold_since >= self.node.onstation_hold_sec:
                    # 记的是**开始保持**的时刻，不是保持够了的时刻：
                    # "到位"发生在前者，后者只是我们确认它的时刻。
                    self.onstation_ms = int((self._hold_since - self.t0) * 1000)
            else:
                self._hold_since = None      # 断了就重新计时


def _run_follow_path(node, goal_handle, wps, speed: float, timeout: float,
                     on_tick) -> tuple[int, str, bool]:
    """跑一段 FollowPath，期间每轮调用 on_tick(now)。

    返回 (FollowPath 结果码, 消息, 是否因取消而结束)。
    on_tick 负责采样延迟、发 Feedback、看守卫 —— 阻塞等结果的同时必须继续采样，
    否则延迟测量会在每次调用之间出现空洞。
    """
    fp_goal = FollowPath.Goal()
    fp_goal.waypoints_ned = [_point(w) for w in wps]
    fp_goal.speed_mps = float(speed)
    fp_goal.accept_radius_m = float(node.revisit_accept_radius_m)
    fp_goal.yaw_mode = FollowPath.Goal.YAW_HOLD    # 复拍不改机头朝向
    fp_goal.start_index = 0
    fp_goal.timeout_sec = float(timeout)

    send_fut = node.fp_client.send_goal_async(fp_goal)
    if not _await(send_fut, 10.0):
        return (FollowPath.Result.RESULT_REJECTED_NOT_READY,
                "FollowPath 未在 10s 内受理 goal", False)
    handle = send_fut.result()
    if not handle.accepted:
        return (FollowPath.Result.RESULT_REJECTED_NOT_READY,
                "FollowPath 拒绝了 goal（iface 可能正忙于别的动作）", False)

    res_fut = handle.get_result_async()
    cancel_sent = False
    while not res_fut.done():
        now = time.monotonic()
        on_tick(now)
        if not cancel_sent and goal_handle.is_cancel_requested:
            handle.cancel_goal_async()
            cancel_sent = True
        time.sleep(0.05)
    r = res_fut.result().result
    return int(r.result_code), str(r.message), cancel_sent


def execute(node, goal_handle):
    t0 = time.monotonic()          # ← 契约的 t0：execute 入口第一行
    log = node.get_logger()
    g = goal_handle.request

    commanded_agl = 0.0     # 夹紧后**要求**的高度（给到位判据当基准）
    achieved_agl = 0.0      # **实测**到达的高度（契约的 actual_agl_m）
    actual_hover = 0.0
    returned = False
    tracker: _Tracker | None = None
    notes: list[str] = []

    def result(code: int, msg: str):
        r = Revisit.Result()
        r.result_code = code
        r.success = (code == Revisit.Result.RESULT_OK)
        # 契约写的是「实际到达的复拍高度」，所以这里必须是**实测值**，
        # 不能是夹紧后的指令值。
        #
        # 实测教训（99_notes/rv1 场景 C）：请求 6 m，飞机停在 6.74 m，
        # 而这里原本回报 6.00 —— 差 12% 的 GSD 被静默吞掉了，
        # 而 GSD 正是复拍这个动作存在的全部理由。
        # 一个都没飞到（前置拒绝）时回 0，与 success=False 一致。
        agl = achieved_agl
        if agl == 0.0 and commanded_agl > 0.0:
            # 中途失败/被取消：没走到悬停那一步，但飞机确实降了一段。
            # 回报**此刻**的实测高度而不是 0 —— 调用方需要知道飞机现在在哪个高度，
            # 尤其是取消之后飞机就停在那里。
            st_now = node.latest_state()
            if st_now is not None:
                agl = float(st_now.altitude_agl_m)
        r.actual_agl_m = float(agl)
        r.actual_hover_sec = float(actual_hover)
        # 拍摄触发接口还不存在（相机在 gz 里是连续出流，"连拍"需要先定义触发语义，
        # 而检测侧由 Window-A 负责）。所以这里如实回 0，并在 message 里写明，
        # 不拿"悬停期间相机反正在出流"充当已拍摄。
        r.images_captured = 0
        r.returned_to_origin = bool(returned)
        if tracker is not None:
            r.latency_goal_to_motion_ms = int(tracker.motion_ms or 0)
            r.latency_goal_to_onstation_ms = int(tracker.onstation_ms or 0)
        r.elapsed_sec = float(time.monotonic() - t0)
        r.message = msg + ("；" + "；".join(notes) if notes else "")
        return r

    def feedback(phase: int) -> None:
        st = node.latest_state()
        fb = Revisit.Feedback()
        fb.phase = phase
        fb.current_agl_m = float(st.altitude_agl_m) if st else 0.0
        fb.images_captured = 0
        fb.elapsed_sec = float(time.monotonic() - t0)
        goal_handle.publish_feedback(fb)

    # ---------------- 前置守卫 ----------------
    state = node.latest_state()
    if state is None:
        goal_handle.abort()
        return result(Revisit.Result.RESULT_REJECTED_NOT_READY,
                      f"收不到 {node.iface_ns}/vehicle_state，"
                      f"skylark_autopilot_iface 在跑吗？")
    if not state.position_valid:
        goal_handle.abort()
        return result(Revisit.Result.RESULT_REJECTED_NOT_READY, "位置估计无效")
    health = node.latest_health()
    if health is None or not health.ready_for_offboard:
        why = "收不到 flight_health" if health is None else \
              (f"ready_for_offboard=false（模式 {health.flight_mode}，"
               f"failsafe={health.failsafe_active}）")
        goal_handle.abort()
        return result(Revisit.Result.RESULT_REJECTED_NOT_READY,
                      f"飞控未就绪：{why}。复拍是飞行中动作，需先起飞")
    if float(health.battery_remaining) < node.battery_abort_threshold:
        goal_handle.abort()
        return result(Revisit.Result.RESULT_ABORTED_LOW_BATTERY,
                      f"剩余电量 {health.battery_remaining * 100:.0f}% 低于阈值 "
                      f"{node.battery_abort_threshold * 100:.0f}%，不开始复拍")

    origin = (float(state.position_ned.x), float(state.position_ned.y),
              float(state.position_ned.z))
    origin_agl = float(state.altitude_agl_m)

    # ---------------- 目标点 ----------------
    if g.use_current_position:
        tx, ty = origin[0], origin[1]
    else:
        if abs(float(state.latitude_deg)) < 1e-6 and \
                abs(float(state.longitude_deg)) < 1e-6:
            goal_handle.abort()
            return result(Revisit.Result.RESULT_REJECTED_UNSAFE,
                          "飞控未提供全局位置（lat/lon 均为 0），"
                          "无法把目标经纬度换算成局部坐标")
        tx, ty = geo.latlon_to_ned(float(g.target_latitude_deg),
                                   float(g.target_longitude_deg),
                                   *_ref_from_state(state))
    offset = math.hypot(tx - origin[0], ty - origin[1])

    # ---------------- 频率限制 ----------------
    # 放在夹紧之前：被限流的请求根本不该进入后续流程，
    # 也不该留下"上次复拍点"的记录（否则一串误检会互相延长限流窗口）。
    limited, why = rp.rate_limited(
        node.last_revisit, t0, tx, ty,
        window_sec=node.revisit_rate_limit_sec,
        radius_m=node.revisit_rate_limit_radius_m)
    if limited:
        goal_handle.abort()
        return result(Revisit.Result.RESULT_REJECTED_RATE_LIMITED, why)

    # ---------------- 夹紧 ----------------
    try:
        c = rp.clamp_revisit(
            requested_agl_m=float(g.descend_to_agl_m),
            requested_hover_sec=float(g.hover_sec),
            requested_burst=int(g.capture_burst),
            offset_m=offset,
            min_agl_m=node.revisit_min_agl_m,
            max_hover_sec=node.revisit_max_hover_sec,
            max_burst=node.revisit_max_burst,
            max_offset_m=node.revisit_max_offset_m)
    except rp.UnsafeRequest as exc:
        goal_handle.abort()
        return result(Revisit.Result.RESULT_REJECTED_UNSAFE, str(exc))
    commanded_agl = c.agl_m
    notes.extend(c.notes)
    notes.append(f"AGL 来源 agl_source={state.agl_source}"
                 f"（1=起飞点推算，2=测距仪；起飞点推算在地形起伏时不可靠）")
    notes.append("images_captured 恒为 0：拍摄触发接口尚未定义"
                 "（相机在仿真里是连续出流，检测侧由 Window-A 负责）")

    node.mark_revisit(tx, ty, t0)
    tracker = _Tracker(node, t0, commanded_agl)
    if tracker.moving_at_t0:
        notes.append("收到 goal 时飞机本来就在移动，latency_goal_to_motion_ms "
                     "无意义，回报 0")

    timeout = float(g.timeout_sec) if g.timeout_sec > 0 else 120.0
    log.info(f"Revisit 开始：目标偏移 {offset:.1f} m，"
             f"降到 {commanded_agl:.1f} m AGL（请求 {g.descend_to_agl_m:.1f}）、"
             f"悬停 {c.hover_sec:.1f}s、连拍 {c.capture_burst} 张"
             f"（触发未实现）、原因「{g.trigger_reason}」严重度 {g.trigger_severity}")
    feedback(Revisit.Feedback.PHASE_ACCEPTED)

    phase = [Revisit.Feedback.PHASE_TRANSIT]
    next_fb = [time.monotonic()]
    fb_period = 1.0 / max(node.feedback_hz, 0.5)

    def tick(now: float) -> None:
        tracker.sample(now)
        if now >= next_fb[0]:
            feedback(phase[0])
            next_fb[0] = now + fb_period

    def bail(fp_code: int, fp_msg: str, canceled: bool, stage: str):
        code = _FP_TO_REVISIT.get(fp_code, Revisit.Result.RESULT_ABORTED_BY_FAILSAFE)
        if canceled or code == Revisit.Result.RESULT_CANCELED:
            code = Revisit.Result.RESULT_CANCELED
            goal_handle.canceled()
        else:
            goal_handle.abort()
        return result(code, f"{stage}阶段未完成（FollowPath: {fp_msg}）")

    def remaining() -> float:
        return max(timeout - (time.monotonic() - t0), 1.0)

    # ---------------- 转场（仅在真有水平偏移时）----------------
    if offset > NO_TRANSIT_EPS_M:
        phase[0] = Revisit.Feedback.PHASE_TRANSIT
        wps = [(origin[0], origin[1], origin[2]), (tx, ty, origin[2])]
        code, msg, canceled = _run_follow_path(
            node, goal_handle, wps, node.revisit_transit_speed_mps,
            remaining(), tick)
        if code != FollowPath.Result.RESULT_OK:
            return bail(code, msg, canceled, "转场")

    # ---------------- 降高（纯垂直航段）----------------
    phase[0] = Revisit.Feedback.PHASE_DESCENDING
    st = node.latest_state() or state
    cur_z = float(st.position_ned.z)
    # 目标 z：按 AGL 差值换算，而不是直接用 -commanded_agl。
    # position_ned.z 的零点是 EKF 起飞点，而 AGL 的零点见 agl_source ——
    # 两者在平地上一致，起伏地形下不一致。用差值换算，两个零点就都不必假设。
    target_z = cur_z + (float(st.altitude_agl_m) - commanded_agl)
    wps = [(tx, ty, cur_z), (tx, ty, target_z)]
    code, msg, canceled = _run_follow_path(
        node, goal_handle, wps, node.revisit_descent_speed_mps, remaining(), tick)
    if code != FollowPath.Result.RESULT_OK:
        return bail(code, msg, canceled, "降高")

    # ---------------- 悬停 ----------------
    phase[0] = Revisit.Feedback.PHASE_HOVERING
    # 实测到达高度在这里定格：悬停开始的那一刻就是"复拍时所处的高度"，
    # 也就是决定 GSD 的那个值。后面爬回原高度会把它冲掉，所以必须在这里取。
    st = node.latest_state()
    achieved_agl = float(st.altitude_agl_m) if st else commanded_agl
    err = achieved_agl - commanded_agl
    if abs(err) > node.onstation_alt_tol_m:
        notes.append(f"实测高度 {achieved_agl:.2f} m 偏离要求 {commanded_agl:.2f} m "
                     f"达 {err:+.2f} m（超出容差 {node.onstation_alt_tol_m:.2f} m），"
                     f"GSD 会随之偏离")
    # 刻意**不**发 PHASE_CAPTURING：拍摄没实现，报一个没做的阶段是误导。
    t_hover = time.monotonic()
    while time.monotonic() - t_hover < c.hover_sec:
        now = time.monotonic()
        tick(now)
        if goal_handle.is_cancel_requested:
            actual_hover = now - t_hover
            goal_handle.canceled()
            return result(Revisit.Result.RESULT_CANCELED,
                          f"悬停 {actual_hover:.1f}s 后被取消，停在复拍高度")
        h = node.latest_health()
        if h is not None and h.failsafe_active:
            actual_hover = now - t_hover
            goal_handle.abort()
            return result(Revisit.Result.RESULT_ABORTED_BY_FAILSAFE,
                          f"悬停期间飞控接管：{', '.join(h.failsafe_reasons)}")
        if now - t0 > timeout:
            actual_hover = now - t_hover
            goal_handle.abort()
            return result(Revisit.Result.RESULT_TIMEOUT,
                          f"{timeout:.0f}s 超时（悬停阶段）")
        time.sleep(0.05)
    actual_hover = time.monotonic() - t_hover

    # ---------------- 返回 ----------------
    if g.return_to_origin:
        phase[0] = Revisit.Feedback.PHASE_RETURNING
        st = node.latest_state() or state
        z_now = float(st.position_ned.z)
        # 先原地爬回原高度，再平移回原位置。顺序不能反：
        # 低空横穿光伏阵列是撞障风险最高的走法。
        wps = [(tx, ty, z_now), (tx, ty, origin[2])]
        code, msg, canceled = _run_follow_path(
            node, goal_handle, wps, node.revisit_descent_speed_mps,
            remaining(), tick)
        if code != FollowPath.Result.RESULT_OK:
            return bail(code, msg, canceled, "爬回原高度")
        if offset > NO_TRANSIT_EPS_M:
            wps = [(tx, ty, origin[2]), (origin[0], origin[1], origin[2])]
            code, msg, canceled = _run_follow_path(
                node, goal_handle, wps, node.revisit_transit_speed_mps,
                remaining(), tick)
            if code != FollowPath.Result.RESULT_OK:
                return bail(code, msg, canceled, "返回原位")
        returned = True

    m_ms = tracker.motion_ms
    o_ms = tracker.onstation_ms
    goal_handle.succeed()
    return result(Revisit.Result.RESULT_OK,
                  f"复拍完成：实测 {achieved_agl:.2f} m AGL"
                  f"（要求 {commanded_agl:.1f} m，起始 {origin_agl:.1f} m）、"
                  f"悬停 {actual_hover:.1f}s、"
                  f"{'已回原位' if returned else '留在复拍点'}；"
                  f"延迟 goal->动作 {m_ms if m_ms is not None else '未测到'} ms、"
                  f"goal->到位稳定 {o_ms if o_ms is not None else '未测到'} ms")
