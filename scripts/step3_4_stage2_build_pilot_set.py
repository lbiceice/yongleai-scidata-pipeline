#!/usr/bin/env python3
"""
Stage 2: 构建 Stratified Pilot Set
- 从 STEP2 train split 按图像统计量分层抽样 20 张
- 写出 pilot/stratified_goldset.csv
- 写出 pilot/pilot_sampling_notes.md
- 不调用任何 API
- 幂等：重复执行覆盖产物

用法:
  python3 scripts/step3_4_stage2_build_pilot_set.py
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import yaml
from PIL import Image

# ─── Paths ───
BASE = Path("/Volumes/小满/yongle_palace_dataset")
STATE_FILE = BASE / "state/step3_4_stage_state.json"
PILOT_PLAN = BASE / "configs/step3_4_pilot_plan.yaml"
SPLIT_MANIFEST = BASE / "02_tiles/manifests/split_manifest_run_20260401_231737_tile_rebuild.csv"
PATCH_DIR = BASE / "02_tiles/STEP2_patch/images/train"

STAGE = "stage2_build_pilot"


def load_state() -> dict:
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    state["updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def check_prereq(state: dict):
    s1 = state["stages"]["stage1_freeze"]["status"]
    if s1 != "completed":
        print(f"ERROR: stage1_freeze status={s1}, must be 'completed'. Run stage1 first.")
        sys.exit(1)


def compute_patch_stats(train_df: pd.DataFrame) -> pd.DataFrame:
    """计算每张 patch 的图像统计量（用于分层代理）"""
    records = []
    total = len(train_df)
    for idx, row in train_df.iterrows():
        p = PATCH_DIR / row["tile_filename"]
        if not p.exists():
            continue
        img = Image.open(p).convert("RGB")
        arr = np.array(img, dtype=np.float32)
        mean_val = float(arr.mean())
        std_val = float(arr.std())
        gray = arr.mean(axis=2)
        dx = np.diff(gray, axis=1)
        dy = np.diff(gray, axis=0)
        edge_var = float((dx.var() + dy.var()) / 2)
        records.append({
            "tile_id": row["tile_id"],
            "tile_filename": row["tile_filename"],
            "source_id": row["source_id"],
            "mean": mean_val,
            "std": std_val,
            "edge_var": edge_var,
        })
        if (len(records) % 500) == 0:
            print(f"  Stats: {len(records)}/{total} ...", flush=True)
    return pd.DataFrame(records)


def stratified_sample(sdf: pd.DataFrame, plan: dict) -> pd.DataFrame:
    """按 pilot plan 中的分层规则抽样"""
    used = set()
    picks = []

    def pick(candidates, n, stratum_name):
        avail = candidates[~candidates["tile_id"].isin(used)].sort_values("tile_id")
        selected = avail.head(n).copy()
        selected["stratum"] = stratum_name
        used.update(selected["tile_id"].tolist())
        return selected

    # Bin 1: intact_background — high mean, low edge_var
    q_mean_75 = sdf["mean"].quantile(0.75)
    q_edge_30 = sdf["edge_var"].quantile(0.30)
    bin1 = sdf[(sdf["mean"] > q_mean_75) & (sdf["edge_var"] < q_edge_30)]
    picks.append(pick(bin1, 4, "intact_background"))

    # Bin 2: ink_line_confusion — very high edge_var
    q_edge_90 = sdf["edge_var"].quantile(0.90)
    bin2 = sdf[sdf["edge_var"] > q_edge_90]
    picks.append(pick(bin2, 4, "ink_line_confusion"))

    # Bin 3: soot_dust_mold — very dark, moderate std
    q_mean_15 = sdf["mean"].quantile(0.15)
    q_std_30 = sdf["std"].quantile(0.30)
    bin3 = sdf[(sdf["mean"] < q_mean_15) & (sdf["std"] > q_std_30)]
    picks.append(pick(bin3, 4, "soot_dust_mold"))

    # Bin 4: flaking_fading — mid brightness, high std
    q_mean_30 = sdf["mean"].quantile(0.30)
    q_mean_70 = sdf["mean"].quantile(0.70)
    q_std_70 = sdf["std"].quantile(0.70)
    bin4 = sdf[(sdf["mean"] > q_mean_30) & (sdf["mean"] < q_mean_70) & (sdf["std"] > q_std_70)]
    picks.append(pick(bin4, 4, "flaking_fading"))

    # Bin 5: mixed_severe — low mean, high edge + high std
    q_mean_40 = sdf["mean"].quantile(0.40)
    q_edge_60 = sdf["edge_var"].quantile(0.60)
    q_std_60 = sdf["std"].quantile(0.60)
    bin5 = sdf[(sdf["mean"] < q_mean_40) & (sdf["edge_var"] > q_edge_60) & (sdf["std"] > q_std_60)]
    picks.append(pick(bin5, 4, "mixed_severe"))

    result = pd.concat(picks, ignore_index=True)
    return result, {
        "bin_sizes": {
            "intact_background": len(bin1),
            "ink_line_confusion": len(bin2),
            "soot_dust_mold": len(bin3),
            "flaking_fading": len(bin4),
            "mixed_severe": len(bin5),
        },
        "quantiles": {
            "mean_Q15": round(q_mean_15, 2),
            "mean_Q30": round(q_mean_30, 2),
            "mean_Q40": round(q_mean_40, 2),
            "mean_Q70": round(q_mean_70, 2),
            "mean_Q75": round(q_mean_75, 2),
            "edge_var_Q30": round(q_edge_30, 2),
            "edge_var_Q60": round(q_edge_60, 2),
            "edge_var_Q90": round(q_edge_90, 2),
            "std_Q30": round(q_std_30, 2),
            "std_Q60": round(q_std_60, 2),
            "std_Q70": round(q_std_70, 2),
        },
    }


def main():
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Check prereq ──
    state = load_state()
    check_prereq(state)

    # ── Update state ──
    state["current_stage"] = STAGE
    state["stages"][STAGE]["status"] = "running"
    state["stages"][STAGE]["started"] = ts_str
    save_state(state)

    output_files = []

    # ── Load pilot plan ──
    with open(PILOT_PLAN) as f:
        plan = yaml.safe_load(f)

    # ── Load split manifest ──
    print(f"=== Stage 2: Build Pilot Set ===")
    split_df = pd.read_csv(SPLIT_MANIFEST)
    train_df = split_df[split_df["split"] == "train"].sort_values("tile_id").reset_index(drop=True)
    print(f"Train patches: {len(train_df)}")

    # ── Compute stats ──
    print("Computing image statistics...")
    sdf = compute_patch_stats(train_df)
    print(f"Stats computed for {len(sdf)} patches")

    # ── Stratified sample ──
    pilot_df, sample_meta = stratified_sample(sdf, plan)
    print(f"Pilot samples: {len(pilot_df)}")
    print(pilot_df[["tile_id", "stratum"]].to_string(index=False))

    # ── Save goldset ──
    pilot_dir = BASE / "pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)

    goldset_path = pilot_dir / "stratified_goldset.csv"
    pilot_df.to_csv(goldset_path, index=False, encoding="utf-8-sig")
    output_files.append(str(goldset_path))

    # ── Save stats cache (so stage3 can reference) ──
    stats_path = pilot_dir / "pilot_image_stats.csv"
    sdf.to_csv(stats_path, index=False)
    output_files.append(str(stats_path))

    # ── Generate sampling notes ──
    notes_path = pilot_dir / "pilot_sampling_notes.md"
    strata_table = "| Stratum | Count | Pool Size | Proxy Rule |\n|---------|-------|-----------|------------|\n"
    for sname, scount in sample_meta["bin_sizes"].items():
        picked = len(pilot_df[pilot_df["stratum"] == sname])
        rule = plan["pilot"]["strata"][[s for s in plan["pilot"]["strata"] if s["name"] == sname][0]["name"] == sname and 1 or 0]["proxy"] if False else ""
        # Get rule from plan
        for s in plan["pilot"]["strata"]:
            if s["name"] == sname:
                rule = s["proxy"]
                break
        strata_table += f"| {sname} | {picked} | {scount} | {rule} |\n"

    notes = f"""# Pilot Sampling Notes

