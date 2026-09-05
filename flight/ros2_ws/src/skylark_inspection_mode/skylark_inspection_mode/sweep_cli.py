"""给 InspectSweep 发 goal 的测试客户端。

单独做这个而不是用 `ros2 action send_goal`，有两个实测理由：

1. **取消不可靠**。集成测试里靠 `kill -INT` 让 `ros2 action send_goal` 转发取消，
   在 FollowPath 上能用，在 InspectSweep 上实测**完全没发出取消请求**
   （客户端日志里没有任何取消痕迹，服务端也没收到，扫掠一路跑完拿到 OK）。
   原因没深究 —— 因为不该把测试的关键路径压在 CLI 的信号处理细节上。
   这里用 `cancel_goal_async()` 显式取消，行为确定且可观测。
2. **输出可断言**。`send_goal -f` 打的是 YAML，而 5 Hz x 60 s 的 Feedback
   会刷出几百段 `rows_total: 5`，把结论埋掉；而且 shell 侧 grep YAML
   踩过两次坑（`result_code=` 写成等号抽不到值）。
   这里用 `key=value` 一行一个字段，退出码就是 result_code。

用法：
    ros2 run skylark_inspection_mode sweep_cli \
        --corner-a 47.397742 8.545594 --corner-b 47.398101 8.545913 \
        --altitude 15 --spacing 6 --speed 4 [--resume-from-row 2] \
        [--cancel-after 20] [--timeout 240]
"""

from __future__ import annotations

import argparse
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from skylark_flight_msgs.action import InspectSweep

RESULT_NAMES = {
    0: "OK", 1: "REJECTED_NOT_READY", 2: "REJECTED_BAD_GEOMETRY",
    3: "REJECTED_COVERAGE", 4: "TIMEOUT", 5: "ABORTED_BY_FAILSAFE",
    6: "ABORTED_LOW_BATTERY", 7: "CANCELED",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="给 skylark_inspection_mode 发 InspectSweep")
    ap.add_argument("--ns", default="/skylark_inspection_mode")
    ap.add_argument("--corner-a", nargs=2, type=float, required=True,
                    metavar=("LAT", "LON"))
    ap.add_argument("--corner-b", nargs=2, type=float, required=True,
                    metavar=("LAT", "LON"))
    ap.add_argument("--heading", type=float, default=0.0)
    ap.add_argument("--altitude", type=float, default=15.0)
    ap.add_argument("--speed", type=float, default=4.0)
    ap.add_argument("--spacing", type=float, default=6.0)
    ap.add_argument("--min-overlap", type=float, default=0.25)
    ap.add_argument("--hfov", type=float, default=0.0,
                    help="0 = 由服务端从配置读（契约语义）")
    ap.add_argument("--resume-from-row", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--cancel-after", type=float, default=0.0,
                    help="受理后多少秒发取消；0 = 不取消")
    ap.add_argument("--wait-server", type=float, default=15.0)
    ap.add_argument("--feedback-every", type=int, default=20,
                    help="每 N 条 Feedback 打一条，避免刷屏")
    args = ap.parse_args(argv)

    rclpy.init()
    node = Node("skylark_sweep_cli")
    client = ActionClient(node, InspectSweep, f"{args.ns.rstrip('/')}/inspect_sweep")
    if not client.wait_for_server(timeout_sec=args.wait_server):
        print(f"动作服务器 {args.ns}/inspect_sweep 不在线", file=sys.stderr)
        rclpy.shutdown()
        return 100

    g = InspectSweep.Goal()
    g.corner_a_latitude_deg, g.corner_a_longitude_deg = args.corner_a
    g.corner_b_latitude_deg, g.corner_b_longitude_deg = args.corner_b
    g.heading_deg = args.heading
    g.altitude_agl_m = args.altitude
    g.speed_mps = args.speed
    g.row_spacing_m = args.spacing
    g.min_overlap = args.min_overlap
    g.camera_hfov_deg = args.hfov
    g.resume_from_row = args.resume_from_row
    g.timeout_sec = args.timeout

    n_fb = [0]

    def on_fb(msg) -> None:
        n_fb[0] += 1
        fb = msg.feedback
        if n_fb[0] % max(args.feedback_every, 1) == 1:
            print(f"  反馈 t={fb.elapsed_sec:6.1f}s  行 {fb.current_row}/{fb.rows_total}"
                  f"  进度 {fb.progress * 100:5.1f}%"
                  f"  横向偏差 {fb.cross_track_error_m:5.2f} m"
                  f"  电量 {fb.battery_remaining * 100:3.0f}%", flush=True)

    print(f"发送 InspectSweep -> {args.ns}/inspect_sweep", flush=True)
    send_fut = client.send_goal_async(g, feedback_callback=on_fb)
    rclpy.spin_until_future_complete(node, send_fut, timeout_sec=20.0)
    if not send_fut.done():
        print("20s 内未收到受理响应", file=sys.stderr)
        rclpy.shutdown()
        return 101
    handle = send_fut.result()
    if not handle.accepted:
        print("goal 被拒绝（服务端可能正忙）", file=sys.stderr)
        rclpy.shutdown()
        return 102
    print("goal 已被接受", flush=True)

    res_fut = handle.get_result_async()
    t0 = time.time()
    cancel_sent = False
    # 上限给 goal 超时再加 90 s：服务端自己会超时并返回，
    # 客户端只需要一个兜底，别比服务端先放弃。
    hard_deadline = t0 + args.timeout + 90.0
    while not res_fut.done() and time.time() < hard_deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        if args.cancel_after > 0 and not cancel_sent \
                and time.time() - t0 >= args.cancel_after:
            print(f"  === {args.cancel_after:.0f}s 到，显式发送取消 ===", flush=True)
            handle.cancel_goal_async()
            cancel_sent = True
    if not res_fut.done():
        print("等结果超时（服务端没返回）", file=sys.stderr)
        rclpy.shutdown()
        return 103

    r = res_fut.result().result
    # key=value 一行一个：shell 侧断言不必解析 YAML
    print("---- 结果 ----", flush=True)
    print(f"result_code={r.result_code}")
    print(f"result_name={RESULT_NAMES.get(r.result_code, '?')}")
    print(f"success={r.success}")
    print(f"rows_total={r.rows_total}")
    print(f"rows_completed={r.rows_completed}")
    print(f"last_completed_row={r.last_completed_row}")
    print(f"area_covered_m2={r.area_covered_m2:.1f}")
    print(f"distance_flown_m={r.distance_flown_m:.1f}")
    print(f"revisits_triggered={r.revisits_triggered}")
    print(f"elapsed_sec={r.elapsed_sec:.1f}")
    print(f"message={r.message}")

    node.destroy_node()
    rclpy.shutdown()
    return int(r.result_code)


if __name__ == "__main__":
    sys.exit(main())
