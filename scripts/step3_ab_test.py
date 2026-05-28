#!/usr/bin/env python3
"""STEP3 A/B Test: v4.0-fixed vs v4.1-draft on 10 patches × 4 engines"""
import os, sys, json, csv, re, time, yaml, random
from pathlib import Path
from collections import Counter

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))
from step3_4_transport import load_engines, build_step3_4_message, image_to_b64_thumbnail, RateLimiter, call_with_retry

HSGF_D1 = ["八主神","帝君","星君","神将","真君仙人","玉女侍从","三官地府","先导护卫","云气装饰","背景留白"]

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

def krippendorff_alpha(ratings_by_unit):
    all_values = set()
    for ur in ratings_by_unit.values():
        for v in ur.values():
            if v: all_values.add(v)
    Do = 0; n_pairs = 0
    for ur in ratings_by_unit.values():
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
    for ur in ratings_by_unit.values():
        for v in ur.values():
            if v: vc[v] += 1; total += 1
    De = sum(vc[v1]*vc[v2] for v1 in all_values for v2 in all_values if v1 != v2) / (total*(total-1)) if total > 1 else 0
    return 1.0 - Do/De if De > 0 else 1.0

# Select 10 patches (mix of high-disagreement and normal)
pilot_csv = PROJECT / "04_damage/runs/step4_damage_init_20260403_203630/manifests/step4_pilot_benchmark_set.csv"
with open(pilot_csv) as f:
    all_pilot = list(csv.DictReader(f))
random.seed(42)
selected = random.sample(all_pilot, 10)

# Load both prompts
v40 = yaml.safe_load(open(PROJECT / "configs/step3_prompt.yaml"))
v41 = yaml.safe_load(open(PROJECT / "configs/step3_prompt_v4.1-draft.yaml"))

TILES = PROJECT / "02_tiles/STEP2_patch/images"
engines = load_engines()
limiter = RateLimiter(min_interval_s=1.5, max_rpm=20)
engine_names = ["openai", "gemini", "claude", "qwen"]

results = {"v4.0": [], "v4.1": []}

print("STEP3 A/B Test: v4.0-fixed vs v4.1-draft")
print(f"10 patches × 4 engines × 2 prompts = 80 calls\n")

for pi, p in enumerate(selected):
    pid = p["patch_id"]
    split = p["split"]
    img_path = TILES / split / f"{pid}.png"
    if not img_path.exists():
        print(f"  SKIP {pid}")
        continue
    img_b64 = image_to_b64_thumbnail(str(img_path), max_size=512)
    print(f"[{pi+1}/10] {pid}")

    for version_name, cfg in [("v4.0", v40), ("v4.1", v41)]:
        for ename in engine_names:
            eng = engines.get(ename)
            if not eng or not eng.ready: continue
            _max_tok = 2048 if ename == "gemini" else 512
            msgs = build_step3_4_message(
                cfg["system_prompt"],
                cfg["user_prompt_template"].format(patch_id=pid, source_id=p.get("source_id",""), wall=p.get("wall","unknown")),
                img_b64
            )
            r = call_with_retry(eng, msgs, limiter, max_tokens=_max_tok, timeout=90, json_validator=json_validator)
            j = r.get("parsed_json") or extract_json(r.get("content"))
            d1 = j.get("D1","") if j else ""
            d2 = j.get("D2","") if j else ""
            d3 = j.get("D3","") if j else ""
            valid = d1 in HSGF_D1
            results[version_name].append({"patch_id": pid, "engine": ename, "D1": d1, "D2": d2, "D3": d3, "valid": valid})
            
        # Brief status
        v40_d1s = [r["D1"] for r in results["v4.0"] if r["patch_id"] == pid]
        v41_d1s = [r["D1"] for r in results["v4.1"] if r["patch_id"] == pid]
        print(f"  v4.0 D1: {v40_d1s}")
        print(f"  v4.1 D1: {v41_d1s}")

# Calculate alpha for each version
print(f"\n{'='*60}")
print("A/B COMPARISON")
print(f"{'='*60}")

patches_list = [p["patch_id"] for p in selected]

for vname in ["v4.0", "v4.1"]:
    vr = results[vname]
    # D1 alpha
    ratings = {}
    for pid in patches_list:
        unit = {}
        for r in vr:
            if r["patch_id"] == pid and r["D1"]:
                unit[r["engine"]] = r["D1"]
        if len(unit) >= 2:
            ratings[pid] = unit
    alpha_d1 = krippendorff_alpha(ratings)
    
    # D1 unique count per patch
    unique_counts = []
    for pid in patches_list:
        d1s = [r["D1"] for r in vr if r["patch_id"] == pid and r["D1"]]
        unique_counts.append(len(set(d1s)))
    avg_unique = sum(unique_counts) / len(unique_counts) if unique_counts else 0
    
    # N/A compliance
    na_violations = 0
    na_total = 0
    for r in vr:
        if r["D1"] in ("云气装饰", "背景留白"):
            na_total += 1
            if r["D2"] not in ("N/A", ""):
                na_violations += 1
    
    print(f"\n{vname}:")
    print(f"  D1 α = {alpha_d1:.3f}")
    print(f"  D1 avg unique/patch = {avg_unique:.1f}")
    print(f"  D2 N/A compliance = {na_total - na_violations}/{na_total}")

alpha_improvement = krippendorff_alpha({pid: {r["engine"]: r["D1"] for r in results["v4.1"] if r["patch_id"] == pid and r["D1"]} for pid in patches_list}) - krippendorff_alpha({pid: {r["engine"]: r["D1"] for r in results["v4.0"] if r["patch_id"] == pid and r["D1"]} for pid in patches_list})
print(f"\nΔα (v4.1 - v4.0) = {alpha_improvement:+.3f}")
print("POSITIVE = improvement" if alpha_improvement > 0 else "NEGATIVE = regression")
