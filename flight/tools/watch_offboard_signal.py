#!/usr/bin/env python3
"""观察 offboard 信号丢失事件与时钟偏移跳变的相关性。

存在的理由
----------
实测中发布节点全程存活、以 10 Hz 稳定发 setpoint，PX4 却会自发报
`offboard_control_signal_lost`。这个工具把两条线打在同一时间轴上定因：

    failsafe_flags.offboard_control_signal_lost      丢失事件
    timesync_status.estimated_offset / round_trip_time  时钟偏移跳变

实测结论（90 s，见 docs/OFFBOARD_CONSTRAINTS.md §7.1）：每次「丢失 -> 恢复」
都紧跟一次偏移跳变，且跳变过程中偏移会瞬间变成 0，对应 uxrce_dds_client 的
重置分支。即根因在 PX4 侧的时钟偏移估计陈旧，不在发布端。

排除过的解释：入站 /fmu/in/* 的 timestamp 未做时钟换算。读源码确认
`ucdr_deserialize_trajectory_setpoint(*ub, data, time_offset_us)` 是换算过的，
所以发布端用 ROS 时钟填 timestamp 是正确写法。

用法
----
    # 需要 SITL 已在跑，且有东西在发 offboard setpoint
    python3 watch_offboard_signal.py --duration 90
退出码：0 = 未观察到自发丢失；1 = 观察到（调用方据此决定是否需要容错）
"""

from __future__ import annotations

import argparse
import re
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from px4_msgs.msg import FailsafeFlags, TimesyncStatus, VehicleStatus

NAV = {0: "MANUAL", 2: "POSCTL", 4: "AUTO_LOITER", 5: "AUTO_RTL", 12: "DESCEND",
       14: "OFFBOARD", 17: "AUTO_TAKEOFF", 18: "AUTO_LAND"}
JUMP_THRESHOLD_US = 100_000     # 偏移变化超过 0.1s 才算跳变，避免刷屏


def resolve(node: Node, base: str, timeout: float = 10.0) -> str | None:
    """按 ^/fmu/out/<base>(_vN)?$ 解析话题名，只认有发布者的那个。

    PX4 v1.17 起后缀由各消息的 MESSAGE_VERSION 决定，写死名字会踩空。
    而只按名字匹配又会撞上「幽灵话题」—— 别的节点订阅了一个不存在的名字，
    该名字也会出现在 ROS 图里。用 count_publishers 筛掉（实测踩过）。
    """
    pat = re.compile(rf"^/fmu/out/{base}(_v\d+)?$")
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [t for t, _ in node.get_topic_names_and_types()
                 if pat.match(t) and node.count_publishers(t) > 0]
        if alive:
            alive.sort(key=lambda t: (0 if re.search(r"_v\d+$", t) else 1, t))
            return alive[0]
        time.sleep(0.3)
    return None


class OffboardSignalWatcher(Node):
    def __init__(self) -> None:
        super().__init__("skylark_offboard_signal_watcher")
        # VOLATILE：PX4 发布端是 TRANSIENT_LOCAL，默认订阅会先收到一串历史消息，
        # 那会让时间轴整体错位
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=20)
        self.t0 = time.time()
        self.lost: bool | None = None
        self.nav: int | None = None
        self.est_off: int | None = None
        self.n_lost_events = 0
        self.n_offset_jumps = 0
        self.rtt_max = 0
        self.missing: list[str] = []

        for base, typ, cb in (("failsafe_flags", FailsafeFlags, self._on_flags),
                              ("timesync_status", TimesyncStatus, self._on_ts),
                              ("vehicle_status", VehicleStatus, self._on_status)):
            topic = resolve(self, base)
            if topic:
                self.create_subscription(typ, topic, cb, qos)
            else:
                self.missing.append(base)

    def _log(self, msg: str) -> None:
        print(f"  [{time.time() - self.t0:7.2f}s] {msg}", flush=True)

    def _on_flags(self, m: FailsafeFlags) -> None:
        if m.offboard_control_signal_lost != self.lost:
            if self.lost is not None and m.offboard_control_signal_lost:
                self.n_lost_events += 1
            off = f"{self.est_off}us" if self.est_off is not None else "未知"
            self._log(f"offboard_control_signal_lost: {self.lost} -> "
                      f"{m.offboard_control_signal_lost}   (当时 estimated_offset={off})")
            self.lost = m.offboard_control_signal_lost

    def _on_status(self, m: VehicleStatus) -> None:
        if m.nav_state != self.nav:
            self._log(f"nav_state: {NAV.get(self.nav, self.nav)} -> "
                      f"{NAV.get(m.nav_state, m.nav_state)}")
            self.nav = m.nav_state

    def _on_ts(self, m: TimesyncStatus) -> None:
        self.rtt_max = max(self.rtt_max, m.round_trip_time)
        if self.est_off is None:
            self.est_off = m.estimated_offset
            self._log(f"timesync 首帧: estimated_offset={m.estimated_offset}us "
                      f"observed={m.observed_offset}us rtt={m.round_trip_time}us")
            return
        jump = abs(m.estimated_offset - self.est_off)
        if jump > JUMP_THRESHOLD_US:
            self.n_offset_jumps += 1
            self._log(f"timesync 偏移跳变 {jump / 1e6:+.3f}s: "
                      f"{self.est_off} -> {m.estimated_offset}us  rtt={m.round_trip_time}us")
        self.est_off = m.estimated_offset


def main() -> int:
    ap = argparse.ArgumentParser(description="观察 offboard 信号丢失与时钟偏移的相关性")
    ap.add_argument("--duration", type=float, default=90.0)
    args = ap.parse_args()

    rclpy.init()
    node = OffboardSignalWatcher()
    for base in node.missing:
        print(f"  警告：找不到 /fmu/out/{base}，该维度不可观测", file=sys.stderr)

    print(f"浸泡 {args.duration:.0f}s，只在事件发生时打印：", flush=True)
    t_end = time.time() + args.duration
    while time.time() < t_end:
        rclpy.spin_once(node, timeout_sec=0.1)

    print("", flush=True)
    print(f"结论数据：自发丢失 {node.n_lost_events} 次   偏移跳变 {node.n_offset_jumps} 次   "
          f"最终 lost={node.lost}   rtt 最大 {node.rtt_max}us", flush=True)
    if node.n_lost_events == 0:
        print("=> 本轮未观察到自发丢失。", flush=True)
    else:
        print("=> 存在自发丢失。offboard 类 action 必须按时间做去抖，"
              "不能一次丢失就 abort（见 docs/OFFBOARD_CONSTRAINTS.md §7.1）。", flush=True)

    node.destroy_node()
    rclpy.shutdown()
    return 1 if node.n_lost_events else 0


if __name__ == "__main__":
    sys.exit(main())
