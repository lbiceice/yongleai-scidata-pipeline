#!/usr/bin/env python3
"""
run_full_batch.py — STEP3+STEP4 全量批处理 v0.5 (final)

用法:
  python3 scripts/run_full_batch.py --dry-run
  python3 scripts/run_full_batch.py --split train --shard 1 --dry-run
  python3 scripts/run_full_batch.py --split train --engines gemini,qwen --version 4.1-draft
  python3 scripts/run_full_batch.py --resume --run-id step3_full_20260407_091610
"""

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# ─── Constants ───

PROJECT_ROOT = Path("/Volumes/小满/yongle_palace_dataset")
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
PATCH_DIR = PROJECT_ROOT / "02_tiles" / "STEP2_patch" / "images"
RUNS_DIR = PROJECT_ROOT / "03_features" / "runs"
VALID_SPLITS = ["train", "val", "test"]
VALID_ENGINES = ["openai", "gemini", "claude", "qwen"]
DEFAULT_SHARD_SIZE = 200
CONTRACT_MODE = "split"
ENGINE_MIN_INTERVALS = {
    "openai": 1.5,
    "gemini": 1.5,
    "claude": 1.5,
    "qwen": 1.0,
}
CSV_FIELDNAMES = [
    "patch_id", "stratum", "split", "contract_mode", "engine", "model_name",
    "provider", "image_mode", "image_size_bytes", "raw_response",
    "parsed_json", "normalized_json", "D1", "D2", "D3", "D4", "D5",
    "raw_valid", "raw_schema_ok", "raw_vocab_ok", "raw_errors",
    "normalized_valid", "cross_dim_warnings", "fallback_reason",
    "gate_pass", "review_required", "latency_ms", "timestamp",
]

from canonical_taxonomy import (
    ALIAS_MAP,
    FALLBACK_DEFAULTS,
    VALID_LABELS,
    normalize_label,
    validate_d1_d2_d3_consistency,
)

EngineClient = None
RateLimiter = None
build_step3_4_message = None
image_to_b64_thumbnail = None
load_engines = None

# ─── Graceful shutdown flag ───
_shutdown_requested = False


# ─── Checkpoint ───

def _run_state_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id / "state"


def load_or_init_checkpoint(run_id: str, *, engines: list[str],
                            version: str, splits: list[str],
                            shard_size: int) -> dict:
    """加载已有 checkpoint 或初始化新的。"""
    state_dir = _run_state_dir(run_id)
    ckpt_path = state_dir / "checkpoint.json"

    if ckpt_path.exists() and ckpt_path.stat().st_size > 0:
        with open(ckpt_path) as f:
            ckpt = json.load(f)
        print(f"  checkpoint 已加载: {len(ckpt['completed'])} patches 已完成")
        return ckpt

    # Init new
    state_dir.mkdir(parents=True, exist_ok=True)
    ckpt = {
        "run_id": run_id,
        "version": version,
        "engines": engines,
        "splits": splits,
        "shard_size": shard_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed": [],       # list of patch_id strings
        "failed": [],          # list of patch_id strings
        "current_split": None,
        "current_shard": None,
        "current_patch": None,
    }
    save_checkpoint_atomic(run_id, ckpt)
    print(f"  checkpoint 已初始化: {ckpt_path}")
    return ckpt


