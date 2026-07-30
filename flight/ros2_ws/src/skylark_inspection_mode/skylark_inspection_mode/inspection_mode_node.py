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
已实现：InspectSweep（含覆盖率 / 几何拒绝、断点续飞、低电量主动中止）。
未实现：Revisit（设计文档 §7 的第 4 步）、扫掠中自动插入 Revisit（第 5 步，
依赖 Window-A 的 DetectionArray）。未实现的部分不注册 action 服务器，
而不是注册一个立即返回失败的桩 —— 调用方发现「服务器不在线」比拿到
一个语义不明的失败码更容易定位。
"""

from __future__ import annotations

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from skylark_flight_internal_msgs.action import FollowPath
from skylark_flight_msgs.action import InspectSweep
from skylark_flight_msgs.msg import FlightHealth, VehicleState

from . import sweep
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

        p = self.get_parameter
        self.iface_ns = str(p("iface_ns").value).rstrip("/")
        self.hfov_deg = float(p("camera_hfov_deg").value)
        self.accept_radius_m = float(p("sweep_accept_radius_m").value)
        self.feedback_hz = float(p("feedback_hz").value)

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
        self.get_logger().info(
            f"就绪：动作 inspect_sweep；iface 命名空间 {self.iface_ns}；"
            f"相机视场 {self.hfov_deg:.2f}°；"
            f"低电量中止阈值 {self.battery_abort_threshold * 100:.0f}%")

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
