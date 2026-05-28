#!/usr/bin/env python3
"""
build_scientific_data_release.py — Scientific Data 论文数据包生成

Usage:
  python3 scripts/build_scientific_data_release.py --help
  python3 scripts/build_scientific_data_release.py
  python3 scripts/build_scientific_data_release.py --output dataset_release_v2
  python3 scripts/build_scientific_data_release.py --verify-only

生成:
  dataset_release/
    README.md
    LICENSE
    annotations/ (consensus + per-engine)
    taxonomy/ (HSGF schema)
    splits/ (train/val/test)
    statistics/ (alpha, agreement)
    prompts/ (frozen prompt)
    codebook.md
    checksums_sha256.tsv
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))

from canonical_taxonomy import VALID_LABELS, DAMAGE_LABELS

ENGINES = ["openai", "gemini", "claude", "qwen"]
STEP3_DIMS = ["D1", "D2", "D3", "D4", "D5"]


def parse_args():
    p = argparse.ArgumentParser(description="Scientific Data 论文数据包生成")
    p.add_argument("--output", default=str(PROJECT / "dataset_release"),
                    help="输出目录 (默认: dataset_release/)")
    p.add_argument("--buckets", default=str(PROJECT / "output_buckets"),
                    help="分类桶目录 (bridge_to_workstation 的输出)")
    p.add_argument("--verify-only", action="store_true",
                    help="只校验已有数据包")
    return p.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def calc_alpha_nominal(rows: list[dict], dim: str) -> float:
    """Krippendorff's alpha (nominal)."""
    patch_data = defaultdict(dict)
    for r in rows:
        patch_data[r["patch_id"]][r.get("engine", "")] = r.get(dim, "")

    all_values = set()
    for ur in patch_data.values():
        all_values.update(v for v in ur.values() if v)

    Do = 0
    n_pairs = 0
    for ur in patch_data.values():
        vals = [v for v in ur.values() if v]
        m = len(vals)
        if m < 2:
            continue
        for i in range(m):
            for j in range(i + 1, m):
                n_pairs += 1
                if vals[i] != vals[j]:
                    Do += 1
    if n_pairs == 0:
        return float("nan")
    Do /= n_pairs

    vc = Counter()
    total = 0
    for ur in patch_data.values():
        for v in ur.values():
            if v:
                vc[v] += 1
                total += 1
    De = (
        sum(vc[v1] * vc[v2] for v1 in all_values for v2 in all_values if v1 != v2)
        / (total * (total - 1))
        if total > 1
        else 0
    )
    return 1.0 - Do / De if De > 0 else 1.0


