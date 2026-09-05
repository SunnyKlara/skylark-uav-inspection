"""takeoff / land / orbit 三个 action 的通用命令行客户端。

退出码 = result_code（0=OK），这样 shell 侧可以直接断言：
    ros2 run skylark_autopilot_iface action_cli takeoff --altitude 5
    ros2 run skylark_autopilot_iface action_cli orbit --radius 8 --revolutions 1
    ros2 run skylark_autopilot_iface action_cli land --mode 1

--cancel-after 用于验证取消语义（三个动作的取消后行为各不相同，见各自契约）。

单独做这个客户端而不是用 `ros2 action send_goal`：后者不方便按 result_code
给退出码，集成测试就只能去 grep 文本输出，那种断言很脆。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from skylark_flight_msgs.action import Land, Orbit, Takeoff

RESULT_NAMES = {
    "takeoff": {0: "OK", 1: "REJECTED_NOT_READY", 2: "REJECTED_ALREADY_FLYING",
                3: "TIMEOUT", 4: "ABORTED_BY_FAILSAFE", 5: "CANCELED",
                6: "AUTOPILOT_ERROR"},
    "land": {0: "OK", 1: "REJECTED_NOT_FLYING", 2: "TIMEOUT", 3: "CANCELED",
             4: "AUTOPILOT_ERROR"},
    "orbit": {0: "OK", 1: "REJECTED_NOT_READY", 2: "REJECTED_BAD_GEOMETRY",
              3: "TIMEOUT", 4: "ABORTED_BY_FAILSAFE", 5: "CANCELED"},
}


def build_goal(args):
    if args.action == "takeoff":
        g = Takeoff.Goal()
        g.altitude_agl_m = args.altitude
        g.climb_rate_mps = args.climb_rate
        g.heading_deg = args.heading
        g.timeout_sec = args.timeout
        return Takeoff, g
    if args.action == "land":
        g = Land.Goal()
        g.mode = args.mode
        g.transit_altitude_agl_m = args.transit_altitude
        g.descent_rate_mps = args.descent_rate
        g.timeout_sec = args.timeout
        return Land, g
    g = Orbit.Goal()
    g.use_global_center = args.use_global_center
    g.center_latitude_deg = args.center_lat
    g.center_longitude_deg = args.center_lon
    g.center_north_m = args.center_north
    g.center_east_m = args.center_east
    g.altitude_agl_m = args.altitude
    g.radius_m = args.radius
    g.speed_mps = args.speed
    g.yaw_mode = args.yaw_mode
    g.clockwise = not args.counter_clockwise
    g.revolutions = args.revolutions
    g.timeout_sec = args.timeout
    return Orbit, g


def format_feedback(action: str, f) -> str:
    if action == "takeoff":
        return (f"t={f.elapsed_sec:5.1f}s  高度 {f.current_altitude_agl_m:6.2f} m  "
                f"进度 {f.progress * 100:5.1f}%")
    if action == "land":
        phase = {0: "返航", 1: "下降", 2: "触地"}.get(f.phase, str(f.phase))
        return (f"t={f.elapsed_sec:5.1f}s  阶段 {phase}  "
                f"高度 {f.current_altitude_agl_m:6.2f} m  "
                f"水平距 {f.distance_to_target_m:6.1f} m")
    return (f"t={f.elapsed_sec:5.1f}s  {f.revolutions_completed:5.2f} 圈  "
            f"方位 {f.bearing_deg:7.1f}°  半径误差 {f.radius_error_m:+6.2f} m")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="给 skylark_autopilot_iface 发 action goal")
    ap.add_argument("action", choices=["takeoff", "land", "orbit"])
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--cancel-after", type=float, default=0.0)
    ap.add_argument("--wait-server", type=float, default=15.0)
    ap.add_argument("--ns", default="/skylark_autopilot_iface")
    # takeoff / orbit 共用
    ap.add_argument("--altitude", type=float, default=5.0)
    ap.add_argument("--climb-rate", type=float, default=1.5)
    ap.add_argument("--heading", type=float, default=-1.0)
    # land
    ap.add_argument("--mode", type=int, default=0, help="0=返航后降落 1=原地降落")
    ap.add_argument("--transit-altitude", type=float, default=30.0)
    ap.add_argument("--descent-rate", type=float, default=0.8)
    # orbit
    ap.add_argument("--use-global-center", action="store_true")
    ap.add_argument("--center-lat", type=float, default=0.0)
    ap.add_argument("--center-lon", type=float, default=0.0)
    ap.add_argument("--center-north", type=float, default=0.0)
    ap.add_argument("--center-east", type=float, default=0.0)
    ap.add_argument("--radius", type=float, default=15.0)
    ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--yaw-mode", type=int, default=0,
                    help="0=朝圆心 1=沿切向 2=保持当前")
    ap.add_argument("--counter-clockwise", action="store_true")
    ap.add_argument("--revolutions", type=float, default=1.0)
    args = ap.parse_args(argv)

    action_type, goal = build_goal(args)
    server = f"{args.ns}/{args.action}"

    rclpy.init()
    node = Node(f"skylark_{args.action}_cli")
    client = ActionClient(node, action_type, server)
    if not client.wait_for_server(timeout_sec=args.wait_server):
        print(f"等不到 action server: {server}", file=sys.stderr)
        node.destroy_node(); rclpy.shutdown(); return 100

    def on_feedback(fb) -> None:
        print("  反馈 " + format_feedback(args.action, fb.feedback), flush=True)

    print(f"发送 {args.action} goal -> {server}", flush=True)
    send_future = client.send_goal_async(goal, feedback_callback=on_feedback)
    threading.Thread(target=lambda: rclpy.spin(node), daemon=True).start()

    deadline = time.time() + args.timeout + 60
    while not send_future.done() and time.time() < deadline:
        time.sleep(0.05)
    if not send_future.done():
        print("发送 goal 无响应", file=sys.stderr); rclpy.shutdown(); return 101

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
        print("等不到 result", file=sys.stderr); rclpy.shutdown(); return 103

    res = result_future.result().result
    name = RESULT_NAMES[args.action].get(res.result_code, f"未知({res.result_code})")
    print("")
    print(f"结果: {name}  success={res.success}  耗时 {res.elapsed_sec:.1f}s")
    if args.action == "takeoff":
        print(f"  最终高度 {res.final_altitude_agl_m:.2f} m")
    elif args.action == "land":
        print(f"  已上锁: {res.disarmed}")
    else:
        print(f"  完成圈数 {res.revolutions_completed:.2f}")
    print(f"  说明: {res.message}")

    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    return int(res.result_code)


if __name__ == "__main__":
    sys.exit(main())
