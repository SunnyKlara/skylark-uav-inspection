#!/usr/bin/env python3
"""估算 PX4 uXRCE-DDS 在串口链路上的带宽占用。

背景
----
Pixhawk 6C 没有以太网口，机载电脑只能通过 TELEM2 串口（实用上限 921600 bps）
与飞控通信。串口带宽是硬约束，必须在设计阶段就算清楚，不能等飞起来丢包才发现。

本工具读取 PX4 固件里的 `dds_topics.yaml`（决定哪些 uORB 话题桥接到 ROS 2）
与 `px4_msgs` 的消息定义，估算每个话题的字节率与总占用，并与串口预算对比。

用法
----
    python dds_bandwidth.py \
        --dds-topics <PX4-Autopilot>/src/modules/uxrce_dds_client/dds_topics.yaml \
        --msg-dir    <px4_msgs>/msg \
        --baud 921600

    # 只看最占带宽的 15 个话题
    python dds_bandwidth.py ... --top 15

    # 假设某些话题被裁掉后重新算
    python dds_bandwidth.py ... --exclude sensor_combined vehicle_imu

精度声明
--------
这是**估算**，不是实测。已知偏差来源：
  1. 未计算 CDR 序列化的对齐填充（会低估，通常几个字节/消息）
  2. 未计算 XRCE-DDS 的帧头与会话开销（会低估，约 10-20 字节/消息）
  3. 变长数组按声明的最大长度计（会高估）
  4. 无 rate_limit 的发布话题速率未知，用 --default-rate 假设值
  5. px4_msgs 版本必须与固件版本一致，否则字段不匹配

真实占用请在联调时实测：
    # 机载电脑侧
    ros2 topic bw /fmu/out/vehicle_local_position
    # 飞控侧（MAVLink Shell）
    uxrce_dds_client status
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# ROS 2 / CDR 基本类型字节数
PRIMITIVE_SIZES: dict[str, int] = {
    "bool": 1, "byte": 1, "char": 1,
    "int8": 1, "uint8": 1,
    "int16": 2, "uint16": 2,
    "int32": 4, "uint32": 4,
    "int64": 8, "uint64": 8,
    "float32": 4, "float64": 8,
}
# 无界 string 的假设长度（4 字节长度前缀 + 内容）
ASSUMED_STRING_LEN = 16

TYPE_RE = re.compile(
    r"^(?P<base>[A-Za-z_][A-Za-z0-9_]*(?:(?:/|::)[A-Za-z_][A-Za-z0-9_]*)*)"
    r"(?P<bound><=\d+)?"
    r"(?P<array>\[(?P<n>\d+|<=\d+)?\])?$"
)


class MsgSizer:
    """递归计算 .msg 定义的序列化字节数（近似）。"""

    def __init__(self, msg_dir: Path) -> None:
        self.msg_dir = msg_dir
        self._cache: dict[str, int] = {}
        self._resolving: set[str] = set()
        self.unresolved: set[str] = set()

    @staticmethod
    def _short_name(type_name: str) -> str:
        """把类型名归一化为裸类型名。

        dds_topics.yaml 用 C++ 风格 'px4_msgs::msg::VehicleOdometry'，
        .msg 文件里用 ROS 风格 'px4_msgs/VehicleOdometry' 或裸名。
        两种分隔符都要处理。
        """
        return re.split(r"::|/", type_name)[-1]

    def size_of(self, type_name: str) -> int:
        short = self._short_name(type_name)
        if short in self._cache:
            return self._cache[short]
        if short in self._resolving:
            # 循环引用，PX4 消息里不应出现；保守返回 0 并记录
            self.unresolved.add(short + " (circular)")
            return 0

        path = self.msg_dir / f"{short}.msg"
        if not path.is_file():
            self.unresolved.add(short)
            return 0

        self._resolving.add(short)
        total = 0
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            head = line.split(None, 1)
            if len(head) < 2:
                continue
            # 跳过常量（'名字 =' 紧跟类型之后）
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", head[1]):
                continue
            total += self._field_size(head[0])
        self._resolving.discard(short)
        self._cache[short] = total
        return total

    def _field_size(self, type_token: str) -> int:
        m = TYPE_RE.match(type_token)
        if not m:
            return 0
        base = m.group("base")
        short = self._short_name(base)

        if short == "string" or short == "wstring":
            elem = 4 + ASSUMED_STRING_LEN
        elif short in PRIMITIVE_SIZES:
            elem = PRIMITIVE_SIZES[short]
        else:
            elem = self.size_of(short)

        if m.group("array") is None:
            return elem
        n_raw = m.group("n")
        if n_raw is None:
            # 无界数组：4 字节长度前缀 + 假设 0 个元素（PX4 极少用）
            return 4
        n = int(n_raw.lstrip("<="))
        prefix = 4 if n_raw.startswith("<=") else 0
        return prefix + elem * n


def load_topics(dds_yaml: Path) -> list[dict]:
    data = yaml.safe_load(dds_yaml.read_text(encoding="utf-8-sig"))
    out: list[dict] = []
    for section in ("publications", "subscriptions", "subscriptions_multi"):
        for entry in data.get(section) or []:
            out.append({
                "section": section,
                "topic": entry.get("topic", "?"),
                "type": entry.get("type", "?"),
                "rate_limit": entry.get("rate_limit"),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="估算 PX4 uXRCE-DDS 串口带宽占用",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dds-topics", type=Path, required=True,
                    help="PX4-Autopilot/src/modules/uxrce_dds_client/dds_topics.yaml")
    ap.add_argument("--msg-dir", type=Path, required=True, help="px4_msgs/msg 目录")
    ap.add_argument("--baud", type=int, default=921600, help="串口波特率，默认 921600")
    ap.add_argument("--efficiency", type=float, default=0.65,
                    help="串口有效载荷率（扣除起止位/协议开销），默认 0.65")
    ap.add_argument("--default-rate", type=float, default=10.0,
                    help="未声明 rate_limit 的话题假设速率 Hz，默认 10")
    ap.add_argument("--overhead-bytes", type=int, default=16,
                    help="每条消息的 XRCE-DDS 帧开销字节，默认 16")
    ap.add_argument("--top", type=int, default=0, help="只显示占用最高的 N 个话题")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="排除的话题名片段（模拟裁剪 dds_topics.yaml 后的效果）")
    ap.add_argument("--publications-only", action="store_true",
                    help="只算下行（飞控 -> 机载电脑），通常是带宽瓶颈方向")
    args = ap.parse_args()

    if not args.dds_topics.is_file():
        print(f"错误: 找不到 {args.dds_topics}", file=sys.stderr)
        return 2
    if not args.msg_dir.is_dir():
        print(f"错误: 找不到 {args.msg_dir}", file=sys.stderr)
        return 2

    sizer = MsgSizer(args.msg_dir)
    topics = load_topics(args.dds_topics)

    rows = []
    for t in topics:
        if args.publications_only and t["section"] != "publications":
            continue
        if any(x in t["topic"] for x in args.exclude):
            continue
        size = sizer.size_of(t["type"])
        rate = t["rate_limit"] if t["rate_limit"] is not None else args.default_rate
        rate_assumed = t["rate_limit"] is None
        bps = (size + args.overhead_bytes) * rate
        rows.append({
            "topic": t["topic"], "section": t["section"], "size": size,
            "rate": rate, "assumed": rate_assumed, "bytes_per_s": bps,
        })

    rows.sort(key=lambda r: r["bytes_per_s"], reverse=True)
    total_bps = sum(r["bytes_per_s"] for r in rows)

    budget_bytes_per_s = args.baud / 10.0 * args.efficiency

    print("=" * 84)
    print("PX4 uXRCE-DDS 串口带宽估算")
    print("=" * 84)
    print(f"dds_topics.yaml : {args.dds_topics}")
    print(f"px4_msgs/msg    : {args.msg_dir}")
    print(f"波特率          : {args.baud} bps")
    print(f"有效载荷率      : {args.efficiency:.0%}")
    print(f"可用预算        : {budget_bytes_per_s:,.0f} B/s")
    print(f"每消息帧开销    : {args.overhead_bytes} B")
    print(f"默认速率假设    : {args.default_rate} Hz（用于未声明 rate_limit 的话题）")
    if args.exclude:
        print(f"已排除          : {', '.join(args.exclude)}")
    print()

    shown = rows[:args.top] if args.top > 0 else rows
    print(f"{'话题':<48} {'字节':>6} {'Hz':>7} {'B/s':>10}  备注")
    print("-" * 84)
    for r in shown:
        note = []
        if r["assumed"]:
            note.append("速率为假设值")
        if r["size"] == 0:
            note.append("消息定义未解析")
        print(f"{r['topic']:<48} {r['size']:>6} {r['rate']:>7.1f} {r['bytes_per_s']:>10,.0f}"
              f"  {'; '.join(note)}")
    if args.top > 0 and len(rows) > args.top:
        print(f"... 另有 {len(rows) - args.top} 个话题未显示")

    print("-" * 84)
    pct = total_bps / budget_bytes_per_s * 100 if budget_bytes_per_s else float("inf")
    print(f"{'合计':<48} {'':>6} {'':>7} {total_bps:>10,.0f}  占预算 {pct:.1f}%")
    print()

    if sizer.unresolved:
        print(f"⚠ {len(sizer.unresolved)} 个消息类型未能解析（可能是 px4_msgs 版本与固件不一致）:")
        for name in sorted(sizer.unresolved)[:10]:
            print(f"    {name}")
        if len(sizer.unresolved) > 10:
            print(f"    ... 另有 {len(sizer.unresolved) - 10} 个")
        print()

    if pct > 100:
        print(f"❌ 超出串口预算 {pct - 100:.1f}%。必须裁剪 dds_topics.yaml：")
        print("   1. 删除用不到的话题")
        print("   2. 给保留的话题加 rate_limit（例如 sensor_combined 从默认降到 10 Hz）")
        print("   3. 用 --exclude 反复试算，找到可行组合")
    elif pct > 70:
        print(f"⚠ 占用 {pct:.1f}%，余量偏少。突发流量或重传会导致丢包，建议裁剪到 70% 以下。")
    else:
        print(f"✅ 占用 {pct:.1f}%，余量充足。")

    print()
    print("提醒: 本结果是估算。联调时用 `ros2 topic bw <topic>` 与 "
          "`uxrce_dds_client status` 实测校准。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
