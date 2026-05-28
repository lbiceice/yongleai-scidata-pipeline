#!/usr/bin/env python3
"""
STEP4 标签校验器 v2.0.0 — 阻断非法标签静默回退

规则:
  1. normalized_label 必须属于官方词表 valid_labels (damage + special)
  2. severity 必须属于 valid_severity
  3. 安全别名自动归一化: raw_label → normalized_label
  4. 不安全标签: raw_label 保留, normalized_label=未知, review_required=true
  5. 禁止将非法标签静默回退为 完好/无病害
     - 完好/无病害 本身是合法标签，但只能由引擎直接输出
     - 非法标签 → normalized_label=未知 (不是完好/无病害)
  6. 跨层共享标签(裂隙)必须附带 layer 字段

用法:
  from step4_label_validator import Step4LabelValidator
  validator = Step4LabelValidator(run_dir)
  result = validator.validate("开裂", layer="P2_地仗层")
"""

import yaml
import json
import os
from pathlib import Path
from datetime import datetime, timezone


class Step4LabelValidator:
    """STEP4 标签归一化与校验器 v2.0.0"""

    def __init__(self, run_dir: str):
        self.run_dir = Path(run_dir)
        self._load_taxonomy()
        self._load_alias_map()

    def _load_taxonomy(self):
        path = self.run_dir / "dictionaries" / "step4_taxonomy.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.valid_labels = set(data["valid_labels"])
        self.valid_damage_labels = set(data["valid_damage_labels"])
        self.valid_severity = set(data["valid_severity"])
        self.valid_special = set(data["valid_special"])
        self.forbidden_pseudo = set(data["forbidden_pseudo_labels"])
        self.cross_layer = data.get("cross_layer_labels", {})
        self.taxonomy = data["taxonomy"]

    def _load_alias_map(self):
        path = self.run_dir / "dictionaries" / "step4_alias_map.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.safe_alias = data.get("safe_alias", {})
        self.unsafe_raw = data.get("unsafe_raw", {})

    def validate(self, raw_label: str, layer: str = None, severity: str = None) -> dict:
        """
        校验并归一化单个标签。

        返回:
          {
            "raw_label": str,
            "normalized_label": str,      # 合法标签 或 "未知"
            "layer": str | None,
            "severity": str | None,
            "severity_valid": bool,
            "review_required": bool,
            "review_reason": str | None,
            "resolution": str  # "direct" | "alias" | "review" | "rejected"
          }
        """
        raw = raw_label.strip()
        result = {
            "raw_label": raw,
            "normalized_label": "未知",
            "layer": layer,
            "severity": severity,
            "severity_valid": severity in self.valid_severity if severity else None,
            "review_required": False,
            "review_reason": None,
            "resolution": None,
        }

        # severity 校验（如果提供了）
        sev_warning = None
        if severity and severity not in self.valid_severity:
            sev_warning = f"severity='{severity}' 不合法，合法值: {sorted(self.valid_severity)}"

        # --- 拦截伪标签 ---
        if raw in self.forbidden_pseudo or raw.lower() in ("none", "null", "", "unknown", "other", "normal"):
            result["normalized_label"] = "未知"
            result["resolution"] = "rejected"
            result["review_required"] = True
            result["review_reason"] = (
                f"禁止的伪标签 '{raw}' — 不允许作为病害标签。"
                f"normalized_label 设为 '未知'，需人工判断。"
            )
            if sev_warning:
                result["review_reason"] += f" 另: {sev_warning}"
            return result

        # --- 直接匹配官方词表 (damage + special) ---
        if raw in self.valid_labels:
            result["normalized_label"] = raw
            result["resolution"] = "direct"
            # 跨层标签检查
            if raw in self.cross_layer and layer is None:
                result["review_required"] = True
                result["review_reason"] = (
                    f"'{raw}' 是跨层共享标签，必须指定 layer 字段消歧。"
                    f"可选层: {self.cross_layer[raw]['layers']}"
                )
            if sev_warning:
                result["review_required"] = True
                reason = result["review_reason"] or ""
                result["review_reason"] = (reason + " " + sev_warning).strip()
            return result

        # --- 安全别名归一化 ---
        if raw in self.safe_alias:
            normalized = self.safe_alias[raw]
            result["normalized_label"] = normalized
            result["resolution"] = "alias"
            if normalized in self.cross_layer and layer is None:
                result["review_required"] = True
                result["review_reason"] = (
                    f"别名 '{raw}' → '{normalized}' 是跨层共享标签，"
                    f"必须指定 layer。可选层: {self.cross_layer[normalized]['layers']}"
                )
            if sev_warning:
                result["review_required"] = True
                reason = result["review_reason"] or ""
                result["review_reason"] = (reason + " " + sev_warning).strip()
            return result

        # --- 不安全标签 → normalized_label=未知, review_required=true ---
        if raw in self.unsafe_raw:
            info = self.unsafe_raw[raw]
            result["normalized_label"] = "未知"
            result["resolution"] = "review"
            result["review_required"] = True
            result["review_reason"] = (
                f"不安全标签 '{raw}': {info['reason']} "
                f"候选: {info.get('candidate_labels', [])}"
            )
            if sev_warning:
                result["review_reason"] += f" 另: {sev_warning}"
            return result

        # --- 未知标签 → 兜底: normalized_label=未知, 绝不静默回退 ---
        result["normalized_label"] = "未知"
        result["resolution"] = "review"
        result["review_required"] = True
        result["review_reason"] = (
            f"未知标签 '{raw}' 不在官方词表和别名表中。"
            f"raw_label 已保留, normalized_label=未知, 需人工判断。"
        )
        if sev_warning:
            result["review_reason"] += f" 另: {sev_warning}"
        return result

    def validate_batch(self, records: list[dict]) -> dict:
        """批量校验。输入: [{"raw_label": ..., "layer": ..., "severity": ...}, ...]"""
        results = []
        stats = {"total": 0, "direct": 0, "alias": 0, "review": 0, "rejected": 0}
        for rec in records:
            raw = rec.get("raw_label", rec.get("label", ""))
            layer = rec.get("layer", None)
            severity = rec.get("severity", None)
            r = self.validate(raw, layer=layer, severity=severity)
            merged = {**rec, **r}
            results.append(merged)
            stats["total"] += 1
            stats[r["resolution"]] += 1
        return {"results": results, "stats": stats}

    def export_review_queue(self, results: list[dict], output_dir: str = None):
        """将 review_required=True 的记录写入 review_queue/"""
        if output_dir is None:
            output_dir = str(self.run_dir / "review_queue")
        os.makedirs(output_dir, exist_ok=True)

        review_items = [r for r in results if r.get("review_required")]
        if not review_items:
            return []

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        outpath = os.path.join(output_dir, f"label_review_{ts}.jsonl")
        with open(outpath, "w", encoding="utf-8") as f:
            for item in review_items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return review_items