def build_release(output_dir: Path, buckets_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    # ─── Annotations ───
    ann_dir = output_dir / "annotations"
    ann_dir.mkdir(exist_ok=True)

    # Copy consensus and per-engine from buckets
    for name in ["consensus_labels_s3.csv", "per_engine_labels_s3.csv"]:
        src = buckets_dir / name
        if src.exists():
            dst = ann_dir / name
            dst.write_bytes(src.read_bytes())
            print(f"  copied: {name}")
        else:
            print(f"  WARNING: {src} not found")

    # ─── Taxonomy ───
    tax_dir = output_dir / "taxonomy"
    tax_dir.mkdir(exist_ok=True)

    taxonomy = {
        "name": "HSGF (Historical Scene Graph Features)",
        "version": "2.9.9",
        "dimensions": {},
    }
    for dim, labels in VALID_LABELS.items():
        taxonomy["dimensions"][dim] = {
            "name": {"D1": "人物身份", "D2": "冠饰类型", "D3": "法器持物",
                      "D4": "保存状态", "D5": "景深层"}.get(dim, dim),
            "labels": labels,
            "count": len(labels),
        }

    with open(tax_dir / "hsgf_taxonomy.json", "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, ensure_ascii=False, indent=2)
    print("  wrote: hsgf_taxonomy.json")

    # ─── Splits ───
    splits_dir = output_dir / "splits"
    splits_dir.mkdir(exist_ok=True)
    tiles = PROJECT / "02_tiles" / "STEP2_patch" / "images"
    for split in ["train", "val", "test"]:
        split_dir = tiles / split
        if split_dir.exists():
            patches = sorted(p.stem for p in split_dir.glob("*.png"))
            (splits_dir / f"{split}.txt").write_text("\n".join(patches) + "\n")
            print(f"  wrote: {split}.txt ({len(patches)} patches)")

    # ─── Statistics ───
    stats_dir = output_dir / "statistics"
    stats_dir.mkdir(exist_ok=True)

    # Load per-engine data for alpha calculation
    pe_path = ann_dir / "per_engine_labels_s3.csv"
    if pe_path.exists():
        with open(pe_path, encoding="utf-8", newline="") as f:
            pe_rows = list(csv.DictReader(f))

        alphas = {}
        for dim in STEP3_DIMS:
            alphas[dim] = round(calc_alpha_nominal(pe_rows, dim), 4)

        with open(stats_dir / "krippendorff_alpha.json", "w", encoding="utf-8") as f:
            json.dump(alphas, f, ensure_ascii=False, indent=2)
        print(f"  wrote: krippendorff_alpha.json — {alphas}")

        # Agreement matrix
        ag_src = buckets_dir / "agreement_matrix.json"
        if ag_src.exists():
            (stats_dir / "agreement_matrix.json").write_bytes(ag_src.read_bytes())
            print("  copied: agreement_matrix.json")
    else:
        print("  WARNING: per_engine_labels_s3.csv not found, skipping statistics")

    # ─── Prompts ───
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    for src_name in ["step3_prompt.yaml", "step3_prompt_v4.1-draft.yaml"]:
        src = PROJECT / "configs" / src_name
        if src.exists():
            (prompts_dir / src_name).write_bytes(src.read_bytes())
            print(f"  copied: {src_name}")

    # ─── LICENSE ───
    (output_dir / "LICENSE").write_text(
        "Creative Commons Attribution 4.0 International (CC BY 4.0)\n"
        "https://creativecommons.org/licenses/by/4.0/\n\n"
        "YongleAI Yongle Palace Mural Dataset\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n",
        encoding="utf-8",
    )
    print("  wrote: LICENSE (CC BY 4.0)")

    # ─── Codebook ───
    codebook_lines = ["# HSGF Codebook\n"]
    for dim in STEP3_DIMS:
        dim_name = {"D1": "人物身份", "D2": "冠饰类型", "D3": "法器持物",
                     "D4": "保存状态", "D5": "景深层"}.get(dim, dim)
        codebook_lines.append(f"\n## {dim} — {dim_name}\n")
        codebook_lines.append(f"| Label | Index |")
        codebook_lines.append(f"|-------|-------|")
        for i, label in enumerate(VALID_LABELS.get(dim, [])):
            codebook_lines.append(f"| {label} | {i} |")

    (output_dir / "codebook.md").write_text("\n".join(codebook_lines) + "\n", encoding="utf-8")
    print("  wrote: codebook.md")

    # ─── README ───
    n_patches = sum(
        len(list((tiles / s).glob("*.png"))) for s in ["train", "val", "test"]
        if (tiles / s).exists()
    )
    readme = f"""# YongleAI Yongle Palace Mural Dataset

## Overview
High-resolution annotation dataset for Chinese ancient murals at the Yongle Palace (永乐宫),
a UNESCO-grade Yuan Dynasty Daoist temple (1247-1358 CE).

## Statistics
- **Total patches**: {n_patches}
- **Annotation dimensions**: 5 (HSGF taxonomy v2.9.9)
- **Annotation engines**: 4 (GPT-4o, Gemini-2.5-Flash, Claude-Sonnet-4, Qwen-VL-Max)
- **Labels**: {sum(len(v) for v in VALID_LABELS.values())} STEP3 labels

## Directory Structure
```
annotations/     Consensus and per-engine labels
taxonomy/         HSGF taxonomy schema (JSON)
splits/           Train/val/test patch lists
statistics/       Krippendorff's alpha, agreement matrices
prompts/          Frozen VLM prompts
codebook.md       Label definitions
LICENSE           CC BY 4.0
checksums_sha256.tsv  File integrity checksums
```

## Citation
[To be added upon publication]

## License
CC BY 4.0
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    print("  wrote: README.md")

    # ─── Checksums ───
    print("\n=== Checksums ===")
    checksum_lines = ["file\tsha256"]
    for f in sorted(output_dir.rglob("*")):
        if f.is_file() and f.name != "checksums_sha256.tsv":
            rel = f.relative_to(output_dir)
            h = sha256_file(f)
            checksum_lines.append(f"{rel}\t{h}")

    (output_dir / "checksums_sha256.tsv").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    print(f"  wrote: checksums_sha256.tsv ({len(checksum_lines) - 1} files)")


def verify_release(output_dir: Path):
    """校验数据包完整性。"""
    print("=== 校验数据包 ===")
    errors = []

    required = [
        "README.md", "LICENSE", "codebook.md", "checksums_sha256.tsv",
        "annotations/consensus_labels_s3.csv",
        "annotations/per_engine_labels_s3.csv",
        "taxonomy/hsgf_taxonomy.json",
        "splits/train.txt", "splits/val.txt", "splits/test.txt",
    ]

    for rel in required:
        p = output_dir / rel
        if not p.exists():
            errors.append(f"MISSING: {rel}")
        else:
            print(f"  ✓ {rel}")

    # Verify checksums
    cksum_path = output_dir / "checksums_sha256.tsv"
    if cksum_path.exists():
        with open(cksum_path) as f:
            reader = csv.reader(f, delimiter="\t")
            next(reader)  # header
            mismatches = 0
            for row in reader:
                if len(row) != 2:
                    continue
                rel, expected = row
                fpath = output_dir / rel
                if fpath.exists():
                    actual = sha256_file(fpath)
                    if actual != expected:
                        errors.append(f"CHECKSUM MISMATCH: {rel}")
                        mismatches += 1
            if mismatches == 0:
                print(f"  ✓ checksums all match")

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
        return False
    else:
        print("\n✓ 数据包完整")
        return True


def main():
    args = parse_args()
    output_dir = Path(args.output)
    buckets_dir = Path(args.buckets)

    if args.verify_only:
        ok = verify_release(output_dir)
        sys.exit(0 if ok else 1)

    print("=== Scientific Data Release Builder ===\n")
    build_release(output_dir, buckets_dir)
    print()
    verify_release(output_dir)


if __name__ == "__main__":
    main()
