"""
STEP2 Manifest 重建脚本
从磁盘实际文件出发，重新扫描所有 tile，生成完整 manifest。
包含：tile_id, source_id, source_path, x, y, width, height, split,
      output_path, checksum, timestamp, overlap, run_id
"""

import os
import csv
import json
import hashlib
import re
from datetime import datetime

PROJECT_ROOT = "L:/yongle_palace_dataset"
PATCH_DIR = os.path.join(PROJECT_ROOT, "02_tiles", "STEP2_patch", "images")
MANIFEST_DIR = os.path.join(PROJECT_ROOT, "02_tiles", "manifests")
QC_DIR = os.path.join(PROJECT_ROOT, "02_tiles", "STEP2_patch", "qc")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")

RUN_ID = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_tile_rebuild"
TIMESTAMP = datetime.now().isoformat()

SOURCE_SPLIT = {
    "yl_raw_001": "train",
    "yl_raw_003": "train",
    "yl_raw_005": "train",
    "yl_raw_004": "val",
    "yl_raw_002": "test",
}

SOURCE_PATHS = {
    "yl_raw_001": "L:/raw/yl_raw_001.jpg",
    "yl_raw_002": "L:/raw/yl_raw_002.jpg",
    "yl_raw_003": "L:/raw/yl_raw_003.jpg",
    "yl_raw_004": "L:/raw/yl_raw_004.jpg",
    "yl_raw_005": "L:/raw/yl_raw_005.jpg",
}

SOURCE_DIMS = {
    "yl_raw_001": (29400, 7511),
    "yl_raw_002": (19220, 7511),
    "yl_raw_003": (29127, 7511),
    "yl_raw_004": (20950, 7511),
    "yl_raw_005": (28223, 7511),
}

PATCH_SIZE = 512
STRIDE = 358
OVERLAP = 154

print(f"=== STEP2 Manifest 重建 ===")
print(f"run_id: {RUN_ID}")

# === 从磁盘扫描所有 tile ===
all_tiles = []
disk_files = {}  # filename -> (split, full_path)
missing_in_manifest = []

for split in ["train", "val", "test"]:
    split_dir = os.path.join(PATCH_DIR, split)
    for fname in os.listdir(split_dir):
        if not fname.endswith(".png"):
            continue
        fpath = os.path.join(split_dir, fname)
        disk_files[fname] = (split, fpath)

print(f"磁盘文件总数: {len(disk_files)}")

# === 解析文件名提取元数据 + 生成 checksum ===
tile_count = 0
errors = []