def save_checkpoint_atomic(run_id: str, ckpt: dict) -> None:
    """原子写入 checkpoint：先写 tmp 再 os.replace。"""
    state_dir = _run_state_dir(run_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = state_dir / "checkpoint.json"
    ckpt["updated_at"] = datetime.now(timezone.utc).isoformat()

    fd, tmp_path = tempfile.mkstemp(
        dir=str(state_dir), prefix=".ckpt_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(ckpt, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(ckpt_path))
    except BaseException:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Signal handling ───

def install_signal_handlers() -> None:
    """注册 SIGINT/SIGTERM，设置优雅退出标志。"""

    def _handler(signum, frame):
        global _shutdown_requested
        sig_name = signal.Signals(signum).name
        if _shutdown_requested:
            print(f"\n[{sig_name}] 再次收到信号，强制退出", file=sys.stderr)
            sys.exit(1)
        _shutdown_requested = True
        print(
            f"\n[{sig_name}] 收到停止信号，当前 patch 完成后退出...",
            file=sys.stderr,
        )

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def is_shutdown_requested() -> bool:
    return _shutdown_requested


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="STEP3+STEP4 全量批处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--split",
        choices=VALID_SPLITS,
        default=None,
        help="只跑指定 split (默认: 全部 split)",
    )
    p.add_argument(
        "--shard",
        type=int,
        default=None,
        help="只跑指定 shard 编号 (1-based, 默认: 全部 shard)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="从 checkpoint 恢复，跳过已完成的 patch",
    )
    p.add_argument(
        "--engines",
        default=",".join(VALID_ENGINES),
        help=f"逗号分隔的引擎列表 (默认: {','.join(VALID_ENGINES)})",
    )
    p.add_argument(
        "--version",
        default="4.1-draft",
        help="prompt 版本 (默认: 4.1-draft)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出执行计划，不实际调用 API",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="自定义 run_id (默认: 自动生成 step3_full_YYYYMMDD_HHMMSS)",
    )
    p.add_argument(
        "--shard-size",
        type=int,
        default=DEFAULT_SHARD_SIZE,
        help=f"每个 shard 的 patch 数 (默认: {DEFAULT_SHARD_SIZE})",
    )
    return p.parse_args(argv)


def discover_patches(split: str) -> list[Path]:
    """枚举指定 split 下所有 .png patch 文件，按文件名排序。"""
    split_dir = PATCH_DIR / split
    if not split_dir.is_dir():
        print(f"ERROR: split 目录不存在: {split_dir}", file=sys.stderr)
        sys.exit(1)
    patches = sorted(split_dir.glob("*.png"))
    return patches


def build_shard_plan(patches: list[Path], shard_size: int) -> list[dict]:
    """将 patch 列表切分为 shard，返回 [{shard_id, start, end, count}]。"""
    n = len(patches)
    n_shards = math.ceil(n / shard_size)
    plan = []
    for i in range(n_shards):
        start = i * shard_size
        end = min(start + shard_size, n)
        plan.append({
            "shard_id": i + 1,
            "start": start,
            "end": end,
            "count": end - start,
        })
    return plan


def generate_run_id() -> str:
    return f"step3_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


# ─── Preflight ───

def run_preflight(
    *,
    version: str,
    run_id: str,
    resume: bool,
    dry_run: bool,
) -> None:
    """预检：prompt/词表/硬盘/空间/checkpoint。失败则 sys.exit(1)。"""
    errors = []
    warnings = []

    print("  [preflight] 开始预检...")

    # 1. Prompt 文件
    prompt_path = PROJECT_ROOT / "configs" / f"step3_prompt_v{version}.yaml"
    verify_script = PROJECT_ROOT / "scripts" / "verify_prompt_integrity.py"
    if verify_script.exists() and not dry_run:
        r = subprocess.run(
            [sys.executable, str(verify_script), str(prompt_path)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            errors.append(f"verify_prompt_integrity 失败: {r.stderr.strip()[:200]}")
        else:
            print("  [preflight] prompt integrity ✓ (外部脚本)")
    else:
        # inline fallback
        if not prompt_path.exists():
            errors.append(f"prompt 文件不存在: {prompt_path}")
        else:
            content = prompt_path.read_text(encoding="utf-8")
            if "八主神" not in content:
                errors.append("prompt 文件缺少关键词 '八主神'，可能文件损坏")
            else:
                print("  [preflight] prompt 文件 ✓")

    # 2. Canonical taxonomy
    taxonomy_path = PROJECT_ROOT / "scripts" / "canonical_taxonomy.py"
    if not taxonomy_path.exists():
        errors.append(f"canonical_taxonomy.py 不存在: {taxonomy_path}")
    else:
        print("  [preflight] canonical_taxonomy ✓")

    # 3. API auth (non-dry-run only)
    auth_script = PROJECT_ROOT / "scripts" / "preflight_api_auth.py"
    if auth_script.exists() and not dry_run:
        r = subprocess.run(
            [sys.executable, str(auth_script)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            warnings.append(f"preflight_api_auth 警告: {r.stderr.strip()[:200]}")
        else:
            print("  [preflight] API auth ✓ (外部脚本)")

    # 4. 外置硬盘可写
    test_file = PROJECT_ROOT / ".preflight_write_test"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print("  [preflight] 硬盘可写 ✓")
    except OSError as e:
        errors.append(f"外置硬盘不可写: {e}")

    # 5. 剩余空间 > 5GB
    try:
        st = os.statvfs(str(PROJECT_ROOT))
        free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
        if free_gb < 5.0:
            errors.append(f"剩余空间不足: {free_gb:.1f}GB < 5GB")
        else:
            print(f"  [preflight] 磁盘空间 ✓ ({free_gb:.1f}GB 可用)")
    except OSError as e:
        warnings.append(f"无法检查磁盘空间: {e}")

    # 6. Resume 时 checkpoint 有效
    if resume:
        ckpt_path = _run_state_dir(run_id) / "checkpoint.json"
        if not ckpt_path.exists():
            errors.append(f"--resume 但 checkpoint 不存在: {ckpt_path}")
        else:
            try:
                with open(ckpt_path, encoding="utf-8") as f:
                    ckpt = json.load(f)
                if "completed" not in ckpt:
                    errors.append("checkpoint.json 格式无效: 缺少 'completed' 字段")
                else:
                    print(f"  [preflight] checkpoint ✓ ({len(ckpt['completed'])} completed)")
            except (json.JSONDecodeError, OSError) as e:
                errors.append(f"checkpoint.json 无法解析: {e}")

    # 7. Patch 目录存在
    if not PATCH_DIR.exists():
        errors.append(f"patch 目录不存在: {PATCH_DIR}")
    else:
        print("  [preflight] patch 目录 ✓")

    # Report
    for w in warnings:
        print(f"  [preflight] WARNING: {w}", file=sys.stderr)

    if errors:
        print("  [preflight] FAILED:", file=sys.stderr)
        for e in errors:
            print(f"    ✗ {e}", file=sys.stderr)
        sys.exit(1)

    print("  [preflight] 全部通过 ✓")


def init_transport() -> None:
    global EngineClient
    global RateLimiter
    global build_step3_4_message
    global image_to_b64_thumbnail
    global load_engines

    if load_engines is not None:
        return

    from step3_4_transport import (
        EngineClient as _EngineClient,
        RateLimiter as _RateLimiter,
        build_step3_4_message as _build_step3_4_message,
        image_to_b64_thumbnail as _image_to_b64_thumbnail,
        load_engines as _load_engines,
    )

    EngineClient = _EngineClient
    RateLimiter = _RateLimiter
    build_step3_4_message = _build_step3_4_message
    image_to_b64_thumbnail = _image_to_b64_thumbnail
    load_engines = _load_engines


def load_prompt_config(version: str) -> dict:
    prompt_path = PROJECT_ROOT / "configs" / f"step3_prompt_v{version}.yaml"
    if not prompt_path.exists():
        print(f"ERROR: prompt 配置不存在: {prompt_path}", file=sys.stderr)
        sys.exit(1)
    text = prompt_path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text)

    def _extract_top_level_quoted(key: str, next_keys: list[str]) -> str:
        next_pattern = "|".join(re.escape(k) for k in next_keys)
        pattern = (
            rf"^{re.escape(key)}:\s*(\"(?:.|\n)*?\")\n(?=^(?:{next_pattern}):|\Z)"
        )
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise RuntimeError(f"无法在 {prompt_path} 中解析字段 {key}")
        return json.loads(match.group(1))

    return {
        "system_prompt": _extract_top_level_quoted(
            "system_prompt",
            ["user_prompt_template", "json_schema"],
        ),
        "user_prompt_template": _extract_top_level_quoted(
            "user_prompt_template",
            ["json_schema"],
        ),
    }


def extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def validate_step3_schema_raw(data: dict | None) -> tuple[bool, list[str]]:
    if not data or not isinstance(data, dict):
        return False, ["not_dict"]
    missing = [k for k in ["D1", "D2", "D3", "D4", "D5", "confidence"] if k not in data]
    return len(missing) == 0, missing


def check_vocab_step3_raw(data: dict | None) -> tuple[bool, list[str]]:
    if not data:
        return False, ["no_data"]
    errors = []
    for dim in ["D1", "D2", "D3", "D4", "D5"]:
        value = data.get(dim, "")
        if value not in VALID_LABELS.get(dim, []):
            errors.append(f"{dim}={value!r}")
    return len(errors) == 0, errors


def normalize_with_tracking(dim: str, raw_value) -> tuple[str, str]:
    vocab = VALID_LABELS.get(dim, [])
    raw_str = str(raw_value or "").strip()

    if raw_str in vocab:
        return raw_str, ""

    normalized = normalize_label(dim, raw_value)
    if normalized == raw_str:
        return normalized, ""

    alias = ALIAS_MAP.get(dim, {}).get(raw_str)
    if alias and alias == normalized:
        return normalized, f"alias: '{raw_str}'→'{normalized}'"

    fallback = FALLBACK_DEFAULTS.get(dim, "")
    if normalized == fallback and raw_str != fallback:
        return normalized, f"fallback: raw='{raw_str}' not in vocab, defaulted to '{fallback}'"

    return normalized, f"mapped: '{raw_str}'→'{normalized}'"


def shard_csv_path(run_id: str, split: str, shard_id: int) -> Path:
    return RUNS_DIR / run_id / "manifests" / f"shard_{split}_{shard_id:03d}.csv"


def append_csv_row(csv_path: Path, row_dict: dict, fieldnames: list[str]) -> None:
    csv_dir = csv_path.parent
    if not csv_dir.exists():
        raise RuntimeError(f"CSV 输出目录不存在，疑似挂载丢失: {csv_dir}")

    write_header = (not csv_path.exists()) or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({name: row_dict.get(name, "") for name in fieldnames})
        f.flush()
        os.fsync(f.fileno())


def source_id_from_patch_id(patch_id: str) -> str:
    parts = patch_id.rsplit("_", 2)
    return parts[0] if len(parts) == 3 else patch_id


def detect_status_code(result: dict) -> int | None:
    error_message = result.get("error_message") or ""
    match = re.search(r"\b(401|402|404|429|500|502|503|504)\b", error_message)
    if match:
        return int(match.group(1))

    error_type = (result.get("error_type") or "").lower()
    if "authentication" in error_type:
        return 401
    if "notfound" in error_type:
        return 404
    return None


def handle_retry_loop(engine: EngineClient, messages: list, limiter: RateLimiter) -> dict:
    backoffs = [5, 15, 45]
    max_tokens = 2048 if engine.name == "gemini" else 512

    for attempt in range(1, len(backoffs) + 2):
        limiter.wait(engine.name)
        result = engine.call(messages, max_tokens=max_tokens, timeout=90)
        result["attempt"] = attempt

        if result.get("success"):
            return result

        status_code = detect_status_code(result)
        if status_code in {401, 402, 404}:
            result["stop_engine"] = True
            return result

        if attempt <= len(backoffs):
            wait_s = backoffs[attempt - 1]
            print(
                f"  [{engine.name}] 调用失败，{wait_s}s 后重试 "
                f"(attempt {attempt}/{len(backoffs) + 1}): "
                f"{(result.get('error_message') or result.get('error_type') or 'unknown')[:160]}",
                flush=True,
            )
            time.sleep(wait_s)

    result["stop_engine"] = False
    return result


def call_transport_for_patch(
    engine: EngineClient,
    patch_path: Path,
    prompt_cfg: dict,
    limiter: RateLimiter,
) -> dict:
    patch_id = patch_path.stem
    image_b64 = image_to_b64_thumbnail(str(patch_path), max_size=512)
    messages = build_step3_4_message(
        prompt_cfg["system_prompt"],
        prompt_cfg["user_prompt_template"].format(
            patch_id=patch_id,
            source_id=source_id_from_patch_id(patch_id),
            wall="unknown",
        ),
        image_b64,
    )
    result = handle_retry_loop(engine, messages, limiter)
    parsed_json = extract_json(result.get("content"))
    return {
        "messages": messages,
        "result": result,
        "parsed_json": parsed_json,
        "image_mode": "thumb",
        "image_size_bytes": patch_path.stat().st_size,
    }


def build_step3_row(
    *,
    patch_id: str,
    split: str,
    engine: EngineClient,
    transport_result: dict,
) -> dict:
    result = transport_result["result"]
    raw_json = transport_result["parsed_json"]

    raw_schema_ok, raw_schema_missing = validate_step3_schema_raw(raw_json)
    raw_vocab_ok, raw_vocab_errors = (
        check_vocab_step3_raw(raw_json) if raw_schema_ok else (False, ["schema_fail"])
    )
    raw_valid = raw_schema_ok and raw_vocab_ok

    normalized = {}
    fallback_reasons = []
    if raw_json:
        for dim in ["D1", "D2", "D3", "D4", "D5"]:
            normed, fallback_reason = normalize_with_tracking(dim, raw_json.get(dim))
            normalized[dim] = normed
            if fallback_reason:
                fallback_reasons.append(f"{dim}: {fallback_reason}")
        normalized["confidence"] = raw_json.get("confidence", 0)

    warnings = (
        validate_d1_d2_d3_consistency(
            normalized.get("D1", ""),
            normalized.get("D2", ""),
            normalized.get("D3", ""),
            normalized.get("D4", ""),
        )
        if normalized else ["no_data"]
    )
    normalized_valid = bool(normalized) and len(warnings) == 0
    review_required = (not normalized_valid) or bool(fallback_reasons)

    raw_response = (result.get("content") or "").strip()
    if not raw_response and not result.get("success"):
        raw_response = (
            result.get("error_message")
            or result.get("error_type")
            or "transport_failure"
        )

    provider = "dashscope" if engine.name == "qwen" else "gptsapi"
    model_name = result.get("model_returned") or engine.model
    return {
        "patch_id": patch_id,
        "stratum": "",
        "split": split,
        "contract_mode": CONTRACT_MODE,
        "engine": engine.name,
        "model_name": model_name,
        "provider": provider,
        "image_mode": transport_result["image_mode"],
        "image_size_bytes": transport_result["image_size_bytes"],
        "raw_response": raw_response[:500],
        "parsed_json": json.dumps(raw_json, ensure_ascii=False) if raw_json else "",
        "normalized_json": json.dumps(normalized, ensure_ascii=False) if normalized else "",
        "D1": normalized.get("D1", ""),
        "D2": normalized.get("D2", ""),
        "D3": normalized.get("D3", ""),
        "D4": normalized.get("D4", ""),
        "D5": normalized.get("D5", ""),
        "raw_valid": raw_valid,
        "raw_schema_ok": raw_schema_ok,
        "raw_vocab_ok": raw_vocab_ok,
        "raw_errors": "; ".join(raw_schema_missing + raw_vocab_errors)
        if (raw_schema_missing or raw_vocab_errors) else "",
        "normalized_valid": normalized_valid,
        "cross_dim_warnings": "; ".join(warnings) if warnings else "",
        "fallback_reason": "; ".join(fallback_reasons) if fallback_reasons else "",
        "gate_pass": raw_valid,
        "review_required": review_required,
        "latency_ms": round(float(result.get("latency_s", 0)) * 1000),
        "timestamp": result.get("timestamp") or datetime.now(timezone.utc).isoformat(),
    }


# ─── Manifest ───

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    run_id: str,
    *,
    version: str,
    engines: list[str],
    engine_clients: dict,
    splits: list[str],
    split_plans: dict,
    ckpt: dict,
    start_time: str,
    end_time: str,
    engine_elapsed: dict,
) -> None:
    """写 _manifest.json 到 reports/ 目录。"""
    prompt_path = PROJECT_ROOT / "configs" / f"step3_prompt_v{version}.yaml"
    taxonomy_path = PROJECT_ROOT / "scripts" / "canonical_taxonomy.py"

    splits_dist = {}
    for sp in splits:
        plan = split_plans[sp]
        splits_dist[sp] = len(plan["patches"])

    engine_configs = {}
    for name in engines:
        ec = engine_clients.get(name)
        if ec and ec.ready:
            engine_configs[name] = {
                "model": ec.model,
                "temperature": ec.temperature,
                "source": ec.source,
                "base_url_masked": ec.base_url[:30] + "..." if ec.base_url else "",
            }

    manifest = {
        "run_id": run_id,
        "prompt_version": version,
        "prompt_sha256": _file_sha256(prompt_path) if prompt_path.exists() else "n/a",
        "canonical_taxonomy_sha256": _file_sha256(taxonomy_path) if taxonomy_path.exists() else "n/a",
        "total_patches": len(ckpt.get("completed", [])) + len(ckpt.get("failed", [])),
        "success_count": len(ckpt.get("completed", [])),
        "failed_count": len(ckpt.get("failed", [])),
        "splits": splits_dist,
        "engines": engines,
        "engine_configs": engine_configs,
        "engine_elapsed_s": {k: round(v, 1) for k, v in engine_elapsed.items()},
        "contract_mode": CONTRACT_MODE,
        "start_time": start_time,
        "end_time": end_time,
        "python_version": platform.python_version(),
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
    }

    reports_dir = RUNS_DIR / run_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = reports_dir / "_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  manifest 已写入: {manifest_path}")


# ─── Cost summary ───

def update_cost_summary(
    run_id: str,
    *,
    completed: int,
    total: int,
    engine_elapsed: dict,
    start_time_ts: float,
) -> None:
    """打印并写入成本/进度摘要。"""
    elapsed = time.time() - start_time_ts
    pct = (completed / total * 100) if total > 0 else 0
    remaining_patches = total - completed
    rate = completed / elapsed if elapsed > 0 else 0
    eta_s = remaining_patches / rate if rate > 0 else 0

    summary = {
        "completed": completed,
        "total": total,
        "percent": round(pct, 1),
        "elapsed_s": round(elapsed, 1),
        "rate_patches_per_min": round(rate * 60, 2),
        "eta_remaining_s": round(eta_s, 1),
        "engine_elapsed_s": {k: round(v, 1) for k, v in engine_elapsed.items()},
        "cost": "n/a",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    eta_min = int(eta_s // 60)
    eta_sec = int(eta_s % 60)
    msg = (
        f"  [进度] {completed}/{total} ({pct:.1f}%) "
        f"| {rate * 60:.1f} patches/min "
        f"| ETA {eta_min}m{eta_sec}s"
    )
    print(msg, flush=True)

    reports_dir = RUNS_DIR / run_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # progress.log (append)
    log_path = reports_dir / "progress.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg.strip()}\n")

    # cost_summary.json (overwrite)
    cost_path = reports_dir / "cost_summary.json"
    with open(cost_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


# ─── Shard CSV merge ───

def merge_shard_csvs(run_id: str) -> None:
    """合并所有 shard CSV → full_results_s3.csv，按 patch_id+engine 去重。"""
    manifests_dir = RUNS_DIR / run_id / "manifests"
    shard_files = sorted(manifests_dir.glob("shard_*.csv"))
    if not shard_files:
        print("  无 shard CSV 可合并")
        return

    seen = set()
    rows = []
    fieldnames = None

    for sf in shard_files:
        with open(sf, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if fieldnames is None:
                fieldnames = reader.fieldnames
            for row in reader:
                key = (row.get("patch_id", ""), row.get("engine", ""))
                if key not in seen:
                    seen.add(key)
                    rows.append(row)

    if not rows or not fieldnames:
        print("  shard CSV 为空，跳过合并")
        return

    out_path = manifests_dir / "full_results_s3.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  shard 合并完成: {out_path} ({len(rows)} 行, {len(shard_files)} shards)")


def main():
    args = parse_args()

    # Parse engines
    engines = [e.strip() for e in args.engines.split(",")]
    for e in engines:
        if e not in VALID_ENGINES:
            print(f"ERROR: 未知引擎 '{e}'，可选: {VALID_ENGINES}", file=sys.stderr)
            sys.exit(1)

    # Determine splits
    splits = [args.split] if args.split else VALID_SPLITS

    # Run ID
    run_id = args.run_id or generate_run_id()

    # Discover and plan
    total_patches = 0
    total_shards = 0
    split_plans = {}

    for split in splits:
        patches = discover_patches(split)
        shard_plan = build_shard_plan(patches, args.shard_size)
        split_plans[split] = {"patches": patches, "shards": shard_plan}
        total_patches += len(patches)
        total_shards += len(shard_plan)

    # Filter to specific shard if requested
    if args.shard is not None:
        for split in splits:
            plan = split_plans[split]
            matching = [s for s in plan["shards"] if s["shard_id"] == args.shard]
            if not matching:
                max_id = len(plan["shards"])
                print(
                    f"WARNING: split={split} 无 shard {args.shard} "
                    f"(共 {max_id} 个 shard)",
                    file=sys.stderr,
                )
            plan["shards"] = matching

    # ─── Preflight ───
    run_preflight(
        version=args.version,
        run_id=run_id,
        resume=args.resume,
        dry_run=args.dry_run,
    )

    # ─── Dry-run report ───
    if args.dry_run:
        completed_set = set()
        ckpt_path = _run_state_dir(run_id) / "checkpoint.json"
        if args.resume and ckpt_path.exists() and ckpt_path.stat().st_size > 0:
            with open(ckpt_path, encoding="utf-8") as f:
                completed_set = set(json.load(f).get("completed", []))
            print(f"  resume 模式: 跳过 {len(completed_set)} 个已完成 patch")

        # Count how many would be skipped per split
        skip_counts = {}
        for split in splits:
            plan = split_plans[split]
            skip_counts[split] = sum(
                1 for p in plan["patches"]
                if p.stem in completed_set
            )

        print("=" * 60)
        print("  STEP3+STEP4 全量批处理 — 执行计划 (dry-run)")
        print("=" * 60)
        print(f"  run_id:       {run_id}")
        print(f"  prompt 版本:  {args.version}")
        print(f"  引擎:         {', '.join(engines)}")
        print(f"  resume:       {args.resume}")
        print(f"  shard 大小:   {args.shard_size}")
        print(f"  checkpoint:   {ckpt_path}")
        if args.resume and completed_set:
            print(f"  已完成跳过:   {len(completed_set)} patches")
        print()

        for split in splits:
            plan = split_plans[split]
            n_patches = len(plan["patches"])
            active_shards = plan["shards"]
            active_count = sum(s["count"] for s in active_shards)
            skipped = skip_counts[split]
            print(f"  [{split}]")
            print(f"    patches 总数: {n_patches}")
            print(f"    shard 总数:   {len(build_shard_plan(plan['patches'], args.shard_size))}")
            print(f"    本次执行:     {len(active_shards)} shard, {active_count} patches")
            if args.resume and skipped:
                print(f"    resume 跳过:  {skipped} patches")
            if active_shards:
                for s in active_shards:
                    print(
                        f"      shard_{s['shard_id']:03d}: "
                        f"patches[{s['start']}:{s['end']}] ({s['count']} 张)"
                    )
            print()

        remaining = 0
        for sp in splits:
            plan = split_plans[sp]
            for shard in plan["shards"]:
                for p in plan["patches"][shard["start"]:shard["end"]]:
                    if not (args.resume and p.stem in completed_set):
                        remaining += 1
        est_calls = remaining * len(engines)
        print(f"  预估 API 调用总数: {est_calls}")
        print("=" * 60)
        return

    # ─── Init checkpoint ───
    ckpt = load_or_init_checkpoint(
        run_id,
        engines=engines,
        version=args.version,
        splits=splits,
        shard_size=args.shard_size,
    )

    # ─── Resume: compute skip set ───
    completed_set = set(ckpt["completed"])
    if args.resume and completed_set:
        print(f"  resume 模式: 跳过 {len(completed_set)} 个已完成 patch")

    # ─── 实际执行 ───
    install_signal_handlers()
    print(f"[{run_id}] 开始执行 — 版本 {args.version}, 引擎 {engines}")

    init_transport()
    prompt_cfg = load_prompt_config(args.version)
    engine_clients = load_engines()
    limiters = {
        name: RateLimiter(
            min_interval_s=ENGINE_MIN_INTERVALS[name],
            max_rpm=60 if name == "qwen" else 40,
        )
        for name in engines
    }
    engine_consecutive_fails = {name: 0 for name in engines}
    engine_elapsed = {name: 0.0 for name in engines}
    stopped_engines = set()
    paused_engines = set()
    start_time_iso = datetime.now(timezone.utc).isoformat()
    start_time_ts = time.time()
    patches_since_last_summary = 0

    for name in engines:
        engine = engine_clients.get(name)
        ready = bool(engine and engine.ready)
        print(f"  engine={name} ready={ready} model={engine.model if engine else 'N/A'}")
        if not ready:
            stopped_engines.add(name)

    manifests_dir = RUNS_DIR / run_id / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    failed_set = set(ckpt.get("failed", []))

    for split in splits:
        plan = split_plans[split]
        for shard in plan["shards"]:
            if is_shutdown_requested():
                print(f"[{run_id}] 优雅退出 (信号)")
                save_checkpoint_atomic(run_id, ckpt)
                sys.exit(0)

            shard_patches = plan["patches"][shard["start"]:shard["end"]]
            ckpt["current_split"] = split
            ckpt["current_shard"] = shard["shard_id"]
            csv_path = shard_csv_path(run_id, split, shard["shard_id"])
            if not csv_path.parent.exists():
                print(f"ERROR: manifests 目录不存在: {csv_path.parent}", file=sys.stderr)
                sys.exit(1)

            for patch_path in shard_patches:
                if is_shutdown_requested():
                    print(f"[{run_id}] 优雅退出 (信号)")
                    save_checkpoint_atomic(run_id, ckpt)
                    sys.exit(0)

                patch_id = patch_path.stem
                if args.resume and patch_id in completed_set:
                    continue

                ckpt["current_patch"] = patch_id
                active_engines = [
                    name for name in engines
                    if name not in stopped_engines and name not in paused_engines
                ]
                if not active_engines:
                    print(f"[{run_id}] 无可用引擎，停止执行", file=sys.stderr)
                    save_checkpoint_atomic(run_id, ckpt)
                    sys.exit(1)

                patch_transport_success = False

                for engine_name in engines:
                    if engine_name in stopped_engines:
                        continue
                    if engine_name in paused_engines:
                        continue

                    engine = engine_clients[engine_name]
                    t_engine_start = time.time()
                    transport_result = call_transport_for_patch(
                        engine,
                        patch_path,
                        prompt_cfg,
                        limiters[engine_name],
                    )
                    engine_elapsed[engine_name] += time.time() - t_engine_start
                    row = build_step3_row(
                        patch_id=patch_id,
                        split=split,
                        engine=engine,
                        transport_result=transport_result,
                    )
                    append_csv_row(csv_path, row, CSV_FIELDNAMES)

                    result = transport_result["result"]
                    parsed_json = transport_result["parsed_json"]
                    usable = bool(result.get("success")) and parsed_json is not None
                    if usable:
                        patch_transport_success = True
                        engine_consecutive_fails[engine_name] = 0
                    else:
                        engine_consecutive_fails[engine_name] += 1
                        if result.get("stop_engine"):
                            stopped_engines.add(engine_name)
                            print(
                                f"  [{engine_name}] 收到不可重试错误，停用该引擎: "
                                f"{result.get('error_message') or result.get('error_type')}",
                                flush=True,
                            )
                        elif engine_consecutive_fails[engine_name] >= 5:
                            paused_engines.add(engine_name)
                            print(
                                f"  [{engine_name}] 连续失败 5 次，暂停该引擎",
                                flush=True,
                            )

                    status = "PASS" if row["gate_pass"] else "FAIL"
                    print(
                        f"  [{split}/shard_{shard['shard_id']:03d}] {patch_id} "
                        f"{engine_name}: {status} ({row['latency_ms']}ms) "
                        f"D1={row['D1']} D2={row['D2']} D3={row['D3']}",
                        flush=True,
                    )

                if patch_transport_success:
                    failed_set.discard(patch_id)
                else:
                    failed_set.add(patch_id)
                ckpt["failed"] = sorted(failed_set)
                ckpt["completed"].append(patch_id)
                completed_set.add(patch_id)
                save_checkpoint_atomic(run_id, ckpt)
                patches_since_last_summary += 1

                # Cost summary every 500 patches
                if patches_since_last_summary >= 500:
                    total_active = sum(
                        sum(s["count"] for s in split_plans[sp]["shards"])
                        for sp in splits
                    )
                    update_cost_summary(
                        run_id,
                        completed=len(ckpt["completed"]),
                        total=total_active,
                        engine_elapsed=engine_elapsed,
                        start_time_ts=start_time_ts,
                    )
                    patches_since_last_summary = 0

    # ─── Final cost summary ───
    total_active = sum(
        sum(s["count"] for s in split_plans[sp]["shards"])
        for sp in splits
    )
    end_time_iso = datetime.now(timezone.utc).isoformat()

    update_cost_summary(
        run_id,
        completed=len(ckpt["completed"]),
        total=total_active,
        engine_elapsed=engine_elapsed,
        start_time_ts=start_time_ts,
    )

    # ─── Manifest ───
    write_manifest(
        run_id,
        version=args.version,
        engines=engines,
        engine_clients=engine_clients,
        splits=splits,
        split_plans=split_plans,
        ckpt=ckpt,
        start_time=start_time_iso,
        end_time=end_time_iso,
        engine_elapsed=engine_elapsed,
    )

    # ─── Merge shard CSVs ───
    merge_shard_csvs(run_id)

    ckpt["current_split"] = None
    ckpt["current_shard"] = None
    ckpt["current_patch"] = None
    save_checkpoint_atomic(run_id, ckpt)
    print(f"[{run_id}] 全部完成 — {len(ckpt['completed'])} patches")


if __name__ == "__main__":
    main()
