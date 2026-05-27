"""一次性脚本：统计 PVEL-AD train/val/test 的类别分布，用于修论文事实。"""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict

ROOT = Path(r"E:\Users\Administrator\Desktop\gp\graduation_project\code\data\processed\pvel_yolo\labels")
NAMES = ['crack','finger','black_core','thick_line','star_crack','corner',
         'fragment','scratch','horizontal_dislocation','vertical_dislocation',
         'printing_error','short_circuit']

count = defaultdict(int)
for split in ['train', 'val', 'test']:
    d = ROOT / split
    if not d.exists():
        continue
    for txt in d.glob('*.txt'):
        for line in txt.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            cls = int(parts[0])
            count[(split, cls)] += 1

print(f"{'class':<25} {'train':>7} {'val':>7} {'test':>7} {'total':>7}")
print('-' * 60)
totals = {'train': 0, 'val': 0, 'test': 0}
for i, name in enumerate(NAMES):
    tr = count[('train', i)]
    v = count[('val', i)]
    te = count[('test', i)]
    tot = tr + v + te
    totals['train'] += tr
    totals['val'] += v
    totals['test'] += te
    print(f"{name:<25} {tr:>7} {v:>7} {te:>7} {tot:>7}")

print('-' * 60)
print(f"{'TOTAL':<25} {totals['train']:>7} {totals['val']:>7} {totals['test']:>7} {sum(totals.values()):>7}")
print()

# 训练集 + 验证集（论文里 trainval 合集层面）
tv_count = {NAMES[i]: count[('train', i)] + count[('val', i)] for i in range(12)}
total_tv = sum(tv_count.values())
print(f"训练+验证集 box 总数: {total_tv}")
print(f"  最多: {max(tv_count.items(), key=lambda x: x[1])}")
print(f"  最少: {min((x for x in tv_count.items() if x[1] > 0), key=lambda x: x[1])}")
nonzero = [v for v in tv_count.values() if v > 0]
if nonzero:
    print(f"  长尾比例: {max(nonzero) / min(nonzero):.1f}x")

# 全集
full_count = {NAMES[i]: count[('train', i)] + count[('val', i)] + count[('test', i)] for i in range(12)}
total_full = sum(full_count.values())
print()
print(f"全集 (train+val+test) box 总数: {total_full}")
print(f"  最多: {max(full_count.items(), key=lambda x: x[1])}")
print(f"  最少: {min((x for x in full_count.items() if x[1] > 0), key=lambda x: x[1])}")
nonzero_f = [v for v in full_count.values() if v > 0]
if nonzero_f:
    print(f"  长尾比例: {max(nonzero_f) / min(nonzero_f):.1f}x")
