"""
BiFPN: Bi-directional Feature Pyramid Network
=================================================
EfficientDet, CVPR 2020, Tan et al.

加权双向特征融合,可替换 YOLO 的 PANet neck。
我们这里实现一个简化版 BiFPN block,可在 yaml 里直接挂在 neck 中。
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class BiFPNBlock(nn.Module):
    """带可学习权重的双向特征融合 block.

    输入 N 个分支(同 channel),输出对应数量的融合特征。
    每个融合点用可学习正权重做加权平均。
    """

    def __init__(self, channels: int, n_inputs: int = 2,
                 epsilon: float = 1e-4) -> None:
        super().__init__()
        self.n = n_inputs
        self.eps = epsilon
        self.weights = nn.Parameter(torch.ones(n_inputs, dtype=torch.float32),
                                    requires_grad=True)
        self.relu = nn.ReLU(inplace=False)
        self.conv = nn.Sequential(
            nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.SiLU(inplace=True),
        )

    def forward(self, inputs: list[torch.Tensor]) -> torch.Tensor:
        assert len(inputs) == self.n, f"BiFPNBlock 输入数 {len(inputs)} != {self.n}"

        # 把所有输入对齐到第一个的空间尺寸
        target_size = inputs[0].shape[-2:]
        aligned = [
            x if x.shape[-2:] == target_size
            else F.interpolate(x, size=target_size, mode="nearest")
            for x in inputs
        ]

        w = self.relu(self.weights)
        w = w / (w.sum() + self.eps)

        fused = sum(w[i] * aligned[i] for i in range(self.n))
        return self.conv(fused)


class BiFPNAdd(nn.Module):
    """ultralytics yaml 友好的 wrapper:接收上层 list 输出,做加权融合."""

    def __init__(self, channels: int, n_inputs: int = 2) -> None:
        super().__init__()
        self.block = BiFPNBlock(channels, n_inputs)

    def forward(self, x):
        if isinstance(x, (list, tuple)):
            return self.block(list(x))
        return self.block([x])


if __name__ == "__main__":
    m = BiFPNAdd(64, n_inputs=2)
    a = torch.randn(2, 64, 16, 16)
    b = torch.randn(2, 64, 32, 32)
    y = m([a, b])
    print(f"BiFPN output: {y.shape}")
    print(f"BiFPN params: {sum(p.numel() for p in m.parameters())}")
