#!/usr/bin/env python3
"""
YongleAI 权威词表 Python 模块
================================
唯一权威源: yongle-workflow-v2_9_9.html
  HSGF_CATEGORIES (line 16683)
  DAMAGE_CATEGORIES (line 16788)
  StepArchive.VOCAB (line 16809)
  STEP3_ALIAS_MAP (line 16720)

用法:
  from canonical_taxonomy import VALID_LABELS, ALIAS_MAP, DAMAGE_LABELS, normalize_label
"""

# ============================================================
# STEP3 — HSGF 五维词表 (51 标签)
# ============================================================

VALID_LABELS = {
    "D1": [
        "八主神", "帝君", "星君", "神将", "真君仙人",
        "玉女侍从", "三官地府", "先导护卫", "云气装饰", "背景留白"
    ],
    "D2": [
        "十二旒冕", "九旒八旒冕", "通天冠", "进贤冠", "凤冠",
        "道冠", "花冠", "小冠", "远游冠", "金冠",
        "簪头", "皮弁", "披发", "幞头扎抹额", "风帽",
        "双鬟髻", "无", "N/A"
    ],
    "D3": [
        "笏板", "塵拂", "宝剑", "经卷如意", "旗帜",
        "乐器", "托盘供品", "兵器", "印诀法器", "天文器具",
        "宫扇", "龙杖", "空手", "N/A"
    ],
    "D4": [
        "完好", "轻微损伤", "中度损伤", "严重损伤", "古代补绘"
    ],
    "D5": [
        "前景", "中景", "背景", "云气区"
    ],
}

# 人物主体 D1 子集 (前8类)
FIGURE_D1 = frozenset([
    "八主神", "帝君", "星君", "神将",
    "真君仙人", "玉女侍从", "三官地府", "先导护卫"
])

# ============================================================
# STEP4 — 四层病害体系 (25 标签 + 5 severity)
# ============================================================

DAMAGE_LABELS = {
    "P1": ["起甲", "龟裂", "脱落", "褪色", "变色", "完好"],
    "P2": ["空鼓", "酥碱", "裂隙", "粉化", "完好"],
    "P3": ["裂隙", "渗水", "变形", "完好"],
    "P4": ["烟熏", "霉斑", "积尘", "涂写", "无"],
    "severity_en": ["intact", "mild", "moderate", "severe", "critical"],
    "severity_cn": {
        "intact": "完好", "mild": "轻微", "moderate": "中度",
        "severe": "严重", "critical": "濒危"
    },
}

# ============================================================
# VLM 输出别名映射 (STEP3_ALIAS_MAP)
# ============================================================

ALIAS_MAP = {
    "D1": {
        "主神帝君": "八主神", "主神": "八主神", "天尊": "八主神",
        "天王神将": "神将",
        "仙官真人": "真君仙人",
        "侍从仙女": "玉女侍从",
        "供养人像": "先导护卫",
        "云气祥瑞": "云气装饰", "云气": "云气装饰", "纹饰图案": "云气装饰",
        "建筑宫殿": "背景留白", "法器器物": "背景留白",
        "留白": "背景留白", "background": "背景留白", "blank": "背景留白",
        # 旧版标签兼容
        "玉女": "玉女侍从", "力士": "神将", "天丁": "先导护卫",
        "真人": "真君仙人", "仙官": "真君仙人", "龙虎": "先导护卫",
    },
    "D2": {
        "十二旒": "十二旒冕", "12旒冕": "十二旒冕",
        "九旒冕": "九旒八旒冕", "八旒冕": "九旒八旒冕",
        "莲花冠": "花冠", "芙蓉冠": "花冠",
        "束发金冠": "金冠", "束发冠": "金冠",
        "无冠": "无", "无冠饰": "无", "none": "无",
        "n/a": "N/A", "na": "N/A",
        # 旧版标签兼容
        "五岳冠": "道冠", "星冠": "道冠",
        "宝髻": "双鬟髻", "扎巾帻": "幞头扎抹额",
        "兜鍪": "皮弁", "卷云发": "披发",
        "抹额": "幞头扎抹额", "其他冠饰": "无",
    },
    "D3": {
        "圭板": "笏板",
        "拂尘": "塵拂",
        "如意": "经卷如意",
        "兵刃": "兵器",
        "龙旗": "旗帜", "长幡": "旗帜",
        "障扇": "宫扇", "团扇": "宫扇",
        "三天火印": "印诀法器", "火印": "印诀法器", "法铃": "印诀法器",
        "帝钟": "天文器具",
        "香炉": "托盘供品", "宝瓶": "托盘供品", "供品": "托盘供品",
        "玉杯": "托盘供品",
        "花枝": "托盘供品",
        "经卷": "经卷如意",
        "无持物": "空手", "无": "空手", "none": "空手",
        "n/a": "N/A", "na": "N/A",
        "其他法器": "印诀法器",
    },
    "D4": {
        "轻度损伤": "轻微损伤",
        "中度": "中度损伤",
        "重度损伤": "严重损伤", "严重": "严重损伤", "极重": "严重损伤",
        "none": "完好",
        # 旧版标签兼容
        "轻微破损": "轻微损伤", "中度破损": "中度损伤",
        "严重破损": "严重损伤", "颜料脱落": "严重损伤",
    },
    "D5": {
        "前景主体": "前景",
        "中景过渡": "中景",
        "背景装饰": "背景", "边缘过渡": "背景",
        "云气带": "云气区", "云气": "云气区",
        # 旧版标签兼容
        "上层": "前景", "中层": "中景", "下层": "背景", "跨层": "前景",
    },
}

