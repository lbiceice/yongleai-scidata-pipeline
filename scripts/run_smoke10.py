#!/usr/bin/env python3
"""
STEP3+STEP4 Smoke10 — 10 张分层冒烟测试
所有 API 调用统一走 step3_4_transport.py
标签正规化统一走 canonical_taxonomy.py

用法: PYTHONUNBUFFERED=1 python3 scripts/run_smoke10.py
"""

import os, sys, json, csv, re, time, yaml, datetime, logging
from pathlib import Path
from io import BytesIO

PROJECT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT / "scripts"))

from step3_4_transport import (
    load_engines, build_step3_4_message, image_to_b64_thumbnail,
    image_to_b64, RateLimiter, call_with_retry
)
from canonical_taxonomy import (
    VALID_LABELS, DAMAGE_LABELS, ALIAS_MAP, FALLBACK_DEFAULTS,
    normalize_label, validate_d1_d2_d3_consistency
)

# ─── Setup logging ─────────────────────────────────
os.makedirs(PROJECT / "logs", exist_ok=True)
logging.basicConfig(
    filename=str(PROJECT / "logs" / "smoke10_runtime.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
log = logging.getLogger("smoke10")

def lprint(msg):
    print(msg, flush=True)
    log.info(msg)

# ─── JSON extraction ─────────────────────────────────
def extract_json(text):
    if not text:
        return None
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except:
        m2 = re.search(r'\{.*\}', text, re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group())
            except:
                pass
    return None

def json_validator(content):
    return extract_json(content)

# ─── RAW validation (before normalize — gate-blocking) ────
def validate_step3_schema_raw(d):
    """Full schema check on raw VLM output."""
    if not d or not isinstance(d, dict):
        return False, ["not_dict"]
    missing = [k for k in ["D1","D2","D3","D4","D5","confidence"] if k not in d]
    return len(missing) == 0, missing

def validate_step4_schema_raw(d):
    if not d or not isinstance(d, dict):
        return False, ["not_dict"]
    missing = [k for k in ["P1","P2","P3","P4","severity","area","confidence"] if k not in d]
    return len(missing) == 0, missing

def check_vocab_step3_raw(d):
    """Check raw labels against canonical vocab (no fallback)."""
    if not d:
        return False, ["no_data"]
    errors = []
    for dim in ["D1","D4","D5"]:
        v = d.get(dim, "")
        if v not in VALID_LABELS.get(dim, []):
            errors.append(f"{dim}={v!r}")
    # D2/D3: check against full vocab
    d2 = d.get("D2", "")
    if d2 and d2 not in VALID_LABELS.get("D2", []):
        errors.append(f"D2={d2!r}")
    d3 = d.get("D3", "")
    if d3 and d3 not in VALID_LABELS.get("D3", []):
        errors.append(f"D3={d3!r}")
    return len(errors) == 0, errors

def check_vocab_step4_raw(d):
    if not d:
        return False, ["no_data"]
    errors = []
    for dim in ["P1","P2","P3","P4"]:
        v = d.get(dim, "")
        if v not in DAMAGE_LABELS.get(dim, []):
            errors.append(f"{dim}={v!r}")
    sev = d.get("severity", "")
    if sev not in ["完好","轻微","中度","严重","濒危"]:
        errors.append(f"severity={sev!r}")
    return len(errors) == 0, errors

# ─── Normalize with fallback tracking ─────────────────
def normalize_with_tracking(dim, raw_value):
    """Returns (normalized_value, fallback_reason or '')"""
    vocab = VALID_LABELS.get(dim) or DAMAGE_LABELS.get(dim, [])
    raw_str = str(raw_value or "").strip()

    # Direct match — no fallback
    if raw_str in vocab:
        return raw_str, ""

    # Try normalize
    normed = normalize_label(dim, raw_value)
    if normed == raw_str:
        return normed, ""

    # Alias hit
    alias = ALIAS_MAP.get(dim, {}).get(raw_str)
    if alias and alias == normed:
        return normed, f"alias: '{raw_str}'→'{normed}'"

    # Fallback hit
    fb = FALLBACK_DEFAULTS.get(dim, "")
    if normed == fb and raw_str != fb:
        return normed, f"fallback: raw='{raw_str}' not in vocab, defaulted to '{fb}'"

    return normed, f"mapped: '{raw_str}'→'{normed}'"

# ─── Image encoding ──────────────────────────────────
def encode_image(path, mode):
    """mode='thumb': 512px JPEG q85; mode='full': original PNG base64"""
    if mode == "thumb":
        return image_to_b64_thumbnail(str(path), max_size=512)
    else:
        return image_to_b64(str(path))

# ─── Main ─────────────────────────────────────────────
def main():
    lprint("=" * 60)
    lprint("STEP3+STEP4 Smoke10 Test")
    lprint("=" * 60)

    # Load smoke10 set
    smoke_csv = PROJECT / "pilot" / "smoke10_set.csv"
    with open(smoke_csv) as f:
        patches = list(csv.DictReader(f))
    lprint(f"Patches: {len(patches)}")

    # Load prompts
    step3_cfg = yaml.safe_load(open(PROJECT / "configs" / "step3_prompt_v4.1-draft.yaml"))
    step4_cfg = yaml.safe_load(open(PROJECT / "configs" / "step4_prompt.yaml"))

    # Load engines
    engines = load_engines()
    engine_names = ["openai", "gemini", "claude", "qwen"]
    for e in engine_names:
        eng = engines.get(e)
        lprint(f"  {e}: ready={eng.ready if eng else False} model={eng.model if eng else 'N/A'}")

    limiter = RateLimiter(min_interval_s=0.8, max_rpm=40)

    TILES = PROJECT / "02_tiles" / "STEP2_patch" / "images"

    # Output dirs
    os.makedirs(PROJECT / "03_features" / "statistics", exist_ok=True)
    os.makedirs(PROJECT / "04_damage" / "statistics", exist_ok=True)

    s3_results = []
    s4_results = []
    t_start = time.time()

    for pi, p in enumerate(patches):
        pid = p["patch_id"]
        split = p["split"]
        stratum = p["stratum"]
        img_mode = p["image_mode"]

        img_path = TILES / split / f"{pid}.png"
        if not img_path.exists():
            lprint(f"[{pi+1}/10] {pid} — NOT FOUND, skip")
            continue

        img_b64 = encode_image(img_path, img_mode)
        img_size = os.path.getsize(img_path)

        lprint(f"\n[{pi+1}/10] {pid} ({stratum}, {img_mode})")

        for ename in engine_names:
            eng = engines.get(ename)
            if not eng or not eng.ready:
                lprint(f"  {ename}: SKIP (not ready)")
                continue

            _max_tok = 2048 if ename == "gemini" else 512
            provider = "gptsapi" if ename != "qwen" else "dashscope"
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # ═══ STEP3 ═══
            msgs3 = build_step3_4_message(
                step3_cfg["system_prompt"],
                step3_cfg["user_prompt_template"].format(
                    patch_id=pid, source_id=pid.rsplit("_", 2)[0], wall="unknown"
                ),
                img_b64
            )
            t0 = time.time()
            r3 = call_with_retry(eng, msgs3, limiter, max_tokens=_max_tok, timeout=90,
                                 json_validator=json_validator)
            lat3 = round((time.time() - t0) * 1000)

            j3_raw = r3.get("parsed_json") or extract_json(r3.get("content"))

            # ── Stage 1: RAW validation (gate-blocking) ──
            raw_schema3_ok, raw_schema3_missing = validate_step3_schema_raw(j3_raw)
            raw_vocab3_ok, raw_vocab3_errors = check_vocab_step3_raw(j3_raw) if raw_schema3_ok else (False, ["schema_fail"])
            raw_valid3 = raw_schema3_ok and raw_vocab3_ok

            # ── Stage 2: Normalize (with fallback tracking) ──
            j3_norm = {}
            fallback_reasons3 = []
            if j3_raw:
                for dim in ["D1", "D2", "D3", "D4", "D5"]:
                    normed, fb_reason = normalize_with_tracking(dim, j3_raw.get(dim))
                    j3_norm[dim] = normed
                    if fb_reason:
                        fallback_reasons3.append(f"{dim}: {fb_reason}")
                j3_norm["confidence"] = j3_raw.get("confidence", 0)

            # ── Stage 3: Normalized cross-dimension validation ──
            d1d2d3_warns = validate_d1_d2_d3_consistency(
                j3_norm.get("D1", ""), j3_norm.get("D2", ""),
                j3_norm.get("D3", ""), j3_norm.get("D4", "")
            ) if j3_norm else ["no_data"]
            norm_valid3 = j3_norm and len(d1d2d3_warns) == 0

            # ── Stage 4: Gate (raw_valid is blocking) ──
            gate3 = raw_valid3  # raw invalid → gate FAIL regardless of normalize
            review3 = (not norm_valid3) or len(fallback_reasons3) > 0

            s3_results.append({
                "patch_id": pid, "stratum": stratum, "split": split,
                "contract_mode": "split",
                "engine": ename, "model_name": eng.model, "provider": provider,
                "image_mode": img_mode, "image_size_bytes": img_size,
                "raw_response": (r3.get("content") or "")[:500],
                "parsed_json": json.dumps(j3_raw, ensure_ascii=False) if j3_raw else "",
                "normalized_json": json.dumps(j3_norm, ensure_ascii=False) if j3_norm else "",
                "D1": j3_norm.get("D1", ""), "D2": j3_norm.get("D2", ""),
                "D3": j3_norm.get("D3", ""), "D4": j3_norm.get("D4", ""),
                "D5": j3_norm.get("D5", ""),
                "raw_valid": raw_valid3,
                "raw_schema_ok": raw_schema3_ok, "raw_vocab_ok": raw_vocab3_ok,
                "raw_errors": "; ".join(raw_schema3_missing + raw_vocab3_errors) if (raw_schema3_missing or raw_vocab3_errors) else "",
                "normalized_valid": norm_valid3,
                "cross_dim_warnings": "; ".join(d1d2d3_warns) if d1d2d3_warns else "",
                "fallback_reason": "; ".join(fallback_reasons3) if fallback_reasons3 else "",
                "gate_pass": gate3,
                "review_required": review3,
                "latency_ms": lat3, "timestamp": ts,
            })

            # ═══ STEP4 ═══
            msgs4 = build_step3_4_message(
                step4_cfg["system_prompt"],
                step4_cfg["user_prompt_template"].format(
                    patch_id=pid, source_id=pid.rsplit("_", 2)[0], wall="unknown"
                ),
                img_b64
            )
            t0 = time.time()
            r4 = call_with_retry(eng, msgs4, limiter, max_tokens=_max_tok, timeout=90,
                                 json_validator=json_validator)
            lat4 = round((time.time() - t0) * 1000)

            j4_raw = r4.get("parsed_json") or extract_json(r4.get("content"))

            # ── Stage 1: RAW validation ──
            raw_schema4_ok, raw_schema4_missing = validate_step4_schema_raw(j4_raw)
            raw_vocab4_ok, raw_vocab4_errors = check_vocab_step4_raw(j4_raw) if raw_schema4_ok else (False, ["schema_fail"])
            raw_valid4 = raw_schema4_ok and raw_vocab4_ok

            # ── Stage 2: Normalize with tracking ──
            j4_norm = {}
            fallback_reasons4 = []
            if j4_raw:
                for dim in ["P1", "P2", "P3", "P4"]:
                    normed, fb_reason = normalize_with_tracking(dim, j4_raw.get(dim))
                    j4_norm[dim] = normed
                    if fb_reason:
                        fallback_reasons4.append(f"{dim}: {fb_reason}")
                j4_norm["severity"] = j4_raw.get("severity", "")
                j4_norm["area"] = j4_raw.get("area", 0)
                j4_norm["confidence"] = j4_raw.get("confidence", 0)

            # ── Stage 3: Gate ──
            gate4 = raw_valid4
            review4 = (not raw_valid4) or len(fallback_reasons4) > 0

            s4_results.append({
                "patch_id": pid, "stratum": stratum, "split": split,
                "contract_mode": "split",
                "engine": ename, "model_name": eng.model, "provider": provider,
                "image_mode": img_mode, "image_size_bytes": img_size,
                "raw_response": (r4.get("content") or "")[:500],
                "parsed_json": json.dumps(j4_raw, ensure_ascii=False) if j4_raw else "",
                "normalized_json": json.dumps(j4_norm, ensure_ascii=False) if j4_norm else "",
                "P1": j4_norm.get("P1", ""), "P2": j4_norm.get("P2", ""),
                "P3": j4_norm.get("P3", ""), "P4": j4_norm.get("P4", ""),
                "severity": j4_norm.get("severity", ""),
                "raw_valid": raw_valid4,
                "raw_schema_ok": raw_schema4_ok, "raw_vocab_ok": raw_vocab4_ok,
                "raw_errors": "; ".join(raw_schema4_missing + raw_vocab4_errors) if (raw_schema4_missing or raw_vocab4_errors) else "",
                "fallback_reason": "; ".join(fallback_reasons4) if fallback_reasons4 else "",
                "gate_pass": gate4,
                "review_required": review4,
                "latency_ms": lat4, "timestamp": ts,
            })

            lprint(f"  {ename}: S3={'PASS' if gate3 else 'FAIL'}({lat3}ms) "
                   f"S4={'PASS' if gate4 else 'FAIL'}({lat4}ms) "
                   f"D1={j3_norm.get('D1','')} P1={j4_norm.get('P1','')}"
                   + (f" [fb:{len(fallback_reasons3)+len(fallback_reasons4)}]" if (fallback_reasons3 or fallback_reasons4) else ""))

    elapsed = time.time() - t_start

    # ─── Save manifests ─────────────────────────────
    s3_path = PROJECT / "03_features" / "statistics" / "smoke10_feature_manifest.csv"
    if s3_results:
        with open(s3_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(s3_results[0].keys()))
            w.writeheader()
            w.writerows(s3_results)

    s4_path = PROJECT / "04_damage" / "statistics" / "smoke10_damage_manifest.csv"
    if s4_results:
        with open(s4_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(s4_results[0].keys()))
            w.writeheader()
            w.writerows(s4_results)

    # ─── Summary ─────────────────────────────────────
    lprint(f"\n{'='*60}")
    lprint(f"SMOKE10 COMPLETE — {elapsed/60:.1f}m")
    gate3_pass = sum(1 for r in s3_results if r['gate_pass'])
    gate4_pass = sum(1 for r in s4_results if r['gate_pass'])
    fb3_count = sum(1 for r in s3_results if r.get('fallback_reason'))
    fb4_count = sum(1 for r in s4_results if r.get('fallback_reason'))
    lprint(f"  STEP3 gate: {gate3_pass}/{len(s3_results)} (fallbacks: {fb3_count})")
    lprint(f"  STEP4 gate: {gate4_pass}/{len(s4_results)} (fallbacks: {fb4_count})")
    for e in engine_names:
        e3 = [r for r in s3_results if r["engine"] == e]
        e4 = [r for r in s4_results if r["engine"] == e]
        ok3 = sum(1 for r in e3 if r["gate_pass"])
        ok4 = sum(1 for r in e4 if r["gate_pass"])
        lprint(f"  {e}: S3={ok3}/{len(e3)} S4={ok4}/{len(e4)}")
    lprint(f"{'='*60}")

    # ─── Sampling notes ─────────────────────────────
    os.makedirs(PROJECT / "pilot", exist_ok=True)
    with open(PROJECT / "pilot" / "smoke10_sampling_notes.md", "w") as f:
        f.write("# Smoke10 Sampling Notes\n\n")
        f.write("## 五层分层策略\n\n")
        f.write("| # | Stratum | Count | Mode | Purpose |\n")
        f.write("|---|---------|-------|------|---------|\n")
        f.write("| 1 | intact_background | 2 | thumb | 无病害/云气装饰判定 |\n")
        f.write("| 2 | figure_confusion | 2 | thumb | 人物身份高分歧样本 |\n")
        f.write("| 3 | headgear_artifact | 2 | thumb | 冠饰/法器可见度低 |\n")
        f.write("| 4 | soot_dust_mold | 2 | thumb | P4三类混淆 |\n")
        f.write("| 5 | mixed_damage_SENTINEL | 2 | full | 全分辨率混合病害 |\n")

if __name__ == "__main__":
    main()
