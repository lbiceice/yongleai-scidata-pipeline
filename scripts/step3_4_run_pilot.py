#!/usr/bin/env python3
"""STEP3+STEP4 Pilot — 20 patches × 4 engines × 2 tasks = 160 API calls"""
import os, sys, json, csv, re, time, yaml, datetime
from pathlib import Path

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))

from step3_4_transport import (
    load_engines, build_step3_4_message, image_to_b64_thumbnail,
    RateLimiter, call_with_retry
)

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "pilot_test"
RUN_DIR = PROJECT / "03_features" / "runs" / RUN_ID

# Load prompts
step3_cfg = yaml.safe_load(open(PROJECT / "configs" / "step3_prompt.yaml"))
step4_cfg = yaml.safe_load(open(PROJECT / "configs" / "step4_prompt.yaml"))

# Load pilot set
pilot_csv = PROJECT / "04_damage" / "runs" / "step4_damage_init_20260403_203630" / "manifests" / "step4_pilot_benchmark_set.csv"
with open(pilot_csv) as f:
    pilot_patches = list(csv.DictReader(f))

TILES = PROJECT / "02_tiles" / "STEP2_patch" / "images"

# HSGF + Damage vocab
HSGF_VOCAB = {
    "D1": ["八主神","帝君","星君","神将","真君仙人","玉女侍从","三官地府","先导护卫","云气装饰","背景留白"],
    "D4": ["完好","轻微损伤","中度损伤","严重损伤","古代补绘"],
    "D5": ["前景","中景","背景","云气区"],
}
DAMAGE_VOCAB = {
    "P1": ["起甲","龟裂","脱落","褪色","变色","完好"],
    "P2": ["空鼓","酥碱","裂隙","粉化","完好"],
    "P3": ["裂隙","渗水","变形","完好"],
    "P4": ["烟熏","霉斑","积尘","涂写","无"],
}

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

engines = load_engines()
limiter = RateLimiter(min_interval_s=1.5, max_rpm=20)
engine_names = ["openai", "gemini", "claude", "qwen"]

results = []
t_start = time.time()

print(f"STEP3+STEP4 Pilot — {len(pilot_patches)} patches × {len(engine_names)} engines")
print(f"run_id: {RUN_ID}")
print()

for pi, p in enumerate(pilot_patches):
    patch_id = p["patch_id"]
    split = p["split"]
    source_id = p["source_id"]
    group = p["group"]
    wall = p.get("wall", "unknown")

    img_path = TILES / split / f"{patch_id}.png"
    if not img_path.exists():
        print(f"[{pi+1}/{len(pilot_patches)}] {patch_id} — FILE NOT FOUND, skip")
        continue

    img_b64 = image_to_b64_thumbnail(str(img_path), max_size=512)
    print(f"[{pi+1}/{len(pilot_patches)}] {patch_id} (Group {group})")

    for ename in engine_names:
        eng = engines.get(ename)
        if not eng or not eng.ready:
            continue

        _max_tok = 2048 if ename == "gemini" else 512

        # STEP3
        msgs3 = build_step3_4_message(
            step3_cfg["system_prompt"],
            step3_cfg["user_prompt_template"].format(patch_id=patch_id, source_id=source_id, wall=wall),
            img_b64
        )
        r3 = call_with_retry(eng, msgs3, limiter, max_tokens=_max_tok, timeout=90, json_validator=json_validator)
        j3 = r3.get("parsed_json") or extract_json(r3.get("content"))

        # STEP4
        msgs4 = build_step3_4_message(
            step4_cfg["system_prompt"],
            step4_cfg["user_prompt_template"].format(patch_id=patch_id, source_id=source_id, wall=wall),
            img_b64
        )
        r4 = call_with_retry(eng, msgs4, limiter, max_tokens=_max_tok, timeout=90, json_validator=json_validator)
        j4 = r4.get("parsed_json") or extract_json(r4.get("content"))

        # Validate
        s3_valid = j3 is not None and j3.get("D1") in HSGF_VOCAB.get("D1", [])
        s4_valid = j4 is not None and j4.get("P1") in DAMAGE_VOCAB.get("P1", [])

        row = {
            "patch_id": patch_id, "group": group, "split": split, "engine": ename,
            "step3_valid": s3_valid, "step3_latency": r3["latency_s"],
            "D1": j3.get("D1","") if j3 else "", "D2": j3.get("D2","") if j3 else "",
            "D3": j3.get("D3","") if j3 else "", "D4": j3.get("D4","") if j3 else "",
            "D5": j3.get("D5","") if j3 else "", "s3_confidence": j3.get("confidence",0) if j3 else 0,
            "step4_valid": s4_valid, "step4_latency": r4["latency_s"],
            "P1": j4.get("P1","") if j4 else "", "P2": j4.get("P2","") if j4 else "",
            "P3": j4.get("P3","") if j4 else "", "P4": j4.get("P4","") if j4 else "",
            "severity": j4.get("severity","") if j4 else "",
            "area": j4.get("area","") if j4 else "",
            "s4_confidence": j4.get("confidence",0) if j4 else 0,
        }
        results.append(row)
        print(f"  {ename}: D1={row['D1'][:6]} P1={row['P1'][:4]} s3={'OK' if s3_valid else 'FAIL'} s4={'OK' if s4_valid else 'FAIL'} ({r3['latency_s']:.0f}s/{r4['latency_s']:.0f}s)")

elapsed = time.time() - t_start

# Save results
fields = list(results[0].keys()) if results else []
csv_path = RUN_DIR / "manifests" / "pilot_results.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(results)

# Also JSONL
with open(RUN_DIR / "manifests" / "pilot_results.jsonl", "w") as f:
    for r in results: f.write(json.dumps(r, ensure_ascii=False) + "\n")

# Summary stats
total = len(results)
s3_pass = sum(1 for r in results if r["step3_valid"])
s4_pass = sum(1 for r in results if r["step4_valid"])

print(f"\n{'='*60}")
print(f"PILOT COMPLETE — {elapsed/60:.1f}m")
print(f"  STEP3: {s3_pass}/{total} valid ({s3_pass/total*100:.0f}%)")
print(f"  STEP4: {s4_pass}/{total} valid ({s4_pass/total*100:.0f}%)")
for e in engine_names:
    er = [r for r in results if r["engine"] == e]
    e3 = sum(1 for r in er if r["step3_valid"])
    e4 = sum(1 for r in er if r["step4_valid"])
    print(f"  {e}: S3={e3}/{len(er)} S4={e4}/{len(er)}")
print(f"{'='*60}")

# Save summary
summary = {
    "run_id": RUN_ID, "elapsed_min": round(elapsed/60, 1),
    "total_calls": total, "step3_pass": s3_pass, "step4_pass": s4_pass,
    "step3_rate": round(s3_pass/total, 4) if total else 0,
    "step4_rate": round(s4_pass/total, 4) if total else 0,
}
with open(RUN_DIR / "manifests" / "pilot_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

sys.exit(0 if (s3_pass/total >= 0.9 and s4_pass/total >= 0.9) else 1)
