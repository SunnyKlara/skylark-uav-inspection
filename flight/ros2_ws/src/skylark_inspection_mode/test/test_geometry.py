"""geometry.py 的单测。不需要 ROS，直接 pytest 跑。

    cd flight/ros2_ws/src/skylark_inspection_mode && python3 -m pytest test -q

断言里的数值都来自可追溯的来源，不是"跑一遍看输出是多少就写进去"：
- 幅宽那几个数抄自设计文档 §2 的表格，而那张表的视场来自
  PX4 v1.17.0 的 mono_cam/model.sdf（1.74 rad）
- 契约默认参数（15 m 高、6 m 行距、min_overlap 0.25）抄自 InspectSweep.action
"""

from __future__ import annotations

import math

import pytest

from skylark_inspection_mode.geometry import (
    MONO_CAM_HFOV_DEG,
    CoverageError,
    GeometryError,
    check_coverage,
    latlon_to_ned,
    max_row_spacing_m,
    ned_to_latlon,
    overlap_ratio,
    plan_sweep,
    swath_width_m,
)

# 测试场地参考点：PX4 SITL 默认起飞点（Zurich Irchel Park），
# 取自 PX4-Autopilot 的 PX4_HOME_LAT/LON 默认值
REF = (47.397742, 8.545594)
HFOV = MONO_CAM_HFOV_DEG


# ---------------------------------------------------------------- 覆盖率

def test_hfov_constant_matches_sdf():
    """常量必须还是 1.74 rad —— 它是整条覆盖率保证的根，被改了要立刻红。"""
    # 弧度值才是真值来源（SDF 里写的是 1.74 rad），度数只是它的换算结果。
    # 第一版这里的度数写的是 99.6949（记忆里的四舍五入），实测是 99.69466 —— 已改正。
    assert math.isclose(math.radians(MONO_CAM_HFOV_DEG), 1.74, abs_tol=1e-12)
    assert math.isclose(MONO_CAM_HFOV_DEG, 99.69466, abs_tol=1e-4)


@pytest.mark.parametrize("alt,expect", [
    (10.0, 23.71),
    (15.0, 35.56),      # 契约默认高度
    (20.0, 47.41),
    (30.0, 71.12),
])
def test_swath_matches_design_table(alt, expect):
    assert swath_width_m(alt, HFOV) == pytest.approx(expect, abs=0.01)


def test_overlap_at_contract_defaults():
    """契约默认 15 m / 6 m 下重叠率 83.1%，远超 min_overlap=0.25。

    这条同时是在固定文档里那句结论：覆盖率校验在当前配置下几乎不会触发。
    """
    swath, ov = check_coverage(15.0, 6.0, 0.25, HFOV)
    assert swath == pytest.approx(35.56, abs=0.01)
    assert ov == pytest.approx(0.831, abs=0.001)


def test_overlap_negative_when_spacing_exceeds_swath():
    """行距大于幅宽时重叠率必须是负数，不能被夹到 0。

    夹到 0 会把"刚好接上"和"漏了 10 米"混为一谈，而后者正是要拦的。
    """
    assert overlap_ratio(10.0, 4.0) == pytest.approx(-1.5)


def test_reject_narrow_fov_camera():
    """真机窄视场相机 + 按仿真经验填的行距 -> 必须拒。

    这是这道校验真正要防的错误之一（设计文档 §2）：
    65° 相机在 3 m 高时幅宽只有 3.82 m，行距还按 6 m 填就是漏拍。
    """
    with pytest.raises(CoverageError) as e:
        check_coverage(3.0, 6.0, 0.25, 65.0)
    assert "重叠" in str(e.value)


def test_max_row_spacing_is_exactly_on_the_boundary():
    """建议值必须刚好落在边界上：用它算出的重叠率等于 min_overlap。

    差一点点就会出现"照建议值填却被拒"，那种拒绝消息比不给建议更糟。
    """
    alt, min_ov = 15.0, 0.30
    s = max_row_spacing_m(alt, min_ov, HFOV)
    _, ov = check_coverage(alt, s, min_ov, HFOV)
    assert ov == pytest.approx(min_ov, abs=1e-9)
    # 再大一丝就必须拒
    with pytest.raises(CoverageError):
        check_coverage(alt, s * 1.001, min_ov, HFOV)


