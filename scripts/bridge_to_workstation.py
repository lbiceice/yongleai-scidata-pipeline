#!/usr/bin/env python3
"""
bridge_to_workstation.py — 四引擎结果合并 + 共识投票 + 分类桶

Usage:
  python3 scripts/bridge_to_workstation.py --help
  python3 scripts/bridge_to_workstation.py --s3-dir 03_features/runs/ --output output_buckets/
  python3 scripts/bridge_to_workstation.py --s3-dir 03_features/runs/ --output output_buckets/ --pack D1_八主神

可在 batch 未完成时运行（只处理已有数据）。
"""

import argparse
import csv
import json
import os
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))

from canonical_taxonomy import VALID_LABELS

ENGINES = ["openai", "gemini", "claude", "qwen"]
STEP3_DIMS = ["D1", "D2", "D3", "D4", "D5"]
TILES_DIR = PROJECT / "02_tiles" / "STEP2_patch" / "images"


def parse_args():
    p = argparse.ArgumentParser(description="四引擎结果合并 + 共识投票 + 分类桶")
    p.add_argument("--s3-dir", default=str(PROJECT / "03_features" / "runs"),
                    help="STEP3 runs 目录")
    p.add_argument("--s4-dir", default=str(PROJECT / "04_damage" / "runs"),
                    help="STEP4 runs 目录 (可选)")
    p.add_argument("--output", default=str(PROJECT / "output_buckets"),
                    help="输出目录")
    p.add_argument("--pack", default=None,
                    help="打包指定桶为 zip (如: D1_八主神)")
    p.add_argument("--min-engines", type=int, default=2,
                    help="最少引擎数才纳入投票 (默认: 2)")
    return p.parse_args()