for fname, (split, fpath) in sorted(disk_files.items()):
    # 解析: yl_raw_NNN_x_y.png
    match = re.match(r'^(yl_raw_\d+)_(\d+)_(\d+)\.png$', fname)
    if not match:
        errors.append({"file": fname, "error": "naming_mismatch"})
        continue

    source_id = match.group(1)
    x = int(match.group(2))
    y = int(match.group(3))

    # 验证 split 一致性
    expected_split = SOURCE_SPLIT.get(source_id)
    if expected_split and expected_split != split:
        errors.append({"file": fname, "error": f"split_mismatch: expected={expected_split}, actual={split}"})

    # Checksum
    h = hashlib.md5()
    with open(fpath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    checksum = h.hexdigest()

    file_size = os.path.getsize(fpath)
    src_w, src_h = SOURCE_DIMS.get(source_id, (0, 0))

    tile_id = f"{source_id}_{x}_{y}"

    all_tiles.append({
        "tile_id": tile_id,
        "tile_filename": fname,
        "source_id": source_id,
        "source_path": SOURCE_PATHS.get(source_id, ""),
        "source_width": src_w,
        "source_height": src_h,
        "x": x,
        "y": y,
        "width": PATCH_SIZE,
        "height": PATCH_SIZE,
        "patch_size": PATCH_SIZE,
        "stride": STRIDE,
        "overlap": OVERLAP,
        "split": split,
        "status": "success",
        "output_path": fpath.replace("\\", "/"),
        "file_size": file_size,
        "checksum_md5": checksum,
        "run_id": RUN_ID,
        "timestamp": TIMESTAMP,
        "config_version": "1.0.0",
    })

    tile_count += 1
    if tile_count % 1000 == 0:
        print(f"  已扫描: {tile_count}/{len(disk_files)}")

print(f"扫描完成: {tile_count} tiles, {len(errors)} errors")

# === 写入 tile_manifest.csv ===
fields = ["tile_id", "tile_filename", "source_id", "source_path", "source_width", "source_height",
          "x", "y", "width", "height", "patch_size", "stride", "overlap", "split", "status",
          "output_path", "file_size", "checksum_md5", "run_id", "timestamp", "config_version"]

csv_path = os.path.join(MANIFEST_DIR, f"tile_manifest_{RUN_ID}.csv")
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(all_tiles)
print(f"tile_manifest.csv: {csv_path}")

# === 写入 tile_manifest.jsonl ===
jsonl_path = os.path.join(MANIFEST_DIR, f"tile_manifest_{RUN_ID}.jsonl")
with open(jsonl_path, "w", encoding="utf-8") as f:
    for t in all_tiles:
        f.write(json.dumps({k: t[k] for k in fields}, ensure_ascii=False) + "\n")
print(f"tile_manifest.jsonl: {jsonl_path}")

# === 写入 split_manifest.csv ===
split_csv = os.path.join(MANIFEST_DIR, f"split_manifest_{RUN_ID}.csv")
with open(split_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["tile_id", "tile_filename", "split", "source_id"])
    for t in all_tiles:
        writer.writerow([t["tile_id"], t["tile_filename"], t["split"], t["source_id"]])
print(f"split_manifest.csv: {split_csv}")

# === 一致性校验 (Step E) ===
# 检查 manifest 每条记录的文件是否存在
manifest_missing = []
for t in all_tiles:
    if not os.path.exists(t["output_path"]):
        manifest_missing.append(t["tile_id"])

# 检查磁盘文件是否都在 manifest 中
manifest_filenames = {t["tile_filename"] for t in all_tiles}
disk_only = [f for f in disk_files if f not in manifest_filenames]

print(f"\n=== Step E: 一致性校验 ===")
print(f"manifest 有但磁盘没有: {len(manifest_missing)}")
print(f"磁盘有但 manifest 没有: {len(disk_only)}")

# 写入一致性报告
mismatch_path = os.path.join(QC_DIR, "step2_missing_or_mismatch.csv")
with open(mismatch_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["type", "tile_id_or_filename", "detail"])
    for m in manifest_missing:
        writer.writerow(["manifest_has_disk_missing", m, ""])
    for d in disk_only:
        writer.writerow(["disk_has_manifest_missing", d, ""])
    for e in errors:
        writer.writerow(["error", e["file"], e["error"]])
print(f"一致性报告: {mismatch_path}")

# === 统计摘要 ===
from collections import defaultdict
split_counts = defaultdict(int)
split_sizes = defaultdict(int)
source_split_map = defaultdict(set)
source_counts = defaultdict(int)
dup_check = defaultdict(int)

for t in all_tiles:
    split_counts[t["split"]] += 1
    split_sizes[t["split"]] += t["file_size"]
    source_split_map[t["source_id"]].add(t["split"])
    source_counts[t["source_id"]] += 1
    dup_check[t["tile_id"]] += 1

# 泄漏检查
leaks = {src: splits for src, splits in source_split_map.items() if len(splits) > 1}
dup_tiles = {tid: cnt for tid, cnt in dup_check.items() if cnt > 1}

print(f"\n=== Source-level 泄漏检查 ===")
print(f"泄漏源: {len(leaks)} {'(CLEAN)' if not leaks else '*** LEAKED ***'}")
for src, splits in leaks.items():
    print(f"  {src}: {splits}")

print(f"重复 tile_id: {len(dup_tiles)}")

print(f"\n=== 最终统计 ===")
total = len(all_tiles)
for sp in ["train", "val", "test"]:
    print(f"  {sp}: {split_counts[sp]} ({split_counts[sp]/total*100:.1f}%)")
print(f"  total: {total}")
total_mb = sum(split_sizes.values()) / 1024 / 1024
print(f"  total size: {total_mb:.1f} MB ({total_mb/1024:.2f} GB)")

# Output JSON summary
summary = {
    "run_id": RUN_ID,
    "timestamp": TIMESTAMP,
    "total_tiles": total,
    "split_counts": dict(split_counts),
    "split_ratios": {k: round(v/total, 4) for k, v in split_counts.items()},
    "source_counts": dict(source_counts),
    "source_split_assignment": {src: list(splits)[0] for src, splits in source_split_map.items()},
    "total_size_mb": round(total_mb, 2),
    "split_sizes_mb": {k: round(v/1024/1024, 2) for k, v in split_sizes.items()},
    "leaks": len(leaks),
    "duplicate_tile_ids": len(dup_tiles),
    "manifest_missing_on_disk": len(manifest_missing),
    "disk_missing_in_manifest": len(disk_only),
    "naming_errors": len(errors),
    "consistency": "PASS" if not manifest_missing and not disk_only and not leaks else "FAIL",
}

summary_json = os.path.join(MANIFEST_DIR, f"step2_summary_{RUN_ID}.json")
with open(summary_json, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"\nSummary JSON: {summary_json}")
print(json.dumps(summary, ensure_ascii=False, indent=2))
