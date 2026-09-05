"""revisit_policy.py 的单测。不需要 ROS。

    cd flight/ros2_ws/src/skylark_inspection_mode && python3 -m pytest test -q

这些规则是**安全边界**：夹紧错了飞机会飞到不该去的高度或位置。
所以它们必须能在秒级反复验，而不是只能在一次 5 分钟的 SITL 里碰运气验到。
断言里的数值来自 INSPECTION_MODE_DESIGN.md §5 的表格。
"""

from __future__ import annotations

import pytest

from skylark_inspection_mode.revisit_policy import (
    DEFAULT_MAX_BURST,
    DEFAULT_MAX_HOVER_SEC,
    DEFAULT_MAX_OFFSET_M,
    DEFAULT_MIN_AGL_M,
    UnsafeRequest,
    clamp_revisit,
    onstation,
    rate_limited,
)


def _clamp(**kw):
    args = dict(requested_agl_m=8.0, requested_hover_sec=4.0,
                requested_burst=5, offset_m=0.0)
    args.update(kw)
    return clamp_revisit(**args)


# ---------------------------------------------------------------- 夹紧

def test_defaults_match_design_table():
    """常量被改了要立刻红 —— 它们是安全边界，不是随手填的默认值。"""
    assert DEFAULT_MIN_AGL_M == 3.0
    assert DEFAULT_MAX_HOVER_SEC == 30.0
    assert DEFAULT_MAX_BURST == 20
    assert DEFAULT_MAX_OFFSET_M == 50.0


def test_reasonable_request_passes_untouched():
    c = _clamp()
    assert (c.agl_m, c.hover_sec, c.capture_burst) == (8.0, 4.0, 5)
    assert not c.was_clamped, "没越界就不该留夹紧记录"


def test_low_altitude_is_raised_to_floor():
    c = _clamp(requested_agl_m=0.5)
    assert c.agl_m == DEFAULT_MIN_AGL_M
    assert any("安全下限" in n for n in c.notes)


def test_hover_and_burst_are_capped():
    c = _clamp(requested_hover_sec=300.0, requested_burst=999)
    assert c.hover_sec == DEFAULT_MAX_HOVER_SEC
    assert c.capture_burst == DEFAULT_MAX_BURST
    assert len(c.notes) == 2


@pytest.mark.parametrize("hover,burst", [(-1.0, 5), (4.0, -3)])
def test_negative_values_become_zero(hover, burst):
    c = _clamp(requested_hover_sec=hover, requested_burst=burst)
    assert c.hover_sec >= 0.0 and c.capture_burst >= 0
    assert c.was_clamped


def test_far_target_is_rejected_not_clamped():
    """偏移超限必须**拒**，不能夹紧。

    这一条是刻意偏离设计文档 §5 表格里写的"夹紧"。理由在同一张表的依据列：
    复拍是就近降高。把 60 m 夹到 50 m 等于飞到一个调用方**没要求**的位置
    去复拍，然后回报 success —— 调用方会拿着错位置的图像下结论，
    比直接拒更糟。夹紧只适用于"同一件事做得更保守"，不适用于"换个地方做"。
    """
    with pytest.raises(UnsafeRequest) as e:
        _clamp(offset_m=60.0)
    assert "偏移上限" in str(e.value)
    # 边界上不能拒
    assert _clamp(offset_m=DEFAULT_MAX_OFFSET_M).offset_m == DEFAULT_MAX_OFFSET_M


def test_nan_is_rejected():
    with pytest.raises(UnsafeRequest):
        _clamp(requested_agl_m=float("nan"))
    with pytest.raises(UnsafeRequest):
        _clamp(offset_m=float("inf"))


# ---------------------------------------------------------------- 频率限制

def test_no_history_never_limited():
    limited, _ = rate_limited(None, 1000.0, 0.0, 0.0)
    assert not limited


def test_same_spot_soon_is_limited():
    limited, why = rate_limited((10.0, 10.0, 1000.0), 1010.0, 11.0, 11.0)
    assert limited
    assert "复拍过" in why


def test_same_spot_later_is_allowed():
    """时间够久就放行 —— 缺陷可能真的需要再看一次。"""
    limited, _ = rate_limited((10.0, 10.0, 1000.0), 1040.0, 11.0, 11.0)
    assert not limited


def test_nearby_but_distinct_defect_is_allowed():
    """相邻的**另一个**缺陷不能被误拒。

    这是为什么判据用"距离 + 时间"而不是全局冷却：
    全局冷却会把巡检最不该漏的情况（同一片区域连着两个真实缺陷）拒掉。
    """
    limited, _ = rate_limited((10.0, 10.0, 1000.0), 1005.0, 20.0, 10.0)
    assert not limited


@pytest.mark.parametrize("dt,dist,expect", [
    (29.9, 4.9, True),      # 都在窗口内 -> 拒
    (30.1, 4.9, False),     # 时间出窗
    (29.9, 5.1, False),     # 距离出窗
])
def test_rate_limit_boundaries(dt, dist, expect):
    limited, _ = rate_limited((0.0, 0.0, 1000.0), 1000.0 + dt, dist, 0.0)
    assert limited is expect


# ---------------------------------------------------------------- 到位判据

def test_onstation_needs_both_altitude_and_speed():
    kw = dict(target_agl_m=8.0, alt_tol_m=0.5, max_speed_mps=0.3)
    assert onstation(agl_m=8.2, speed_mps=0.1, **kw)
    assert not onstation(agl_m=8.2, speed_mps=0.9, **kw), "还在飘就不算到位"
    assert not onstation(agl_m=6.0, speed_mps=0.1, **kw), "高度没到就不算到位"
    # 边界：正好等于容差与速度上限都算到位
    assert onstation(agl_m=8.5, speed_mps=0.3, **kw)