# ============================================================
# 缺省值 (VLM 返回空值时的 fallback)
# ============================================================

FALLBACK_DEFAULTS = {
    "D1": "背景留白",
    "D2": "N/A",
    "D3": "N/A",
    "D4": "严重损伤",
    "D5": "中景",
    "P1": "完好",
    "P2": "完好",
    "P3": "完好",
    "P4": "无",
}

# ============================================================
# 正规化函数
# ============================================================

import re

def _clean_value(v: str) -> str:
    """清理 VLM 原始输出中的前缀/标点"""
    s = str(v or "").strip().strip("\"'`")
    s = re.sub(r"[()（）]", "", s)
    s = s.replace("_", "")
    # 去除 D1-5 前缀
    s = re.sub(r"^D[1-5]\s*[-_：:]*\s*\d+\s*", "", s, flags=re.I)
    s = re.sub(r"^D[1-5]\s*[-_：:]\s*", "", s, flags=re.I)
    s = re.sub(r"^[0-9]+\s*[).、:：\-]\s*", "", s)
    # 只取首个片段
    s = re.split(r"[，,;；\n]", s)[0]
    return s.strip()


def normalize_label(dim: str, value, fallback: str = None) -> str:
    """
    将 VLM 输出正规化为工作站 canonical 标签。

    dim: "D1"-"D5" 或 "P1"-"P4"
    value: VLM 原始输出
    fallback: 未匹配时的默认值（None 则使用 FALLBACK_DEFAULTS）

    返回: canonical 标签字符串
    """
    if fallback is None:
        fallback = FALLBACK_DEFAULTS.get(dim, "")

    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None or str(value).strip() == "":
        return fallback

    # 数值编码处理
    code_map = {
        "D1": {1:"八主神",2:"帝君",3:"星君",4:"神将",5:"真君仙人",
               6:"玉女侍从",7:"三官地府",8:"先导护卫",9:"云气装饰",10:"背景留白"},
        "D4": {0:"完好",1:"轻微损伤",2:"中度损伤",3:"严重损伤",4:"古代补绘"},
        "D5": {1:"前景",2:"中景",3:"背景",4:"云气区"},
    }
    sv = str(value).strip()
    if sv.isdigit() and dim in code_map:
        mapped = code_map[dim].get(int(sv))
        if mapped:
            return mapped

    # 文本清理
    cleaned = _clean_value(value)

    # 直接匹配
    vocab = VALID_LABELS.get(dim) or DAMAGE_LABELS.get(dim, [])
    if cleaned in vocab:
        return cleaned

    # 别名匹配
    alias = ALIAS_MAP.get(dim, {}).get(cleaned)
    if alias and alias in vocab:
        return alias

    # 大小写不敏感匹配
    lower_map = {v.lower(): v for v in vocab}
    if cleaned.lower() in lower_map:
        return lower_map[cleaned.lower()]

    alias_lower = ALIAS_MAP.get(dim, {}).get(cleaned.lower())
    if alias_lower and alias_lower in vocab:
        return alias_lower

    return fallback


