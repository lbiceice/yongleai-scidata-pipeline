#!/usr/bin/env python3
"""
validate_release.py — dataset_release/ 完整性校验
用法: python3 scripts/validate_release.py [--output OUTPUT_DIR]
"""
import argparse, csv, json, hashlib, os, sys
from pathlib import Path
from collections import Counter

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dataset_release", help="发布包目录")
    args = parser.parse_args()
    DR = PROJECT / args.output

    errors = []
    warnings = []
    passes = []

    def check(ok, msg):
        if ok:
            passes.append(msg)
        else:
            errors.append(msg)

    def warn(msg):
        warnings.append(msg)

    # ── 1. 文件清单 ──────────────────────────────────────
    required_files = [
        "README.md", "LICENSE", "codebook.md", "checksums_sha256.tsv",
        "annotations/consensus_labels_s3.csv",
        "annotations/per_engine_labels_s3.csv",
        "splits/train.txt", "splits/val.txt", "splits/test.txt",
        "statistics/krippendorff_alpha.json",
    ]
    optional_files = [
        "CITATION.cff", ".zenodo.json",
        "source_description.md", "ethics_and_copyright.md",
        "taxonomy/hsgf_taxonomy_v2.9.9.json", "taxonomy/damage_taxonomy.json",
        "statistics/cohen_kappa_matrix.json", "statistics/agreement_matrix.json",
    ]
    for f in required_files:
        check((DR / f).exists(), f"required file: {f}")
    for f in optional_files:
        if (DR / f).exists():
            passes.append(f"optional file: {f}")
        else:
            warn(f"optional file missing: {f}")

    # ── 2. Checksums ─────────────────────────────────────
    cksum_path = DR / "checksums_sha256.tsv"
    if cksum_path.exists():
        all_release_files = set()
        for root, dirs, files in os.walk(DR):
            for fn in files:
                if fn.startswith("._") or fn == "checksums_sha256.tsv":
                    continue
                all_release_files.add(os.path.relpath(os.path.join(root, fn), DR))

        cksum_entries = {}
        for line in cksum_path.read_text().strip().split("\n")[1:]:
            if "\t" in line:
                sha, rel = line.split("\t", 1)
                cksum_entries[rel] = sha

        uncovered = all_release_files - set(cksum_entries.keys())
        if uncovered:
            errors.append(f"checksums missing for: {sorted(uncovered)}")
        else:
            passes.append(f"checksums cover all {len(cksum_entries)} files")

        mismatched = []
        for rel, expected in cksum_entries.items():
            p = DR / rel
            if p.exists():
                actual = hashlib.sha256(p.read_bytes()).hexdigest()
                if actual != expected:
                    mismatched.append(rel)
        check(not mismatched, f"checksums match" if not mismatched else f"checksum mismatch: {mismatched}")

    # ── 3. Splits ────────────────────────────────────────
    train = set((DR / "splits/train.txt").read_text().strip().split("\n"))
    val = set((DR / "splits/val.txt").read_text().strip().split("\n"))
    test = set((DR / "splits/test.txt").read_text().strip().split("\n"))
    total_split = len(train) + len(val) + len(test)
    check(total_split == 7455, f"splits total: {total_split} (expect 7455)")
    check(not (train & val) and not (train & test) and not (val & test), "splits: no overlap")

    # ── 4. Consensus CSV ─────────────────────────────────
    with open(DR / "annotations/consensus_labels_s3.csv") as f:
        cons = list(csv.DictReader(f))
    cons_pids = set(r["patch_id"] for r in cons)
    all_pids = train | val | test
    check(cons_pids == all_pids, f"consensus covers all splits ({len(cons)} rows)")

    # consensus_level check
    levels = Counter(r.get("consensus_level", "") for r in cons)
    bad_levels = set(levels.keys()) - {"high", "medium", "low"}
    check(not bad_levels, f"consensus_level values valid: {dict(levels)}" if not bad_levels else f"invalid consensus_level: {bad_levels}")

    # ── 5. Per-engine CSV ────────────────────────────────
    with open(DR / "annotations/per_engine_labels_s3.csv") as f:
        pe = list(csv.DictReader(f))
    eng_cnt = Counter(r["engine"] for r in pe)
    for eng in ["openai", "claude", "qwen"]:
        check(eng_cnt.get(eng, 0) == 7455, f"{eng}: {eng_cnt.get(eng, 0)} rows (expect 7455)")
    gemini_cnt = eng_cnt.get("gemini", 0)
    check(gemini_cnt > 0, f"gemini: {gemini_cnt} rows (partial)")

    # blank engine check
    blank = sum(1 for r in pe if not r.get("engine", "").strip())
    if blank:
        warn(f"blank engine records: {blank}")

    # gate_pass
    gate_fail = sum(1 for r in pe if r.get("gate_pass") == "False")
    passes.append(f"gate_pass=False: {gate_fail} ({100*gate_fail/len(pe):.2f}%)")

    # ── 6. Taxonomy consistency ──────────────────────────
    tax_path = DR / "taxonomy/hsgf_taxonomy_v2.9.9.json"
    if tax_path.exists():
        tax = json.load(open(tax_path))
        dims = tax.get("dimensions", {})
        for dim in ["D1", "D2", "D3", "D4", "D5"]:
            if dim in dims:
                passes.append(f"taxonomy {dim}: {dims[dim]['count']} labels")

    # ── 7. Engine configs — no API keys ──────────────────
    ec_dir = DR / "engine_configs"
    if ec_dir.exists():
        for cfg_file in ec_dir.glob("*.json"):
            cfg = json.load(open(cfg_file))
            for key in ["api_key", "key", "secret", "token", "password"]:
                check(key not in cfg, f"no secrets in {cfg_file.name}")

    # ── 8. Placeholder check ─────────────────────────────
    placeholder_files = ["README.md", "CITATION.cff", ".zenodo.json", "ethics_and_copyright.md"]
    for fn in placeholder_files:
        p = DR / fn
        if p.exists():
            text = p.read_text()
            if "[To be" in text or "10.xxxx" in text or "XXXXXXX" in text:
                warn(f"placeholder text in {fn}")

    # ── Report ───────────────────────────────────────────
    print("=" * 55)
    print("  validate_release.py — 校验报告")
    print("=" * 55)
    for p in passes:
        print(f"  PASS  {p}")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    print()
    print(f"  {len(passes)} PASS / {len(warnings)} WARN / {len(errors)} FAIL")
    if errors:
        print("  结论: NOT READY")
        sys.exit(1)
    elif warnings:
        print("  结论: PASS with warnings")
    else:
        print("  结论: PASS")

if __name__ == "__main__":
    main()
