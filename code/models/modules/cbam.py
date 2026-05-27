"""
CBAM: Convolutional Block Attention Module
==============================================
ECCV 2018, Woo et al.

通道注意力 + 空间注意力的双分支注意力模块。
插入到 YOLOv11 的 backbone 各个 C2f 模块之后即可。

用法(在 ultralytics 的网络 yaml 里):
    - [-1, 1, CBAM, [256]]
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class ChannelAttention(nn.Module):
    """通道注意力(避免与 ultralytics 自带模块同名冲突)."""

    def __init__(self, channels: int, reduction: int = 16) -> None:
        super().__init__()
        hidden = max(channels // reduction, 8)
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)
        self.mlp = nn.Sequential(
            nn.Conv2d(channels, hidden, 1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden, channels, 1, bias=False),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        avg = self.mlp(self.avg_pool(x))
        mx = self.mlp(self.max_pool(x))
        return torch.sigmoid(avg + mx)


class SpatialAttention(nn.Module):
    """空间注意力."""

    def __init__(self, kernel_size: int = 7) -> None:
        super().__init__()
        assert kernel_size in (3, 7), "kernel_size 必须是 3 或 7"
        padding = kernel_size // 2
        self.conv = nn.Conv2d(2, 1, kernel_size, padding=padding, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        avg = torch.mean(x, dim=1, keepdim=True)
        mx, _ = torch.max(x, dim=1, keepdim=True)
        feat = torch.cat([avg, mx], dim=1)
        return torch.sigmoid(self.conv(feat))


class CBAM(nn.Module):
    """CBAM = ChannelAttention -> SpatialAttention,残差直通."""

    def __init__(self, channels: int, reduction: int = 16,
                 spatial_kernel: int = 7) -> None:
        super().__init__()
        self.channel_attn = ChannelAttention(channels, reduction)
        self.spatial_attn = SpatialAttention(spatial_kernel)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x * self.channel_attn(x)
        x = x * self.spatial_attn(x)
        return x


if __name__ == "__main__":
    # 自测
    m = CBAM(64)
    x = torch.randn(2, 64, 32, 32)
    y = m(x)
    print(f"CBAM input  : {x.shape}")
    print(f"CBAM output : {y.shape}")
    print(f"CBAM params : {sum(p.numel() for p in m.parameters())}")
