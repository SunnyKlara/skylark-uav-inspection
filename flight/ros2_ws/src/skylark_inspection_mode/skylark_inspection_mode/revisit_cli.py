"""给 Revisit 发 goal 的测试客户端。理由与 sweep_cli 相同：

输出 key=value 便于 shell 断言，退出码即 result_code，取消走显式
cancel_goal_async（不指望 `ros2 action send_goal` 的信号处理 —— 实测那条路
在本项目的 action 上不可靠，见 sweep_cli 的说明）。

**两个延迟字段是论文的原始素材**，所以这里把它们单独打成
latency_goal_to_motion_ms / latency_goal_to_onstation_ms 两行，
好让实验脚本直接采集，不必解析人类可读的 message。

用法：
    ros2 run skylark_inspection_mode revisit_cli --agl 5 --hover 4 [--burst 5]
    ros2 run skylark_inspection_mode revisit_cli --target 47.3978 8.5457 --agl 6
"""

from __future__ import annotations

import argparse
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from skylark_flight_msgs.action import Revisit

RESULT_NAMES = {
    0: "OK", 1: "REJECTED_NOT_READY", 2: "REJECTED_UNSAFE",
    3: "REJECTED_RATE_LIMITED", 4: "TIMEOUT", 5: "ABORTED_BY_FAILSAFE",
    6: "ABORTED_LOW_BATTERY", 7: "CANCELED",
}
PHASE_NAMES = {0: "受理", 1: "转场", 2: "下降", 3: "悬停", 4: "连拍", 5: "返回"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="给 skylark_inspection_mode 发 Revisit")
    ap.add_argument("--ns", default="/skylark_inspection_mode")
    ap.add_argument("--target", nargs=2, type=float, default=None,
                    metavar=("LAT", "LON"),
                    help="指定复拍点；不给则用当前水平位置")
    ap.add_argument("--agl", type=float, default=8.0, help="请求的复拍高度（米）")
    ap.add_argument("--hover", type=float, default=4.0)
    ap.add_argument("--burst", type=int, default=5)
    ap.add_argument("--no-return", action="store_true",
                    help="完成后不回原位（扫掠续飞需要回，单独复拍可以不回）")
    ap.add_argument("--reason", default="test:manual")
    ap.add_argument("--severity", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--cancel-after", type=float, default=0.0)
    ap.add_argument("--wait-server", type=float, default=15.0)
    args = ap.parse_args(argv)

    rclpy.init()
    node = Node("skylark_revisit_cli")
    client = ActionClient(node, Revisit, f"{args.ns.rstrip('/')}/revisit")
    if not client.wait_for_server(timeout_sec=args.wait_server):
        print(f"动作服务器 {args.ns}/revisit 不在线", file=sys.stderr)
        rclpy.shutdown()
        return 100

    g = Revisit.Goal()
    if args.target is None:
        g.use_current_position = True
    else:
        g.use_current_position = False
        g.target_latitude_deg, g.target_longitude_deg = args.target
    g.descend_to_agl_m = args.agl
    g.hover_sec = args.hover
    g.capture_burst = args.burst
    g.return_to_origin = not args.no_return
    g.trigger_reason = args.reason
    g.trigger_severity = args.severity
    g.timeout_sec = args.timeout

    last_phase = [-1]

    def on_fb(msg) -> None:
        fb = msg.feedback
        if fb.phase != last_phase[0]:
            last_phase[0] = fb.phase
            print(f"  阶段 -> {PHASE_NAMES.get(fb.phase, fb.phase)}"
                  f"  t={fb.elapsed_sec:5.1f}s  高度 {fb.current_agl_m:5.2f} m",
                  flush=True)

    print(f"发送 Revisit -> {args.ns}/revisit（请求 AGL {args.agl} m）", flush=True)
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
    print("---- 结果 ----", flush=True)
    print(f"result_code={r.result_code}")
    print(f"result_name={RESULT_NAMES.get(r.result_code, '?')}")
    print(f"success={r.success}")
    print(f"actual_agl_m={r.actual_agl_m:.2f}")
    print(f"actual_hover_sec={r.actual_hover_sec:.2f}")
    print(f"images_captured={r.images_captured}")
    print(f"returned_to_origin={r.returned_to_origin}")
    # 论文原始素材：单独两行，实验脚本直接采集
    print(f"latency_goal_to_motion_ms={r.latency_goal_to_motion_ms}")
    print(f"latency_goal_to_onstation_ms={r.latency_goal_to_onstation_ms}")
    print(f"elapsed_sec={r.elapsed_sec:.2f}")
    print(f"message={r.message}")

    node.destroy_node()
    rclpy.shutdown()
    return int(r.result_code)


if __name__ == "__main__":
    sys.exit(main())