**Generated:** {ts_str}
**Source:** train split (n={len(train_df)})
**Selected:** {len(pilot_df)} patches

## Method

Stratified sampling using image-level statistics as proxy (no prior labels).
Deterministic: sorted by tile_id, pick first 4 per bin, no overlap between bins.

## Strata

{strata_table}

## Quantile Thresholds

| Metric | Quantile | Value |
|--------|----------|-------|
"""
    for k, v in sample_meta["quantiles"].items():
        notes += f"| {k} | — | {v} |\n"

    notes += f"""
## Patch List

| # | tile_id | stratum | mean | std | edge_var |
|---|---------|---------|------|-----|----------|
"""
    for i, row in pilot_df.iterrows():
        notes += f"| {i+1} | {row['tile_id']} | {row['stratum']} | {row['mean']:.1f} | {row['std']:.1f} | {row['edge_var']:.1f} |\n"

    with open(notes_path, "w") as f:
        f.write(notes)
    output_files.append(str(notes_path))

    # ── Generate stage report ──
    report_path = BASE / "reports" / "step3_4_stage2_pilot_build_report.md"
    report = f"""# Stage 2: Pilot Set Build Report

**Generated:** {ts_str}
**Train pool:** {len(train_df)} patches
**Pilot set:** {len(pilot_df)} patches
**Strata:** {len(sample_meta['bin_sizes'])}

## Files
- `{goldset_path}`
- `{notes_path}`
- `{stats_path}`

## Next Step
Run `python3 scripts/step3_4_stage3_run_pilot.py`
"""
    with open(report_path, "w") as f:
        f.write(report)
    output_files.append(str(report_path))

    # ── Update state ──
    state = load_state()
    state["stages"][STAGE]["status"] = "completed"
    state["stages"][STAGE]["completed"] = datetime.now(timezone.utc).isoformat()
    state["stages"][STAGE]["output_files"] = output_files
    save_state(state)

    print(f"\n=== Stage 2 COMPLETE ===")
    for p in output_files:
        print(f"  {p}")


if __name__ == "__main__":
    main()
