"""飞控接口节点：发布 FlightHealth，提供 Takeoff action。

为什么是**一个**节点而不是拆开
------------------------------
offboard 的 setpoint 流必须只有一个发布者。拆成「健康发布节点 + 动作节点」后，
两个节点都持有 PX4Link 就会各发一路 setpoint 互相打断，
而这种故障在日志里看不出来（两路都"正常"发着）。所以合成一个。

执行模型
--------
必须用 MultiThreadedExecutor + ReentrantCallbackGroup。
action 的 execute 回调是阻塞式状态机，单线程 executor 会把 10 Hz 心跳定时器饿死，
setpoint 断流约 1 秒后 PX4 就 AUTO_RTL 降落 —— 一个只在真飞起来时才暴露的坑。

设计依据见 flight/docs/OFFBOARD_CONSTRAINTS.md。
"""

from __future__ import annotations

import math
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from skylark_flight_msgs.action import Takeoff
from skylark_flight_msgs.msg import FlightHealth

from .px4_link import (
    NAV_AUTO_LAND,
    NAV_AUTO_LOITER,
    NAV_AUTO_MISSION,
    NAV_AUTO_RTL,
    NAV_MANUAL,
    NAV_OFFBOARD,
    NAV_POSCTL,
    PX4Link,
)

# PX4 的 nav_state 映射到契约里那套精简枚举（FlightHealth.msg）
_NAV_TO_CONTRACT = {
    NAV_MANUAL: FlightHealth.NAV_STATE_MANUAL,
    NAV_POSCTL: FlightHealth.NAV_STATE_POSITION,
    NAV_AUTO_MISSION: FlightHealth.NAV_STATE_MISSION,
    NAV_OFFBOARD: FlightHealth.NAV_STATE_OFFBOARD,
    NAV_AUTO_RTL: FlightHealth.NAV_STATE_RTL,
    NAV_AUTO_LAND: FlightHealth.NAV_STATE_LAND,
}


