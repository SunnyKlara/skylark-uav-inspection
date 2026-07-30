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
import re
import time
from dataclasses import dataclass, field

from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from px4_msgs.msg import (
    BatteryStatus,
    FailsafeFlags,
    OffboardControlMode,
    SensorGps,
    TrajectorySetpoint,
    VehicleCommand,
    VehicleCommandAck,
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
        self.last_status_recv: float = 0.0
        self._acks: list[_Ack] = []
        self._offboard_lost_since: float | None = None

        # ---- 心跳目标 ----
        self._hb_active = False
        self._hb_target_ned = (0.0, 0.0, 0.0)   # x, y, z(下为正)
        self._hb_yaw: float | None = None
        self._hb_count = 0

        # ---- 订阅 ----
        self._sub_missing: list[str] = []
        self._subscribe("vehicle_status", VehicleStatus, self._on_status, qos)
        self._subscribe("vehicle_local_position", VehicleLocalPosition, self._on_lpos, qos)
        self._subscribe("failsafe_flags", FailsafeFlags, self._on_flags, qos)
        self._subscribe("vehicle_command_ack", VehicleCommandAck, self._on_ack, qos)
        self._subscribe("battery_status", BatteryStatus, self._on_battery, qos)
        self._subscribe("vehicle_gps_position", SensorGps, self._on_gps, qos)

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

    def px4_timestamp_us(self) -> int:
        """填给 PX4 的 timestamp。

        用 ROS 时钟是**正确**的：uxrce_dds_client 对入站 /fmu/in/* 会用
        time_offset_us 把时间戳换算到 PX4 时钟域
        （ucdr_deserialize_trajectory_setpoint(*ub, data, time_offset_us)）。
        实现层不要自己再换算一遍，那会叠加两次偏移。
        """
        return int(self.node.get_clock().now().nanoseconds / 1000)

    # ------------------------------------------------------------ 回调
    def _on_status(self, msg: VehicleStatus) -> None:
        self.status = msg
        self.last_status_recv = time.time()

    def _on_lpos(self, msg: VehicleLocalPosition) -> None:
        self.lpos = msg

    def _on_flags(self, msg: FailsafeFlags) -> None:
        self.flags = msg
        now = time.time()
        if msg.offboard_control_signal_lost:
            if self._offboard_lost_since is None:
                self._offboard_lost_since = now
        else:
            self._offboard_lost_since = None

    def _on_ack(self, msg: VehicleCommandAck) -> None:
        self._acks.append(_Ack(command=int(msg.command), result=int(msg.result)))
        # 只保留最近一小段，避免长时间运行后无界增长
        if len(self._acks) > 50:
            del self._acks[:-50]

    def _on_battery(self, msg: BatteryStatus) -> None:
        self.battery = msg

    def _on_gps(self, msg: SensorGps) -> None:
        self.gps = msg

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
        f = self.flags
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
        if f.local_position_invalid:
            reasons.append("local_position_invalid")
        if f.global_position_invalid:
            reasons.append("global_position_invalid")
        if f.home_position_invalid:
            reasons.append("home_position_invalid")
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
        ts = self.px4_timestamp_us()

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

    def current_ned(self) -> tuple[float, float, float]:
        if not self.lpos:
            return (0.0, 0.0, 0.0)
        return (float(self.lpos.x), float(self.lpos.y), float(self.lpos.z))

    def current_heading(self) -> float:
        if not self.lpos or math.isnan(self.lpos.heading):
            return 0.0
        return float(self.lpos.heading)
