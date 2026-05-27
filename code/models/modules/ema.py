"""
EMA: Efficient Multi-Scale Attention Module
================================================
ICASSP 2023, Ouyang et al.
arXiv:2305.13563

跨空间维度的高效多尺度注意力,比 CBAM 更新更快。
"""
from __future__ import annotations

import torch
import torch.nn as nn


class EMA(nn.Module):
    """EMA - Efficient Multi-Scale Attention."""

    def __init__(self, channels: int, factor: int = 8) -> None:
        super().__init__()
        self.groups = factor
        assert channels % factor == 0, "channels 必须能被 factor 整除"

        self.softmax = nn.Softmax(dim=-1)
        self.agp = nn.AdaptiveAvgPool2d(1)
        self.pool_h = nn.AdaptiveAvgPool2d((None, 1))
        self.pool_w = nn.AdaptiveAvgPool2d((1, None))
        gc = channels // factor
        self.gn = nn.GroupNorm(gc, gc)
        self.conv1x1 = nn.Conv2d(gc, gc, kernel_size=1, stride=1, padding=0)
        self.conv3x3 = nn.Conv2d(gc, gc, kernel_size=3, stride=1, padding=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, h, w = x.shape
        group_x = x.reshape(b * self.groups, -1, h, w)

        x_h = self.pool_h(group_x)
        x_w = self.pool_w(group_x).permute(0, 1, 3, 2)
        hw = self.conv1x1(torch.cat([x_h, x_w], dim=2))
        x_h, x_w = torch.split(hw, [h, w], dim=2)
        x1 = self.gn(group_x * x_h.sigmoid() * x_w.permute(0, 1, 3, 2).sigmoid())
        x2 = self.conv3x3(group_x)

        x11 = self.softmax(self.agp(x1).reshape(b * self.groups, -1, 1)
                           .permute(0, 2, 1))
        x12 = x2.reshape(b * self.groups, x2.shape[1], -1)
        x21 = self.softmax(self.agp(x2).reshape(b * self.groups, -1, 1)
                           .permute(0, 2, 1))
        x22 = x1.reshape(b * self.groups, x1.shape[1], -1)
        weights = (torch.matmul(x11, x12) + torch.matmul(x21, x22))
        weights = weights.reshape(b * self.groups, 1, h, w).sigmoid()
        return (group_x * weights).reshape(b, c, h, w)


if __name__ == "__main__":
    m = EMA(64)
    x = torch.randn(2, 64, 32, 32)
    y = m(x)
    print(f"EMA input  : {x.shape}")
    print(f"EMA output : {y.shape}")
    print(f"EMA params : {sum(p.numel() for p in m.parameters())}")
