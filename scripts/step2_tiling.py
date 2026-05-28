"""
STEP2 切片脚本 - 永乐宫壁画数据集
顶刊级数据集生产，非普通裁剪脚本

参数:
  patch_size: 512x512
  stride: 358
  overlap: 30% (154px)
  format: PNG lossless (compress_level=1)
  split: 80/10/10 (seed=42, patch-level)
"""

import os
import sys
import csv
import json
import math
import hashlib
import numpy as np
from PIL import Image
from datetime import datetime
import random

Image.MAX_IMAGE_PIXELS = None

# === 配置 ===
PATCH_SIZE = 512
STRIDE = 358
COMPRESS_LEVEL = 1
RANDOM_SEED = 42
SPLIT_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
PROGRESS_INTERVAL = 300

PROJECT_ROOT = "L:/yongle_palace_dataset"
RAW_DIR = "L:/raw"
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "02_tiles", "STEP2_patch", "images")
MANIFEST_DIR = os.path.join(PROJECT_ROOT, "02_tiles", "manifests")
LOG_DIR = os.path.join(PROJECT_ROOT, "02_tiles", "logs")

# run_id
RUN_ID = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_tile"
START_TIME = datetime.now().isoformat()

os.makedirs(MANIFEST_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
for split in ["train", "val", "test"]:
    os.makedirs(os.path.join(OUTPUT_BASE, split), exist_ok=True)

# === 日志 ===
log_path = os.path.join(LOG_DIR, f"step2_{RUN_ID}.log")
log_file = open(log_path, "w", encoding="utf-8")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    log_file.write(line + "\n")
    log_file.flush()

log(f"STEP2 切片开始")
log(f"run_id: {RUN_ID}")
log(f"patch_size: {PATCH_SIZE}, stride: {STRIDE}, overlap: {PATCH_SIZE - STRIDE}px ({(PATCH_SIZE - STRIDE)/PATCH_SIZE*100:.0f}%)")
log(f"output_format: PNG lossless (compress_level={COMPRESS_LEVEL})")
log(f"split: train={SPLIT_RATIOS['train']}, val={SPLIT_RATIOS['val']}, test={SPLIT_RATIOS['test']}, seed={RANDOM_SEED}")

# === 扫描原图 ===
raw_files = sorted([f for f in os.listdir(RAW_DIR) if f.endswith('.jpg') and not f.startswith('._')])
log(f"原图数量: {len(raw_files)}")

# === 第一遍：计算所有 tile 坐标 ===
all_tiles = []
for raw_f in raw_files:
    raw_path = os.path.join(RAW_DIR, raw_f)
    img = Image.open(raw_path)
    w, h = img.size
    img.close()

    source_id = raw_f.replace('.jpg', '')

    # 计算 tile 网格
    tiles_x = math.ceil((w - PATCH_SIZE) / STRIDE) + 1
    tiles_y = math.ceil((h - PATCH_SIZE) / STRIDE) + 1

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            x = tx * STRIDE
            y = ty * STRIDE
            # 确保不超出边界
            if x + PATCH_SIZE > w:
                x = w - PATCH_SIZE
            if y + PATCH_SIZE > h:
                y = h - PATCH_SIZE

            tile_id = f"{source_id}_{x}_{y}"
            tile_filename = f"{source_id}_{x}_{y}.png"

            all_tiles.append({
                "tile_id": tile_id,
                "tile_filename": tile_filename,
                "source_file": raw_f,
                "source_path": raw_path,
                "source_id": source_id,
                "source_width": w,
                "source_height": h,
                "x": x,
                "y": y,
                "patch_size": PATCH_SIZE,
                "stride": STRIDE,
                "tx": tx,
                "ty": ty,
            })

    log(f"  {raw_f}: {w}x{h} → {tiles_x}x{tiles_y} = {tiles_x * tiles_y} tiles")

total_tiles = len(all_tiles)
log(f"总切片数: {total_tiles}")

# === 去重检查 ===
tile_coords = set()
duplicates = 0
for t in all_tiles:
    key = (t["source_id"], t["x"], t["y"])
    if key in tile_coords:
        duplicates += 1
    tile_coords.add(key)

# 由于边缘对齐，可能有坐标重复，去重
if duplicates > 0:
    seen = set()
    unique_tiles = []
    for t in all_tiles:
        key = (t["source_id"], t["x"], t["y"])
        if key not in seen:
            seen.add(key)
            unique_tiles.append(t)
    log(f"去重: {duplicates} 个重复坐标被移除，剩余 {len(unique_tiles)} 个唯一 tile")
    all_tiles = unique_tiles
    total_tiles = len(all_tiles)

# === 划分 train/val/test ===
random.seed(RANDOM_SEED)
indices = list(range(total_tiles))
random.shuffle(indices)

n_train = int(total_tiles * SPLIT_RATIOS["train"])
n_val = int(total_tiles * SPLIT_RATIOS["val"])
n_test = total_tiles - n_train - n_val

train_indices = set(indices[:n_train])
val_indices = set(indices[n_train:n_train + n_val])
test_indices = set(indices[n_train + n_val:])

for i, t in enumerate(all_tiles):
    if i in train_indices:
        t["split"] = "train"
    elif i in val_indices:
        t["split"] = "val"
    else:
        t["split"] = "test"

log(f"划分: train={n_train}, val={n_val}, test={n_test}")

# === 第二遍：逐图加载并切片 ===
completed = 0
failed_count = 0
failed_records = []

current_source = None
current_img_array = None

for t in all_tiles:
    # 按需加载原图（避免重复加载同一张）
    if t["source_path"] != current_source:
        if current_img_array is not None:
            del current_img_array
        current_source = t["source_path"]
        log(f"加载原图: {t['source_file']}")
        img = Image.open(current_source)
        current_img_array = np.array(img)
        img.close()
        log(f"  numpy array shape: {current_img_array.shape}")

    # numpy 切片
    x, y = t["x"], t["y"]
    try:
        patch = current_img_array[y:y+PATCH_SIZE, x:x+PATCH_SIZE]

        if patch.shape[0] != PATCH_SIZE or patch.shape[1] != PATCH_SIZE:
            raise ValueError(f"Patch size mismatch: {patch.shape}")

        # 保存
        out_dir = os.path.join(OUTPUT_BASE, t["split"])
        out_path = os.path.join(out_dir, t["tile_filename"])

        patch_img = Image.fromarray(patch)
        patch_img.save(out_path, format="PNG", compress_level=COMPRESS_LEVEL)

        t["output_path"] = out_path
        t["status"] = "success"
        t["file_size"] = os.path.getsize(out_path)

        completed += 1

        if completed % PROGRESS_INTERVAL == 0:
            log(f"进度: {completed}/{total_tiles} ({completed/total_tiles*100:.1f}%)")

    except Exception as e:
        t["status"] = "failed"
        t["error"] = str(e)
        t["output_path"] = ""
        t["file_size"] = 0
        failed_count += 1
        failed_records.append(t.copy())
        log(f"FAILED: {t['tile_id']} - {e}")

if current_img_array is not None:
    del current_img_array

END_TIME = datetime.now().isoformat()
log(f"切片完成: {completed} 成功, {failed_count} 失败, 总计 {total_tiles}")

# === 写入 tile manifest ===
manifest_csv = os.path.join(MANIFEST_DIR, f"tile_manifest_{RUN_ID}.csv")
manifest_jsonl = os.path.join(MANIFEST_DIR, f"tile_manifest_{RUN_ID}.jsonl")

fields = ["tile_id", "tile_filename", "source_file", "source_id", "source_width", "source_height",
          "x", "y", "patch_size", "stride", "tx", "ty", "split", "status", "output_path", "file_size"]

with open(manifest_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(all_tiles)

with open(manifest_jsonl, "w", encoding="utf-8") as f:
    for t in all_tiles:
        row = {k: t.get(k) for k in fields}
        row["run_id"] = RUN_ID
        row["config_version"] = "1.0.0"
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

log(f"Tile manifest 已写入: {manifest_csv}")

# === 写入 split manifest ===
split_manifest_path = os.path.join(MANIFEST_DIR, f"split_manifest_{RUN_ID}.csv")
with open(split_manifest_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["tile_id", "tile_filename", "split", "source_id"])
    for t in all_tiles:
        if t["status"] == "success":
            writer.writerow([t["tile_id"], t["tile_filename"], t["split"], t["source_id"]])

log(f"Split manifest 已写入: {split_manifest_path}")

# === 写入 failed 记录 ===
if failed_records:
    failed_path = os.path.join(PROJECT_ROOT, "02_tiles", "failed", f"failed_{RUN_ID}.json")
    with open(failed_path, "w", encoding="utf-8") as f:
        json.dump(failed_records, f, ensure_ascii=False, indent=2)
    log(f"Failed 记录已写入: {failed_path}")

# === QC 统计 ===
split_counts = {"train": 0, "val": 0, "test": 0}
split_sizes = {"train": 0, "val": 0, "test": 0}
source_counts = {}
for t in all_tiles:
    if t["status"] == "success":
        split_counts[t["split"]] += 1
        split_sizes[t["split"]] += t.get("file_size", 0)
        src = t["source_id"]
        source_counts[src] = source_counts.get(src, 0) + 1

total_size_mb = sum(split_sizes.values()) / 1024 / 1024

# === 写入 summary ===
summary = {
    "run_id": RUN_ID,
    "start_time": START_TIME,
    "end_time": END_TIME,
    "config_version": "1.0.0",
    "operator": "claude_code",
    "patch_size": PATCH_SIZE,
    "stride": STRIDE,
    "overlap_pixels": PATCH_SIZE - STRIDE,
    "overlap_ratio": round((PATCH_SIZE - STRIDE) / PATCH_SIZE, 2),
    "output_format": "PNG",
    "compress_level": COMPRESS_LEVEL,
    "random_seed": RANDOM_SEED,
    "split_strategy": "patch_level",
    "split_ratios": SPLIT_RATIOS,
    "total_source_images": len(raw_files),
    "total_tiles": total_tiles,
    "successful_tiles": completed,
    "failed_tiles": failed_count,
    "split_counts": split_counts,
    "source_tile_counts": source_counts,
    "total_output_size_mb": round(total_size_mb, 2),
    "split_sizes_mb": {k: round(v/1024/1024, 2) for k, v in split_sizes.items()},
    "tile_manifest": manifest_csv,
    "split_manifest": split_manifest_path,
}

summary_path = os.path.join(MANIFEST_DIR, f"step2_summary_{RUN_ID}.json")
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

log(f"Summary 已写入: {summary_path}")

# === 打印最终统计 ===
log("=" * 60)
log("STEP2 切片最终统计")
log(f"  总切片数: {total_tiles}")
log(f"  成功: {completed}")
log(f"  失败: {failed_count}")
log(f"  train: {split_counts['train']}")
log(f"  val: {split_counts['val']}")
log(f"  test: {split_counts['test']}")
log(f"  总输出大小: {total_size_mb:.1f} MB ({total_size_mb/1024:.2f} GB)")
log(f"  各源图切片数:")
for src, cnt in sorted(source_counts.items()):
    log(f"    {src}: {cnt}")
log("=" * 60)

# Print summary to stdout for capture
print(json.dumps(summary, ensure_ascii=False, indent=2))

log_file.close()