def pre_export_label_gate(records: list[dict], run_dir: str) -> list[dict]:
    """
    导出前标签守门。

    规则:
      - normalized_label 是 forbidden_pseudo → 阻断 (ValueError)
      - normalized_label 不在 valid_labels → 阻断 (ValueError)
      - normalized_label=未知 → 合法但 review_required，从导出中剔除
      - review_required=True → 从导出中剔除，写入 review_queue
    """
    validator = Step4LabelValidator(run_dir)
    clean = []
    blocked = []

    for rec in records:
        nl = rec.get("normalized_label")

        # 阻断 forbidden pseudo
        if nl in validator.forbidden_pseudo or (
            isinstance(nl, str) and nl.lower() in ("none", "null", "", "unknown", "other", "normal")
        ):
            raise ValueError(
                f"EXPORT BLOCKED: normalized_label='{nl}' 是禁止伪标签。"
                f"raw_label='{rec.get('raw_label')}'。静默回退已被阻断。"
            )

        # 阻断非法标签
        if nl is not None and nl not in validator.valid_labels:
            raise ValueError(
                f"EXPORT BLOCKED: normalized_label='{nl}' 不在官方词表中。"
            )

        # 剔除待审核记录（包含 normalized_label=未知 的）
        if rec.get("review_required"):
            blocked.append(rec)
            continue

        clean.append(rec)

    if blocked:
        validator.export_review_queue(blocked)

    return clean


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python step4_label_validator.py <run_dir>")
        sys.exit(1)

    run_dir = sys.argv[1]
    validator = Step4LabelValidator(run_dir)

    test_labels = [
        # --- 直接匹配 (damage) ---
        {"raw_label": "起甲", "layer": "P1_颜料层", "severity": "中度"},
        {"raw_label": "裂隙", "layer": "P2_地仗层", "severity": "严重"},
        {"raw_label": "裂隙"},  # 跨层缺 layer → review
        # --- 直接匹配 (special) ---
        {"raw_label": "无病害", "severity": "完好"},
        {"raw_label": "未知"},
        # --- 安全别名 ---
        {"raw_label": "开裂", "layer": "P3_支撑体", "severity": "轻微"},
        {"raw_label": "潮湿痕迹", "layer": "P3_支撑体"},
        {"raw_label": "微生物污染", "layer": "P4_表面污染"},
        # --- 不安全标签 → normalized_label=未知 ---
        {"raw_label": "剥离"},
        {"raw_label": "水渍"},
        {"raw_label": "污染"},
        {"raw_label": "掉色"},
        # --- 伪标签 → rejected ---
        {"raw_label": "无"},
        {"raw_label": "none"},
        {"raw_label": ""},
        # --- 未知标签 → review ---
        {"raw_label": "虫蛀"},
        # --- severity 校验 ---
        {"raw_label": "霉斑", "layer": "P4_表面污染", "severity": "极重"},  # 非法 severity
    ]

    batch = validator.validate_batch(test_labels)
    print("=== STEP4 标签校验自检 v2.0.0 ===")
    print(f"总数: {batch['stats']['total']}")
    print(f"  直接匹配 (direct): {batch['stats']['direct']}")
    print(f"  别名归一化 (alias): {batch['stats']['alias']}")
    print(f"  需审核 (review):    {batch['stats']['review']}")
    print(f"  已拦截 (rejected):  {batch['stats']['rejected']}")
    print()
    for r in batch["results"]:
        flag = "REVIEW" if r["review_required"] else "OK"
        nl = r["normalized_label"]
        sev = r.get("severity", "-")
        print(f"  [{flag:6s}] {r['raw_label']:12s} → {nl:6s}  sev={str(sev):4s}  [{r['resolution']}]")
        if r["review_reason"]:
            print(f"           reason: {r['review_reason']}")
