"""skylark_inspection_mode：flight 层的任务状态机。

分界（设计文档 §1）
------------------
本节点**不订阅 px4_msgs、不发 setpoint、不切飞行模式**。
它只做三件事：把任务意图翻译成航线、调 skylark_autopilot_iface 的 action、
把执行进度翻译回契约字段。

这条分界不是洁癖：offboard 的 setpoint 流必须只有一个发布者，
两个进程都能动飞机时它们会互相打断，而且**日志里看不出是谁打断了谁**。
所以「谁能动飞机」这件事必须收敛到 iface 一个包里。

执行模型
--------
与 iface 同样用 MultiThreadedExecutor + ReentrantCallbackGroup：
action 的 execute 回调是阻塞式状态机，它内部还要**等另一个 action 的结果**。
单线程 executor 下这会直接死锁 —— 等的那个 future 永远没人去处理。
同理，等 future 一律用轮询 + sleep，不能用 spin_until_future_complete。

当前进度
--------
已实现：InspectSweep（覆盖率 / 几何拒绝、断点续飞、低电量主动中止）、
Revisit（参数夹紧、频率限制、两个延迟埋点）。
未实现：扫掠中自动插入 Revisit（设计文档 §7 的第 5 步，依赖 Window-A 的
DetectionArray）、拍摄触发（相机在仿真里是连续出流，"连拍"需要先定义触发语义）。
未实现的部分不注册 action 服务器、也不假装填字段 —— 调用方发现
「服务器不在线」或看到 images_captured 恒为 0 并附说明，
都比拿到一个语义不明的成功更容易定位。
"""

from __future__ import annotations

import time

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from skylark_flight_internal_msgs.action import FollowPath
from skylark_flight_msgs.action import InspectSweep, Revisit
from skylark_flight_msgs.msg import FlightHealth, VehicleState

from . import revisit, revisit_policy as rp, sweep
from .geometry import MONO_CAM_HFOV_DEG

# 状态新鲜度上限。VehicleState 名义 10 Hz、FlightHealth 名义 2 Hz，
# 给到 2 秒既容得下抖动，又不至于拿着几秒前的状态去决定飞哪里。
STATE_STALE_SEC = 2.0


