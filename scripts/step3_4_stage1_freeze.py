#!/usr/bin/env python3
"""
Stage 1: 配置冻结
- 读取 .env.step4.local（不打印 key）
- 冻结引擎配置、taxonomy、prompt 版本
- 生成 freeze 报告
- 不调用任何 API
- 幂等：重复执行只覆盖产物

用法:
  python3 scripts/step3_4_stage1_freeze.py
"""

import json, hashlib, sys, os
from pathlib import Path
from datetime import datetime, timezone

import yaml
from dotenv import dotenv_values

# ─── Paths ───
BASE = Path("/Volumes/小满/yongle_palace_dataset")
ENV_FILE = BASE / ".env.step4.local"
STATE_FILE = BASE / "state/step3_4_stage_state.json"
RUN_LOCK = BASE / "configs/step3_4_run_lock.yaml"

STAGE = "stage1_freeze"


def mask_key(k: str) -> str:
    if not k or len(k) < 10:
        return "(empty)"
    return f"{k[:6]}...{k[-4:]}"


def load_state() -> dict:
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict):
    state["updated"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def main():
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Update state: started ──
    state = load_state()
    state["current_stage"] = STAGE
    state["stages"][STAGE]["status"] = "running"
    state["stages"][STAGE]["started"] = ts_str
    save_state(state)

    output_files = []

    # ── 1. Read env (no print keys) ──
    if not ENV_FILE.exists():
        print(f"ERROR: {ENV_FILE} not found")
        state["stages"][STAGE]["status"] = "failed"
        state["stages"][STAGE]["errors"].append(f"{ENV_FILE} not found")
        save_state(state)
        sys.exit(1)

    env = dotenv_values(str(ENV_FILE))
    env_audit = {}
    expected_keys = {
        "OPENAI_API_KEY": "openai",
        "OPENAI_BASE_URL": "openai",
        "ANTHROPIC_API_KEY": "claude",
        "ANTHROPIC_BASE_URL": "claude",
        "GEMINI_API_KEY": "gemini",
        "GEMINI_BASE_URL": "gemini",
        "DASHSCOPE_API_KEY": "qwen",
    }
    for var, engine in expected_keys.items():
        val = env.get(var, "")
        if "KEY" in var:
            env_audit[var] = {"status": "found" if val else "missing", "preview": mask_key(val)}
        else:
            env_audit[var] = {"status": "found" if val else "missing", "value": val}

    print("=== Stage 1: Config Freeze ===")
    print(f"Timestamp: {ts_str}")
    for var, info in env_audit.items():
        if "preview" in info:
            print(f"  {var}: {info['status']} ({info['preview']})")
        else:
            print(f"  {var}: {info['status']} ({info.get('value', '')})")

    # ── 2. Check run_lock exists ──
    if not RUN_LOCK.exists():
        print(f"ERROR: {RUN_LOCK} not found")
        state["stages"][STAGE]["status"] = "failed"
        state["stages"][STAGE]["errors"].append(f"{RUN_LOCK} not found")
        save_state(state)
        sys.exit(1)

    with open(RUN_LOCK) as f:
        lock = yaml.safe_load(f)

    # ── 3. Define prompts and compute hashes ──
    system_prompt = """你是永乐宫三清殿《朝元图》的文化遗产数字化标注专家。
请对输入的壁画切片执行两项任务：
(1) STEP3：按 HSGF 框架输出 D1-D5 五维语义特征
(2) STEP4：按 GB/T 30237-2013 输出 P1-P4 四维病害检测与严重度

严格要求：
- 只返回纯 JSON
- 每个维度只选一个合法值
- 不允许输出词表外标签
- D1 为云气装饰或背景留白时，D2 和 D3 必须为 N/A
- "九旒冕"不是有效标签
- 必须区分绘画元素与病害，不得把墨线、衣纹、云纹、正常轮廓误判为裂隙/龟裂
- "空鼓"纯视觉下证据不足时应保守，不可激进判定
- 若无法确定，优先选择"未知"或低置信，而不是编造

输出格式严格为：
{
  "step3": {...},
  "step4": {...}
}"""

    user_prompt = """分析这张永乐宫壁画切片，严格返回纯 JSON：
{
  "step3": {
    "D1": "", "D1c": 0.0,
    "D2": "", "D2c": 0.0,
    "D3": "", "D3c": 0.0,
    "D4": "", "D4c": 0.0,
    "D5": "", "D5c": 0.0,
    "confidence": 0.0,
    "reasoning": ""
  },
  "step4": {
    "P1": "", "P2": "", "P3": "", "P4": "",
    "severity": "", "area_pct": 0.0,
    "confidence": 0.0,
    "reasoning": ""
  }
}"""

    sys_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
    usr_hash = hashlib.sha256(user_prompt.encode()).hexdigest()[:16]

    # Save prompts
    prompts_dir = BASE / "configs"
    prompt_data = {
        "version": "v1.0.0-pilot",
        "system_prompt": system_prompt,
        "system_prompt_sha256_16": sys_hash,
        "user_prompt": user_prompt,
        "user_prompt_sha256_16": usr_hash,
    }
    prompt_file = prompts_dir / "step3_4_prompts_frozen.json"
    with open(prompt_file, "w") as f:
        json.dump(prompt_data, f, indent=2, ensure_ascii=False)
    output_files.append(str(prompt_file))
    print(f"\nPrompt frozen: sys={sys_hash} usr={usr_hash}")

    # ── 4. Taxonomy freeze ──
    step3_vocab = {
        "D1": ["八主神","帝君","星君","神将","真君仙人","玉女侍从",
               "三官地府","先导护卫","云气装饰","背景留白"],
        "D2": ["十二旒冕","九旒八旒冕","通天冠","进贤冠","凤冠","道冠",
               "花冠","小冠","远游冠","金冠","簪头","皮弁","披发",
               "幞头扎抹额","风帽","双鬟髻","无","N/A"],
        "D3": ["笏板","塵拂","宝剑","经卷如意","旗帜","乐器","托盘供品",
               "兵器","印诀法器","天文器具","宫扇","龙杖","空手","N/A"],
        "D4": ["完好","轻微损伤","中度损伤","严重损伤","古代补绘"],
        "D5": ["前景","中景","背景","云气区"],
    }
    step4_vocab = {
        "P1": ["起甲","龟裂","脱落","褪色","变色","完好"],
        "P2": ["空鼓","酥碱","裂隙","粉化","完好"],
        "P3": ["裂隙","渗水","变形","完好"],
        "P4": ["烟熏","霉斑","积尘","涂写","无"],
        "severity": ["intact","mild","moderate","severe","critical"],
    }
    cross_dim_rules = [
        {"condition": "D1 in [云气装饰, 背景留白]", "enforce": "D2=N/A, D3=N/A"},
        {"condition": "D2 in [十二旒冕, 凤冠]", "enforce": "D1 in [八主神, 帝君]"},
        {"condition": "D3 in [兵器, 宝剑]", "enforce": "D1 in [神将, 先导护卫]"},
        {"condition": "D2 = 九旒冕", "enforce": "REJECT — not a valid label"},
    ]
    forbidden_step4 = ["剥离", "水渍", "污染", "掉色"]
    high_ambiguity_step4 = ["空鼓"]

    taxonomy_file = BASE / "configs" / "step3_4_taxonomy_frozen.json"
    taxonomy_data = {
        "version": "v1.0.0",
        "frozen_at": ts_str,
        "step3_vocab": step3_vocab,
        "step4_vocab": step4_vocab,
        "cross_dim_rules": cross_dim_rules,
        "step4_forbidden_raw": forbidden_step4,
        "step4_high_ambiguity": high_ambiguity_step4,
    }
    with open(taxonomy_file, "w") as f:
        json.dump(taxonomy_data, f, indent=2, ensure_ascii=False)
    output_files.append(str(taxonomy_file))
    print(f"Taxonomy frozen: {taxonomy_file.name}")

    # ── 5. Engine config (no API call, placeholder verified flags) ──
    for step_dir in ["03_features", "04_damage"]:
        ec_path = BASE / step_dir / "metadata" / "engine_config.json"
        ec_path.parent.mkdir(parents=True, exist_ok=True)
        ec = {
            "frozen_at": ts_str,
            "frozen_by": "stage1_freeze",
            "transport_module": "scripts/step3_4_transport.py",
            "interface": "OpenAI-compatible /v1/chat/completions",
            "auth": "Bearer",
            "node_undici_blocked": True,
            "engines": lock.get("engines", {}),
            "prompt_version": "v1.0.0-pilot",
            "prompt_system_hash": sys_hash,
            "prompt_user_hash": usr_hash,
            "taxonomy_version": "v1.0.0",
        }
        with open(ec_path, "w") as f:
            json.dump(ec, f, indent=2, ensure_ascii=False)
        output_files.append(str(ec_path))

    # ── 6. Generate freeze report ──
    report_path = BASE / "reports" / "step3_4_stage1_freeze_report.md"
    report_lines = [
        "# Stage 1: Config Freeze Report",
        f"\n**Generated:** {ts_str}",
        f"**Stage:** {STAGE}",
        "\n## Environment",
        "| Variable | Status | Preview |",
        "|----------|--------|---------|",
    ]
    for var, info in env_audit.items():
        preview = info.get("preview", info.get("value", ""))
        report_lines.append(f"| {var} | {info['status']} | {preview} |")

    report_lines += [
        "\n## Frozen Versions",
        f"| Component | Version |",
        f"|-----------|---------|",
        f"| Prompt (system) | {sys_hash} |",
        f"| Prompt (user) | {usr_hash} |",
        f"| Taxonomy STEP3 | v1.0.0 |",
        f"| Taxonomy STEP4 | v1.0.0 |",
        f"| Transport | scripts/step3_4_transport.py |",
        "\n## Transport Constraints",
        "- All calls via `step3_4_transport.py`",
        "- OpenAI-compatible `/v1/chat/completions` only",
        "- Bearer auth unified",
        "- Node/undici paths BLOCKED",
        "- Legacy paths (`/v1/messages`, `/v1beta`) BLOCKED",
        "\n## Output Files",
    ]
    for f_path in output_files:
        report_lines.append(f"- `{f_path}`")

    with open(report_path, "w") as f:
        f.write("\n".join(report_lines) + "\n")
    output_files.append(str(report_path))

    # ── 7. Update state: completed ──
    state = load_state()
    state["stages"][STAGE]["status"] = "completed"
    state["stages"][STAGE]["completed"] = datetime.now(timezone.utc).isoformat()
    state["stages"][STAGE]["output_files"] = output_files
    save_state(state)

    print(f"\n=== Stage 1 COMPLETE ===")
    print(f"Output files: {len(output_files)}")
    for p in output_files:
        print(f"  {p}")


if __name__ == "__main__":
    main()