@pytest.mark.parametrize("alt,spacing,min_ov,hfov", [
    (0.0, 6.0, 0.25, HFOV),      # 高度为 0
    (-5.0, 6.0, 0.25, HFOV),     # 负高度
    (15.0, 0.0, 0.25, HFOV),     # 行距为 0
    (15.0, 6.0, 1.0, HFOV),      # min_overlap 越界
    (15.0, 6.0, -0.1, HFOV),
    (15.0, 6.0, 0.25, 0.0),      # 视场为 0
    (15.0, 6.0, 0.25, 180.0),    # 视场 180（tan 发散）
])
def test_bad_inputs_raise_geometry_error(alt, spacing, min_ov, hfov):
    with pytest.raises(GeometryError):
        check_coverage(alt, spacing, min_ov, hfov)


# ---------------------------------------------------------------- 经纬度换算

def test_latlon_ned_roundtrip():
    """正反变换必须严格互逆 —— 这是选用参考点纬度（而非目标点纬度）算
    经度缩放的直接理由。"""
    for dn, de in [(0.0, 0.0), (100.0, -50.0), (-320.5, 640.25)]:
        lat, lon = ned_to_latlon(dn, de, REF[0], REF[1])
        n2, e2 = latlon_to_ned(lat, lon, REF[0], REF[1])
        assert n2 == pytest.approx(dn, abs=1e-6)
        assert e2 == pytest.approx(de, abs=1e-6)


def test_latlon_scale_sanity():
    """纬度 1e-5 度约 1.11 m —— 用一个独立的量级判断挡住 cos 因子写反之类的错。"""
    n, e = latlon_to_ned(REF[0] + 1e-5, REF[1], REF[0], REF[1])
    assert n == pytest.approx(1.113, abs=0.01)
    assert e == pytest.approx(0.0, abs=1e-9)
    # 同样的经度差在瑞士（约 47.4°N）对应更短的东向距离：cos(47.4°) ≈ 0.677
    n, e = latlon_to_ned(REF[0], REF[1] + 1e-5, REF[0], REF[1])
    assert n == pytest.approx(0.0, abs=1e-9)
    assert e == pytest.approx(1.113 * math.cos(math.radians(REF[0])), abs=0.01)


# ---------------------------------------------------------------- 航线生成

def _rect(north_m: float, east_m: float):
    """以参考点为一角、边长 north_m x east_m 的矩形，返回两个对角点 (lat, lon)。"""
    a = ned_to_latlon(0.0, 0.0, REF[0], REF[1])
    b = ned_to_latlon(north_m, east_m, REF[0], REF[1])
    return a, b


def _plan(north_m=60.0, east_m=24.0, **kw):
    a, b = _rect(north_m, east_m)
    args = dict(heading_deg=0.0, altitude_agl_m=15.0, row_spacing_m=6.0,
                min_overlap=0.25, hfov_deg=HFOV)
    args.update(kw)
    return plan_sweep(a, b, REF, **args)


def test_row_count_covers_both_edges():
    """24 m 横向跨度 / 6 m 行距 -> 4 段 -> 5 行，首行贴一边、末行贴另一边。

    用 floor 会得到 4 行并漏掉末行边界，这条就是钉住这一点。
    """
    p = _plan(north_m=60.0, east_m=24.0)
    assert p.rows_total == 5
    assert len(p.waypoints_ned) == 10          # 每行两个端点
    easts = sorted({round(w[1], 6) for w in p.waypoints_ned})
    assert easts[0] == pytest.approx(0.0, abs=1e-6)
    assert easts[-1] == pytest.approx(24.0, abs=1e-6)


def test_rows_are_boustrophedon():
    """偶数行正向、奇数行反向。方向搞错的表现是每行之间多飞一整行长度，
    航程会接近翻倍 —— 所以顺带断言航程。"""
    p = _plan(north_m=60.0, east_m=24.0)
    for row in range(p.rows_total):
        start, end = p.waypoints_ned[2 * row], p.waypoints_ned[2 * row + 1]
        if row % 2 == 0:
            assert start[0] < end[0], f"第 {row} 行应正向（北向增大）"
        else:
            assert start[0] > end[0], f"第 {row} 行应反向"
    # 5 行 x 60 m 行长 + 4 次转行 x 6 m = 324 m
    assert p.path_length_m == pytest.approx(5 * 60.0 + 4 * 6.0, abs=1e-6)


def test_altitude_sign_is_ned_down():
    p = _plan(altitude_agl_m=12.0)
    assert all(w[2] == pytest.approx(-12.0) for w in p.waypoints_ned)


def test_heading_90_makes_rows_run_east():
    """heading=90（正东）时每行应沿东向延伸，行与行之间沿北向错开。

    航空角与数学极角的旋向相反，这条挡的就是旋转矩阵写反。
    """
    p = _plan(north_m=24.0, east_m=60.0, heading_deg=90.0)
    start, end = p.waypoints_ned[0], p.waypoints_ned[1]
    assert abs(end[1] - start[1]) == pytest.approx(60.0, abs=1e-6)   # 东向跨 60
    assert abs(end[0] - start[0]) == pytest.approx(0.0, abs=1e-6)    # 北向不动
    assert p.rows_total == 5


