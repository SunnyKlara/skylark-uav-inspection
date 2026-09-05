"""与 PX4 通信的一层薄封装：状态订阅、offboard 心跳、命令下发与应答。

这一层存在的意义是把 flight/docs/OFFBOARD_CONSTRAINTS.md 里实测到的约束
集中处理掉，不让每个 action 各写一遍、各踩一遍。

集中处理的三件事：
  1. 话题名按 ^/fmu/out/<base>(_vN)?$ 动态解析。PX4 v1.17 起后缀由每条消息的
     MESSAGE_VERSION 决定（VehicleStatus=1 -> vehicle_status_v1，
     VehicleAttitude=0 -> 无后缀），写死名字必然踩空。
  2. offboard 信号丢失按**时间**去抖。实测发布端完全正常时该标志也会短暂置真
     （90s 内 2 次，与 PX4 时钟偏移重估同步），一次就 abort 会导致随机失败。
  3. 命令结果从 VehicleCommandAck 取，能区分「被拒」与「无响应」——
     不必去 grep 飞控日志。

订阅一律用 BEST_EFFORT + VOLATILE：PX4 发布端是 TRANSIENT_LOCAL，
默认订阅会先收到一串写端缓存的旧消息（实测起始落后 4~18 秒）。
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from px4_msgs.msg import (
    BatteryStatus,
    FailsafeFlags,
    OffboardControlMode,
    SensorGps,
    TrajectorySetpoint,
    VehicleAttitude,
    VehicleCommand,
    VehicleCommandAck,
    VehicleGlobalPosition,
    VehicleLandDetected,
    VehicleLocalPosition,
    VehicleStatus,
)

# ---- PX4 nav_state（取自 px4_msgs release/1.17 的 VehicleStatus.msg）----
NAV_MANUAL = 0
NAV_POSCTL = 2
NAV_AUTO_MISSION = 3
NAV_AUTO_LOITER = 4
NAV_AUTO_RTL = 5
NAV_DESCEND = 12
NAV_OFFBOARD = 14
NAV_AUTO_TAKEOFF = 17
NAV_AUTO_LAND = 18
NAV_ORBIT = 21

NAV_NAMES = {
    NAV_MANUAL: "MANUAL", 1: "ALTCTL", NAV_POSCTL: "POSCTL",
    NAV_AUTO_MISSION: "AUTO.MISSION", NAV_AUTO_LOITER: "AUTO.LOITER",
    NAV_AUTO_RTL: "AUTO.RTL", 6: "POSITION_SLOW", 8: "ALTITUDE_CRUISE",
    10: "ACRO", NAV_DESCEND: "DESCEND", 13: "TERMINATION",
    NAV_OFFBOARD: "OFFBOARD", 15: "STAB", NAV_AUTO_TAKEOFF: "AUTO.TAKEOFF",
    NAV_AUTO_LAND: "AUTO.LAND", 19: "AUTO.FOLLOW", 20: "AUTO.PRECLAND",
    NAV_ORBIT: "ORBIT", 22: "AUTO.VTOL_TAKEOFF",
}

ARMING_DISARMED = 1
ARMING_ARMED = 2

# ---- PX4 自定义模式编号，DO_SET_MODE 的 param2/param3 ----
# 官方示例切 offboard 用的是 (param1=1, param2=6)
PX4_MAIN_MODE_AUTO = 4
PX4_MAIN_MODE_OFFBOARD = 6
PX4_SUB_MODE_AUTO_LOITER = 3
PX4_SUB_MODE_AUTO_RTL = 5
PX4_SUB_MODE_AUTO_LAND = 6

ACK_ACCEPTED = 0
ACK_TEMPORARILY_REJECTED = 1
ACK_DENIED = 2
ACK_UNSUPPORTED = 3
ACK_FAILED = 4
ACK_IN_PROGRESS = 5
ACK_CANCELLED = 6

ACK_NAMES = {
    ACK_ACCEPTED: "ACCEPTED", ACK_TEMPORARILY_REJECTED: "TEMPORARILY_REJECTED",
    ACK_DENIED: "DENIED", ACK_UNSUPPORTED: "UNSUPPORTED", ACK_FAILED: "FAILED",
    ACK_IN_PROGRESS: "IN_PROGRESS", ACK_CANCELLED: "CANCELLED",
}


@dataclass
class CommandResult:
    """命令下发的结果。刻意把「被拒」和「无响应」分成两种，
    因为对调用方意味着完全不同的处置：前者要报原因，后者要怀疑链路。"""
    acked: bool
    result: int = -1
    timed_out: bool = False

    @property
    def accepted(self) -> bool:
        return self.acked and self.result == ACK_ACCEPTED

    def describe(self) -> str:
        if self.timed_out:
            return "无应答（超时）"
        return ACK_NAMES.get(self.result, f"未知应答码 {self.result}")


@dataclass
class _Ack:
    command: int
    result: int
    stamp: float = field(default_factory=time.time)


class PX4Link:
    """挂在一个 rclpy Node 上，提供 PX4 的读写接口。

    刻意不自己继承 Node：本包只应存在一个节点（offboard setpoint 流必须唯一），
    做成组合而不是继承，能避免以后有人顺手再实例化一个。
    """

    def __init__(self, node: Node, heartbeat_hz: float = 10.0,
                 offboard_loss_grace_sec: float = 3.0) -> None:
        self.node = node
        self.log = node.get_logger()
        self.heartbeat_hz = heartbeat_hz
        self.offboard_loss_grace_sec = offboard_loss_grace_sec

        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=10)

        # ---- 状态 ----
        self.status: VehicleStatus | None = None
        self.lpos: VehicleLocalPosition | None = None
        self.flags: FailsafeFlags | None = None
        self.battery: BatteryStatus | None = None
        self.gps: SensorGps | None = None
        self.land_detected: bool | None = None
        self.gpos: VehicleGlobalPosition | None = None
        self.attitude: VehicleAttitude | None = None
        self._offset_samples: list[int] = []
        self.last_status_recv: float = 0.0
        self._acks: list[_Ack] = []
        self._offboard_lost_since: float | None = None
        # 最新一帧 vehicle_local_position 的**本机接收时刻**。
        # 出站时间戳要相位锁定到飞控自己的时钟，就必须知道"那一帧是我什么时候拿到的"。
        self._lpos_recv_wall: float = 0.0
        # 时钟漂移的测量锚点：(本机接收时刻, 该帧的 PX4 时间戳)。
        # 只记第一帧，之后拿当前帧和它比，算出 PX4 时钟相对本机的快慢。
        self._drift_anchor: tuple[float, int] | None = None
        # 时钟伺服的观测窗口：(本机接收时刻, 该帧的 PX4 时间戳)。
        # 用来估飞控时钟相对本机的**速率**，好在两帧之间做外推。
        self._clock_samples: deque[tuple[float, int]] = deque()
        self._lpos_max_gap_s: float = 0.0
        # 时序取证用的环形缓冲：每条心跳记下"我发了什么时间戳"，
        # 每帧入站位置记下"飞控当时的时间戳是多少"。
        # 出事（被判过期）时把最近这一段落盘，就能离线算出
        # 飞控那边看到的"陈旧程度"到底是多少 —— 这是唯一能把责任
        # 从"我们算错时间戳"和"消息没按时送到飞控"里分开的办法。
        self._trace: deque[tuple[str, float, int]] = deque(maxlen=4000)
        # 上面这几项由位置回调写、由心跳线程读，而位置回调在
        # MultiThreadedExecutor + ReentrantCallbackGroup 下会并发执行。
        # 逐项操作在 GIL 下是原子的，但"读-改-写"的组合不是，必须显式加锁。
        self._lpos_lock = threading.Lock()
        self._lpos_last_ts: int = 0
        # 飞控**自己**判定 offboard 信号丢失的次数与最长持续时间。
        # 这是唯一有权威性的判据：我们发得多勤只是我们的说法。
        self._offboard_lost_events: int = 0
        self._offboard_lost_max_s: float = 0.0
        self._offboard_seen_ok: bool = False
        self._offboard_lost_flags: list[str] = []

        # ---- 心跳目标 ----
        self._hb_active = False
        self._hb_target_ned = (0.0, 0.0, 0.0)   # x, y, z(下为正)
        self._hb_yaw: float | None = None
        self._hb_count = 0
        self._hb_last_pub = 0.0
        self._hb_max_gap_s = 0.0

        # ---- 订阅 ----
        self._sub_missing: list[str] = []
        self._subscribe("vehicle_status", VehicleStatus, self._on_status, qos)
        self._subscribe("vehicle_local_position", VehicleLocalPosition, self._on_lpos, qos)
        self._subscribe("failsafe_flags", FailsafeFlags, self._on_flags, qos)
        self._subscribe("vehicle_command_ack", VehicleCommandAck, self._on_ack, qos)
        self._subscribe("battery_status", BatteryStatus, self._on_battery, qos)
        self._subscribe("vehicle_gps_position", SensorGps, self._on_gps, qos)
        # 触地判据用飞控的 land detector，不用"高度接近 0"（斜坡与气压漂移会误判）
        self._subscribe("vehicle_land_detected", VehicleLandDetected,
                        self._on_land_detected, qos)
        # 下面两条只为聚合出 VehicleState，动作逻辑不依赖它们
        self._subscribe("vehicle_global_position", VehicleGlobalPosition, self._on_gpos, qos)
        self._subscribe("vehicle_attitude", VehicleAttitude, self._on_attitude, qos)

        # ---- 发布 ----
        self.pub_ocm = node.create_publisher(
            OffboardControlMode, "/fmu/in/offboard_control_mode", 10)
        self.pub_sp = node.create_publisher(
            TrajectorySetpoint, "/fmu/in/trajectory_setpoint", 10)
        self.pub_cmd = node.create_publisher(
            VehicleCommand, "/fmu/in/vehicle_command", 10)

    # ------------------------------------------------------------ 基础设施
    def _resolve(self, base: str, discovery_timeout: float = 12.0) -> str:
        """解析带版本后缀的话题名，**只认真的有发布者的那个**。

        两个必须做对的地方，都踩过：
        1. 必须轮询等 DDS 发现完成。节点构造那一刻图里还是空的，只扫一次必然扫不到，
           于是退化成无后缀名。
        2. 必须用「有发布者」筛选，不能只看名字匹配。因为订阅一个不存在的话题名
           会把该名字注册进 ROS 图（订阅端也是端点），于是后启动的工具按正则解析时
           会先撞上这个**幽灵话题**，订阅到一个永远没有数据的名字上。
           实测症状是节点全程收不到 vehicle_status，报「与飞控无连接」，
           而根因在十几秒前的一次静默退化。
        """
        pat = re.compile(rf"^/fmu/out/{base}(_v\d+)?$")
        deadline = time.time() + discovery_timeout
        while True:
            candidates = [t for t, _ in self.node.get_topic_names_and_types() if pat.match(t)]
            alive = [t for t in candidates if self.node.count_publishers(t) > 0]
            if alive:
                # 有多个时优先带版本后缀的（无后缀那个更可能是别人留下的幽灵）
                alive.sort(key=lambda t: (0 if re.search(r"_v\d+$", t) else 1, t))
                return alive[0]
            if time.time() >= deadline:
                fallback = f"/fmu/out/{base}"
                self.log.warn(
                    f"{discovery_timeout:.0f}s 内没发现有发布者的 {pat.pattern}，"
                    f"退化订阅 {fallback}。若飞控未启动这是预期的；"
                    f"若飞控在跑则说明话题名或版本后缀有变")
                return fallback
            time.sleep(0.25)

    def _subscribe(self, base: str, msg_type, cb, qos) -> None:
        topic = self._resolve(base)
        self.node.create_subscription(msg_type, topic, cb, qos)
        self.log.info(f"订阅 {topic}（发布者 {self.node.count_publishers(topic)} 个）")

    # 出站时间戳的口径判据。
    #
    # 纪元微秒在 2001 年之后就大于 1e15，而 PX4 的开机计时在正常运行时长内
    # 远小于这个数（1e15 us = 31.7 年）。所以用它区分两种口径足够稳。
    _EPOCH_SCALE_US = 1_000_000_000_000_000

    # ---- 时钟伺服的三个常数 ----
    #
    # 为什么需要伺服而不是"拿最新一帧的时间戳直接用"：实测仿真时钟比本机快 13.5%
    # （clock_drift_ppm，fp5 轮），所以"过了多少本机时间"换算成飞控时间要乘速率。
    # 不乘的版本（fp5）把场景 C 从 3 个航点推进到 5 个，但仍在最后一段被判过期一次。
    _CLOCK_WINDOW_SEC = 8.0       # 速率估计的观测跨度
    _CLOCK_MIN_SPAN_SEC = 2.0     # 跨度不足就不敢估，按 1.0 用
    _CLOCK_RATE_BOUNDS = (0.5, 2.0)   # 估出界外的值一律不信（丢包/重启会造出怪值）
    # 入站断流超过这么久就停止外推。
    # 取 5 s（> COM_OF_LOSS_T 出厂 1 s）：SITL 里几百毫秒级的入站抖动不该升级成
    # 失效保护，而链路真死了必须能被发现 —— 后者主要由我们自己的 connected
    # （2 s 没收到 vehicle_status 就判断开）负责，这里只是兜底。
    _TS_FREEZE_AFTER_SEC = 5.0

    def _px4_clock_rate_locked(self) -> float:
        """飞控时钟相对本机时钟的速率（1.0 = 同速）。**调用方须持 _lpos_lock**。

        只取首尾两点，所以窗口里哪怕只混进一对乱序样本，速率就会歪 ——
        歪到 ±2 倍再乘上外推时长，足够让出站时间戳超出 COM_OF_LOSS_T。
        这是必须持锁的直接原因，不是洁癖。
        """
        if len(self._clock_samples) < 2:
            return 1.0
        (w0, t0), (w1, t1) = self._clock_samples[0], self._clock_samples[-1]
        span = w1 - w0
        if span < self._CLOCK_MIN_SPAN_SEC:
            return 1.0
        rate = ((t1 - t0) / 1e6) / span
        lo, hi = self._CLOCK_RATE_BOUNDS
        return rate if lo <= rate <= hi else 1.0

    def px4_clock_rate(self) -> float:
        with self._lpos_lock:
            return self._px4_clock_rate_locked()

    def px4_now_estimate_us(self) -> int | None:
        """用飞控自己的刻度写出的"现在"。SYNCT=0 口径下才有意义。"""
        with self._lpos_lock:
            if not self._clock_samples:
                return None
            w1, t1 = self._clock_samples[-1]
            rate = self._px4_clock_rate_locked()
        age = max(0.0, min(time.time() - w1, self._TS_FREEZE_AFTER_SEC))
        return t1 + int(age * rate * 1e6)

    def px4_timestamp_us(self) -> int:
        """填给 PX4 的 timestamp（出站方向）。口径**跟随飞控当前配置自动切换**。

        两种口径：
        - `UXRCE_DDS_SYNCT=1`（出厂）：uxrce_dds_client 会用 time_offset_us 把入站
          `/fmu/in/*` 的时间戳换算到 PX4 时钟域
          （`ucdr_deserialize_trajectory_setpoint(*ub, data, time_offset_us)`），
          所以我们应该发**本机纪元**时间，让它去换算。自己再换一遍会叠加两次偏移。
        - `UXRCE_DDS_SYNCT=0`（我们在 SITL 下的设置，用来压制 offboard 抖动）：
          PX4 不做换算，直接拿我们发的数去比新鲜度。此时必须发**PX4 开机计时**，
          否则差值是几十年量级。

        判据不读参数，而是看**飞控发来的时间戳量级** —— 那是它当前口径的原话：
        出站被换算过就是纪元级，没换算就是开机计时级。

        ⚠ 这个自适应不是锦上添花，它修掉的是一个**被绿灯掩盖的安全问题**：
        上一版无条件发本机纪元时间（约 1.785e18 us），而 SYNCT=0 时 PX4 不换算，
        于是它看到的时间戳在未来约 5.6 万年。offboardCheck 的判据是
            hrt_absolute_time() < timestamp + COM_OF_LOSS_T
        右边一旦是天文数字，这个不等式恒成立 ——
        **飞控的 offboard 过期检测被完全废掉了**，机载电脑真死了它也发现不了。
        当时那份"集成测试 13/13"正是在这个前提下取得的，
        旧注释还据此推断"关掉同步后这条校验的行为与开启时不同"，
        属于把"检查失效"读成了"检查通过"。
        教训：测试全绿不等于机制成立，尤其当被测的是"应该拦下什么"。

        SYNCT=0 分支为什么是**相位锁定**而不是"本机时间减偏移"：
        飞控那边的判据是（v1.17.0 offboardCheck.cpp:46）
            hrt_absolute_time() < timestamp + COM_OF_LOSS_T
        比较的双方都在 PX4 时钟域里，所以我们只需要一个"用飞控自己的刻度写出来的
        当前时刻"。而 lockstep SITL 的仿真时钟与墙钟速率不同（见 clock_drift_ppm），
        "本机时间 - 偏移估计" 的误差会随偏移估计的陈旧程度线性累积 ——
        滑动窗口最小值滤波把窗口内的漂移量（8 s × 漂移率）直接变成误差，
        起飞这种十几秒的动作看不出来，一条 60 s 的航段就够踩线。
        直接拿飞控最新一帧的时间戳当基准，误差就被钉死在"那一帧有多旧"
        （50 Hz 下 ≤ 20 ms），与漂移率无关。

        两帧之间的外推要**乘速率**，不能按本机时间等量加：仿真时钟实测比本机快
        13.5%，等量加会让我们的时间戳系统性偏旧。见 _px4_clock_rate。

        断流后停止外推（`_TS_FREEZE_AFTER_SEC`）是为了**保住失效保护语义**：
        入站流真断了还照着推，我们会一直造出"新鲜"的时间戳，飞控就永远发现不了
        链路已死。停住之后飞控照常在 COM_OF_LOSS_T 后接管 —— 那正是想要的行为。
        """
        now_us = int(self.node.get_clock().now().nanoseconds / 1000)
        lpos = self.lpos
        if lpos is None:
            return now_us
        px4_ts = int(lpos.timestamp)
        if px4_ts >= self._EPOCH_SCALE_US:
            return now_us                      # SYNCT=1：发纪元时间，PX4 会换算
        est = self.px4_now_estimate_us()        # SYNCT=0：相位锁定到飞控时钟域
        return est if est is not None else px4_ts

    # ---- 入站时间戳的时钟域换算 ----
    #
    # 为什么要自己做：契约要求 VehicleState.header.stamp 是"飞控采样时刻"。
    # 而我们为根治 offboard 掉线把 UXRCE_DDS_SYNCT 关了，PX4 出站时间戳
    # 因此是**开机计时**而非系统纪元 —— 直接填进 header 会得到 1970 年附近的值。
    #
    # 估计量用**最小值滤波**而不是均值：offset = 本机接收时刻 - 飞控采样时刻，
    # 其中传输延迟恒为正，所以观测到的 offset 恒大于真值，最小值最接近真值。
    # 这也正好避开了 PX4 自己那个每 30s 才校正一次、会漂 2.5s 的估计器
    # （同一份数据实测出来的问题，见 OFFBOARD_CONSTRAINTS.md §7.2）。
    # 窗口滑动是为了跟踪时钟漂移，不能一次定终身。
    _OFFSET_WINDOW = 400

    def _update_clock_offset(self, px4_ts_us: int, recv_wall: float) -> None:
        """由 _on_lpos 持锁调用。接收时刻由调用方传进来，不在这里再取一次
        time.time() —— 那样取到的是"处理到这一行的时刻"，与配对的时间戳不同源。"""
        if px4_ts_us <= 0:
            return
        self._offset_samples.append(int(recv_wall * 1e6) - px4_ts_us)
        if len(self._offset_samples) > self._OFFSET_WINDOW:
            del self._offset_samples[:-self._OFFSET_WINDOW]

    @property
    def clock_offset_us(self) -> int | None:
        """把 PX4 时间戳加上这个值，就得到本机纪元时间（微秒）。"""
        if not self._offset_samples:
            return None
        return min(self._offset_samples)

    @property
    def clock_drift_ppm(self) -> float | None:
        """PX4 时钟相对本机时钟的快慢（百万分率，正=飞控走得快）。

        存在的理由是**定量**：offboard 周期性掉线的整条推理链都建立在
        "lockstep 仿真时钟与墙钟速率不同"上，但此前从没量过方向和大小，
        于是修法只能靠试（先怪参数、再怪时间戳口径、再想抬容限）。
        算法就是两点法：拿第一帧和当前帧，比两个时钟各自走了多少。
        只在 SYNCT=0（出站是开机计时口径）下有意义。
        """
        with self._lpos_lock:
            anchor = self._drift_anchor
            ts_now = self._lpos_last_ts
            wall_now = self._lpos_recv_wall
        if anchor is None or ts_now <= 0:
            return None
        wall0, ts0 = anchor
        wall_span = wall_now - wall0
        if wall_span < 5.0:               # 跨度太短，量出来全是噪声
            return None
        px4_span = (ts_now - ts0) / 1e6
        return (px4_span - wall_span) / wall_span * 1e6

    def px4_ts_to_epoch_us(self, px4_ts_us: int) -> int | None:
        off = self.clock_offset_us
        if off is None or px4_ts_us <= 0:
            return None
        return px4_ts_us + off

    # ------------------------------------------------------------ 回调
    def _on_status(self, msg: VehicleStatus) -> None:
        self.status = msg
        self.last_status_recv = time.time()

    def _on_lpos(self, msg: VehicleLocalPosition) -> None:
        """位置回调。**整段必须持锁，且只能用局部变量**。

        为什么：节点用 MultiThreadedExecutor + ReentrantCallbackGroup，
        同一个回调会被多个线程并发执行。上一版在这里先写 self._lpos_recv_wall
        再拿它去 append，两个线程交错时就会把「A 线程的时间戳」和
        「B 线程的接收时刻」配成一对。

        这不是理论风险，是实测抓到的（99_notes/fp7/timing_trace.csv）：
        trace 里出现相邻两帧本机间隔 **-2852 ms** 的记录，
        分析工具据此报出"仿真时钟单次跳变 2.87 s"，差点让我把根因写成
        仿真保真度问题。同一份乱序数据还会污染时钟伺服的速率估计
        （_clock_samples 只取首尾两点），估歪之后出站时间戳就真的偏旧了 ——
        这正好解释了每轮**恰好一次**、时机随机的单帧过期误判。
        """
        recv = time.time()
        ts = int(msg.timestamp)
        with self._lpos_lock:
            # 乱序帧直接丢：它比已记录的还旧，既不该覆盖 self.lpos，
            # 也不该进任何统计。判据用 PX4 时间戳（严格单调），
            # 再加一道本机接收时刻的单调性兜底。
            if ts <= self._lpos_last_ts or recv < self._lpos_recv_wall:
                return
            prev_recv = self._lpos_recv_wall
            self._lpos_last_ts = ts
            self._lpos_recv_wall = recv
            self.lpos = msg
            # 入站间隔也要量：出站时间戳现在锚定在入站帧上，入站一卡出站就跟着变旧。
            # 不量这个的话，"被判过期"到底是外推算错还是入站断流，仍然只能猜。
            if prev_recv > 0.0:
                self._lpos_max_gap_s = max(self._lpos_max_gap_s, recv - prev_recv)
            # 用位置消息喂时钟偏移估计：它频率稳定（50 Hz）且样本量足
            self._update_clock_offset(ts, recv)
            if 0 < ts < self._EPOCH_SCALE_US:
                if self._drift_anchor is None:
                    self._drift_anchor = (recv, ts)
                self._clock_samples.append((recv, ts))
                cutoff = recv - self._CLOCK_WINDOW_SEC
                while len(self._clock_samples) > 2 and self._clock_samples[0][0] < cutoff:
                    self._clock_samples.popleft()
                self._trace.append(("lp", recv, ts))

    def _on_gpos(self, msg: VehicleGlobalPosition) -> None:
        self.gpos = msg

    def _on_attitude(self, msg: VehicleAttitude) -> None:
        self.attitude = msg

    def _on_flags(self, msg: FailsafeFlags) -> None:
        self.flags = msg
        now = time.time()
        if msg.offboard_control_signal_lost:
            if self._offboard_lost_since is None:
                self._offboard_lost_since = now
                # 只统计"飞控先确认在线、之后又丢"的事件。
                # 动作起手时该标志本来就是真的（还没开始发心跳），
                # 把那一段算进去的话计数恒不为 0，就没有判据价值了。
                if self._offboard_seen_ok:
                    self._offboard_lost_events += 1
                    # 抓翻转瞬间的**全部**标志位。
                    #
                    # 为什么非要这一份快照：offboardCheck.cpp 里置
                    # offboard_control_signal_lost 的有两条路 ——
                    # 一条是时间戳过期，另一条是
                    #   position && local_position_invalid  ->  offboard_available=false
                    # 后者在源码里明确写着"这是模式需求，无需上报"，
                    # 于是飞控不会给出任何别的原因，标志位名字还会把人往
                    # "链路丢了"的方向带。而我们读 failsafe_flags 是 1.85 Hz 的快照，
                    # 等到动作中止时再读，EKF 早恢复了，证据就没了。
                    self._offboard_lost_flags = self._flag_names(msg)
            if self._offboard_seen_ok:
                self._offboard_lost_max_s = max(self._offboard_lost_max_s,
                                                now - self._offboard_lost_since)
        else:
            self._offboard_lost_since = None
            self._offboard_seen_ok = True

    def _on_ack(self, msg: VehicleCommandAck) -> None:
        self._acks.append(_Ack(command=int(msg.command), result=int(msg.result)))
        # 只保留最近一小段，避免长时间运行后无界增长
        if len(self._acks) > 50:
            del self._acks[:-50]

    def _on_battery(self, msg: BatteryStatus) -> None:
        self.battery = msg

    def _on_gps(self, msg: SensorGps) -> None:
        self.gps = msg

    def _on_land_detected(self, msg: VehicleLandDetected) -> None:
        self.land_detected = bool(msg.landed)

    # ------------------------------------------------------------ 状态查询
    @property
    def connected(self) -> bool:
        """与飞控的链路是否新鲜。2 秒没收到 vehicle_status 就算断。"""
        return self.last_status_recv > 0 and (time.time() - self.last_status_recv) < 2.0

    @property
    def link_age_ms(self) -> int:
        if self.last_status_recv <= 0:
            return 0xFFFFFFFF
        return int((time.time() - self.last_status_recv) * 1000)

    @property
    def armed(self) -> bool:
        return bool(self.status and self.status.arming_state == ARMING_ARMED)

    @property
    def nav_state(self) -> int | None:
        return int(self.status.nav_state) if self.status else None

    @property
    def nav_state_name(self) -> str:
        n = self.nav_state
        return NAV_NAMES.get(n, f"UNKNOWN({n})") if n is not None else "UNKNOWN"

    @property
    def in_offboard(self) -> bool:
        return self.nav_state == NAV_OFFBOARD

    @property
    def altitude_agl_m(self) -> float | None:
        """相对起飞点的高度。

        注意这是 -z（NED 的 z 向下），参考面是 EKF 的局部原点，
        约等于「相对起飞点」而非真正的对地高度。装了下视测距仪后
        应改用 dist_bottom，届时这里要改。
        """
        if not self.lpos or not self.lpos.z_valid:
            return None
        return float(-self.lpos.z)

    @property
    def position_valid(self) -> bool:
        return bool(self.lpos and self.lpos.xy_valid and self.lpos.z_valid)

    @property
    def preflight_ok(self) -> bool:
        return bool(self.status and self.status.pre_flight_checks_pass)

    @property
    def failsafe_active(self) -> bool:
        return bool(self.status and self.status.failsafe)

    def offboard_signal_lost_for(self) -> float:
        """offboard 信号已持续丢失多久（秒）。0 表示当前未丢失。"""
        if self._offboard_lost_since is None:
            return 0.0
        return time.time() - self._offboard_lost_since

    @property
    def offboard_signal_really_lost(self) -> bool:
        """去抖后的判据。

        实测（docs/OFFBOARD_CONSTRAINTS.md §7.1）：发布端完全正常时该标志也会
        短暂置真，与 PX4 时钟偏移重估同步，90s 内出现 2 次。
        按次数去抖不行 —— failsafe_flags 实测只有约 1.85 Hz，
        「连续 N 帧」会隐含一个随发布频率变化的时长。所以按时间。
        """
        return self.offboard_signal_lost_for() > self.offboard_loss_grace_sec

    def failsafe_reasons(self) -> list[str]:
        """把 failsafe_flags 展成人类可读的原因列表。

        不要用飞控日志判断失效保护原因：日志里紧跟 "Failsafe activated" 的那行
        是 tone_alarm 的提示音，与原因无关（实测 setpoint 断流触发的失效保护，
        紧跟的照样是 battery warning）。
        """
        return self._flag_names(self.flags)

    @staticmethod
    def _flag_names(f) -> list[str]:
        """列出这一帧里为真的标志位。抽成静态方法是为了能对**历史快照**用同一套口径。"""
        if not f:
            return []
        reasons = []
        if f.offboard_control_signal_lost:
            reasons.append("offboard_signal_lost")
        if f.gcs_connection_lost:
            reasons.append("gcs_link_lost")
        if f.manual_control_signal_lost:
            reasons.append("rc_signal_lost")
        if f.battery_warning:
            reasons.append(f"battery_warning_{int(f.battery_warning)}")
        # 下面这几项是 offboardCheck 的"另一条路"会用到的前置条件，
        # 必须逐个列出来，否则 offboard_signal_lost 的真实成因分不清
        for name in ("local_position_invalid", "local_position_invalid_relaxed",
                     "local_velocity_invalid", "local_altitude_invalid",
                     "attitude_invalid", "angular_velocity_invalid",
                     "global_position_invalid", "home_position_invalid",
                     "position_accuracy_low", "navigator_failure"):
            if getattr(f, name, False):
                reasons.append(name)
        return reasons

    # ------------------------------------------------------------ 心跳
    def start_heartbeat(self, target_ned: tuple[float, float, float],
                        yaw: float | None = None) -> None:
        self._hb_target_ned = target_ned
        self._hb_yaw = yaw
        self._hb_count = 0
        self._hb_active = True

    def update_heartbeat_target(self, target_ned: tuple[float, float, float],
                               yaw: float | None = None) -> None:
        self._hb_target_ned = target_ned
        if yaw is not None:
            self._hb_yaw = yaw

    def stop_heartbeat(self) -> None:
        self._hb_active = False

    @property
    def heartbeat_count(self) -> int:
        return self._hb_count

    @property
    def hb_max_gap_ms(self) -> float:
        """心跳发布的最大间隔（毫秒）。

        存在的理由是**定因**：offboard 信号被判丢失有两种可能来源 ——
        我们这边的发布卡了（executor 被饿死、GIL、日志阻塞），
        或者飞控侧的时钟/新鲜度判定出问题。
        `COM_OF_LOSS_T` 出厂 1.0 s，10 Hz 发布下只要我们卡超过 1 s 就会被判丢失。
        不量这个值就只能猜，而猜的两轮都没修对（先怪参数、再怪时间戳口径）。
        """
        return self._hb_max_gap_s * 1000.0

    @property
    def offboard_lost_events(self) -> int:
        """本轮动作期间，飞控判定 offboard 信号丢失的**次数**（上升沿）。

        与 hb_max_gap_ms 配成一对，用来把责任分清：
        心跳间隔正常而这个数不为 0，说明问题在飞控侧的新鲜度判定（时间戳口径），
        两个都不正常才是我们发布卡了。动作开始时归零，见 reset_hb_stats。
        """
        return self._offboard_lost_events

    @property
    def offboard_lost_max_sec(self) -> float:
        return self._offboard_lost_max_s

    def timing_summary(self) -> str:
        """一行时序自证，附在 action 的 Result.message 里。

        这样每一次运行都自带证据，不必事后翻日志去猜是谁的问题。
        """
        drift = self.clock_drift_ppm
        drift_s = f"{drift / 10000:.2f}%" if drift is not None else "未测到"
        snap = ("，翻转瞬间标志位: " + "/".join(self._offboard_lost_flags)
                if self._offboard_lost_flags else "")
        return (f"心跳最大间隔 {self.hb_max_gap_ms:.0f} ms（{self.heartbeat_count} 条）；"
                f"入站位置最大间隔 {self._lpos_max_gap_s * 1000:.0f} ms；"
                f"飞控判 offboard 丢失 {self._offboard_lost_events} 次"
                f"（最长 {self._offboard_lost_max_s:.2f} s{snap}）；"
                f"仿真时钟相对本机 {drift_s}")

    def dump_timing_trace(self, path: str | None = None) -> str | None:
        """把最近一段时序落盘（CSV）。出事时调，用于离线定因。

        列：kind(hb=我发的心跳/lp=收到的位置), wall_epoch_s, px4_ts_us。
        离线用 lp 那两列拟合出"飞控时钟随本机时间怎么走"，
        再对每条 hb 算出飞控收到它时会算出多大的陈旧度，就能判断
        1 s 的容限是被我们的时间戳吃掉的，还是被消息传输/调度吃掉的。
        """
        target = path or os.environ.get("SKYLARK_TRACE_OUT")
        if not target or not self._trace:
            return None
        with self._lpos_lock:
            snapshot = list(self._trace)
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write("kind,wall_epoch_s,px4_ts_us\n")
                for kind, wall, ts in snapshot:
                    f.write(f"{kind},{wall:.6f},{ts}\n")
        except OSError as exc:
            self.log.warn(f"时序 trace 落盘失败（{target}）：{exc}")
            return None
        return target

    def reset_hb_stats(self) -> None:
        """归零本轮的时序统计。每个 offboard 动作起手都要调。

        连 offboard 丢失计数一起清：动作开始前该标志本来就是真的
        （还没开始发心跳），不清零的话第一个事件必然被记上，计数就失去意义。
        """
        self._hb_max_gap_s = 0.0
        self._hb_last_pub = 0.0
        self._lpos_max_gap_s = 0.0
        self._offboard_lost_events = 0
        self._offboard_lost_max_s = 0.0
        self._offboard_seen_ok = False
        self._offboard_lost_flags = []

    def tick_heartbeat(self) -> None:
        """定时器回调里调。

        OffboardControlMode 与 TrajectorySetpoint **必须成对发**，只发一个不生效。
        这个方法必须在 action 执行期间持续被调到 —— 用单线程 executor 时
        长时间阻塞的 action 回调会把定时器饿死，setpoint 断流约 1 秒后
        PX4 就会 RTL 降落。所以节点必须用 MultiThreadedExecutor +
        ReentrantCallbackGroup。
        """
        if not self._hb_active:
            return
        now = time.time()
        if self._hb_last_pub > 0.0:
            self._hb_max_gap_s = max(self._hb_max_gap_s, now - self._hb_last_pub)
        self._hb_last_pub = now
        ts = self.px4_timestamp_us()
        self._trace.append(("hb", now, ts))

        ocm = OffboardControlMode()
        ocm.timestamp = ts
        ocm.position = True
        ocm.velocity = False
        ocm.acceleration = False
        ocm.attitude = False
        ocm.body_rate = False
        self.pub_ocm.publish(ocm)

        sp = TrajectorySetpoint()
        sp.timestamp = ts
        x, y, z = self._hb_target_ned
        sp.position = [float(x), float(y), float(z)]
        sp.yaw = float(self._hb_yaw) if self._hb_yaw is not None else float("nan")
        self.pub_sp.publish(sp)

        self._hb_count += 1

    # ------------------------------------------------------------ 命令
    def _send_command(self, command: int, **params) -> None:
        msg = VehicleCommand()
        msg.timestamp = self.px4_timestamp_us()
        msg.command = int(command)
        for i in range(1, 8):
            setattr(msg, f"param{i}", float(params.get(f"param{i}", 0.0)))
        msg.target_system = 1
        msg.target_component = 1
        msg.source_system = 1
        msg.source_component = 1
        msg.from_external = True          # 少了这一位 PX4 会当成内部指令
        self.pub_cmd.publish(msg)

    def _take_ack(self, command: int, since: float) -> _Ack | None:
        for ack in reversed(self._acks):
            if ack.command == command and ack.stamp >= since:
                return ack
        return None

    def send_command_and_wait(self, command: int, timeout_sec: float = 3.0,
                              **params) -> CommandResult:
        """下发命令并等应答。

        调用方所在线程会阻塞在这里，但心跳定时器跑在别的线程里（见 tick_heartbeat
        的说明），所以不会导致 setpoint 断流。
        """
        since = time.time()
        self._send_command(command, **params)
        deadline = since + timeout_sec
        while time.time() < deadline:
            ack = self._take_ack(command, since)
            if ack:
                return CommandResult(acked=True, result=ack.result)
            time.sleep(0.05)
        return CommandResult(acked=False, timed_out=True)

    def set_mode_offboard(self, timeout_sec: float = 3.0) -> CommandResult:
        return self.send_command_and_wait(
            VehicleCommand.VEHICLE_CMD_DO_SET_MODE, timeout_sec,
            param1=1.0, param2=float(PX4_MAIN_MODE_OFFBOARD))

    def set_mode_auto_loiter(self, timeout_sec: float = 3.0) -> CommandResult:
        """交还控制权用的模式。

        为什么必须显式切模式而不是简单停发 setpoint：实测停发后约 1 秒触发失效保护，
        PX4 会 AUTO_RTL 并自动降落（约 10 秒后 "Disarmed by landing"）。
        AUTO_LOITER 会原地保持高度悬停，符合 Takeoff.action 声明的取消语义。
        """
        return self.send_command_and_wait(
            VehicleCommand.VEHICLE_CMD_DO_SET_MODE, timeout_sec,
            param1=1.0, param2=float(PX4_MAIN_MODE_AUTO),
            param3=float(PX4_SUB_MODE_AUTO_LOITER))

    def arm(self, timeout_sec: float = 3.0) -> CommandResult:
        return self.send_command_and_wait(
            VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, timeout_sec, param1=1.0)

    def disarm(self, timeout_sec: float = 3.0) -> CommandResult:
        return self.send_command_and_wait(
            VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, timeout_sec, param1=0.0)

    def wait_offboard_signal_ready(self, timeout_sec: float = 5.0) -> tuple[bool, str]:
        """等到**飞控自己认为** offboard 信号在线，再去切模式。

        为什么不能只靠"我发够了 N 条心跳"：那是我们这边的启发式，
        而判定权在飞控。实测教训（2026-07-30，FollowPath 集成测试）：
        飞机**已解锁飞行中**切 OFFBOARD 时，只要飞控此刻仍认为 offboard 信号陈旧，
        就会立刻失效保护转 AUTO_RTL —— 那次横向偏差只有 0.50 m，跟踪毫无问题，
        纯粹是切模式的时机不对。
        Takeoff 之所以没暴露这个问题，是因为它在**未解锁**时切模式，
        那时飞控不会因 offboard 信号触发失效保护。

        判据直接取 failsafe_flags.offboard_control_signal_lost —— 飞控的原话。
        """
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self.flags is not None and not self.flags.offboard_control_signal_lost:
                return (True, "飞控已确认 offboard 信号在线")
            time.sleep(0.05)
        if self.flags is None:
            return (False, "未收到 failsafe_flags，无法确认 offboard 信号状态")
        return (False, f"{timeout_sec:.0f}s 内飞控仍认为 offboard 信号丢失，"
                       f"不切模式（切了会立刻触发失效保护）")

    def handover_to_loiter(self, reason: str, settle_sec: float = 2.0) -> tuple[bool, str]:
        """把控制权交回飞控的 AUTO_LOITER，然后停心跳。

        每个 offboard 动作的**所有**退出路径都必须走这一步（成功、失败、被取消）。
        原因是实测的约束 5：停发 setpoint 后约 1 秒飞控触发失效保护并 AUTO_RTL
        自动降落，约 10 秒后 "Disarmed by landing"。也就是说"什么都不做"这个
        收尾方式的实际后果是飞机自己飞走并降落。

        顺序也重要：先确认已离开 OFFBOARD 再停心跳，否则会撞上
        「已停发 setpoint 但模式还没切过去」的窗口。
        """
        self.log.info(f"移交控制权到 AUTO_LOITER（{reason}）")
        res = self.set_mode_auto_loiter()
        if not res.accepted:
            self.log.error(
                f"移交 AUTO_LOITER 失败：{res.describe()}。"
                f"继续保持心跳，以免飞机自行返航降落")
            return (False, f"移交失败: {res.describe()}")
        deadline = time.time() + settle_sec
        while time.time() < deadline:
            if not self.in_offboard:
                break
            time.sleep(0.05)
        self.stop_heartbeat()
        return (True, "已移交 AUTO_LOITER")

    def set_mode_auto_land(self, timeout_sec: float = 3.0) -> CommandResult:
        """切飞控自带的 AUTO_LAND。

        刻意用飞控的降落而不是自己在 offboard 里往下压高度：
        触地检测（land detector）与落地上锁是安全关键逻辑，PX4 那套经过大量验证，
        自己实现只会更差。代价是 Land.action 的 descent_rate_mps 无法逐次生效
        （由 MPC_LAND_SPEED 等参数决定），这一点在 land.py 里如实告知调用方。
        """
        return self.send_command_and_wait(
            VehicleCommand.VEHICLE_CMD_DO_SET_MODE, timeout_sec,
            param1=1.0, param2=float(PX4_MAIN_MODE_AUTO),
            param3=float(PX4_SUB_MODE_AUTO_LAND))

    def set_mode_auto_rtl(self, timeout_sec: float = 3.0) -> CommandResult:
        return self.send_command_and_wait(
            VehicleCommand.VEHICLE_CMD_DO_SET_MODE, timeout_sec,
            param1=1.0, param2=float(PX4_MAIN_MODE_AUTO),
            param3=float(PX4_SUB_MODE_AUTO_RTL))

    @property
    def landed(self) -> bool:
        """是否已触地。用飞控的判据而不是"高度接近 0"——
        后者在斜坡地形或气压漂移下会误判。"""
        return bool(self.land_detected)

    def global_to_ned(self, lat_deg: float, lon_deg: float) -> tuple[float, float] | None:
        """把经纬度换算成 EKF 局部 NED 的 (north, east)。

        用等距圆柱近似：巡检任务的作业半径在百米量级，这个近似的误差远小于
        GPS 自身误差，不值得引入完整的大地投影。
        xy_global 为假时返回 None —— 那说明 EKF 还没有全局参考，
        此时任何经纬度输入都无法解释，必须拒绝而不是猜。
        """
        if not self.lpos or not self.lpos.xy_global:
            return None
        ref_lat = math.radians(float(self.lpos.ref_lat))
        d_lat = math.radians(lat_deg - float(self.lpos.ref_lat))
        d_lon = math.radians(lon_deg - float(self.lpos.ref_lon))
        r_earth = 6371000.0
        north = d_lat * r_earth
        east = d_lon * r_earth * math.cos(ref_lat)
        return (north, east)

    def current_ned(self) -> tuple[float, float, float]:
        if not self.lpos:
            return (0.0, 0.0, 0.0)
        return (float(self.lpos.x), float(self.lpos.y), float(self.lpos.z))

    def current_heading(self) -> float:
        if not self.lpos or math.isnan(self.lpos.heading):
            return 0.0
        return float(self.lpos.heading)
