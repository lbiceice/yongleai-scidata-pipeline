#!/usr/bin/env python3
"""
STEP3 A/B Test: v4.0.1-patch (baseline) vs v4.1-draft (candidate)
200 patches x 4 engines x 2 prompt versions

Usage:
  python3 step3_ab_200.py                    # 全量 200 patches
  python3 step3_ab_200.py --dry-run          # 只打印计划，不调用 API
  python3 step3_ab_200.py --limit 10         # 调试: 前 10 patches
  python3 step3_ab_200.py --version v4.1     # 只跑 candidate (快速验证)

输出:
  03_features/runs/ab_200_{timestamp}/
    ab_results_v40.csv
    ab_results_v41.csv
    ab_comparison.json
"""
import os, sys, json, csv, re, time, yaml, random, argparse, datetime
from pathlib import Path
from collections import Counter

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))

from step3_4_transport import (
    load_engines, build_step3_4_message,
    image_to_b64_thumbnail, RateLimiter, call_with_retry
)
from canonical_taxonomy import (
    VALID_LABELS, normalize_label, validate_d1_d2_d3_consistency
)

# ── CLI ──
parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="打印计划不调用 API")
parser.add_argument("--limit", type=int, default=200, help="patch 数量上限")
parser.add_argument("--version", choices=["both", "v4.0", "v4.1"], default="both",
                    help="跑哪个版本")
parser.add_argument("--seed", type=int, default=42, help="随机种子")
args = parser.parse_args()

# ── Prompt configs ──
CONFIGS = {
    "v4.0": yaml.safe_load(open(PROJECT / "configs/step3_prompt.yaml")),
    "v4.1": yaml.safe_load(open(PROJECT / "configs/step3_prompt_v4.1-draft.yaml")),
}

# ── Patch sampling: 200 stratified from train split ──
pilot_csv = PROJECT / "04_damage/runs/step4_damage_init_20260403_203630/manifests/step4_pilot_benchmark_set.csv"
with open(pilot_csv) as f:
    all_patches = list(csv.DictReader(f))

# Also add from the full train manifest if available
train_manifest = PROJECT / "02_tiles/STEP2_patch/manifests/train_manifest.csv"
if train_manifest.exists():
    with open(train_manifest) as f:
        extra = list(csv.DictReader(f))
    # Merge, deduplicate by patch_id
    seen = {p["patch_id"] for p in all_patches}
    for p in extra:
        if p.get("patch_id") and p["patch_id"] not in seen:
            all_patches.append(p)
            seen.add(p["patch_id"])

# If we still don't have enough, scan the train directory
if len(all_patches) < args.limit:
    TILES = PROJECT / "02_tiles/STEP2_patch/images/train"
    if TILES.exists():
        seen = {p["patch_id"] for p in all_patches}
        for png in sorted(TILES.glob("*.png")):
            pid = png.stem
            if pid not in seen:
                all_patches.append({
                    "patch_id": pid, "split": "train",
                    "source_id": "", "wall": "unknown",
                    "group": "auto", "group_label": "auto"
                })
                seen.add(pid)

random.seed(args.seed)
random.shuffle(all_patches)
selected = all_patches[:args.limit]

print(f"A/B Test: {len(selected)} patches x 4 engines x {'2 prompts' if args.version == 'both' else '1 prompt'}")
if args.dry_run:
    versions_to_run = ["v4.0", "v4.1"] if args.version == "both" else [args.version]
    total_calls = len(selected) * 4 * len(versions_to_run)
    print(f"DRY RUN — would make {total_calls} API calls")
    print(f"Patches: {[p['patch_id'] for p in selected[:5]]}...")
    sys.exit(0)

# ── Setup ──
TILES = PROJECT / "02_tiles/STEP2_patch/images"
engines = load_engines()
engine_names = ["openai", "gemini", "claude", "qwen"]
limiter = RateLimiter(min_interval_s=1.0, max_rpm=30)

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = PROJECT / f"03_features/runs/ab_200_{ts}"
os.makedirs(RUN_DIR, exist_ok=True)

def extract_json(text):
    if not text: return None
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m: text = m.group(1)
    text = text.strip()
    try: return json.loads(text)
    except:
        m2 = re.search(r'\{.*\}', text, re.DOTALL)
        if m2:
            try: return json.loads(m2.group())
            except: pass
    return None

def json_validator(content):
    return extract_json(content)

versions_to_run = ["v4.0", "v4.1"] if args.version == "both" else [args.version]
results = {v: [] for v in versions_to_run}

t_start = time.time()