def collect_shard_csvs(runs_dir: Path) -> list[dict]:
    """收集所有 shard CSV 行，去重 (patch_id + engine)。"""
    rows = []
    seen = set()
    for csv_path in sorted(runs_dir.rglob("shard_*.csv")):
        try:
            with open(csv_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or "D1" not in reader.fieldnames:
                    continue
                for row in reader:
                    key = (row.get("patch_id", ""), row.get("engine", ""))
                    if key[0] and key not in seen:
                        seen.add(key)
                        rows.append(row)
        except Exception:
            continue
    return rows


def vote_consensus(rows: list[dict], dims: list[str], min_engines: int) -> list[dict]:
    """按 patch_id 四引擎投票。"""
    # Group by patch_id
    by_patch = defaultdict(list)
    for r in rows:
        by_patch[r["patch_id"]].append(r)

    consensus = []
    for pid, engine_rows in sorted(by_patch.items()):
        n_engines = len(engine_rows)
        if n_engines < min_engines:
            continue

        entry = {"patch_id": pid, "n_engines": n_engines, "split": engine_rows[0].get("split", "")}

        # Vote per dimension
        all_agree = True
        for dim in dims:
            vals = [r.get(dim, "") for r in engine_rows if r.get(dim)]
            if not vals:
                entry[dim] = ""
                entry[f"{dim}_agreement"] = 0
                all_agree = False
                continue
            counter = Counter(vals)
            winner, count = counter.most_common(1)[0]
            entry[dim] = winner
            entry[f"{dim}_agreement"] = count
            entry[f"{dim}_total"] = len(vals)
            if count < len(vals):
                all_agree = False

        # Confidence bucket
        agree_ratio = min(
            entry.get(f"{dim}_agreement", 0) / max(entry.get(f"{dim}_total", 1), 1)
            for dim in dims if entry.get(f"{dim}_total", 0) > 0
        ) if any(entry.get(f"{dim}_total", 0) > 0 for dim in dims) else 0

        if n_engines >= 4 and all_agree:
            entry["consensus"] = "high"
        elif agree_ratio >= 0.75:
            entry["consensus"] = "medium"
        else:
            entry["consensus"] = "review"

        consensus.append(entry)
    return consensus


def build_agreement_matrix(rows: list[dict], dims: list[str]) -> dict:
    """引擎对之间的 Cohen's Kappa 近似（简化为 agreement rate）。"""
    by_patch = defaultdict(dict)
    for r in rows:
        by_patch[r["patch_id"]][r.get("engine", "")] = r

    matrix = {}
    for dim in dims:
        dim_matrix = {}
        for e1 in ENGINES:
            for e2 in ENGINES:
                if e1 >= e2:
                    continue
                agree = 0
                total = 0
                for pid, engines in by_patch.items():
                    if e1 in engines and e2 in engines:
                        v1 = engines[e1].get(dim, "")
                        v2 = engines[e2].get(dim, "")
                        if v1 and v2:
                            total += 1
                            if v1 == v2:
                                agree += 1
                if total > 0:
                    dim_matrix[f"{e1}_vs_{e2}"] = {
                        "agree": agree, "total": total,
                        "rate": round(agree / total, 4),
                    }
        matrix[dim] = dim_matrix
    return matrix


def create_buckets(consensus: list[dict], output_dir: Path, dims: list[str]):
    """创建分类桶 symlink 目录。"""
    # D1 buckets (big)
    for label in VALID_LABELS.get("D1", []):
        bucket = output_dir / f"D1_{label}"
        bucket.mkdir(parents=True, exist_ok=True)
        members = [e for e in consensus if e.get("D1") == label]
        _write_bucket_manifest(bucket, members, f"D1={label}")

    # D4 buckets (big)
    for label in VALID_LABELS.get("D4", []):
        bucket = output_dir / f"D4_{label}"
        bucket.mkdir(parents=True, exist_ok=True)
        members = [e for e in consensus if e.get("D4") == label]
        _write_bucket_manifest(bucket, members, f"D4={label}")

    # D2 buckets (small)
    for label in VALID_LABELS.get("D2", []):
        if label in ("N/A", "无"):
            continue
        bucket = output_dir / f"D2_{label}"
        bucket.mkdir(parents=True, exist_ok=True)
        members = [e for e in consensus if e.get("D2") == label]
        _write_bucket_manifest(bucket, members, f"D2={label}")

    # D3 buckets (small)
    for label in VALID_LABELS.get("D3", []):
        if label == "N/A":
            continue
        bucket = output_dir / f"D3_{label}"
        bucket.mkdir(parents=True, exist_ok=True)
        members = [e for e in consensus if e.get("D3") == label]
        _write_bucket_manifest(bucket, members, f"D3={label}")

    # Consensus buckets
    for level in ["high", "medium", "review"]:
        bucket = output_dir / f"consensus_{level}"
        bucket.mkdir(parents=True, exist_ok=True)
        members = [e for e in consensus if e.get("consensus") == level]
        _write_bucket_manifest(bucket, members, f"consensus={level}")

    # Symlinks to patch images
    for entry in consensus:
        pid = entry["patch_id"]
        split = entry.get("split", "train")
        src = TILES_DIR / split / f"{pid}.png"
        if not src.exists():
            continue

        # Link into D1 bucket
        d1 = entry.get("D1", "")
        if d1:
            dst = output_dir / f"D1_{d1}" / f"{pid}.png"
            if not dst.exists():
                try:
                    dst.symlink_to(src)
                except OSError:
                    pass

        # Link into consensus bucket
        cons = entry.get("consensus", "review")
        dst = output_dir / f"consensus_{cons}" / f"{pid}.png"
        if not dst.exists():
            try:
                dst.symlink_to(src)
            except OSError:
                pass


def _write_bucket_manifest(bucket: Path, members: list, description: str):
    """Write manifest.csv and README.md for a bucket."""
    # manifest.csv
    manifest_path = bucket / "manifest.csv"
    if members:
        fieldnames = list(members[0].keys())
        with open(manifest_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(members)
    else:
        manifest_path.write_text("patch_id\n", encoding="utf-8")

    # README.md
    readme = bucket / "README.md"
    readme.write_text(
        f"# {bucket.name}\n\n"
        f"Filter: {description}\n"
        f"Count: {len(members)}\n",
        encoding="utf-8",
    )


def pack_bucket(output_dir: Path, bucket_name: str):
    """打包指定桶为 zip。"""
    bucket = output_dir / bucket_name
    if not bucket.is_dir():
        print(f"ERROR: bucket not found: {bucket}", file=sys.stderr)
        sys.exit(1)
    zip_path = output_dir / f"{bucket_name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(bucket.rglob("*")):
            if f.is_file():
                # Resolve symlinks
                real = f.resolve() if f.is_symlink() else f
                zf.write(real, f"{bucket_name}/{f.name}")
    print(f"Packed: {zip_path} ({zip_path.stat().st_size // 1024}KB)")


def main():
    args = parse_args()
    s3_dir = Path(args.s3_dir)
    output_dir = Path(args.output)

    # Pack mode
    if args.pack:
        pack_bucket(output_dir, args.pack)
        return

    print("=== 收集 shard CSV ===")
    rows = collect_shard_csvs(s3_dir)
    print(f"  {len(rows)} 行 (去重后)")
    if not rows:
        print("ERROR: 无数据", file=sys.stderr)
        sys.exit(1)

    # Per-engine stats
    eng_counts = Counter(r.get("engine", "") for r in rows)
    for eng, cnt in sorted(eng_counts.items()):
        print(f"  {eng}: {cnt} rows")

    # Unique patches
    unique_patches = set(r["patch_id"] for r in rows)
    print(f"  unique patches: {len(unique_patches)}")

    # Vote
    print("\n=== 共识投票 ===")
    consensus = vote_consensus(rows, STEP3_DIMS, args.min_engines)
    cons_counts = Counter(e["consensus"] for e in consensus)
    print(f"  total: {len(consensus)} patches")
    for level in ["high", "medium", "review"]:
        print(f"  {level}: {cons_counts.get(level, 0)}")

    # Save consensus CSV
    output_dir.mkdir(parents=True, exist_ok=True)
    cons_path = output_dir / "consensus_labels_s3.csv"
    if consensus:
        fieldnames = list(consensus[0].keys())
        with open(cons_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(consensus)
        print(f"  saved: {cons_path}")

    # Per-engine labels
    eng_path = output_dir / "per_engine_labels_s3.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(eng_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"  saved: {eng_path}")

    # Agreement matrix
    print("\n=== 引擎间一致性 ===")
    matrix = build_agreement_matrix(rows, STEP3_DIMS)
    matrix_path = output_dir / "agreement_matrix.json"
    with open(matrix_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, ensure_ascii=False, indent=2)
    print(f"  saved: {matrix_path}")

    for dim in STEP3_DIMS:
        pairs = matrix.get(dim, {})
        if pairs:
            avg_rate = sum(p["rate"] for p in pairs.values()) / len(pairs)
            print(f"  {dim} avg agreement: {avg_rate:.1%}")

    # Bucket index
    bucket_index = {
        "D1": {label: sum(1 for e in consensus if e.get("D1") == label)
                for label in VALID_LABELS.get("D1", [])},
        "D4": {label: sum(1 for e in consensus if e.get("D4") == label)
                for label in VALID_LABELS.get("D4", [])},
        "consensus": dict(cons_counts),
        "total_patches": len(consensus),
    }
    idx_path = output_dir / "bucket_index.json"
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(bucket_index, f, ensure_ascii=False, indent=2)
    print(f"  saved: {idx_path}")

    # Create buckets
    print("\n=== 创建分类桶 ===")
    create_buckets(consensus, output_dir, STEP3_DIMS)
    bucket_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
    non_empty = sum(1 for d in bucket_dirs if any(d.glob("*.png")))
    print(f"  {len(bucket_dirs)} 桶, {non_empty} 桶有 symlink")

    print("\n=== 完成 ===")


if __name__ == "__main__":
    main()
