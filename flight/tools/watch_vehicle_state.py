#!/usr/bin/env python3
"""监视 PX4 的解锁状态 / 导航模式 / 失效保护 / 高度，并把状态跃变打成时间线。

为什么需要它
------------
飞行动作（Takeoff / Land / Orbit）的正确性没法靠"命令发出去了"来判断，只能靠
状态机实际走到了哪个 nav_state、什么时候解锁、失效保护有没有介入。
排查 offboard 相关问题时，「模式在第几秒掉出 OFFBOARD、掉成了什么」是核心证据。

前一轮踩过的教训直接催生了这个工具：脚本只发 `commander arm` 不看结果，
把「解锁被拒」当成了「已在飞行」，于是拿静止数据当飞行数据报了出来。
动作类操作必须有独立的状态观测手段。

用法
----
    # 观测 60 秒，状态跃变打到 stdout，逐帧数据写 CSV
    python3 watch_vehicle_state.py --duration 60 --csv /tmp/state.csv

    # 等待进入 OFFBOARD 且爬升到 4.5 m 以上，成功即退出（退出码 0）
    python3 watch_vehicle_state.py --duration 40 --expect-nav 14 --expect-alt 4.5

QoS 说明：订阅端声明 VOLATILE。PX4 发布端是 TRANSIENT_LOCAL，默认订阅会先收到
一串历史消息（实测能落后 4~18 秒），那会让时间线整体错位。
"""

from __future__ import annotations

import argparse
import re
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from px4_msgs.msg import FailsafeFlags, VehicleLocalPosition, VehicleStatus

# 取自 px4_msgs release/1.17 的 VehicleStatus.msg
NAV_STATE = {
    0: "MANUAL", 1: "ALTCTL", 2: "POSCTL", 3: "AUTO_MISSION", 4: "AUTO_LOITER",
    5: "AUTO_RTL", 6: "POSITION_SLOW", 8: "ALTITUDE_CRUISE", 10: "ACRO",
    12: "DESCEND", 13: "TERMINATION", 14: "OFFBOARD", 15: "STAB",
    17: "AUTO_TAKEOFF", 18: "AUTO_LAND", 19: "AUTO_FOLLOW_TARGET",
    20: "AUTO_PRECLAND", 21: "ORBIT", 22: "AUTO_VTOL_TAKEOFF",
}
ARMING_STATE = {1: "DISARMED", 2: "ARMED"}


