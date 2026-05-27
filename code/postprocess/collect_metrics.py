"""
collect_metrics.py
==================

把流水线产出的所有数字汇总成一份 ``runs/collected_metrics.json``，
后续填表 / 填论文都从这一份消费。

来源（按存在性自动跳过）:
  - runs/baseline/<name>_metrics.json         (yolov8n / yolov10n / yolo11n)
  - runs/baseline/<name>/results.csv          (兜底：从 results.csv 取 best epoch)
  - runs/ours/yolo11n_full_metrics.json
  - runs/ours/yolo11n_full/results.csv         (兜底)
  - runs/ablation/<name>_metrics.json          (5 组消融)
  - runs/ablation/<name>/results.csv           (兜底)
  - runs/complexity.json                       (eval/eval_complexity.py)
  - paper/tables/deployment_table.md           (eval/eval_deployment.py 输出)
  - paper/tables/robustness_table.md           (eval/eval_robustness.py 输出)
  - <run_dir>/weights/best.pt                  (大小)

用法:
  python postprocess/collect_metrics.py
  python postprocess/collect_metrics.py --print     # 同时打 stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = PROJECT_ROOT / "runs"
TABLE_DIR = PROJECT_ROOT / "paper" / "tables"
OUT_FILE = RUNS_ROOT / "collected_metrics.json"

BASELINE_NAMES = ["yolov8n", "yolov10n", "yolo11n"]
ABLATION_NAMES = ["yolo11n", "yolo11n_cbam", "yolo11n_ema",
                  "yolo11n_p2", "yolo11n_full"]
OURS_NAME = "yolo11n_full"


# ---------- 兜底：从 results.csv 抓最佳 epoch ----------
def best_from_results_csv(csv_path: Path) -> dict | None:
    if not csv_path.exists():
        return None
    try:
        import csv as _csv
        with csv_path.open(encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        if not rows:
            return None

        def _f(row: dict, *keys: str) -> float | None:
            for k in keys:
                v = row.get(k)
                if v is None:
                    continue
                try:
                    return float(v)
                except ValueError:
                    continue
            return None

        # 取 mAP50 最大的 epoch
        def _key(r: dict) -> float:
            return _f(r, "metrics/mAP50(B)", "metrics/mAP_0.5") or 0.0

        best = max(rows, key=_key)
        return {
            "mAP_50":    _f(best, "metrics/mAP50(B)", "metrics/mAP_0.5"),
            "mAP_50_95": _f(best, "metrics/mAP50-95(B)", "metrics/mAP_0.5:0.95"),
            "precision": _f(best, "metrics/precision(B)", "metrics/precision"),
            "recall":    _f(best, "metrics/recall(B)", "metrics/recall"),
            "epochs":    int(_f(best, "epoch") or len(rows)),
            "_source":   "results.csv",
        }
    except Exception as e:
        print(f"  [warn] 解析 {csv_path} 失败: {e}", file=sys.stderr)
        return None


def weights_size_mb(run_dir: Path) -> float | None:
    w = run_dir / "weights" / "best.pt"
    if w.exists():
        return w.stat().st_size / 1024 / 1024
    return None


def merge(*sources: dict | None) -> dict:
    """按顺序合并，前者优先（None 不写入，后者只补缺）"""
    out: dict = {}
    for s in sources:
        if not s:
            continue
        for k, v in s.items():
            if v is None or v == "":
                continue
            out.setdefault(k, v)
    return out


def collect_one(name: str, kind: str) -> dict:
    """kind in {baseline, ours, ablation}"""
    if kind == "baseline":
        run_dir = RUNS_ROOT / "baseline" / name
        json_path = RUNS_ROOT / "baseline" / f"{name}_metrics.json"
    elif kind == "ours":
        run_dir = RUNS_ROOT / "ours" / OURS_NAME
        json_path = RUNS_ROOT / "ours" / f"{OURS_NAME}_metrics.json"
    elif kind == "ablation":
        run_dir = RUNS_ROOT / "ablation" / name
        json_path = RUNS_ROOT / "ablation" / f"{name}_metrics.json"
    else:
        raise ValueError(kind)

    json_data = None
    if json_path.exists():
        try:
            json_data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [warn] 解析 {json_path} 失败: {e}", file=sys.stderr)

    csv_data = best_from_results_csv(run_dir / "results.csv")

    size_mb = weights_size_mb(run_dir)

    rec = merge(
        json_data,
        csv_data,
        {"weights_size_mb": size_mb},
    )
    rec.setdefault("name", name)
    rec.setdefault("kind", kind)
    rec.setdefault("run_dir", str(run_dir.relative_to(PROJECT_ROOT)) if run_dir.exists() else None)
    rec["available"] = (run_dir / "weights" / "best.pt").exists()
    return rec


# ---------- 复杂度 / 部署 / 鲁棒性 ----------
def collect_complexity() -> list[dict]:
    """eval/eval_complexity.py 直接 dump 到 runs/complexity.json"""
    p = RUNS_ROOT / "complexity.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def parse_deployment_md() -> list[dict]:
    """从 paper/tables/deployment_table.md 反解，避免再跑一次"""
    md = TABLE_DIR / "deployment_table.md"
    if not md.exists():
        return []
    out: list[dict] = []
    for line in md.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "Engine" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        engine, fps, ms, size = cells[0], cells[1], cells[2], cells[3]

        def _f(s: str) -> float | None:
            try:
                return float(s)
            except ValueError:
                return None

        out.append({
            "engine":  engine,
            "fps":     _f(fps),
            "ms":      _f(ms),
            "size_MB": _f(size),
        })
    return out


def parse_robustness_md() -> dict:
    """从 paper/tables/robustness_table.md 反解，按 model -> {clean, perturbations -> [s0.3, s0.6, s0.9]}"""
    md = TABLE_DIR / "robustness_table.md"
    if not md.exists():
        return {}
    text = md.read_text(encoding="utf-8")
    blocks = re.split(r"## strength = ([\d.]+)", text)
    # blocks: [前言, '0.3', table0.3, '0.6', table0.6, '0.9', table0.9]
    perts = ["brightness_dim", "brightness_bright", "gaussian_noise",
             "motion_blur", "jpeg_compression", "rotation"]
    result: dict = {}
    for i in range(1, len(blocks), 2):
        s = float(blocks[i])
        body = blocks[i + 1]
        for line in body.splitlines():
            if not line.startswith("|") or "Model" in line or "---" in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 + len(perts):
                continue
            name = cells[0]

            def _f(x: str) -> float | None:
                try:
                    return float(x)
                except ValueError:
                    return None

            entry = result.setdefault(name, {"clean": _f(cells[1]),
                                             "perturbations": {p: {} for p in perts}})
            for j, p in enumerate(perts):
                entry["perturbations"][p][f"{s:.1f}"] = _f(cells[2 + j])
    return result


# ---------- 主入口 ----------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()

    out: dict = {
        "baselines": {n: collect_one(n, "baseline") for n in BASELINE_NAMES},
        "ours":      collect_one(OURS_NAME, "ours"),
        "ablations": {n: collect_one(n, "ablation") for n in ABLATION_NAMES},
        "complexity":  collect_complexity(),
        "deployment":  parse_deployment_md(),
        "robustness":  parse_robustness_md(),
    }

    # 派生量：Δ vs YOLOv11n baseline
    base = out["baselines"].get("yolo11n", {}) or {}
    if base.get("mAP_50") is not None and out["ours"].get("mAP_50") is not None:
        out["delta_mAP50_pp"] = (out["ours"]["mAP_50"] - base["mAP_50"]) * 100.0

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    print(f"[OK] 汇总数字 -> {OUT_FILE}")

    if args.do_print:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        # 简要状态报告
        print()
        print("=== 状态简报 ===")
        for n, rec in out["baselines"].items():
            ok = "✓" if rec.get("available") else "·"
            m = rec.get("mAP_50")
            print(f"  baseline {ok} {n:10}  mAP50={m if m is not None else '?'}")
        ok = "✓" if out["ours"].get("available") else "·"
        m = out["ours"].get("mAP_50")
        print(f"  ours     {ok} yolo11n_full  mAP50={m if m is not None else '?'}")
        for n, rec in out["ablations"].items():
            ok = "✓" if rec.get("available") else "·"
            m = rec.get("mAP_50")
            print(f"  ablation {ok} {n:14}  mAP50={m if m is not None else '?'}")
        print(f"  complexity rows : {len(out['complexity'])}")
        print(f"  deployment rows : {len(out['deployment'])}")
        print(f"  robustness rows : {len(out['robustness'])}")
        if "delta_mAP50_pp" in out:
            print(f"  Δ mAP50 vs YOLOv11n: {out['delta_mAP50_pp']:.2f} pp")

    return 0


if __name__ == "__main__":
    sys.exit(main())
