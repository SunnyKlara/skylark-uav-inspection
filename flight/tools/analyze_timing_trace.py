#!/usr/bin/env python3
"""离线分析 px4_link 落盘的时序 trace，回答一个问题：

    飞控判我们的 offboard setpoint「过期」时，那 1 秒容限是被谁吃掉的？

两个候选，结论互斥，所以值得单独写个脚本算清楚：
  (a) 我们填的 timestamp 本身就偏旧 —— 那是本地时钟换算的问题，改代码能修；
  (b) timestamp 是对的，但消息没能及时送进飞控的 uORB —— 那是传输/调度的问题，
      改我们的代码修不了，只能调 COM_OF_LOSS_T 或换传输配置。

做法：
  用 trace 里的 lp 行（飞控发来的位置消息：本机接收时刻 + 飞控时间戳）
  拟合出「飞控时钟随本机时间怎么走」，得到 px4_now(wall)。
  对每条 hb 行（我们发出的心跳：发出时刻 + 填进去的时间戳）算
      stamp_lag = px4_now(发出时刻) - 填进去的时间戳
  这就是**消息刚离开我们时**飞控会算出的陈旧度。飞控真正比较的是
      hrt_now(收到并处理时) - timestamp = stamp_lag + 传输与调度耗时
  所以 stamp_lag 的最大值直接对应候选 (a) 的份额，剩下的就是 (b)。

拟合刻意用**最小二乘直线**而不是两点：两点法会被单帧抖动带偏，
而我们要判断的量级只有几十毫秒到一秒，抖动不能忽略。

用法：
    python3 analyze_timing_trace.py <trace.csv> [--loss-t 1.0]
"""

from __future__ import annotations

import argparse
import csv
import sys