def resolve(node: Node, base: str, timeout: float = 10.0) -> str | None:
    """PX4 v1.17 起话题名按各消息的 MESSAGE_VERSION 拼 _vN 后缀
    （VehicleStatus=1 -> vehicle_status_v1，VehicleAttitude=0 -> 无后缀）。
    写死名字必然踩空，按正则匹配运行时真实存在的那个。

    ⚠ 必须用「有发布者」筛选，不能只看名字匹配：别的节点订阅一个不存在的话题名时，
    那个名字也会出现在 ROS 图里（订阅端也是端点）。只按名字匹配会撞上这种
    **幽灵话题**，订阅到永远没有数据的名字上。实测踩过：autopilot_iface 曾因
    发现未完成而退化订阅了无后缀名，随后本工具就解析到了那个幽灵话题，
    全程读不到任何状态。
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


class Watcher(Node):
    def __init__(self, csv_path: str | None) -> None:
        super().__init__("skylark_state_watcher")
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=20,
        )
        self.t0 = time.time()
        self.arming: int | None = None
        self.nav: int | None = None
        self.failsafe: bool | None = None
        self.checks_pass: bool | None = None
        self.z: float | None = None
        self.vz: float | None = None
        self.cause: str = ""      # 失效保护的原因，取自 failsafe_flags
        self.transitions: list[tuple[float, str]] = []

        self._csv = open(csv_path, "w", encoding="utf-8") if csv_path else None
        if self._csv:
            self._csv.write("t_rel_s,arming,nav,failsafe,checks_pass,alt_m,vz_mps\n")

        t_status = resolve(self, "vehicle_status")
        t_lpos = resolve(self, "vehicle_local_position")
        if not t_status:
            raise RuntimeError("找不到 /fmu/out/vehicle_status[_vN]，PX4 起了吗？")
        self.get_logger().info(f"订阅 {t_status} 与 {t_lpos}")
        self.create_subscription(VehicleStatus, t_status, self._on_status, qos)
        if t_lpos:
            self.create_subscription(VehicleLocalPosition, t_lpos, self._on_lpos, qos)
        # 失效保护的**原因**必须从 failsafe_flags 取。
        # 日志里紧跟 "Failsafe activated" 的那行是 tone_alarm 的提示音，与原因无关
        # —— 实测 setpoint 断流触发的失效保护，紧跟的照样是 battery warning，
        # 照着日志判因会把结论带偏（踩过）。
        t_flags = resolve(self, "failsafe_flags")
        if t_flags:
            self.create_subscription(FailsafeFlags, t_flags, self._on_flags, qos)

    # -------------------------------------------------- 回调
    def _on_status(self, msg: VehicleStatus) -> None:
        changed = []
        if msg.arming_state != self.arming:
            changed.append(f"arming {ARMING_STATE.get(self.arming, self.arming)}"
                           f" -> {ARMING_STATE.get(msg.arming_state, msg.arming_state)}")
            self.arming = msg.arming_state
        if msg.nav_state != self.nav:
            changed.append(f"nav {NAV_STATE.get(self.nav, self.nav)}"
                           f" -> {NAV_STATE.get(msg.nav_state, msg.nav_state)}")
            self.nav = msg.nav_state
        if msg.failsafe != self.failsafe:
            changed.append(f"failsafe {self.failsafe} -> {msg.failsafe}")
            self.failsafe = msg.failsafe
        self.checks_pass = msg.pre_flight_checks_pass
        for c in changed:
            t = time.time() - self.t0
            self.transitions.append((t, c))
            alt = -self.z if self.z is not None else float("nan")
            print(f"  [{t:6.2f}s] {c}   (alt={alt:.2f}m)", flush=True)

    def _on_lpos(self, msg: VehicleLocalPosition) -> None:
        self.z = msg.z if msg.z_valid else None
        self.vz = msg.vz

    def _on_flags(self, msg: FailsafeFlags) -> None:
        causes = []
        if msg.offboard_control_signal_lost:
            causes.append("offboard信号丢失")
        if msg.gcs_connection_lost:
            causes.append("地面站链路丢失")
        if msg.manual_control_signal_lost:
            causes.append("遥控信号丢失")
        if msg.battery_warning:
            causes.append(f"电池告警等级{msg.battery_warning}")
        if msg.local_position_invalid:
            causes.append("本地位置无效")
        if msg.global_position_invalid:
            causes.append("全局位置无效")
        cause = " + ".join(causes) if causes else ""
        if cause != self.cause:
            t = time.time() - self.t0
            desc = f"failsafe原因: [{cause or '无'}]"
            self.transitions.append((t, desc))
            print(f"  [{t:6.2f}s] {desc}", flush=True)
            self.cause = cause

    def write_row(self) -> None:
        if not self._csv:
            return
        alt = -self.z if self.z is not None else ""
        self._csv.write(
            f"{time.time() - self.t0:.2f},"
            f"{ARMING_STATE.get(self.arming, '')},"
            f"{NAV_STATE.get(self.nav, '')},"
            f"{self.failsafe if self.failsafe is not None else ''},"
            f"{self.checks_pass if self.checks_pass is not None else ''},"
            f"{alt if alt == '' else f'{alt:.3f}'},"
            f"{self.vz if self.vz is not None else ''}\n")
        self._csv.flush()

    def close(self) -> None:
        if self._csv:
            self._csv.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="监视 PX4 状态跃变")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--csv", default="")
    ap.add_argument("--hz", type=float, default=5.0, help="CSV 采样率")
    ap.add_argument("--expect-nav", type=int, default=None,
                    help="等待达到该 nav_state（14=OFFBOARD, 17=AUTO_TAKEOFF）")
    ap.add_argument("--expect-alt", type=float, default=None,
                    help="等待高度达到该值（米，正数）")
    ap.add_argument("--label", default="", help="打印在时间线开头的标签")
    args = ap.parse_args()

    rclpy.init()
    try:
        w = Watcher(args.csv or None)
    except RuntimeError as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        rclpy.shutdown()
        return 2

    if args.label:
        print(f"--- {args.label} ---", flush=True)
    print("状态时间线：", flush=True)

    period = 1.0 / max(args.hz, 0.1)
    next_row = time.time()
    hit_nav = args.expect_nav is None
    hit_alt = args.expect_alt is None
    t_hit_nav = t_hit_alt = None

    t_end = time.time() + args.duration
    while time.time() < t_end:
        rclpy.spin_once(w, timeout_sec=0.05)
        if time.time() >= next_row:
            w.write_row()
            next_row += period
        if not hit_nav and w.nav == args.expect_nav:
            hit_nav = True
            t_hit_nav = time.time() - w.t0
            print(f"  [{t_hit_nav:6.2f}s] ✓ 达到期望模式 "
                  f"{NAV_STATE.get(args.expect_nav, args.expect_nav)}", flush=True)
        if not hit_alt and w.z is not None and -w.z >= args.expect_alt:
            hit_alt = True
            t_hit_alt = time.time() - w.t0
            print(f"  [{t_hit_alt:6.2f}s] ✓ 达到期望高度 {args.expect_alt} m", flush=True)
        if hit_nav and hit_alt and (args.expect_nav is not None or args.expect_alt is not None):
            break

    alt_now = -w.z if w.z is not None else float("nan")
    print(f"\n结束状态: arming={ARMING_STATE.get(w.arming, w.arming)} "
          f"nav={NAV_STATE.get(w.nav, w.nav)} failsafe={w.failsafe} "
          f"alt={alt_now:.2f}m 预检通过={w.checks_pass}", flush=True)
    if w.cause:
        print(f"当前 failsafe 原因: {w.cause}", flush=True)
    print(f"共 {len(w.transitions)} 次状态跃变", flush=True)

    w.close()
    w.destroy_node()
    rclpy.shutdown()

    ok = hit_nav and hit_alt
    if not ok:
        missed = []
        if not hit_nav:
            missed.append(f"未达到 nav_state={NAV_STATE.get(args.expect_nav, args.expect_nav)}")
        if not hit_alt:
            missed.append(f"未达到高度 {args.expect_alt} m")
        print("未满足期望: " + "；".join(missed), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