for pi, p in enumerate(selected):
    pid = p["patch_id"]
    split = p.get("split", "train")
    img_path = TILES / split / f"{pid}.png"
    if not img_path.exists():
        print(f"  [{pi+1}/{len(selected)}] {pid} — NOT FOUND, skip")
        continue
    img_b64 = image_to_b64_thumbnail(str(img_path), max_size=512)
    print(f"[{pi+1}/{len(selected)}] {pid}", end="", flush=True)

    for vname in versions_to_run:
        cfg = CONFIGS[vname]
        for ename in engine_names:
            eng = engines.get(ename)
            if not eng or not eng.ready: continue
            _max_tok = 2048 if ename == "gemini" else 512
            msgs = build_step3_4_message(
                cfg["system_prompt"],
                cfg["user_prompt_template"].format(
                    patch_id=pid,
                    source_id=p.get("source_id", ""),
                    wall=p.get("wall", "unknown")
                ),
                img_b64
            )
            t0 = time.time()
            r = call_with_retry(eng, msgs, limiter, max_tokens=_max_tok,
                                timeout=90, json_validator=json_validator)
            lat = round((time.time() - t0) * 1000)
            j = r.get("parsed_json") or extract_json(r.get("content"))

            d1 = normalize_label("D1", j.get("D1")) if j else ""
            d2 = normalize_label("D2", j.get("D2")) if j else ""
            d3 = normalize_label("D3", j.get("D3")) if j else ""
            d4 = normalize_label("D4", j.get("D4")) if j else ""
            d5 = normalize_label("D5", j.get("D5")) if j else ""
            warns = validate_d1_d2_d3_consistency(d1, d2, d3, d4) if j else ["no_data"]

            results[vname].append({
                "patch_id": pid, "engine": ename, "version": vname,
                "D1": d1, "D2": d2, "D3": d3, "D4": d4, "D5": d5,
                "confidence": j.get("confidence", 0) if j else 0,
                "cross_dim_warnings": "; ".join(warns) if warns else "",
                "cross_dim_ok": len(warns) == 0,
                "schema_ok": j is not None and all(j.get(k) for k in ["D1","D2","D3","D4","D5"]),
                "latency_ms": lat,
            })
        print(f" {vname}", end="", flush=True)
    print()

elapsed = time.time() - t_start

# ── Save per-version CSVs ──
for vname, rows in results.items():
    if not rows: continue
    outpath = RUN_DIR / f"ab_results_{vname.replace('.','')}.csv"
    with open(outpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {outpath}")

# ── Comparison summary ──
def calc_alpha_nominal(rows_list, dim):
    """Quick Krippendorff alpha (nominal) for one dimension."""
    patch_data = {}
    for r in rows_list:
        pid = r["patch_id"]
        if pid not in patch_data:
            patch_data[pid] = {}
        patch_data[pid][r["engine"]] = r[dim]

    all_values = set()
    for ur in patch_data.values():
        all_values.update(v for v in ur.values() if v)

    Do = 0; n_pairs = 0
    for ur in patch_data.values():
        vals = [v for v in ur.values() if v]
        m = len(vals)
        if m < 2: continue
        for i in range(m):
            for j in range(i+1, m):
                n_pairs += 1
                if vals[i] != vals[j]: Do += 1
    if n_pairs == 0: return float('nan')
    Do /= n_pairs

    vc = Counter()
    total = 0
    for ur in patch_data.values():
        for v in ur.values():
            if v: vc[v] += 1; total += 1
    De = sum(vc[v1]*vc[v2] for v1 in all_values for v2 in all_values if v1 != v2) / (total*(total-1)) if total > 1 else 0
    return 1.0 - Do/De if De > 0 else 1.0

comparison = {"elapsed_min": round(elapsed/60, 1), "n_patches": len(selected)}
for vname, rows in results.items():
    n = len(rows)
    schema_ok = sum(1 for r in rows if r["schema_ok"])
    cross_ok = sum(1 for r in rows if r["cross_dim_ok"])
    comparison[vname] = {
        "total": n,
        "schema_valid_rate": round(schema_ok / n * 100, 1) if n else 0,
        "cross_dim_valid_rate": round(cross_ok / n * 100, 1) if n else 0,
        "alpha": {dim: round(calc_alpha_nominal(rows, dim), 4) for dim in ["D1","D2","D3","D4","D5"]},
    }

json.dump(comparison, open(RUN_DIR / "ab_comparison.json", "w"), indent=2, ensure_ascii=False)

print(f"\n{'='*60}")
print(f"A/B COMPARISON — {elapsed/60:.1f} min")
print(f"{'='*60}")
for vname in versions_to_run:
    c = comparison[vname]
    print(f"\n{vname}:")
    print(f"  schema_valid_rate:    {c['schema_valid_rate']}%")
    print(f"  cross_dim_valid_rate: {c['cross_dim_valid_rate']}%")
    for dim in ["D1","D2","D3","D4","D5"]:
        print(f"  alpha_{dim}: {c['alpha'][dim]:.4f}")

if len(versions_to_run) == 2:
    print(f"\nDelta (v4.1 - v4.0):")
    for dim in ["D1","D2","D3","D4","D5"]:
        delta = comparison["v4.1"]["alpha"][dim] - comparison["v4.0"]["alpha"][dim]
        print(f"  alpha_{dim}: {delta:+.4f}")
    delta_cd = comparison["v4.1"]["cross_dim_valid_rate"] - comparison["v4.0"]["cross_dim_valid_rate"]
    print(f"  cross_dim_valid_rate: {delta_cd:+.1f}%")

print(f"\nResults: {RUN_DIR}")