def validate_d1_d2_d3_consistency(d1: str, d2: str, d3: str, d4: str = "") -> list[str]:
    """检查 D1-D2-D3(-D4) 联动一致性，返回警告列表。

    v4.1-draft 变更:
    - D4=严重损伤 时，D2=N/A 和 D3=N/A 合法（不算 cross-dim fail）
    - D4=严重损伤 且 D2/D3 非 N/A 时，增加 warning（不自动改写标签）
    """
    warnings = []

    # 规则 1: 非人物区域 D2/D3 必须 N/A
    if d1 in ("云气装饰", "背景留白"):
        if d2 != "N/A":
            warnings.append(f"D1={d1} 时 D2 应为 N/A，实际为 {d2}")
        if d3 != "N/A":
            warnings.append(f"D1={d1} 时 D3 应为 N/A，实际为 {d3}")

    # 规则 2: 严重损伤下的 D2/D3 宽松处理
    if d4 == "严重损伤":
        # D2=N/A 或 D3=N/A 在严重损伤下合法，不产生 warning
        # 但如果 D2/D3 给出了具体值，发出提醒（不阻塞）
        if d1 in ("八主神", "帝君") and d3 not in ("N/A", ""):
            warnings.append(f"D4=严重损伤 下 D1={d1} D3={d3}，建议核查持物是否可辨")
        if d2 not in ("N/A", "无", "") and d1 not in ("云气装饰", "背景留白"):
            warnings.append(f"D4=严重损伤 下 D2={d2}，建议核查冠饰是否可辨")
    else:
        # 规则 3: 非严重损伤下，高阶神像空手仍为 warning
        if d1 in ("八主神", "帝君") and d3 == "空手":
            warnings.append(f"D1={d1} 通常持笏板/经卷如意/龙杖，但 D3=空手")

    # 规则 4: 武将戴文冠
    if d1 in ("神将", "先导护卫") and d2 in ("十二旒冕", "通天冠"):
        warnings.append(f"D1={d1} 通常不戴 {d2}")

    return warnings


# ============================================================
# 自检
# ============================================================

if __name__ == "__main__":
    print("=== YongleAI 权威词表自检 ===\n")

    # 标签计数
    s3_total = sum(len(v) for v in VALID_LABELS.values())
    s4_total = sum(len(v) for k, v in DAMAGE_LABELS.items() if isinstance(v, list))
    print(f"STEP3 标签总数: {s3_total} (预期 51)")
    for dim, items in VALID_LABELS.items():
        print(f"  {dim}: {len(items)} — {items}")

    print(f"\nSTEP4 标签总数: {s4_total} (预期 20, + 5 severity)")
    for dim, items in DAMAGE_LABELS.items():
        if isinstance(items, list):
            print(f"  {dim}: {len(items)} — {items}")

    # 别名映射测试
    print("\n=== 别名映射测试 ===")
    test_cases = [
        ("D1", "天尊", "八主神"),
        ("D1", "玉女", "玉女侍从"),
        ("D1", "力士", "神将"),
        ("D2", "九旒冕", "九旒八旒冕"),
        ("D2", "莲花冠", "花冠"),
        ("D3", "圭板", "笏板"),
        ("D3", "拂尘", "塵拂"),
        ("D3", "如意", "经卷如意"),
        ("D3", "无持物", "空手"),
        ("D4", "轻微破损", "轻微损伤"),
        ("D4", "颜料脱落", "严重损伤"),
        ("D5", "上层", "前景"),
        ("D5", "中层", "中景"),
        ("D5", "下层", "背景"),
    ]

    all_pass = True
    for dim, input_val, expected in test_cases:
        result = normalize_label(dim, input_val)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_pass = False
        print(f"  {status} {dim}: '{input_val}' → '{result}' (预期: '{expected}')")

    print(f"\n{'🎉 全部通过' if all_pass else '❌ 有失败项'}")
