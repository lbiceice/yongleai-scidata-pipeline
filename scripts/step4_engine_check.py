#!/usr/bin/env python3
"""
STEP3/STEP4 统一引擎自检 v3.0.0

重构说明 (v3):
  - 所有引擎定义和连接逻辑统一从 step3_4_transport.py 导入
  - 移除旧的 Anthropic 原生 /v1/messages 路径
  - 移除旧的 Google 原生 /v1beta 路径
  - 自检包含实际 text-only 连通性测试（不再 deferred）

密钥来源:
  .env.step4.local（唯一来源）

安全规则:
  - 不打印完整 key
  - 不从 stdin 读取 key
"""

import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone

# ─── Import shared transport (唯一 API 调用路径) ───
sys.path.insert(0, str(Path(__file__).parent))
from step3_4_transport import load_engines, RateLimiter, call_with_retry, build_text_message

PROJECT_ROOT = Path("/Volumes/小满/yongle_palace_dataset")


def run_check(output_dir: Path = None) -> dict:
    """执行全量引擎自检，包含实际连通性测试。"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    engines = load_engines()
    limiter = RateLimiter(min_interval_s=1.5)

    results = []
    for name, eng in engines.items():
        info = eng.info()
        record = {
            "engine": name,
            **info,
            "connectivity": None,
            "connectivity_latency": None,
            "connectivity_model": None,
            "connectivity_error": None,
        }

        if not eng.ready:
            record["connectivity"] = "skipped"
            record["connectivity_error"] = "not ready (missing key or url)"
        else:
            # 实际 text-only 连通性测试
            r = call_with_retry(
                eng,
                build_text_message("Reply with exactly: ENGINE_CHECK_OK"),
                limiter,
                max_tokens=50,
                timeout=30,
            )
            record["connectivity"] = "pass" if r["success"] else "fail"
            record["connectivity_latency"] = r["latency_s"]
            record["connectivity_model"] = r.get("model_returned")
            if not r["success"]:
                record["connectivity_error"] = f"{r.get('error_type')}: {r.get('error_message', '')[:200]}"

        results.append(record)

    ready_engines = [r for r in results if r["ready"] and r["connectivity"] == "pass"]
    summary = {
        "timestamp": ts,
        "transport_module": "scripts/step3_4_transport.py",
        "interface": "OpenAI-compatible /v1/chat/completions (all engines)",
        "env_file": str(PROJECT_ROOT / ".env.step4.local"),
        "engines": results,
        "ready_count": len(ready_engines),
        "ready_engines": [r["engine"] for r in ready_engines],
        "consensus_ready": len(ready_engines) >= 2,
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Log
        log_dir = output_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        with open(log_dir / "engine_check.log", "w") as f:
            f.write(f"[{ts}] Engine Connectivity Check\n")
            f.write(f"  transport: step3_4_transport.py\n")
            f.write(f"  interface: OpenAI-compatible /v1/chat/completions\n\n")
            for r in results:
                status = "READY" if r["connectivity"] == "pass" else "FAIL"
                lat = f"{r['connectivity_latency']}s" if r["connectivity_latency"] else "N/A"
                f.write(f"  [{status}] {r['engine']:<10} {lat:<8} model={r.get('connectivity_model', 'N/A'):<30} base={r['base_url']}\n")
            f.write(f"\n  Ready: {len(ready_engines)}/{len(results)}\n")
            f.write(f"  Consensus: {'YES' if summary['consensus_ready'] else 'NO'}\n")

        # JSON
        with open(output_dir / "engine_check.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


if __name__ == "__main__":
    out_dir = None
    if len(sys.argv) > 1:
        out_dir = Path(sys.argv[1])

    summary = run_check(output_dir=out_dir)

    print("=== Engine Check (via step3_4_transport.py) ===")
    print(f"Transport: OpenAI-compatible /v1/chat/completions (all engines)")
    print()
    for e in summary["engines"]:
        status = "PASS" if e["connectivity"] == "pass" else "FAIL"
        lat = f"{e['connectivity_latency']}s" if e["connectivity_latency"] else "—"
        model = e.get("connectivity_model") or "—"
        print(f"  [{status}] {e['engine']:<10} {lat:<8} model={model:<30} base={e['base_url']}")
    print()
    print(f"Ready: {summary['ready_count']}/{len(summary['engines'])}")
    print(f"Consensus (>=2): {'YES' if summary['consensus_ready'] else 'NO'}")

    sys.exit(0 if summary["consensus_ready"] else 1)
