"""
fill_paper.py
=============

把 ``runs/collected_metrics.json`` 中的真实数字回填到论文的两份骨架：

  - paper/tex/main.tex     (英文 IEEE TII 风格)
  - paper/tex/main_zh.tex  (中文版)
  - paper/04_experiments.md
  - paper/00_meta.md / 01_introduction.md / 03_method.md / 05_conclusion.md

设计要点：
  - 幂等：重复运行结果一样
  - 缺数据降级：找不到就保留原 \TBF{...} 并在末尾报告里列出
  - 行级匹配：用"行首前缀"识别 LaTeX 表行，替换整行；不动其他文本
  - 输出 ``runs/fill_report.md`` 的小报告

用法:
  python postprocess/fill_paper.py
  python postprocess/fill_paper.py --dry-run     # 只打印将做的改动，不写文件
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAPER_ROOT = PROJECT_ROOT.parent / "paper"      # graduation_project/paper
RUNS_ROOT = PROJECT_ROOT / "runs"
METRICS_FILE = RUNS_ROOT / "collected_metrics.json"
REPORT_FILE = RUNS_ROOT / "fill_report.md"

TEX_MAIN = PAPER_ROOT / "tex" / "main.tex"
TEX_ZH = PAPER_ROOT / "tex" / "main_zh.tex"
MD_EXP = PAPER_ROOT / "04_experiments.md"
MD_META = PAPER_ROOT / "00_meta.md"
MD_INTRO = PAPER_ROOT / "01_introduction.md"
MD_METHOD = PAPER_ROOT / "03_method.md"
MD_CONCL = PAPER_ROOT / "05_conclusion.md"


# ============================================================================
#  工具：格式化 + 安全获取
# ============================================================================
def fmt(v: float | None, prec: int = 3, default: str = r"\TBF{}") -> str:
    """数字格式化；None / 非数 -> 占位"""
    if v is None or (isinstance(v, float) and (v != v)):  # NaN
        return default
    try:
        return f"{float(v):.{prec}f}"
    except Exception:
        return default


def fmt_pct(v: float | None, prec: int = 2, default: str = r"\TBF{$\Delta$}") -> str:
    if v is None:
        return default
    try:
        return f"{float(v):.{prec}f}"
    except Exception:
        return default


def get(d: dict | None, *keys: str, default=None):
    if not d:
        return default
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def find_engine(rows: list[dict], substr: str) -> dict | None:
    for r in rows:
        if substr.lower() in (r.get("engine", "") or "").lower():
            return r
    return None


def find_complexity(rows: list[dict], substr: str) -> dict | None:
    for r in rows:
        if substr.lower() in (r.get("name", "") or "").lower():
            return r
    return None


# ============================================================================
#  报告
# ============================================================================
@dataclass
class Report:
    filled: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)

    def fill(self, where: str, what: str) -> None:
        self.filled.append((where, what))

    def miss(self, where: str, what: str) -> None:
        self.missing.append((where, what))

    def write(self, p: Path) -> None:
        self.written.append(p)

    def render(self) -> str:
        lines = ["# 论文回填报告", ""]
        lines.append(f"- 已写文件: {len(self.written)}")
        for p in self.written:
            try:
                rel = p.relative_to(PROJECT_ROOT.parent)
            except ValueError:
                rel = p
            lines.append(f"  - {rel}")
        lines.append("")
        lines.append(f"- 已填字段: {len(self.filled)}")
        for w, what in self.filled:
            lines.append(f"  - [{w}] {what}")
        lines.append("")
        lines.append(f"- **缺数据 / 仍占位**: {len(self.missing)}")
        for w, what in self.missing:
            lines.append(f"  - [{w}] {what}")
        return "\n".join(lines) + "\n"


# ============================================================================
#  替换工具：行前缀匹配
# ============================================================================
def replace_line_by_prefix(text: str, prefix: str, new_line: str,
                           must_be_only: bool = True) -> tuple[str, bool]:
    """
    把以 prefix（去 leading whitespace 后）开头的那一行整行替换为 new_line。
    new_line 不必带换行符。返回 (new_text, replaced)。
    """
    new_lines: list[str] = []
    replaced = False
    target = prefix.strip()
    for ln in text.splitlines():
        if not replaced and ln.lstrip().startswith(target):
            # 保留前导空白
            indent = ln[:len(ln) - len(ln.lstrip())]
            new_lines.append(indent + new_line.rstrip("\r\n"))
            replaced = True
        else:
            new_lines.append(ln)
    out = "\n".join(new_lines)
    if text.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out, replaced


# ============================================================================
#  英文 LaTeX
# ============================================================================
def fill_tex_en(metrics: dict, report: Report, dry: bool) -> None:
    if not TEX_MAIN.exists():
        report.miss("main.tex", "文件不存在")
        return

    text = TEX_MAIN.read_text(encoding="utf-8")
    ours = metrics.get("ours") or {}
    base = (metrics.get("baselines") or {}).get("yolo11n") or {}
    delta = metrics.get("delta_mAP50_pp")
    complexity = metrics.get("complexity") or []
    deployment = metrics.get("deployment") or []

    ours_complex = find_complexity(complexity, "Ours")

    # ---- 1. 五个宏定义 ----
    macro_table = [
        (r"mAPHalf",  fmt(get(ours, "mAP_50"), 4, r"\TBF{mAP@0.5}")),
        (r"mAPFull",  fmt(get(ours, "mAP_50_95"), 4, r"\TBF{mAP@0.5:0.95}")),
        (r"paramsM",  fmt(get(ours_complex, "params_M"), 2, r"\TBF{params}")),
        (r"flopsG",   fmt(get(ours_complex, "flops_G"), 2, r"\TBF{FLOPs}")),
        (r"fpsVal",   fmt(get(ours_complex, "fps"), 1, r"\TBF{FPS}")),
    ]
    for name, val in macro_table:
        pattern = re.compile(
            rf"^(\\newcommand\{{\\{name}\}}\{{).*\}}\s*$",
            re.MULTILINE,
        )
        if pattern.search(text):
            # greedy 到行尾的最后 }，replacement 自带闭合 }
            text = pattern.sub(lambda m, _v=val: m.group(1) + _v + "}", text)
            if val.startswith(r"\TBF"):
                report.miss("main.tex", f"\\{name} -> 仍占位")
            else:
                report.fill("main.tex", f"\\{name} = {val}")
        else:
            report.miss("main.tex", f"找不到宏定义 \\{name}")

    # ---- 2. \TBF{$\Delta$} 替换为 ΔmAP50 数值 ----
    if delta is not None:
        text = text.replace(r"\TBF{$\Delta$}", f"{delta:.2f}")
        report.fill("main.tex", rf"\TBF{{$\Delta$}} = {delta:.2f} pp")
    else:
        report.miss("main.tex", r"\TBF{$\Delta$} 缺数据")

    # ---- 3. baseline 表中 Ours 行 ----
    p, r = get(ours, "precision"), get(ours, "recall")
    mb = get(ours, "weights_size_mb")
    train_h = get(ours, "train_time")
    train_h = train_h / 3600 if isinstance(train_h, (int, float)) else None

    new_row = (r"\textbf{Ours (CBAM + P2)}         "
               r"& \textbf{\mAPHalf} & \textbf{\mAPFull} "
               f"& {fmt(p, 4)} & {fmt(r, 4)} "
               f"& {fmt(mb, 2)} & {fmt(train_h, 2)} \\\\")
    text, ok = replace_line_by_prefix(text, r"\textbf{Ours (CBAM + P2)}", new_row)
    if ok:
        report.fill("main.tex", "Table baseline -> Ours 行")
    else:
        report.miss("main.tex", "Table baseline Ours 行未匹配")

    # ---- 4. ablation 表 ----
    abls = metrics.get("ablations") or {}
    abl_rows = [
        ("A1 (+CBAM)", "yolo11n_cbam"),
        ("A2 (+EMA)",  "yolo11n_ema"),
        ("A3 (+P2 head)", "yolo11n_p2"),
    ]
    for label, key in abl_rows:
        rec = abls.get(key) or {}
        line = (f"{label:<22} "
                + ("& \\checkmark " if "cbam" in key else "& --- ")
                + ("& \\checkmark " if "ema" in key else "& --- ")
                + ("& \\checkmark " if "p2" in key else "& --- ")
                + f"& {fmt(get(rec, 'mAP_50'), 4)} "
                + f"& {fmt(get(rec, 'mAP_50_95'), 4)} "
                + f"& {fmt(get(rec, 'precision'), 4)} "
                + f"& {fmt(get(rec, 'recall'), 4)} \\\\")
        text, ok = replace_line_by_prefix(text, label, line)
        report.fill("main.tex", f"Table ablation -> {label}") if ok else \
            report.miss("main.tex", f"Table ablation {label} 未匹配")

    # A4 = ours
    a4 = abls.get("yolo11n_full") or ours
    a4_line = ("A4 (Ours, Full)        & \\checkmark & --- & \\checkmark "
               f"& \\textbf{{{fmt(get(a4, 'mAP_50'), 4)}}} "
               f"& \\textbf{{{fmt(get(a4, 'mAP_50_95'), 4)}}} "
               f"& \\textbf{{{fmt(get(a4, 'precision'), 4)}}} "
               f"& \\textbf{{{fmt(get(a4, 'recall'), 4)}}} \\\\")
    text, ok = replace_line_by_prefix(text, "A4 (Ours, Full)", a4_line)
    report.fill("main.tex", "Table ablation -> A4") if ok else \
        report.miss("main.tex", "Table ablation A4 未匹配")

    # ---- 5. complexity 表 ----
    cx_rows = [
        ("YOLOv8n",  "YOLOv8n",  5.96),
        ("YOLOv10n", "YOLOv10n", 5.49),
        ("YOLOv11n", "YOLOv11n", 5.22),
    ]
    for prefix, name, weights_mb in cx_rows:
        rec = find_complexity(complexity, name) or {}
        line = (f"{prefix:<12} "
                f"& {fmt(get(rec, 'params_M'), 2)} "
                f"& {fmt(get(rec, 'flops_G'), 2)} "
                f"& {fmt(get(rec, 'fps'), 1)} "
                f"& {weights_mb:.2f} \\\\")
        text, ok = replace_line_by_prefix(text, prefix + " ", line)
        report.fill("main.tex", f"Table complexity -> {prefix}") if ok else \
            report.miss("main.tex", f"Table complexity {prefix} 未匹配")

    # Ours
    ours_line = (r"\textbf{Ours} "
                 f"& {fmt(get(ours_complex, 'params_M'), 2)} "
                 f"& {fmt(get(ours_complex, 'flops_G'), 2)} "
                 f"& {fmt(get(ours_complex, 'fps'), 1)} "
                 f"& {fmt(get(ours_complex, 'size_MB') or get(ours, 'weights_size_mb'), 2)} \\\\")
    text, ok = replace_line_by_prefix(text, r"\textbf{Ours}", ours_line)
    report.fill("main.tex", "Table complexity -> Ours") if ok else \
        report.miss("main.tex", "Table complexity Ours 未匹配")

    # ---- 6. deployment 表 ----
    deploy_rows = [
        ("PyTorch FP32",         "FP32"),
        ("PyTorch FP16 (AMP)",   "FP16"),
        ("ONNX Runtime (CUDA)",  "ONNX"),
    ]
    fp32 = find_engine(deployment, "FP32")
    fp16 = find_engine(deployment, "FP16")
    for prefix, key in deploy_rows:
        rec = find_engine(deployment, key) or {}
        line = (f"{prefix:<20} "
                f"& {fmt(get(rec, 'fps'), 1)} "
                f"& {fmt(get(rec, 'ms'), 2)} "
                f"& {fmt(get(rec, 'size_MB'), 2)} \\\\")
        text, ok = replace_line_by_prefix(text, prefix, line)
        report.fill("main.tex", f"Table deploy -> {prefix}") if ok else \
            report.miss("main.tex", f"Table deploy {prefix} 未匹配")

    # FP16 加速比
    if fp32 and fp16 and fp32.get("fps") and fp16.get("fps"):
        speedup = (fp16["fps"] / fp32["fps"] - 1.0) * 100.0
        text = text.replace(r"\TBF{X}", f"{speedup:.1f}")
        report.fill("main.tex", f"FP16 speedup = {speedup:.1f}%")
    else:
        report.miss("main.tex", r"\TBF{X} (FP16 speedup) 缺数据")

    if not dry:
        TEX_MAIN.write_text(text, encoding="utf-8")
        report.write(TEX_MAIN)


# ============================================================================
#  中文 LaTeX（与英文同结构，行前缀略不同）
# ============================================================================
def fill_tex_zh(metrics: dict, report: Report, dry: bool) -> None:
    if not TEX_ZH.exists():
        report.miss("main_zh.tex", "文件不存在")
        return

    text = TEX_ZH.read_text(encoding="utf-8")
    ours = metrics.get("ours") or {}
    delta = metrics.get("delta_mAP50_pp")
    complexity = metrics.get("complexity") or []
    deployment = metrics.get("deployment") or []
    ours_complex = find_complexity(complexity, "Ours")

    # 宏定义（与英文同）
    macro_table = [
        (r"mAPHalf",  fmt(get(ours, "mAP_50"), 4, r"\TBF{mAP@0.5}")),
        (r"mAPFull",  fmt(get(ours, "mAP_50_95"), 4, r"\TBF{mAP@0.5:0.95}")),
        (r"paramsM",  fmt(get(ours_complex, "params_M"), 2, r"\TBF{参数量}")),
        (r"flopsG",   fmt(get(ours_complex, "flops_G"), 2, r"\TBF{FLOPs}")),
        (r"fpsVal",   fmt(get(ours_complex, "fps"), 1, r"\TBF{FPS}")),
    ]
    for name, val in macro_table:
        pattern = re.compile(
            rf"^(\\newcommand\{{\\{name}\}}\{{).*\}}\s*$",
            re.MULTILINE,
        )
        if pattern.search(text):
            text = pattern.sub(lambda m, _v=val: m.group(1) + _v + "}", text)
            if val.startswith(r"\TBF"):
                report.miss("main_zh.tex", f"\\{name} -> 仍占位")
            else:
                report.fill("main_zh.tex", f"\\{name} = {val}")
        else:
            report.miss("main_zh.tex", f"找不到宏定义 \\{name}")

    if delta is not None:
        text = text.replace(r"\TBF{$\Delta$}", f"{delta:.2f}")
        report.fill("main_zh.tex", rf"\TBF{{$\Delta$}} = {delta:.2f} pp")
    else:
        report.miss("main_zh.tex", r"\TBF{$\Delta$} 缺数据")

    # baseline 表 Ours 行
    p, r = get(ours, "precision"), get(ours, "recall")
    mb = get(ours, "weights_size_mb")
    train_h = get(ours, "train_time")
    train_h = train_h / 3600 if isinstance(train_h, (int, float)) else None
    new_row = (r"\textbf{本文方法（CBAM + P2）}    "
               r"& \textbf{\mAPHalf} & \textbf{\mAPFull} "
               f"& {fmt(p, 4)} & {fmt(r, 4)} "
               f"& {fmt(mb, 2)} & {fmt(train_h, 2)} \\\\")
    text, ok = replace_line_by_prefix(text, r"\textbf{本文方法（CBAM + P2）}", new_row)
    report.fill("main_zh.tex", "Table baseline -> 本文方法") if ok else \
        report.miss("main_zh.tex", "Table baseline 本文方法行未匹配")

    # ablation
    abls = metrics.get("ablations") or {}
    abl_rows = [
        ("A1 (+CBAM)", "yolo11n_cbam"),
        ("A2 (+EMA)",  "yolo11n_ema"),
        ("A3 (+P2 head)", "yolo11n_p2"),
    ]
    for label, key in abl_rows:
        rec = abls.get(key) or {}
        line = (f"{label:<18} "
                + ("& \\checkmark " if "cbam" in key else "& --- ")
                + ("& \\checkmark " if "ema" in key else "& --- ")
                + ("& \\checkmark " if "p2" in key else "& --- ")
                + f"& {fmt(get(rec, 'mAP_50'), 4)} "
                + f"& {fmt(get(rec, 'mAP_50_95'), 4)} "
                + f"& {fmt(get(rec, 'precision'), 4)} "
                + f"& {fmt(get(rec, 'recall'), 4)} \\\\")
        text, ok = replace_line_by_prefix(text, label, line)
        report.fill("main_zh.tex", f"Table ablation -> {label}") if ok else \
            report.miss("main_zh.tex", f"Table ablation {label} 未匹配")

    a4 = abls.get("yolo11n_full") or ours
    a4_line = ("A4 (本文方法 全集成) & \\checkmark & --- & \\checkmark "
               f"& \\textbf{{{fmt(get(a4, 'mAP_50'), 4)}}} "
               f"& \\textbf{{{fmt(get(a4, 'mAP_50_95'), 4)}}} "
               f"& \\textbf{{{fmt(get(a4, 'precision'), 4)}}} "
               f"& \\textbf{{{fmt(get(a4, 'recall'), 4)}}} \\\\")
    text, ok = replace_line_by_prefix(text, "A4 (本文方法 全集成)", a4_line)
    report.fill("main_zh.tex", "Table ablation -> A4") if ok else \
        report.miss("main_zh.tex", "Table ablation A4 未匹配")

    # complexity
    cx_rows = [
        ("YOLOv8n",  "YOLOv8n",  5.96),
        ("YOLOv10n", "YOLOv10n", 5.49),
        ("YOLOv11n", "YOLOv11n", 5.22),
    ]
    for prefix, name, weights_mb in cx_rows:
        rec = find_complexity(complexity, name) or {}
        line = (f"{prefix:<12} "
                f"& {fmt(get(rec, 'params_M'), 2)} "
                f"& {fmt(get(rec, 'flops_G'), 2)} "
                f"& {fmt(get(rec, 'fps'), 1)} "
                f"& {weights_mb:.2f} \\\\")
        text, ok = replace_line_by_prefix(text, prefix + " ", line)
        report.fill("main_zh.tex", f"Table complexity -> {prefix}") if ok else \
            report.miss("main_zh.tex", f"Table complexity {prefix} 未匹配")

    ours_line = (r"\textbf{本文方法} "
                 f"& {fmt(get(ours_complex, 'params_M'), 2)} "
                 f"& {fmt(get(ours_complex, 'flops_G'), 2)} "
                 f"& {fmt(get(ours_complex, 'fps'), 1)} "
                 f"& {fmt(get(ours_complex, 'size_MB') or get(ours, 'weights_size_mb'), 2)} \\\\")
    text, ok = replace_line_by_prefix(text, r"\textbf{本文方法}", ours_line)
    report.fill("main_zh.tex", "Table complexity -> 本文方法") if ok else \
        report.miss("main_zh.tex", "Table complexity 本文方法 未匹配")

    # deployment
    deploy_rows = [
        ("PyTorch FP32",         "FP32"),
        ("PyTorch FP16 (AMP)",   "FP16"),
        ("ONNX Runtime (CUDA)",  "ONNX"),
    ]
    fp32 = find_engine(deployment, "FP32")
    fp16 = find_engine(deployment, "FP16")
    for prefix, key in deploy_rows:
        rec = find_engine(deployment, key) or {}
        line = (f"{prefix:<20} "
                f"& {fmt(get(rec, 'fps'), 1)} "
                f"& {fmt(get(rec, 'ms'), 2)} "
                f"& {fmt(get(rec, 'size_MB'), 2)} \\\\")
        text, ok = replace_line_by_prefix(text, prefix, line)
        report.fill("main_zh.tex", f"Table deploy -> {prefix}") if ok else \
            report.miss("main_zh.tex", f"Table deploy {prefix} 未匹配")

    if fp32 and fp16 and fp32.get("fps") and fp16.get("fps"):
        speedup = (fp16["fps"] / fp32["fps"] - 1.0) * 100.0
        text = text.replace(r"\TBF{X}", f"{speedup:.1f}")
        report.fill("main_zh.tex", f"FP16 speedup = {speedup:.1f}%")

    if not dry:
        TEX_ZH.write_text(text, encoding="utf-8")
        report.write(TEX_ZH)


# ============================================================================
#  Markdown 文件
# ============================================================================
def fill_md_experiments(metrics: dict, report: Report, dry: bool) -> None:
    """paper/04_experiments.md 表格行替换 + Δ 描述"""
    if not MD_EXP.exists():
        report.miss("04_experiments.md", "文件不存在")
        return
    text = MD_EXP.read_text(encoding="utf-8")
    ours = metrics.get("ours") or {}
    delta = metrics.get("delta_mAP50_pp")
    complexity = metrics.get("complexity") or []
    deployment = metrics.get("deployment") or []
    abls = metrics.get("ablations") or {}
    ours_complex = find_complexity(complexity, "Ours")

    # baseline 表行
    p, r = get(ours, "precision"), get(ours, "recall")
    mb = get(ours, "weights_size_mb")
    train_h = get(ours, "train_time")
    train_h = train_h / 3600 if isinstance(train_h, (int, float)) else None
    new = (f"| **本文方法（YOLOv11n + CBAM + P2）** | "
           f"**{fmt(get(ours, 'mAP_50'), 4)}** | "
           f"**{fmt(get(ours, 'mAP_50_95'), 4)}** | "
           f"**{fmt(p, 4)}** | "
           f"**{fmt(r, 4)}** | "
           f"**{fmt(mb, 2)}** | "
           f"**{fmt(train_h, 2)}** |")
    text, ok = replace_line_by_prefix(text, "| **本文方法（YOLOv11n + CBAM + P2）**", new)
    report.fill("04.md", "baseline 表 -> 本文方法") if ok else \
        report.miss("04.md", "baseline 表 本文方法行未匹配")

    # Δ 说明
    if delta is not None:
        text = text.replace("提升 [待填] 个百分点**", f"提升 {delta:.2f} 个百分点**")
        report.fill("04.md", f"baseline 段 Δ = {delta:.2f} pp")
    else:
        report.miss("04.md", "baseline 段 Δ 缺数据")

    # ablation 表
    a_rows = [
        ("| A1 yolo11n_cbam   |", "yolo11n_cbam"),
        ("| A2 yolo11n_ema    |", "yolo11n_ema"),
        ("| A3 yolo11n_p2     |", "yolo11n_p2"),
    ]
    base50 = (metrics.get("baselines", {}).get("yolo11n") or {}).get("mAP_50")
    for prefix, key in a_rows:
        rec = abls.get(key) or {}
        cur_map = get(rec, "mAP_50")
        d = (cur_map - base50) * 100.0 if (cur_map is not None and base50 is not None) else None
        line = (f"{prefix} "
                f"{fmt(cur_map, 4)} | "
                f"{fmt(get(rec, 'mAP_50_95'), 4)} | "
                f"{fmt(get(rec, 'precision'), 4)} | "
                f"{fmt(get(rec, 'recall'), 4)} | "
                f"{fmt_pct(d, 2, '[待填]')} |")
        text, ok = replace_line_by_prefix(text, prefix, line)
        report.fill("04.md", f"ablation 表 -> {key}") if ok else \
            report.miss("04.md", f"ablation 表 {key} 未匹配")

    # A4
    a4 = abls.get("yolo11n_full") or ours
    cur_map = get(a4, "mAP_50")
    d = (cur_map - base50) * 100.0 if (cur_map is not None and base50 is not None) else None
    a4_line = ("| A4 yolo11n_full   | "
               f"**{fmt(cur_map, 4)}** | "
               f"**{fmt(get(a4, 'mAP_50_95'), 4)}** | "
               f"**{fmt(get(a4, 'precision'), 4)}** | "
               f"**{fmt(get(a4, 'recall'), 4)}** | "
               f"**{fmt_pct(d, 2, '[待填]')}** |")
    text, ok = replace_line_by_prefix(text, "| A4 yolo11n_full   |", a4_line)
    report.fill("04.md", "ablation 表 -> A4") if ok else \
        report.miss("04.md", "ablation 表 A4 未匹配")

    # complexity 表
    cx_rows = [
        ("| YOLOv8n  |", "YOLOv8n",  5.96),
        ("| YOLOv10n |", "YOLOv10n", 5.49),
        ("| YOLOv11n |", "YOLOv11n", 5.22),
    ]
    for prefix, name, mb_ in cx_rows:
        rec = find_complexity(complexity, name) or {}
        line = (f"{prefix} "
                f"{fmt(get(rec, 'params_M'), 2)} | "
                f"{fmt(get(rec, 'flops_G'), 2)} | "
                f"{fmt(get(rec, 'fps'), 1)} | "
                f"{mb_:.2f} |")
        text, ok = replace_line_by_prefix(text, prefix, line)
        report.fill("04.md", f"complexity -> {name}") if ok else \
            report.miss("04.md", f"complexity {name} 未匹配")

    ours_line = ("| **本文方法** | "
                 f"{fmt(get(ours_complex, 'params_M'), 2)} | "
                 f"{fmt(get(ours_complex, 'flops_G'), 2)} | "
                 f"{fmt(get(ours_complex, 'fps'), 1)} | "
                 f"{fmt(get(ours_complex, 'size_MB') or get(ours, 'weights_size_mb'), 2)} |")
    text, ok = replace_line_by_prefix(text, "| **本文方法** |", ours_line)
    report.fill("04.md", "complexity -> 本文方法") if ok else \
        report.miss("04.md", "complexity 本文方法未匹配")

    # deployment 表
    deploy_rows = [
        ("| PyTorch FP32 |",          "FP32"),
        ("| PyTorch FP16 |",          "FP16"),
        ("| ONNX (onnxruntime-gpu) |", "ONNX"),
    ]
    for prefix, key in deploy_rows:
        rec = find_engine(deployment, key) or {}
        line = (f"{prefix} "
                f"{fmt(get(rec, 'fps'), 1)} | "
                f"{fmt(get(rec, 'ms'), 2)} | "
                f"{fmt(get(rec, 'size_MB'), 2)} |")
        text, ok = replace_line_by_prefix(text, prefix, line)
        report.fill("04.md", f"deploy -> {prefix}") if ok else \
            report.miss("04.md", f"deploy {prefix} 未匹配")

    if not dry:
        MD_EXP.write_text(text, encoding="utf-8")
        report.write(MD_EXP)


def fill_md_others(metrics: dict, report: Report, dry: bool) -> None:
    """填 00_meta / 01_introduction / 03_method / 05_conclusion 中零散的 [待填]"""
    ours = metrics.get("ours") or {}
    delta = metrics.get("delta_mAP50_pp")
    complexity = metrics.get("complexity") or []
    ours_complex = find_complexity(complexity, "Ours")

    map50 = get(ours, "mAP_50")
    params_m = get(ours_complex, "params_M")
    flops_g = get(ours_complex, "flops_G")
    fps = get(ours_complex, "fps")

    # ----- 00_meta.md -----
    if MD_META.exists():
        text = MD_META.read_text(encoding="utf-8")
        n_repl = 0
        if map50 is not None:
            new, n = re.subn(r"mAP@0\.5 = \[待填\]", f"mAP@0.5 = {map50:.4f}", text)
            text = new
            n_repl += n
        if delta is not None:
            new, n = re.subn(r"基线提升 \*\*\[待填\]\*\* 个百分点",
                             f"基线提升 **{delta:.2f}** 个百分点", text)
            text = new
            n_repl += n
        if params_m is not None:
            new, n = re.subn(r"模型参数量为 \*\*\[待填\]M\*\*",
                             f"模型参数量为 **{params_m:.2f}M**", text)
            text = new
            n_repl += n
            new, n = re.subn(r"\*\*\[TBF\]M\*\* parameters",
                             f"**{params_m:.2f}M** parameters", text)
            text = new
            n_repl += n
        if fps is not None:
            new, n = re.subn(r"FPS 为 \*\*\[待填\]\*\*",
                             f"FPS 为 **{fps:.1f}**", text)
            text = new
            n_repl += n
            new, n = re.subn(r"\*\*\[TBF\]\*\* FPS",
                             f"**{fps:.1f}** FPS", text)
            text = new
            n_repl += n
        if map50 is not None:
            new, n = re.subn(r"mAP@0\.5 = \[TBF\]",
                             f"mAP@0.5 = {map50:.4f}", text)
            text = new
            n_repl += n
        if delta is not None:
            new, n = re.subn(r"improvement of \*\*\[TBF\]\*\* percentage points",
                             f"improvement of **{delta:.2f}** percentage points", text)
            text = new
            n_repl += n
        if n_repl:
            report.fill("00_meta.md", f"{n_repl} 处 [待填]/[TBF]")
            if not dry:
                MD_META.write_text(text, encoding="utf-8")
                report.write(MD_META)

    # ----- 01_introduction.md -----
    if MD_INTRO.exists():
        text = MD_INTRO.read_text(encoding="utf-8")
        if map50 is not None:
            new, n = re.subn(r"mAP@0\.5 = \[待填\]",
                             f"mAP@0.5 = {map50:.4f}", text)
            if n:
                text = new
                report.fill("01_introduction.md", f"{n} 处 mAP")
                if not dry:
                    MD_INTRO.write_text(text, encoding="utf-8")
                    report.write(MD_INTRO)

    # ----- 03_method.md -----
    if MD_METHOD.exists():
        text = MD_METHOD.read_text(encoding="utf-8")
        n_repl = 0
        if params_m is not None:
            new, n = re.subn(r"约\s*\[待填\]\s*M",
                             f"约 {params_m:.2f} M", text)
            text = new
            n_repl += n
        if flops_g is not None:
            new, n = re.subn(r"GFLOPs \| 6\.5 \| 约 \[待填\] \|",
                             f"GFLOPs | 6.5 | 约 {flops_g:.2f} |", text)
            text = new
            n_repl += n
            new, n = re.subn(r"实际新增 GFLOPs 约 \[待填\]",
                             f"实际新增 GFLOPs 约 {flops_g - 6.5:.2f}" if flops_g > 6.5
                             else f"实际新增 GFLOPs 约 {flops_g:.2f}", text)
            text = new
            n_repl += n
        if n_repl:
            report.fill("03_method.md", f"{n_repl} 处")
            if not dry:
                MD_METHOD.write_text(text, encoding="utf-8")
                report.write(MD_METHOD)

    # ----- 05_conclusion.md -----
    if MD_CONCL.exists():
        text = MD_CONCL.read_text(encoding="utf-8")
        n_repl = 0
        if map50 is not None:
            new, n = re.subn(r"mAP@0\.5 = \[待填\]",
                             f"mAP@0.5 = {map50:.4f}", text)
            text = new
            n_repl += n
        if delta is not None:
            new, n = re.subn(r"提升 \[待填\] 个百分点",
                             f"提升 {delta:.2f} 个百分点", text)
            text = new
            n_repl += n
        if n_repl:
            report.fill("05_conclusion.md", f"{n_repl} 处")
            if not dry:
                MD_CONCL.write_text(text, encoding="utf-8")
                report.write(MD_CONCL)


# ============================================================================
#  主入口
# ============================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印将做的改动，不真改文件")
    args = ap.parse_args()

    if not METRICS_FILE.exists():
        print(f"[err] 找不到 {METRICS_FILE}，先运行 collect_metrics.py", file=sys.stderr)
        return 1
    metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))

    report = Report()
    fill_tex_en(metrics, report, args.dry_run)
    fill_tex_zh(metrics, report, args.dry_run)
    fill_md_experiments(metrics, report, args.dry_run)
    fill_md_others(metrics, report, args.dry_run)

    rendered = report.render()
    if not args.dry_run:
        REPORT_FILE.write_text(rendered, encoding="utf-8")
    print(rendered)
    print(f"\n[OK] 报告 -> {REPORT_FILE}" if not args.dry_run else "[dry-run] 不写文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