class AutopilotIface(Node):
    def __init__(self) -> None:
        super().__init__("skylark_autopilot_iface")

        self.declare_parameter("heartbeat_hz", 10.0)
        self.declare_parameter("health_hz", 2.0)
        self.declare_parameter("feedback_hz", 5.0)
        self.declare_parameter("offboard_loss_grace_sec", 3.0)
        self.declare_parameter("altitude_tolerance_m", 0.4)
        self.declare_parameter("mode_switch_settle_sec", 2.0)
        # 官方示例发满 10 拍（10 Hz 下 1 秒）才切模式。切模式前必须已有 setpoint 流，
        # 否则会被拒。这里留同样的余量。
        self.declare_parameter("preheat_setpoints", 15)

        p = self.get_parameter
        self.heartbeat_hz = float(p("heartbeat_hz").value)
        self.health_hz = float(p("health_hz").value)
        self.feedback_hz = float(p("feedback_hz").value)
        self.alt_tol = float(p("altitude_tolerance_m").value)
        self.mode_settle = float(p("mode_switch_settle_sec").value)
        self.preheat = int(p("preheat_setpoints").value)

        self.cbg = ReentrantCallbackGroup()
        self.link = PX4Link(
            self,
            heartbeat_hz=self.heartbeat_hz,
            offboard_loss_grace_sec=float(p("offboard_loss_grace_sec").value),
        )

        self.pub_health = self.create_publisher(FlightHealth, "~/flight_health", 10)
        self.create_timer(1.0 / self.heartbeat_hz, self.link.tick_heartbeat,
                          callback_group=self.cbg)
        self.create_timer(1.0 / self.health_hz, self._publish_health,
                          callback_group=self.cbg)

        self._takeoff_busy = False
        self.takeoff_server = ActionServer(
            self, Takeoff, "~/takeoff",
            execute_callback=self._execute_takeoff,
            goal_callback=self._on_goal,
            cancel_callback=self._on_cancel,
            callback_group=self.cbg,
        )
        self.get_logger().info(
            f"就绪：心跳 {self.heartbeat_hz} Hz，健康 {self.health_hz} Hz，"
            f"offboard 丢失去抖 {self.link.offboard_loss_grace_sec}s")

    # ------------------------------------------------------------ FlightHealth
    def _publish_health(self) -> None:
        link = self.link
        m = FlightHealth()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = "px4"

        m.armed = link.armed
        m.flight_mode = link.nav_state_name
        n = link.nav_state
        m.nav_state = _NAV_TO_CONTRACT.get(n, FlightHealth.NAV_STATE_UNKNOWN) \
            if n is not None else FlightHealth.NAV_STATE_UNKNOWN

        # ready_for_offboard 按契约语义：已解锁 + 位置有效 + 无 failsafe + 链路健康。
        #
        # 注意 Takeoff **不能**用这一位做前置条件 —— 起飞时飞机必然还没解锁，
        # 这一位必然为 false。契约里 Takeoff 的注释写着以它为前置条件，
        # 那句话对不上实际时序（见 _preflight_reject 的说明），已记入待澄清项。
        # 这一位是给 Orbit / Revisit / InspectSweep 这些**飞行中**动作用的。
        m.ready_for_offboard = bool(
            link.armed and link.position_valid
            and not link.failsafe_active and link.connected)

        m.failsafe_active = link.failsafe_active
        m.failsafe_reasons = link.failsafe_reasons()

        if link.battery:
            rem = float(link.battery.remaining)
            m.battery_remaining = rem if not math.isnan(rem) else 0.0
            v = float(link.battery.voltage_v)
            m.battery_voltage_v = v if not math.isnan(v) else 0.0
        if link.gps:
            m.gps_fix_type = int(link.gps.fix_type)
            m.gps_satellites_used = int(link.gps.satellites_used)

        flags = link.flags
        m.rc_link_ok = not flags.manual_control_signal_lost if flags else False
        m.gcs_link_ok = not flags.gcs_connection_lost if flags else False
        m.companion_link_ok = link.connected
        m.companion_link_age_ms = link.link_age_ms
        self.pub_health.publish(m)

    # ------------------------------------------------------------ action 回调
    def _on_goal(self, goal_request) -> GoalResponse:
        # 结构性问题在这里直接拒（调用方拿不到 result_code，所以只拒明显无意义的请求）；
        # 需要回传具体原因的一律接受后 abort，让 result_code 说话。
        if goal_request.altitude_agl_m <= 0.0:
            self.get_logger().warn(
                f"拒绝：目标高度 {goal_request.altitude_agl_m} m 无意义")
            return GoalResponse.REJECT
        if self._takeoff_busy:
            self.get_logger().warn("拒绝：已有 Takeoff 在执行")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _on_cancel(self, goal_handle) -> CancelResponse:
        self.get_logger().info("收到取消请求")
        return CancelResponse.ACCEPT

    # ------------------------------------------------------------ 前置校验
    def _preflight_reject(self) -> tuple[int, str] | None:
        """返回 (result_code, message) 表示该拒；None 表示可以继续。

        刻意不查 FlightHealth.ready_for_offboard：那一位含"已解锁"，
        而起飞时必然未解锁。契约注释与实际时序对不上，这里用起飞自己的判据。
        """
        link = self.link
        if not link.connected:
            return (Takeoff.Result.RESULT_REJECTED_NOT_READY,
                    f"与飞控无连接（上次收到状态 {link.link_age_ms} ms 前）")
        if not link.position_valid:
            return (Takeoff.Result.RESULT_REJECTED_NOT_READY,
                    "位置估计无效（EKF 未收敛？xy_valid/z_valid 为假）")
        if link.armed:
            return (Takeoff.Result.RESULT_REJECTED_ALREADY_FLYING,
                    f"飞机已解锁，当前模式 {link.nav_state_name}")
        if link.failsafe_active:
            return (Takeoff.Result.RESULT_ABORTED_BY_FAILSAFE,
                    f"飞控处于失效保护：{', '.join(link.failsafe_reasons()) or '原因未知'}")
        return None

    # ------------------------------------------------------------ Takeoff
    def _execute_takeoff(self, goal_handle):
        self._takeoff_busy = True
        try:
            return self._run_takeoff(goal_handle)
        finally:
            self._takeoff_busy = False

    def _run_takeoff(self, goal_handle):
        link = self.link
        g = goal_handle.request
        t_start = time.time()
        target_alt = float(g.altitude_agl_m)
        climb_rate = max(float(g.climb_rate_mps), 0.1)
        timeout = float(g.timeout_sec) if g.timeout_sec > 0 else 60.0

        def result(code: int, msg: str):
            r = Takeoff.Result()
            r.result_code = code
            r.success = (code == Takeoff.Result.RESULT_OK)
            r.final_altitude_agl_m = float(link.altitude_agl_m or 0.0)
            r.elapsed_sec = float(time.time() - t_start)
            r.message = msg
            return r

        def handover(reason: str) -> None:
            """无论成功失败都要走这一步。

            停发 setpoint 不是安全收尾：实测断流约 1 秒后 PX4 触发失效保护并
            AUTO_RTL 自动降落。必须显式移交到 AUTO_LOITER 原地悬停。
            """
            self.get_logger().info(f"移交控制权到 AUTO_LOITER（{reason}）")
            res = link.set_mode_auto_loiter()
            if not res.accepted:
                self.get_logger().error(
                    f"移交 AUTO_LOITER 失败：{res.describe()}。"
                    f"仍保持心跳以免飞机自行返航降落")
                return
            # 确认已离开 OFFBOARD 再停心跳，否则会撞上"已停发但模式还没切"的窗口
            deadline = time.time() + self.mode_settle
            while time.time() < deadline:
                if not link.in_offboard:
                    break
                time.sleep(0.05)
            link.stop_heartbeat()

        self.get_logger().info(
            f"Takeoff 开始：目标 {target_alt:.1f} m，上升率 {climb_rate:.1f} m/s，"
            f"超时 {timeout:.0f} s")

        rej = self._preflight_reject()
        if rej:
            code, msg = rej
            self.get_logger().warn(f"前置校验未过：{msg}")
            goal_handle.abort()
            return result(code, msg)

        # ---- 1. 起心跳。目标先设成当前位置的目标高度，水平位置保持不动 ----
        x0, y0, z0 = link.current_ned()
        yaw = link.current_heading() if g.heading_deg < 0 else math.radians(g.heading_deg)
        link.start_heartbeat((x0, y0, z0), yaw)

        # ---- 2. 攒够 setpoint 再切模式。切模式前没有 setpoint 流会被拒 ----
        deadline = time.time() + 5.0
        while link.heartbeat_count < self.preheat and time.time() < deadline:
            time.sleep(0.05)
        if link.heartbeat_count < self.preheat:
            handover("心跳未能起来")
            goal_handle.abort()
            return result(Takeoff.Result.RESULT_AUTOPILOT_ERROR,
                          f"心跳发布异常：{self.mode_settle}s 内只发出 "
                          f"{link.heartbeat_count} 条 setpoint")

        # ---- 3. 切 OFFBOARD ----
        res = link.set_mode_offboard()
        if not res.accepted:
            handover("切 OFFBOARD 失败")
            goal_handle.abort()
            return result(Takeoff.Result.RESULT_AUTOPILOT_ERROR,
                          f"切 OFFBOARD 被拒：{res.describe()}")
        deadline = time.time() + self.mode_settle
        while not link.in_offboard and time.time() < deadline:
            time.sleep(0.05)
        if not link.in_offboard:
            handover("模式未变为 OFFBOARD")
            goal_handle.abort()
            return result(Takeoff.Result.RESULT_AUTOPILOT_ERROR,
                          f"命令已被接受但 {self.mode_settle}s 后模式仍是 "
                          f"{link.nav_state_name}")
        self.get_logger().info("已进入 OFFBOARD")

        # ---- 4. 解锁。被拒与无响应必须分开报 ----
        res = link.arm()
        if not res.accepted:
            reasons = ", ".join(link.failsafe_reasons()) or "无"
            handover("解锁失败")
            goal_handle.abort()
            if res.timed_out:
                return result(Takeoff.Result.RESULT_AUTOPILOT_ERROR,
                              "解锁命令无应答，怀疑与飞控链路异常")
            # 被拒基本都是健康检查没过。headless SITL 下常见原因是
            # gcs_link_lost（没有地面站连上来），需 param set NAV_DLL_ACT 0 或接 QGC。
            return result(Takeoff.Result.RESULT_REJECTED_NOT_READY,
                          f"解锁被飞控拒绝（{res.describe()}）。"
                          f"当前 failsafe 标志: [{reasons}]，"
                          f"预检通过={link.preflight_ok}")

        deadline = time.time() + self.mode_settle
        while not link.armed and time.time() < deadline:
            time.sleep(0.05)
        if not link.armed:
            handover("解锁未生效")
            goal_handle.abort()
            return result(Takeoff.Result.RESULT_AUTOPILOT_ERROR,
                          f"解锁命令被接受但 {self.mode_settle}s 后仍未解锁")
        self.get_logger().info("已解锁，开始爬升")

        # ---- 5. 爬升。按上升率斜坡给 z 目标，而不是一步给到顶 ----
        fb_period = 1.0 / self.feedback_hz
        next_fb = time.time()
        alt0 = link.altitude_agl_m or 0.0
        while True:
            now = time.time()
            elapsed = now - t_start

            if goal_handle.is_cancel_requested:
                handover("被取消")
                goal_handle.canceled()
                return result(Takeoff.Result.RESULT_CANCELED,
                              "已取消，保持当前高度悬停")

            # 去抖只影响**我们何时报告**，并不能保护飞行。
            #
            # 实测教训：PX4 的 COM_OF_LOSS_T 出厂是 1.0 s，而抖动宽度可达数秒 ——
            # 飞控会在我们的宽限期到期前就切 AUTO_RTL 接管（集成测试场景 C 实测到
            # 「飞控接管（模式 AUTO.RTL），原因: offboard_signal_lost」）。
            # 也就是说这类抖动不能靠调用方"容忍"，只能靠
            #   ① 抬高飞控侧的 COM_OF_LOSS_T（SITL 下的现行做法），或
            #   ② 从根上消除时钟抖动
            # 来处理。下面这个分支保留的意义是：真的持续丢失时给出准确的原因，
            # 而不是让 action 静静地超时。
            if link.offboard_signal_really_lost:
                handover("offboard 信号持续丢失")
                goal_handle.abort()
                return result(Takeoff.Result.RESULT_AUTOPILOT_ERROR,
                              f"offboard 信号持续丢失 "
                              f"{link.offboard_signal_lost_for():.1f}s")

            if link.failsafe_active and link.nav_state not in (NAV_OFFBOARD,):
                reasons = ", ".join(link.failsafe_reasons()) or "原因未知"
                goal_handle.abort()
                return result(Takeoff.Result.RESULT_ABORTED_BY_FAILSAFE,
                              f"飞控接管（模式 {link.nav_state_name}），原因: {reasons}")

            if not link.armed:
                goal_handle.abort()
                return result(Takeoff.Result.RESULT_ABORTED_BY_FAILSAFE,
                              f"飞行中被解除解锁，当前模式 {link.nav_state_name}")

            if elapsed > timeout:
                alt = link.altitude_agl_m
                handover("超时")
                goal_handle.abort()
                return result(Takeoff.Result.RESULT_TIMEOUT,
                              f"{timeout:.0f}s 内未到位，当前 "
                              f"{alt if alt is not None else float('nan'):.2f} m / "
                              f"目标 {target_alt:.2f} m")

            # 斜坡目标：从起始高度按上升率往上走，封顶在目标高度
            ramp_alt = min(alt0 + climb_rate * elapsed, target_alt)
            link.update_heartbeat_target((x0, y0, -ramp_alt), yaw)

            alt = link.altitude_agl_m
            if alt is not None and alt >= target_alt - self.alt_tol:
                link.update_heartbeat_target((x0, y0, -target_alt), yaw)
                self.get_logger().info(f"到达目标高度 {alt:.2f} m，用时 {elapsed:.1f}s")
                # 成功时同样移交 —— 否则调用方一旦不再发 setpoint 飞机就会返航降落
                handover("起飞完成")
                goal_handle.succeed()
                return result(Takeoff.Result.RESULT_OK,
                              f"到达 {alt:.2f} m（目标 {target_alt:.2f} m）")

            if now >= next_fb:
                fb = Takeoff.Feedback()
                fb.current_altitude_agl_m = float(alt or 0.0)
                fb.progress = float(min(max((alt or 0.0) / target_alt, 0.0), 1.0))
                fb.elapsed_sec = float(elapsed)
                goal_handle.publish_feedback(fb)
                next_fb = now + fb_period

            time.sleep(0.05)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AutopilotIface()
    # 必须多线程：单线程下 action 的阻塞式 execute 会饿死心跳定时器，
    # setpoint 断流约 1 秒后 PX4 就会 AUTO_RTL 降落
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.link.stop_heartbeat()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