class InspectionMode(Node):
    def __init__(self) -> None:
        super().__init__("skylark_inspection_mode")

        def desc(text: str) -> ParameterDescriptor:
            return ParameterDescriptor(description=text)

        self.declare_parameter("iface_ns", "/skylark_autopilot_iface",
                               desc("skylark_autopilot_iface 的命名空间"))
        # 相机水平视场。契约允许 goal 里的 camera_hfov_deg=0 表示"由服务端从配置读"，
        # 读的就是这个参数。
        #
        # ⚠ 默认值必须可追溯到实际相机，不能是个凭感觉的数：
        # 99.69466° = 1.74 rad，实测自 PX4 v1.17.0 的
        # Tools/simulation/gz/models/mono_cam/model.sdf:54 <horizontal_fov>。
        # 换真机相机时**必须**同步改这个参数，否则覆盖率保证是假的。
        self.declare_parameter(
            "camera_hfov_deg", MONO_CAM_HFOV_DEG,
            desc("相机水平视场（度）。默认 99.69466° = 1.74 rad，"
                 "实测自 PX4 v1.17.0 mono_cam/model.sdf:54。换真机相机必须同步改"))
        self.declare_parameter("sweep_accept_radius_m", 1.5,
                               desc("航点到达半径（米），传给 FollowPath"))
        self.declare_parameter("feedback_hz", 5.0, desc("Feedback 发布频率"))
        # 低电量主动中止阈值（设计文档 §6）。这是状态机自己的判断，
        # 与飞控的 COM_LOW_BAT_ACT 是两回事。
        self.declare_parameter("battery_abort_threshold", 0.15,
                               desc("剩余电量低于此值则主动中止扫掠（0.0~1.0）"))

        # ---- Revisit 的安全边界。默认值与理由见 revisit_policy.py 与设计文档 §5 ----
        # 全部做成参数而不是写死：真机的安全下限、可接受的悬停时长都要重新定，
        # 而改这些不该动代码。
        self.declare_parameter("revisit_min_agl_m", rp.DEFAULT_MIN_AGL_M,
                               desc("复拍高度下限（米）。低于此值地效与测距噪声显著"))
        self.declare_parameter("revisit_max_hover_sec", rp.DEFAULT_MAX_HOVER_SEC,
                               desc("悬停时长上限（秒）"))
        self.declare_parameter("revisit_max_burst", rp.DEFAULT_MAX_BURST,
                               desc("连拍张数上限"))
        self.declare_parameter(
            "revisit_max_offset_m", rp.DEFAULT_MAX_OFFSET_M,
            desc("复拍点相对当前位置的水平偏移上限（米）。**超限拒绝而非夹紧**"))
        self.declare_parameter("revisit_rate_limit_sec", rp.DEFAULT_RATE_LIMIT_SEC,
                               desc("同一点复拍的最小间隔（秒）"))
        self.declare_parameter("revisit_rate_limit_radius_m",
                               rp.DEFAULT_RATE_LIMIT_RADIUS_M,
                               desc("判定「同一点」的半径（米）"))
        self.declare_parameter("revisit_descent_speed_mps", 1.0,
                               desc("降高/爬升速率（米/秒）"))
        self.declare_parameter("revisit_transit_speed_mps", 3.0,
                               desc("水平转场速度（米/秒）"))
        # ⚠ 这个值必须**小于** onstation_alt_tol_m，否则"到位"判据不可达：
        # FollowPath 一进到达半径就宣布到达并移交 LOITER，而 LOITER 保持的是
        # 当时的高度，不会再向指令高度收敛。实测踩过（99_notes/rv1）：
        # 半径 0.8 > 容差 0.5，飞机停在偏 0.74 m 处，latency_goal_to_onstation_ms
        # 全程测不到。启动时会检查这个关系并告警。
        self.declare_parameter(
            "revisit_accept_radius_m", 0.35,
            desc("复拍航点到达半径（米）。必须小于 onstation_alt_tol_m"))
        # ---- 延迟测量的判据（设计文档 §4）----
        self.declare_parameter("motion_speed_mps", 0.3,
                               desc("速度超过此值即认为「飞机开始动作」"))
        self.declare_parameter("onstation_alt_tol_m", 0.5,
                               desc("到位判据：高度误差容差（米）"))
        self.declare_parameter("onstation_speed_mps", 0.3,
                               desc("到位判据：水平速度上限（米/秒）"))
        self.declare_parameter(
            "onstation_hold_sec", 1.0,
            desc("到位判据必须**连续保持**的时长（秒）。单帧命中会在超调时误触发，"
                 "测出的延迟会系统性偏小"))

        p = self.get_parameter
        self.iface_ns = str(p("iface_ns").value).rstrip("/")
        self.hfov_deg = float(p("camera_hfov_deg").value)
        self.accept_radius_m = float(p("sweep_accept_radius_m").value)
        self.feedback_hz = float(p("feedback_hz").value)
        self.revisit_min_agl_m = float(p("revisit_min_agl_m").value)
        self.revisit_max_hover_sec = float(p("revisit_max_hover_sec").value)
        self.revisit_max_burst = int(p("revisit_max_burst").value)
        self.revisit_max_offset_m = float(p("revisit_max_offset_m").value)
        self.revisit_rate_limit_sec = float(p("revisit_rate_limit_sec").value)
        self.revisit_rate_limit_radius_m = float(p("revisit_rate_limit_radius_m").value)
        self.revisit_descent_speed_mps = float(p("revisit_descent_speed_mps").value)
        self.revisit_transit_speed_mps = float(p("revisit_transit_speed_mps").value)
        self.revisit_accept_radius_m = float(p("revisit_accept_radius_m").value)
        self.motion_speed_mps = float(p("motion_speed_mps").value)
        self.onstation_alt_tol_m = float(p("onstation_alt_tol_m").value)
        self.onstation_speed_mps = float(p("onstation_speed_mps").value)
        self.onstation_hold_sec = float(p("onstation_hold_sec").value)
        # 频率限制的记账：(x, y, 单调时钟时刻)。
        # 用单调时钟而不是墙钟 —— 系统时间被 NTP 拨动时，墙钟差值会算出负间隔，
        # 于是限流失效。
        self._last_revisit: tuple[float, float, float] | None = None

        self.cbg = ReentrantCallbackGroup()

        # iface 的两个话题都是普通 ROS 话题（不是 PX4 的 best-effort 流），
        # 用 RELIABLE 即可；深度给 1，我们只关心最新一帧。
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
        self._state: VehicleState | None = None
        self._state_recv: float = 0.0
        self._health: FlightHealth | None = None
        self._health_recv: float = 0.0
        self.create_subscription(VehicleState, f"{self.iface_ns}/vehicle_state",
                                 self._on_state, qos, callback_group=self.cbg)
        self.create_subscription(FlightHealth, f"{self.iface_ns}/flight_health",
                                 self._on_health, qos, callback_group=self.cbg)

        self.fp_client = ActionClient(self, FollowPath,
                                      f"{self.iface_ns}/follow_path",
                                      callback_group=self.cbg)

        # 与 iface 同样的「忙」标志：扫掠独占飞机，并发请求一律拒。
        # 将来 Revisit 会作为扫掠的**子步骤**插入，那时它共用这把标志
        # （由扫掠自己让出），而不是各持一把。
        self._busy: str | None = None

        self.sweep_server = ActionServer(
            self, InspectSweep, "~/inspect_sweep",
            execute_callback=self._execute_sweep,
            goal_callback=lambda _g: self._on_goal("inspect_sweep"),
            cancel_callback=lambda _g: CancelResponse.ACCEPT,
            callback_group=self.cbg,
        )
        self.revisit_server = ActionServer(
            self, Revisit, "~/revisit",
            execute_callback=self._execute_revisit,
            goal_callback=lambda _g: self._on_goal("revisit"),
            cancel_callback=lambda _g: CancelResponse.ACCEPT,
            callback_group=self.cbg,
        )
        # 自检一条参数间的耦合关系。写成启动告警而不是注释：
        # 这两个值单看都合理，只有放在一起才矛盾，而矛盾的表现是
        # "延迟字段永远测不到"——一个不会报错、只会静默出错的形态。
        if self.revisit_accept_radius_m >= self.onstation_alt_tol_m:
            self.get_logger().warn(
                f"参数自相矛盾：revisit_accept_radius_m="
                f"{self.revisit_accept_radius_m:.2f} >= onstation_alt_tol_m="
                f"{self.onstation_alt_tol_m:.2f}。到达半径比高度容差还宽时，"
                f"飞机会在容差之外就被判到达并移交 LOITER，"
                f"latency_goal_to_onstation_ms 将永远测不到")

        self.get_logger().info(
            f"就绪：动作 inspect_sweep / revisit；iface 命名空间 {self.iface_ns}；"
            f"相机视场 {self.hfov_deg:.2f}°；"
            f"低电量中止阈值 {self.battery_abort_threshold * 100:.0f}%；"
            f"复拍安全下限 {self.revisit_min_agl_m:.1f} m、"
            f"偏移上限 {self.revisit_max_offset_m:.0f} m、"
            f"限流 {self.revisit_rate_limit_radius_m:.0f} m/"
            f"{self.revisit_rate_limit_sec:.0f} s")

    @property
    def battery_abort_threshold(self) -> float:
        """每次用时都读参数，而不是在 __init__ 里存一份。

        这样 `ros2 param set` 能立刻生效 —— 集成测试要靠这一点单独挑衅
        这条守卫（把阈值临时抬到 0.99，扫掠必须立刻回 ABORTED_LOW_BATTERY），
        否则就得为它重启节点。查一次参数的开销可以忽略。
        """
        return float(self.get_parameter("battery_abort_threshold").value)

    # ------------------------------------------------------------ 状态缓存
    def _on_state(self, msg: VehicleState) -> None:
        first = self._state is None
        self._state = msg
        self._state_recv = self.get_clock().now().nanoseconds / 1e9
        if first:
            self._log_link_ready()

    def _on_health(self, msg: FlightHealth) -> None:
        first = self._health is None
        self._health = msg
        self._health_recv = self.get_clock().now().nanoseconds / 1e9
        if first:
            self._log_link_ready()

    def _log_link_ready(self) -> None:
        """两个话题都收到过之后打一行「状态就绪」。

        存在的理由是给测试一个**可观测的就绪条件**。
        「节点起来了」不等于「节点能判断飞机状态」：话题发现要一点时间，
        这期间发 goal 会拿到"收不到 vehicle_state"而不是真正的拒绝理由。
        实测踩过（99_notes/isw1 vs isw2：同一条断言一轮过一轮不过），
        修法不是在脚本里 sleep 几秒，而是让节点自己报就绪。
        """
        if self._state is not None and self._health is not None:
            self.get_logger().info("状态就绪：已收到 vehicle_state 与 flight_health")

    def _fresh(self, msg, recv: float):
        """过期的状态一律当"没有"。

        返回一帧陈旧的状态比返回 None 更危险：调用方会拿它当真，
        而扫掠会据此算出一条基于几秒前位置的航线。
        """
        if msg is None:
            return None
        now = self.get_clock().now().nanoseconds / 1e9
        return msg if (now - recv) <= STATE_STALE_SEC else None

    def latest_state(self) -> VehicleState | None:
        return self._fresh(self._state, self._state_recv)

    def latest_health(self) -> FlightHealth | None:
        return self._fresh(self._health, self._health_recv)

    # ------------------------------------------------------------ 动作
    def _on_goal(self, name: str) -> GoalResponse:
        if self._busy is not None:
            self.get_logger().warn(
                f"拒绝 {name}：正在执行 {self._busy}。任务动作独占飞机，"
                f"并发请求一律拒，由调用方串行编排")
            return GoalResponse.REJECT
        self._busy = name
        return GoalResponse.ACCEPT

    def _execute_sweep(self, goal_handle):
        try:
            return sweep.execute(self, goal_handle)
        finally:
            self._busy = None

    def _execute_revisit(self, goal_handle):
        before = self._last_revisit
        try:
            return revisit.execute(self, goal_handle)
        finally:
            self._busy = None
            # 冷却窗口从复拍**结束**时刻起算，不是开始时刻。
            #
            # 实测教训（99_notes/rv1 场景 B）：一次复拍本身要飞 30 秒上下
            # （下降 + 悬停 + 爬回），从开始时刻起算的话，动作刚结束
            # 30 s 窗口就已经过期了 —— 限流等于不存在，而它要防的正是
            # "刚拍完又被同一个误检拽下去"。
            if self._last_revisit is not None and self._last_revisit is not before:
                x, y, _ = self._last_revisit
                self._last_revisit = (x, y, time.monotonic())

    # ---- 频率限制的记账 ----
    @property
    def last_revisit(self) -> tuple[float, float, float] | None:
        return self._last_revisit

    def mark_revisit(self, x: float, y: float, t_mono: float) -> None:
        """记下这次复拍点。刻意在**开始执行前**记，不是完成后：
        限流要防的是"反复下降"，而下降在开始那一刻就已经发生了。"""
        self._last_revisit = (float(x), float(y), float(t_mono))


def main(argv=None) -> None:
    rclpy.init(args=argv)
    node = InspectionMode()
    # 必须多线程：execute 回调里要等 FollowPath 的 future，
    # 单线程下没人去处理那个 future -> 死锁（见模块 docstring）
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
