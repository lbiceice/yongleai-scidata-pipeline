#!/usr/bin/env python3
"""
Smoke10 QC — 读取 smoke10 manifests，计算质量指标，生成 go/no-go 报告
用法: python3 scripts/qc_smoke10.py
"""

import os, csv, json, datetime
from pathlib import Path
from collections import Counter, defaultdict

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")

# ─── Thresholds ─────────────────────────────────────
THRESH = {
    "schema_valid_rate": 0.90,
    "cross_dim_valid_rate": 0.95,
    "single_engine_success": 0.70,
}

def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))

def main():
    s3_path = PROJECT / "03_features" / "statistics" / "smoke10_feature_manifest.csv"
    s4_path = PROJECT / "04_damage" / "statistics" / "smoke10_damage_manifest.csv"

    if not s3_path.exists() or not s4_path.exists():
        print("ERROR: manifest files not found. Run run_smoke10.py first.")
        return 1

    s3 = load_csv(s3_path)
    s4 = load_csv(s4_path)

    engines = sorted(set(r["engine"] for r in s3))
    NOW = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # ─── STEP3 metrics (using gate_pass as primary) ──
    s3_total = len(s3)
    s3_raw_schema = sum(1 for r in s3 if r.get("raw_schema_ok") == "True")
    s3_raw_vocab = sum(1 for r in s3 if r.get("raw_vocab_ok") == "True")
    s3_gate = sum(1 for r in s3 if r.get("gate_pass") == "True")
    s3_cross_ok = sum(1 for r in s3 if not r.get("cross_dim_warnings"))
    s3_review = sum(1 for r in s3 if r.get("review_required") == "True")
    s3_fallback = sum(1 for r in s3 if r.get("fallback_reason"))
    contract_mode = s3[0].get("contract_mode", "unknown") if s3 else "unknown"

    s3_schema_rate = s3_raw_schema / s3_total if s3_total else 0
    s3_vocab_rate = s3_raw_vocab / s3_total if s3_total else 0
    s3_gate_rate = s3_gate / s3_total if s3_total else 0
    s3_cross_rate = s3_cross_ok / s3_total if s3_total else 0

    # ─── STEP4 metrics ─────────────────────────────
    s4_total = len(s4)
    s4_raw_schema = sum(1 for r in s4 if r.get("raw_schema_ok") == "True")
    s4_raw_vocab = sum(1 for r in s4 if r.get("raw_vocab_ok") == "True")
    s4_gate = sum(1 for r in s4 if r.get("gate_pass") == "True")
    s4_review = sum(1 for r in s4 if r.get("review_required") == "True")
    s4_fallback = sum(1 for r in s4 if r.get("fallback_reason"))

    s4_schema_rate = s4_raw_schema / s4_total if s4_total else 0
    s4_vocab_rate = s4_raw_vocab / s4_total if s4_total else 0
    s4_gate_rate = s4_gate / s4_total if s4_total else 0

    # ─── Per-engine ─────────────────────────────────
    engine_stats = {}
    for e in engines:
        e3 = [r for r in s3 if r["engine"] == e]
        e4 = [r for r in s4 if r["engine"] == e]
        ok3 = sum(1 for r in e3 if r.get("gate_pass") == "True")
        ok4 = sum(1 for r in e4 if r.get("gate_pass") == "True")
        lat3 = [int(r["latency_ms"]) for r in e3 if r.get("latency_ms")]
        lat4 = [int(r["latency_ms"]) for r in e4 if r.get("latency_ms")]
        engine_stats[e] = {
            "s3_pass": ok3, "s3_total": len(e3),
            "s4_pass": ok4, "s4_total": len(e4),
            "success_rate": (ok3 + ok4) / (len(e3) + len(e4)) if (len(e3) + len(e4)) else 0,
            "avg_latency_ms": round(sum(lat3 + lat4) / len(lat3 + lat4)) if (lat3 + lat4) else 0,
        }

    # ─── Thumb vs Full ──────────────────────────────
    thumb3 = [r for r in s3 if r["image_mode"] == "thumb"]
    full3 = [r for r in s3 if r["image_mode"] == "full"]
    thumb_ok = sum(1 for r in thumb3 if r.get("gate_pass") == "True") / len(thumb3) if thumb3 else 0
    full_ok = sum(1 for r in full3 if r.get("gate_pass") == "True") / len(full3) if full3 else 0

    # ─── Go/No-Go ───────────────────────────────────
    checks = []
    checks.append(("raw_schema_rate_s3", s3_schema_rate >= THRESH["schema_valid_rate"], f"{s3_schema_rate:.1%}"))
    checks.append(("raw_schema_rate_s4", s4_schema_rate >= THRESH["schema_valid_rate"], f"{s4_schema_rate:.1%}"))
    checks.append(("cross_dim_valid_rate", s3_cross_rate >= THRESH["cross_dim_valid_rate"], f"{s3_cross_rate:.1%}"))
    for e in engines:
        es = engine_stats[e]
        checks.append((f"engine_{e}_gate_pass", es["success_rate"] >= THRESH["single_engine_success"], f"{es['success_rate']:.1%}"))
    all_pass = all(c[1] for c in checks)
    verdict = "GO" if all_pass else "NO-GO"

    # ─── Output dirs ────────────────────────────────
    os.makedirs(PROJECT / "03_features" / "quality_control", exist_ok=True)
    os.makedirs(PROJECT / "04_damage" / "quality_control", exist_ok=True)
    os.makedirs(PROJECT / "reports", exist_ok=True)

    # ─── QC JSONs ───────────────────────────────────
    s3_qc = {"date": NOW, "total": s3_total, "raw_schema_valid": s3_raw_schema, "raw_vocab_valid": s3_raw_vocab,
             "gate_pass": s3_gate, "cross_dim_ok": s3_cross_ok, "review": s3_review,
             "fallback_triggered": s3_fallback, "contract_mode": contract_mode,
             "schema_rate": round(s3_schema_rate, 4), "vocab_rate": round(s3_vocab_rate, 4),
             "gate_rate": round(s3_gate_rate, 4), "cross_rate": round(s3_cross_rate, 4)}
    with open(PROJECT / "03_features" / "quality_control" / "smoke10_qc_report.json", "w") as f:
        json.dump(s3_qc, f, indent=2)

    s4_qc = {"date": NOW, "total": s4_total, "raw_schema_valid": s4_raw_schema, "raw_vocab_valid": s4_raw_vocab,
             "gate_pass": s4_gate, "review": s4_review,
             "fallback_triggered": s4_fallback, "contract_mode": contract_mode,
             "schema_rate": round(s4_schema_rate, 4), "vocab_rate": round(s4_vocab_rate, 4),
             "gate_rate": round(s4_gate_rate, 4)}
    with open(PROJECT / "04_damage" / "quality_control" / "smoke10_qc_report.json", "w") as f:
        json.dump(s4_qc, f, indent=2)

    # ─── Summary MD ─────────────────────────────────
    md = f"# Smoke10 Summary\n\n**日期**: {NOW}\n**contract_mode**: {contract_mode}\n\n"
    md += "## STEP3 (HSGF)\n| Metric | Value |\n|--------|-------|\n"
    md += f"| raw_schema_valid | {s3_raw_schema}/{s3_total} ({s3_schema_rate:.1%}) |\n"
    md += f"| raw_vocab_valid | {s3_raw_vocab}/{s3_total} ({s3_vocab_rate:.1%}) |\n"
    md += f"| gate_pass | {s3_gate}/{s3_total} ({s3_gate_rate:.1%}) |\n"
    md += f"| cross_dim_ok | {s3_cross_ok}/{s3_total} ({s3_cross_rate:.1%}) |\n"
    md += f"| fallback_triggered | {s3_fallback} |\n"
    md += f"| review_required | {s3_review} |\n\n"
    md += "## STEP4 (Damage)\n| Metric | Value |\n|--------|-------|\n"
    md += f"| raw_schema_valid | {s4_raw_schema}/{s4_total} ({s4_schema_rate:.1%}) |\n"
    md += f"| raw_vocab_valid | {s4_raw_vocab}/{s4_total} ({s4_vocab_rate:.1%}) |\n"
    md += f"| gate_pass | {s4_gate}/{s4_total} ({s4_gate_rate:.1%}) |\n"
    md += f"| fallback_triggered | {s4_fallback} |\n"
    md += f"| review_required | {s4_review} |\n\n"
    md += "## Per-Engine\n| Engine | S3 | S4 | Success | Avg Latency |\n|--------|----|----|---------|-------------|\n"
    for e in engines:
        es = engine_stats[e]
        md += f"| {e} | {es['s3_pass']}/{es['s3_total']} | {es['s4_pass']}/{es['s4_total']} | {es['success_rate']:.1%} | {es['avg_latency_ms']}ms |\n"
    md += f"\n## Thumb vs Full\n| Mode | Schema Rate |\n|------|-------------|\n"
    md += f"| thumb | {thumb_ok:.1%} |\n| full | {full_ok:.1%} |\n"
    with open(PROJECT / "reports" / "step3_4_smoke10_summary.md", "w") as f:
        f.write(md)

    # ─── Go/No-Go MD ────────────────────────────────
    gmd = f"# Smoke10 Go/No-Go\n\n**Verdict: {verdict}**\n\n"
    gmd += "## Checks\n| # | Check | Pass | Value |\n|---|-------|------|-------|\n"
    for i, (name, passed, val) in enumerate(checks, 1):
        gmd += f"| {i} | {name} | {'PASS' if passed else 'FAIL'} | {val} |\n"
    gmd += f"\n## Thresholds\n- schema_valid >= {THRESH['schema_valid_rate']:.0%}\n"
    gmd += f"- cross_dim_valid >= {THRESH['cross_dim_valid_rate']:.0%}\n"
    gmd += f"- single_engine >= {THRESH['single_engine_success']:.0%}\n"
    gmd += f"\n## Next Step\n"
    gmd += "GO → 进入 stratified pilot (20 patches × 4 engines)\n" if all_pass else "NO-GO → 修复失败引擎/prompt 后重跑\n"
    with open(PROJECT / "reports" / "step3_4_smoke10_go_no_go.md", "w") as f:
        f.write(gmd)

    # ─── Speed report ───────────────────────────────
    smd = f"# Smoke10 Speed Report\n\n"
    smd += "| Engine | Provider | Calls | Avg Latency | Total Time |\n|--------|----------|-------|-------------|------------|\n"
    for e in engines:
        es = engine_stats[e]
        total_calls = es["s3_total"] + es["s4_total"]
        total_time = es["avg_latency_ms"] * total_calls / 1000
        prov = "gptsapi" if e != "qwen" else "dashscope"
        smd += f"| {e} | {prov} | {total_calls} | {es['avg_latency_ms']}ms | {total_time:.0f}s |\n"
    with open(PROJECT / "reports" / "step3_4_smoke10_speed_report.md", "w") as f:
        f.write(smd)

    print(f"\nVerdict: {verdict}")
    print(f"Reports written to reports/")
    return 0 if all_pass else 1

if __name__ == "__main__":
    exit(main())
