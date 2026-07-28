#!/usr/bin/env python3
"""实测 PX4 经 uXRCE-DDS 桥出来的每个话题的发布频率与序列化字节数。

存在的理由
----------
`dds_bandwidth.py` 是**估算**：消息大小由 .msg 定义推算，速率取 `dds_topics.yaml`
的 `rate_limit`，没有 `rate_limit` 的话题只能用 `--default-rate` 猜（默认 10 Hz）。

这个猜测在 PX4 v1.17.0 上错得很厉害 —— 该版本里 `vehicle_odometry`（带宽第一大户）
和 `vehicle_attitude` 都**没有** `rate_limit` 行，实测分别在 100 Hz 量级，
比 10 Hz 的假设高一个数量级。本工具用实测值替掉猜测值。

为什么不用 `ros2 topic hz` / `ros2 topic bw`
-------------------------------------------
它们量的是**订阅端每秒收到多少**。`/fmu/out/*` 是 BEST_EFFORT，Python 订阅端
跟不上时消息直接丢，读数系统性偏低且随机器负载乱跳 —— 实测同一个健康系统，
`vehicle_local_position` 两轮分别报 50.0 Hz 和 21.4 Hz（2026-07-27）。

本工具改用消息里的 `timestamp` 字段（PX4 自己的时钟）反推间隔：
消息晚到甚至丢了，剩下那些的时间戳间隔仍然反映真实发布节奏。
估计量是「剔除离群后的截尾均值」，对丢包与双峰间隔分布都稳（限流器作用在
量化的源上时，间隔会在两个值之间交替，取众数会算出超过上限的荒谬值）。

QoS 上刻意用 VOLATILE
--------------------
PX4 发布端是 TRANSIENT_LOCAL，晚加入的订阅者会先收到一串历史缓存（实测能落后
4~18 秒）。订阅端声明 VOLATILE 依然能匹配（durability 只要不强于发布端），
但不会收到历史 —— 一上来就是实时消息，省掉排空步骤。

用法
----
    # 需要先起好 SITL + MicroXRCEAgent，并 source 过 ROS 2 环境
    python3 measure_dds_topics.py --duration 25 --out measured_dds_sitl.json

    # 只量指定话题
    python3 measure_dds_topics.py --topics /fmu/out/vehicle_odometry --duration 15

输出的 JSON 可直接喂给 `dds_bandwidth.py --measured <file>`。
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.serialization import serialize_message
from rosidl_runtime_py.utilities import get_message


def trimmed_rate_hz(stamps_us: list[int]) -> tuple[float | None, dict]:
    """从时间戳序列反推发布频率。返回 (频率, 诊断信息)。

    做法：相邻间隔 -> 剔除离群（<0.2x 或 >5x 中位数）-> 剩余取均值 -> 取倒数。
    离群多半是丢包造成的整数倍间隔，或采样起止处的抖动。
    """
    diag: dict = {"n_samples": len(stamps_us)}
    if len(stamps_us) < 5:
        return None, diag

    deltas = [b - a for a, b in zip(stamps_us, stamps_us[1:])]
    positive = [d for d in deltas if d > 0]
    diag["n_nonmonotonic"] = len(deltas) - len(positive)
    if len(positive) < 4:
        return None, diag

    med = statistics.median(positive)
    lo, hi = med * 0.2, med * 5
    kept = [d for d in positive if lo <= d <= hi]
    diag["n_outliers"] = len(positive) - len(kept)
    if not kept:
        return None, diag

    mean_us = sum(kept) / len(kept)
    diag["mean_interval_ms"] = round(mean_us / 1000, 3)
    diag["median_interval_ms"] = round(med / 1000, 3)
    diag["max_interval_ms"] = round(max(positive) / 1000, 3)
    return 1e6 / mean_us, diag


class Collector(Node):
    def __init__(self, topics: list[tuple[str, str]], depth: int) -> None:
        super().__init__("skylark_dds_measure")
        # 与 PX4 发布端匹配的最宽松组合；durability 用 VOLATILE 以跳过历史回放
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=depth,
        )
        self.stamps: dict[str, list[int]] = {t: [] for t, _ in topics}
        self.sizes: dict[str, list[int]] = {t: [] for t, _ in topics}
        self.arrivals: dict[str, list[float]] = {t: [] for t, _ in topics}
        self.type_names: dict[str, str] = dict(topics)
        self._subs = []
        skipped = []
        for topic, type_name in topics:
            try:
                msg_cls = get_message(type_name)
            except (ImportError, ValueError, AttributeError) as exc:
                skipped.append((topic, f"{type_name}: {exc}"))
                continue
            self._subs.append(
                self.create_subscription(
                    msg_cls, topic,
                    lambda msg, t=topic: self._on_msg(t, msg),
                    qos,
                )
            )
        self.skipped = skipped

    def _on_msg(self, topic: str, msg) -> None:
        self.arrivals[topic].append(time.time())
        self.sizes[topic].append(len(serialize_message(msg)))
        stamp = getattr(msg, "timestamp", None)
        if isinstance(stamp, int) and stamp > 0:
            self.stamps[topic].append(stamp)


def gazebo_rtf() -> float | None:
    """采一次 Gazebo 实时率。SITL 下发布频率是仿真时钟频率，
    RTF 明显偏离 1 时要在报告里说明，否则墙钟侧的数字没法解释。"""
    try:
        listed = subprocess.run(["gz", "topic", "-l"], capture_output=True,
                                text=True, timeout=8).stdout
        stats = next((ln.strip() for ln in listed.splitlines()
                      if ln.strip().startswith("/world/") and ln.strip().endswith("/stats")), None)
        if not stats:
            return None
        out = subprocess.run(["gz", "topic", "-e", "-t", stats, "-n", "3"],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "real_time_factor" in line:
                return float(line.split(":")[1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return None


def px4_ref() -> str:
    """记下被测固件源码树的 git ref。没有这个，测量结果无法追溯到版本。"""
    import os
    px4_dir = os.environ.get("PX4_DIR", os.path.expanduser("~/PX4-Autopilot"))
    try:
        out = subprocess.run(["git", "-C", px4_dir, "describe", "--tags", "--always"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description="实测 PX4 DDS 话题的频率与字节数")
    ap.add_argument("--duration", type=float, default=25.0, help="采集时长（秒），默认 25")
    ap.add_argument("--prefix", default="/fmu/out/", help="只测该前缀下的话题")
    ap.add_argument("--topics", nargs="*", default=[], help="指定话题（覆盖 --prefix）")
    ap.add_argument("--depth", type=int, default=200, help="订阅队列深度，默认 200")
    ap.add_argument("--out", default="", help="结果写入 JSON 文件")
    args = ap.parse_args()

    rclpy.init()
    probe = rclpy.create_node("skylark_dds_probe")
    # 话题发现需要一点时间，否则会漏掉尚未被发现的发布端
    deadline = time.time() + 8
    found: dict[str, str] = {}
    while time.time() < deadline:
        for topic, types in probe.get_topic_names_and_types():
            if types and (topic in args.topics if args.topics else topic.startswith(args.prefix)):
                found[topic] = types[0]
        if found and time.time() > deadline - 5:
            break
        time.sleep(0.5)
    probe.destroy_node()

    if not found:
        print(f"没发现任何匹配话题（prefix={args.prefix}）。SITL 起了吗？", file=sys.stderr)
        rclpy.shutdown()
        return 1

    topics = sorted(found.items())
    print(f"发现 {len(topics)} 个话题，采集 {args.duration:.0f}s ...")
    rtf_before = gazebo_rtf()

    node = Collector(topics, args.depth)
    for topic, why in node.skipped:
        print(f"  跳过 {topic}（类型导入失败 {why}）", file=sys.stderr)

    t_start = time.time()
    while time.time() - t_start < args.duration:
        rclpy.spin_once(node, timeout_sec=0.1)
    wall = time.time() - t_start
    rtf_after = gazebo_rtf()

    results = []
    for topic, type_name in topics:
        stamps = node.stamps[topic]
        sizes = node.sizes[topic]
        arrivals = node.arrivals[topic]
        n = len(sizes)
        rate, diag = trimmed_rate_hz(stamps)
        arrival_hz = (len(arrivals) - 1) / (arrivals[-1] - arrivals[0]) \
            if len(arrivals) > 1 and arrivals[-1] > arrivals[0] else None
        # 一致性自检：时间戳推出的频率 vs 墙钟到达频率。
        # 差得多说明订阅端在丢包或积压，这条测量要单独重测。
        consistent = None
        if rate and arrival_hz:
            consistent = abs(arrival_hz - rate) / rate < 0.15
        results.append({
            "topic": topic,
            "type": type_name,
            "n_msgs": n,
            "size_bytes_mean": round(statistics.fmean(sizes), 1) if sizes else None,
            "size_bytes_min": min(sizes) if sizes else None,
            "size_bytes_max": max(sizes) if sizes else None,
            "rate_hz": round(rate, 3) if rate else None,
            "arrival_hz": round(arrival_hz, 3) if arrival_hz else None,
            "consistent": consistent,
            "bytes_per_s": round(statistics.fmean(sizes) * rate, 1) if (sizes and rate) else None,
            "diag": diag,
        })

    node.destroy_node()
    rclpy.shutdown()

    results.sort(key=lambda r: r["bytes_per_s"] or -1, reverse=True)
    total = sum(r["bytes_per_s"] or 0 for r in results)

    print()
    print(f"{'话题':<46}{'条数':>6}{'字节':>7}{'Hz':>9}{'B/s':>10}  自检")
    print("-" * 88)
    for r in results:
        flag = "" if r["consistent"] is None else ("ok" if r["consistent"] else "不一致")
        if r["rate_hz"] is None:
            flag = f"样本不足({r['n_msgs']})"
        print(f"{r['topic']:<46}{r['n_msgs']:>6}"
              f"{(r['size_bytes_mean'] or 0):>7.0f}"
              f"{(r['rate_hz'] or 0):>9.2f}"
              f"{(r['bytes_per_s'] or 0):>10,.0f}  {flag}")
    print("-" * 88)
    print(f"{'合计（仅计量到频率的话题，纯 CDR 载荷）':<46}{'':>6}{'':>7}{'':>9}{total:>10,.0f} B/s")

    n_bad = sum(1 for r in results if r["consistent"] is False)
    n_few = sum(1 for r in results if r["rate_hz"] is None)
    if n_bad:
        print(f"\n⚠ {n_bad} 个话题的时间戳频率与到达频率不一致（订阅端丢包/积压），"
              f"这些值请用 --topics 单独重测")
    if n_few:
        print(f"ℹ {n_few} 个话题样本不足 —— 多为事件驱动型（如 vehicle_command_ack "
              f"只在收到指令时发），静止仿真里本就不发或极低频")

    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": "PX4 SITL + Gazebo (gz_x500, headless), WSL2 Ubuntu 22.04",
        "px4_ref": px4_ref(),
        "duration_s": round(wall, 1),
        "gazebo_rtf_before": rtf_before,
        "gazebo_rtf_after": rtf_after,
        "note": ("载荷为 CDR 序列化字节数，不含 XRCE-DDS 帧头与串口起止位。"
                 "SITL 速率由仿真时钟决定，真机 IMU/EKF2 速率可能不同，S2 需重测。"),
        "total_payload_bytes_per_s": round(total, 1),
        "topics": results,
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\n已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
