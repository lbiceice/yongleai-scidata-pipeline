#!/usr/bin/env python3
"""引擎完成后的全面自检脚本。
Usage: python3 scripts/engine_completion_check.py [--engine openai|gemini|claude|qwen|all]
"""
import csv, json, os, sys, glob, argparse
from pathlib import Path
from datetime import datetime
from collections import Counter

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))
TOTAL_PATCHES = 7455


def check_engine(engine):
    report = {"engine": engine, "timestamp": datetime.now().isoformat(), "checks": {}}
    runs_dir = PROJECT / "03_features" / "runs"
    engine_dirs = sorted(runs_dir.glob(f"batch_{engine}*"))
    if not engine_dirs:
        report["checks"]["run_exists"] = {"status": "FAIL", "detail": "no run dir"}
        return report

    # Collect all CSV rows
    s3_rows = []
    patch_ids = set()
    for d in engine_dirs:
        for cf in sorted((d / "manifests").glob("shard_*.csv")):
            try:
                with open(cf, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        s3_rows.append(row)
                        pid = row.get("patch_id", "")
                        if pid:
                            patch_ids.add(pid)
            except Exception:
                pass

    # 1. Coverage
    cov = len(patch_ids) / TOTAL_PATCHES * 100 if TOTAL_PATCHES else 0
    report["checks"]["coverage"] = {
        "status": "PASS" if cov >= 90 else "WARN" if cov >= 50 else "INFO",
        "unique_patches": len(patch_ids), "total_rows": len(s3_rows),
        "pct": round(cov, 1),
    }

    if not s3_rows:
        return report

    # 2. Schema
    required = ["patch_id", "engine", "D1", "D2", "D3", "D4", "D5"]
    missing = [c for c in required if c not in s3_rows[0]]
    report["checks"]["schema"] = {
        "status": "PASS" if not missing else "FAIL",
        "columns": len(s3_rows[0]), "missing": missing,
    }

    # 3. Vocab
    try:
        from canonical_taxonomy import VALID_LABELS
        violations = 0
        total_checked = 0
        for row in s3_rows:
            for dim in ["D1", "D2", "D3", "D4", "D5"]:
                val = row.get(dim, "")
                if val and dim in VALID_LABELS:
                    total_checked += 1
                    if val not in VALID_LABELS[dim]:
                        violations += 1
        rate = (total_checked - violations) / max(total_checked, 1) * 100
        report["checks"]["vocab"] = {
            "status": "PASS" if rate >= 95 else "WARN",
            "rate_pct": round(rate, 2), "violations": violations,
        }
    except ImportError:
        report["checks"]["vocab"] = {"status": "WARN", "detail": "import failed"}

    # 4. Gate pass rate
    gate_pass = sum(1 for r in s3_rows if str(r.get("gate_pass", "")).lower() in ("true", "1"))
    gate_rate = gate_pass / max(len(s3_rows), 1) * 100
    report["checks"]["gate_pass"] = {
        "status": "PASS" if gate_rate >= 95 else "WARN",
        "rate_pct": round(gate_rate, 2), "passed": gate_pass, "total": len(s3_rows),
    }

    # 5. Fallback
    fb = sum(1 for r in s3_rows if r.get("fallback_reason", "").strip())
    fb_rate = fb / max(len(s3_rows), 1) * 100
    report["checks"]["fallback"] = {
        "status": "PASS" if fb_rate < 5 else "WARN",
        "count": fb, "rate_pct": round(fb_rate, 2),
    }

    # 6. D1 distribution
    d1 = Counter(r.get("D1", "") for r in s3_rows)
    report["checks"]["d1_dist"] = {
        "status": "PASS" if len(d1) >= 3 else "WARN",
        "unique": len(d1), "top5": dict(d1.most_common(5)),
    }

    # 7. Duplicates
    dup = {k: v for k, v in Counter(r.get("patch_id") for r in s3_rows).items() if v > 1}
    report["checks"]["duplicates"] = {
        "status": "PASS" if not dup else "WARN",
        "count": len(dup),
    }

    # 8. Latency
    lats = []
    for r in s3_rows:
        try:
            l = float(r.get("latency_ms", 0))
            if l > 0:
                lats.append(l)
        except (ValueError, TypeError):
            pass
    if lats:
        lats.sort()
        report["checks"]["latency"] = {
            "status": "PASS",
            "mean_ms": round(sum(lats) / len(lats)),
            "median_ms": round(lats[len(lats) // 2]),
            "p95_ms": round(lats[int(len(lats) * 0.95)]),
        }

    # Summary
    s = {"total": 0, "pass": 0, "fail": 0, "warn": 0}
    for c in report["checks"].values():
        s["total"] += 1
        st = c.get("status", "")
        if st == "PASS": s["pass"] += 1
        elif st == "FAIL": s["fail"] += 1
        elif st == "WARN": s["warn"] += 1
    report["summary"] = s
    report["verdict"] = "PASS" if s["fail"] == 0 else "FAIL"
    return report


def main():
    parser = argparse.ArgumentParser(description="引擎完成自检")
    parser.add_argument("--engine", default="all", help="openai|gemini|claude|qwen|all")
    args = parser.parse_args()

    engines = ["openai", "gemini", "claude", "qwen"] if args.engine == "all" else [args.engine]
    all_reports = {}

    for eng in engines:
        print(f"\n{'=' * 50}\n  自检: {eng}\n{'=' * 50}")
        r = check_engine(eng)
        all_reports[eng] = r
        for name, c in r["checks"].items():
            st = c.get("status", "?")
            icon = {"PASS": "+", "WARN": "!", "FAIL": "X", "INFO": "i"}.get(st, "?")
            extra = f" ({c.get('pct', c.get('rate_pct', c.get('count', '')))})" if any(
                k in c for k in ("pct", "rate_pct", "count")) else ""
            print(f"  [{icon}] {name}{extra}")
        s = r.get("summary", {})
        print(f"  => {r.get('verdict', '?')} ({s.get('pass', 0)}P/{s.get('warn', 0)}W/{s.get('fail', 0)}F)")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = PROJECT / "reports" / f"engine_check_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2))
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