def test_resume_closure_relation():
    """契约的闭合关系：resume_from_row = last_completed_row + 1 必须无缝接上。

    具体断言：从第 k 行续飞得到的航点，恰好等于完整航线去掉前 k 行的尾巴；
    且 rows_total 仍是完整行数（否则 last_completed_row 的编号会错位）。
    这条是设计文档 §3 点名要单测的。
    """
    full = _plan(north_m=60.0, east_m=24.0)
    for k in range(full.rows_total):
        part = _plan(north_m=60.0, east_m=24.0, resume_from_row=k)
        assert part.rows_total == full.rows_total
        assert part.waypoints_ned == full.waypoints_ned[2 * k:], \
            f"从第 {k} 行续飞的航点与完整航线的尾巴不一致"


def test_resume_keeps_serpentine_phase():
    """从**奇数**行续飞时，该行仍必须是反向的。

    按"切完之后的位置"判奇偶是个很自然的写法，但那样蛇形相位会翻，
    接缝处白飞一整行。单独拎出来断言，别指望上一条能顺带覆盖到。
    """
    part = _plan(resume_from_row=1)
    start, end = part.waypoints_ned[0], part.waypoints_ned[1]
    assert start[0] > end[0], "第 1 行（奇数）续飞时应保持反向"


def test_area_and_row_length():
    p = _plan(north_m=60.0, east_m=24.0)
    assert p.row_length_m == pytest.approx(60.0, abs=1e-6)
    assert p.area_m2 == pytest.approx(60.0 * 24.0, rel=1e-9)


def test_last_row_clamped_inside_area():
    """横向跨度不是行距整数倍时，末行必须夹在边界上，不能飞到区域外。"""
    p = _plan(north_m=60.0, east_m=20.0)     # 20 / 6 -> 4 段 -> 5 行
    assert p.rows_total == 5
    assert max(w[1] for w in p.waypoints_ned) == pytest.approx(20.0, abs=1e-6)


# ---------------------------------------------------------------- 几何拒绝

def test_reject_degenerate_area():
    a, b = _rect(60.0, 0.05)
    with pytest.raises(GeometryError) as e:
        plan_sweep(a, b, REF, heading_deg=0.0, altitude_agl_m=15.0,
                   row_spacing_m=6.0, min_overlap=0.25, hfov_deg=HFOV)
    assert "退化" in str(e.value)


def test_reject_oversized_area():
    """对角线 > 1000 m -> 疑似坐标或单位传错（与 Orbit 的 MAX_CENTER_DIST_M 同源思路）。"""
    a, b = _rect(900.0, 900.0)
    with pytest.raises(GeometryError) as e:
        plan_sweep(a, b, REF, heading_deg=0.0, altitude_agl_m=15.0,
                   row_spacing_m=6.0, min_overlap=0.25, hfov_deg=HFOV)
    assert "对角线" in str(e.value)


def test_reject_area_too_narrow_for_two_rows():
    """横向跨度不足 2 x 行距 -> 排不下两行。

    注意判据落在**横向**跨度上：行方向短只是每行短，不影响能不能扫。
    """
    a, b = _rect(60.0, 8.0)     # 8 < 2*6
    with pytest.raises(GeometryError) as e:
        plan_sweep(a, b, REF, heading_deg=0.0, altitude_agl_m=15.0,
                   row_spacing_m=6.0, min_overlap=0.25, hfov_deg=HFOV)
    assert "排不下" in str(e.value)


def test_short_rows_are_allowed():
    """反过来：行方向只有 8 m、横向 24 m 的窄长条应当**接受**。"""
    p = _plan(north_m=8.0, east_m=24.0)
    assert p.rows_total == 5
    assert p.row_length_m == pytest.approx(8.0, abs=1e-6)


@pytest.mark.parametrize("k", [-1, 99])
def test_reject_bad_resume_index(k):
    with pytest.raises(GeometryError):
        _plan(resume_from_row=k)


def test_coverage_rejection_beats_row_layout():
    """区域合法但覆盖率不达标时，抛的必须是 CoverageError（-> RESULT_REJECTED_COVERAGE），
    不能被几何检查抢先报成 BAD_GEOMETRY —— 两个结果码对调用方含义完全不同。"""
    a, b = _rect(60.0, 24.0)
    with pytest.raises(CoverageError):
        plan_sweep(a, b, REF, heading_deg=0.0, altitude_agl_m=2.0,
                   row_spacing_m=6.0, min_overlap=0.25, hfov_deg=HFOV)