def fit_line(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """最小二乘 y = a*x + b，返回 (a, b)。"""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    a = sxy / sxx if sxx > 0 else 1.0
    return a, my - a * mx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--loss-t", type=float, default=1.0,
                    help="飞控的 COM_OF_LOSS_T，用来算余量（秒）")
    args = ap.parse_args()

    lp: list[tuple[float, int]] = []
    hb: list[tuple[float, int]] = []
    with open(args.trace, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rec = (float(row["wall_epoch_s"]), int(row["px4_ts_us"]))
            (lp if row["kind"] == "lp" else hb).append(rec)

    if len(lp) < 20 or not hb:
        print(f"样本不足：lp={len(lp)} hb={len(hb)}")
        return 2

    # 先查乱序，再谈结论。
    # 起因：第一版没查，trace 里混进了并发回调造成的乱序样本
    # （相邻两帧本机间隔 -2852 ms），于是"时钟跳变"这一项算出 2.87 s，
    # 差点把根因写成仿真保真度问题。乱序数据必须先被点出来。
    bad_wall = sum(1 for i in range(1, len(lp)) if lp[i][0] <= lp[i - 1][0])
    bad_ts = sum(1 for i in range(1, len(lp)) if lp[i][1] <= lp[i - 1][1])
    if bad_wall or bad_ts:
        print(f"⚠ trace 自身有乱序：本机时刻不单调 {bad_wall} 处，"
              f"PX4 时间戳不单调 {bad_ts} 处。")
        print("  这说明采集侧存在并发写竞态，下面的时钟结论**不可信** —— 先修采集。")
        print("")

    w0 = lp[0][0]
    xs = [w - w0 for w, _ in lp]
    ys = [ts / 1e6 for _, ts in lp]
    rate, _ = fit_line(xs, ys)

    # px4_now(wall) 用**相邻两帧线性插值**，不用全局拟合直线。
    #
    # 起因：仿真时钟会一次性往前蹦（实测单次 1.94 s，fp9）。全局直线会把这一下
    # 摊到整段上，于是每一条心跳都被算出几百毫秒的滞后，看起来像"我们的时间戳
    # 一直不准"，实际只有跳变那一瞬间不准。插值是局部精确的，能把责任分对。
    JUMP_THRESH_S = 0.3

    def bracket(wall: float) -> tuple[int, int]:
        lo, hi = 0, len(lp) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if lp[mid][0] <= wall:
                lo = mid
            else:
                hi = mid
        return lo, hi

    def px4_now_s(wall: float) -> tuple[float, bool]:
        """返回 (飞控时钟估计秒, 这一段里是否含跳变)。"""
        i, j = bracket(wall)
        wi, ti = lp[i][0], lp[i][1] / 1e6
        wj, tj = lp[j][0], lp[j][1] / 1e6
        dw, dt = wj - wi, tj - ti
        jumped = (dt - dw) > JUMP_THRESH_S
        if dw <= 0:
            return ti, jumped
        r = (wall - wi) / dw
        return ti + dt * max(0.0, min(r, 1.0)), jumped

    lags = []
    for w, ts in hb:
        est, jumped = px4_now_s(w)
        lags.append((w, est - ts / 1e6, jumped))
    calm = [(w, l) for w, l, j in lags if not j]
    noisy = [(w, l) for w, l, j in lags if j]

    span = xs[-1] - xs[0]
    print(f"trace: {args.trace}")
    print(f"样本: 入站位置 {len(lp)} 帧 / 心跳 {len(hb)} 条，跨度 {span:.1f} s")
    print("")
    print(f"飞控时钟平均速率 = {rate:.5f} × 本机时钟"
          f"（即快 {(rate - 1) * 100:.2f}%）")
    print("")
    budget = args.loss_t
    print("我们填的 timestamp 相对飞控当时时钟的滞后（stamp_lag，正=偏旧）：")
    if calm:
        worst_w, worst = max(calm, key=lambda t: t[1])
        print(f"  【无跳变区间，共 {len(calm)} 条】"
              f"最小 {min(l for _, l in calm) * 1000:+.1f} ms  "
              f"最大 {worst * 1000:+.1f} ms（wall={worst_w:.3f}）  "
              f"平均 {sum(l for _, l in calm) / len(calm) * 1000:+.1f} ms")
    else:
        worst = 0.0
    if noisy:
        nw, nl = max(noisy, key=lambda t: t[1])
        print(f"  【跨跳变区间，共 {len(noisy)} 条】最大 {nl * 1000:+.1f} ms"
              f"（wall={nw:.3f}）—— 这一段的滞后由时钟跳变造成，不是算法误差")
    print("")
    print(f"COM_OF_LOSS_T = {budget:.1f} s")
    if worst >= budget:
        print(f"  => 判定：**我们的 timestamp 在时钟平稳时就超了容限**"
              f"（{worst:.3f} s ≥ {budget:.1f} s）。这是本地时钟换算的问题，改代码能修。")
    else:
        print(f"  => 判定：时钟平稳时我们只吃掉 {worst / budget * 100:.1f}% 的容限"
              f"（{worst * 1000:.0f} ms / {budget * 1000:.0f} ms），发布侧无可归责。")

    # 心跳间隔。>1 s 的那些是**动作之间的间隙**（移交 AUTO_LOITER 后会停心跳），
    # 属于设计行为，不能和"发布卡住"混在一起统计 —— 混了会得出
    # "最大间隔 3.1 s"这种把人带偏的数字。
    gaps = [(hb[i][0] - hb[i - 1][0]) for i in range(1, len(hb))]
    in_action = [g for g in gaps if g < 1.0]
    idle = [g for g in gaps if g >= 1.0]
    if in_action:
        print("")
        print(f"心跳间隔（本机，剔除动作间隙）: 最大 {max(in_action) * 1000:.0f} ms，"
              f"共 {len(in_action)} 个间隔；动作间隙 {len(idle)} 段"
              + (f"（最长 {max(idle):.1f} s，停心跳期间）" if idle else ""))

    # 飞控时钟的**瞬时跳变**：相邻两帧位置消息里，飞控时钟比本机时钟多走了多少。
    # 这是整件事的关键量 —— lockstep 下仿真时钟不是匀速的，
    # 它会一次性往前蹦一大截。蹦的幅度只要超过 COM_OF_LOSS_T，
    # 那么**任何**由发送端填写的时间戳都会在那一瞬间被判过期，
    # 与我们怎么算时间戳无关。
    jumps = []
    for i in range(1, len(lp)):
        d_wall = lp[i][0] - lp[i - 1][0]
        d_px4 = (lp[i][1] - lp[i - 1][1]) / 1e6
        if d_wall <= 0 or d_px4 <= 0:
            continue          # 乱序样本，上面已单独报，别混进跳变统计
        jumps.append((d_px4 - d_wall, lp[i][0], d_wall, d_px4))
    if jumps:
        over, at, dw, dp = max(jumps, key=lambda t: t[0])
        print("")
        print("飞控时钟相对本机的瞬时超前（相邻位置帧之间，正=飞控多走）：")
        print(f"  最大 {over * 1000:+.0f} ms  （wall={at:.3f}，"
              f"该帧间隔 本机 {dw * 1000:.0f} ms / 飞控 {dp * 1000:.0f} ms）")
        big = sorted((j for j in jumps if j[0] > budget * 0.5),
                     key=lambda t: -t[0])
        print(f"  超过 COM_OF_LOSS_T 一半（{budget / 2:.2f} s）的跳变: {len(big)} 次")
        for over_i, at_i, dw_i, dp_i in big[:5]:
            print(f"    wall={at_i:.3f}  超前 {over_i * 1000:+.0f} ms"
                  f"（本机 {dw_i * 1000:.0f} ms / 飞控 {dp_i * 1000:.0f} ms）")
        if over >= budget:
            print(f"  => 判定：仿真时钟单次跳变 {over:.2f} s ≥ 容限 {budget:.1f} s，"
                  f"**这就够单独造成一次误判**。属仿真保真度问题，发送端无法规避。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
