"""Takeoff action 的命令行客户端。给集成测试与手工验证用。

退出码就是 result_code（0=OK），这样 shell 侧可以直接断言：
    ros2 run skylark_autopilot_iface takeoff_cli --altitude 5 || echo "失败码 $?"

也支持 --cancel-after 用来验证取消语义（取消后应保持悬停而不是降落）。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from skylark_flight_msgs.action import Takeoff

RESULT_NAMES = {
    Takeoff.Result.RESULT_OK: "OK",
    Takeoff.Result.RESULT_REJECTED_NOT_READY: "REJECTED_NOT_READY",
    Takeoff.Result.RESULT_REJECTED_ALREADY_FLYING: "REJECTED_ALREADY_FLYING",
    Takeoff.Result.RESULT_TIMEOUT: "TIMEOUT",
    Takeoff.Result.RESULT_ABORTED_BY_FAILSAFE: "ABORTED_BY_FAILSAFE",
    Takeoff.Result.RESULT_CANCELED: "CANCELED",
    Takeoff.Result.RESULT_AUTOPILOT_ERROR: "AUTOPILOT_ERROR",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="发一个 Takeoff goal")
    ap.add_argument("--altitude", type=float, default=5.0, help="目标高度 m")
    ap.add_argument("--climb-rate", type=float, default=1.5, help="上升率 m/s")
    ap.add_argument("--heading", type=float, default=-1.0, help="朝向 deg；<0 保持当前")
    ap.add_argument("--timeout", type=float, default=60.0, help="action 内部超时 s")
    ap.add_argument("--server", default="/skylark_autopilot_iface/takeoff")
    ap.add_argument("--cancel-after", type=float, default=0.0,
                    help=">0 则在该秒数后发取消，用于验证取消语义")
    ap.add_argument("--wait-server", type=float, default=15.0)
    args = ap.parse_args(argv)

    rclpy.init()
    node = Node("skylark_takeoff_cli")
    client = ActionClient(node, Takeoff, args.server)

    if not client.wait_for_server(timeout_sec=args.wait_server):
        print(f"等不到 action server: {args.server}", file=sys.stderr)
        node.destroy_node(); rclpy.shutdown()
        return 100

    goal = Takeoff.Goal()
    goal.altitude_agl_m = args.altitude
    goal.climb_rate_mps = args.climb_rate
    goal.heading_deg = args.heading
    goal.timeout_sec = args.timeout

    state: dict = {"result": None, "handle": None, "rejected": False}

    def on_feedback(fb) -> None:
        f = fb.feedback
        print(f"  反馈 t={f.elapsed_sec:5.1f}s  高度 {f.current_altitude_agl_m:6.2f} m  "
              f"进度 {f.progress * 100:5.1f}%", flush=True)

    print(f"发送 goal: 高度 {args.altitude} m，上升率 {args.climb_rate} m/s", flush=True)
    send_future = client.send_goal_async(goal, feedback_callback=on_feedback)

    def spin() -> None:
        rclpy.spin(node)

    t = threading.Thread(target=spin, daemon=True)
    t.start()

    deadline = time.time() + args.timeout + 30
    while not send_future.done() and time.time() < deadline:
        time.sleep(0.05)
    if not send_future.done():
        print("发送 goal 无响应", file=sys.stderr)
        rclpy.shutdown(); return 101

    handle = send_future.result()
    if not handle.accepted:
        print("goal 被 server 拒绝（结构性拒绝，无 result_code）", file=sys.stderr)
        rclpy.shutdown(); return 102
    print("goal 已被接受", flush=True)

    result_future = handle.get_result_async()

    if args.cancel_after > 0:
        def do_cancel() -> None:
            time.sleep(args.cancel_after)
            print(f"  === {args.cancel_after}s 到，发送取消 ===", flush=True)
            handle.cancel_goal_async()
        threading.Thread(target=do_cancel, daemon=True).start()

    while not result_future.done() and time.time() < deadline:
        time.sleep(0.05)
    if not result_future.done():
        print("等不到 result", file=sys.stderr)
        rclpy.shutdown(); return 103

    res = result_future.result().result
    name = RESULT_NAMES.get(res.result_code, f"未知({res.result_code})")
    print("")
    print(f"结果: {name}  success={res.success}")
    print(f"  最终高度 {res.final_altitude_agl_m:.2f} m   耗时 {res.elapsed_sec:.1f}s")
    print(f"  说明: {res.message}")

    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    return int(res.result_code)


if __name__ == "__main__":
    sys.exit(main())
