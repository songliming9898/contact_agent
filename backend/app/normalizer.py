"""
合同文本归一化模块 — 金额/日期/百分比归一化

归一化目的：不同写法的金额/日期/百分比在向量空间中距离更近，提升语义检索精度。
归一化策略：在原始文本末尾追加归一化标记，不改变原文内容。
"""

import re
import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)

# ============================================================
#  金额归一化
# ============================================================

# 中文数字映射
CN_NUM_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000,
    "万": 10000, "亿": 100000000,
}
# 大写中文数字
CN_UPPER_MAP = {
    "零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
    "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    "拾": 10, "佰": 100, "仟": 1000,
    "萬": 10000, "亿": 100000000,
    "元": None, "圆": None, "整": None,
}

# 金额正则模式
AMOUNT_PATTERNS = [
    # 大写中文金额: 人民币伍拾万元整
    (re.compile(
        r'(?:人民币|￥|¥)?'
        r'([零壹贰叁肆伍陆柒捌玖拾佰仟万亿元圆整]{2,})'
        r'(?:元|圆)?(?:整)?'
    ), "cn_upper"),

    # 小写中文金额: 五十万元
    (re.compile(
        r'([零一二两三四五六七八九十百千万亿]+)元'
    ), "cn_lower"),

    # 数字+万: 50万 / 50万元
    (re.compile(
        r'([\d,]+\.?\d*)\s*万(?:元)?'
    ), "wan"),

    # 数字+亿: 1.5亿元
    (re.compile(
        r'([\d,]+\.?\d*)\s*亿(?:元)?'
    ), "yi"),

    # 标准数字金额: ¥500,000.00 / 500,000.00 CNY
    (re.compile(
        r'(?:￥|¥|CNY|RMB)?\s*'
        r'([\d,]+\.?\d{0,2})'
        r'\s*(?:元|CNY|RMB)?'
    ), "numeric"),
]


def _cn_num_to_int(cn_str: str, upper: bool = False) -> int:
    """中文数字字符串 → 整数"""
    num_map = CN_UPPER_MAP if upper else CN_NUM_MAP
    result = 0
    section = 0
    for ch in cn_str:
        if ch in ("元", "圆", "整"):
            continue
        val = num_map.get(ch, None)
        if val is None:
            continue
        if val >= 10000:
            section = (section + result) * val
            result = 0
        elif val >= 10:
            section = (section or 1) * val
            result += section
            section = 0
        else:
            section = val
    result += section
    return result


def normalize_amount(text: str) -> Tuple[str, List[str]]:
    """
    归一化文本中的金额，追加 [AMOUNT:xxx.xxCNY] 标记。

    Args:
        text: 原始文本

    Returns:
        (归一化后的文本, 检测到的金额标记列表)
    """
    tags = []
    normalized = text

    # 1. 大写中文金额
    pattern_upper = re.compile(
        r'(?:人民币\s*)?'
        r'([零壹贰叁肆伍陆柒捌玖拾佰仟万亿元圆整]{2,})'
        r'(?:元|圆)?(?:整)?'
    )
    for m in pattern_upper.finditer(text):
        cn_str = m.group(1)
        try:
            amount = _cn_num_to_int(cn_str, upper=True)
            tag = f"[AMOUNT:{amount:.2f}CNY]"
            tags.append(tag)
        except Exception:
            continue
    if tags:
        normalized = normalized.rstrip() + " " + " ".join(tags)

    # 2. 小写中文金额: XX万元
    pattern_wan_cn = re.compile(r'([零一二两三四五六七八九十百千万亿]+)万元')
    for m in pattern_wan_cn.finditer(text):
        try:
            amount = _cn_num_to_int(m.group(1)) * 10000
            tag = f"[AMOUNT:{amount:.2f}CNY]"
            if tag not in tags:
                tags.append(tag)
                normalized = normalized.rstrip() + " " + tag
        except Exception:
            continue

    # 3. 数字+万
    pattern_wan = re.compile(r'([\d,]+\.?\d*)\s*万(?:元)?')
    for m in pattern_wan.finditer(text):
        try:
            amount = float(m.group(1).replace(",", "")) * 10000
            tag = f"[AMOUNT:{amount:.2f}CNY]"
            if tag not in tags:
                tags.append(tag)
                normalized = normalized.rstrip() + " " + tag
        except Exception:
            continue

    # 4. 标准数字金额: ¥500,000.00
    pattern_num = re.compile(
        r'(?:￥|¥|CNY|RMB)?\s*'
        r'([\d,]+\.?\d{0,2})'
        r'\s*(?:元|CNY|RMB)'
    )
    for m in pattern_num.finditer(text):
        try:
            amount = float(m.group(1).replace(",", ""))
            tag = f"[AMOUNT:{amount:.2f}CNY]"
            if tag not in tags:
                tags.append(tag)
                normalized = normalized.rstrip() + " " + tag
        except Exception:
            continue

    return normalized, tags


# ============================================================
#  日期归一化
# ============================================================

DATE_PATTERNS = [
    # YYYY年MM月DD日
    (re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日'), "ymd_cn"),
    # YYYY年MM月
    (re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月'), "ym_cn"),
    # YYYY/MM/DD
    (re.compile(r'(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})'), "ymd_slash"),
    # YYYY-MM-DD
    (re.compile(r'(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})'), "ymd_dash"),
    # 中文大写日期: 二〇二四年三月十五日
    (re.compile(r'([二〇一二三四五六七八九]{4,6})年([一二三四五六七八九十]{1,2})月([一二三四五六七八九十]{1,3})日'), "ymd_upper"),
]

# 中文大写数字 → 数字
CN_UPPER_YEAR = {
    "〇": "0", "一": "1", "二": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}

CN_UPPER_DAY = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
    "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29, "三十": 30,
    "三十一": 31,
}


def normalize_date(text: str) -> Tuple[str, List[str]]:
    """
    归一化文本中的日期，追加 [DATE:YYYY-MM-DD] 标记。

    Args:
        text: 原始文本

    Returns:
        (归一化后的文本, 检测到的日期标记列表)
    """
    tags = []
    normalized = text
    seen = set()

    # 1. YYYY年MM月DD日
    for m in DATE_PATTERNS[0][0].finditer(text):
        y, mth, d = m.group(1), m.group(2), m.group(3)
        tag = f"[DATE:{int(y):04d}-{int(mth):02d}-{int(d):02d}]"
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # 2. YYYY/MM/DD
    for m in DATE_PATTERNS[2][0].finditer(text):
        y, mth, d = m.group(1), m.group(2), m.group(3)
        tag = f"[DATE:{int(y):04d}-{int(mth):02d}-{int(d):02d}]"
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # 3. YYYY-MM-DD
    for m in DATE_PATTERNS[3][0].finditer(text):
        y, mth, d = m.group(1), m.group(2), m.group(3)
        tag = f"[DATE:{int(y):04d}-{int(mth):02d}-{int(d):02d}]"
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # 4. 中文大写日期
    for m in DATE_PATTERNS[4][0].finditer(text):
        try:
            y_cn, m_cn, d_cn = m.group(1), m.group(2), m.group(3)
            y = "".join(CN_UPPER_YEAR.get(c, c) for c in y_cn)
            mth = CN_UPPER_DAY.get(m_cn, int(m_cn) if m_cn.isdigit() else 1)
            d = CN_UPPER_DAY.get(d_cn, int(d_cn) if d_cn.isdigit() else 1)
            tag = f"[DATE:{int(y):04d}-{int(mth):02d}-{int(d):02d}]"
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
        except Exception:
            continue

    if tags:
        normalized = normalized.rstrip() + " " + " ".join(tags)

    # 期限检测: X个工作日/X个月/X年
    duration_patterns = [
        (re.compile(r'(\d+)\s*个?\s*工作日'), "working_days"),
        (re.compile(r'(\d+)\s*个?\s*月'), "months"),
        (re.compile(r'(\d+)\s*个?\s*年'), "years"),
        (re.compile(r'(\d+)\s*个?\s*日'), "days"),
    ]
    for pat, unit in duration_patterns:
        for m in pat.finditer(text):
            num = int(m.group(1))
            tag = f"[DURATION:{num}_{unit}]"
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
                normalized = normalized.rstrip() + " " + tag

    return normalized, tags


# ============================================================
#  百分比归一化
# ============================================================

PCT_PATTERNS = [
    # 数字%: 30%
    (re.compile(r'(\d+\.?\d*)\s*%'), "num_pct"),
    # 中文百分比: 百分之三十
    (re.compile(r'百分之\s*([零一二两三四五六七八九十百]+)'), "cn_pct"),
]


def normalize_percentage(text: str) -> Tuple[str, List[str]]:
    """
    归一化文本中的百分比，追加 [PCT:X%] 标记。

    Args:
        text: 原始文本

    Returns:
        (归一化后的文本, 检测到的百分比标记列表)
    """
    tags = []
    normalized = text
    seen = set()

    # 数字百分比
    for m in PCT_PATTERNS[0][0].finditer(text):
        pct = float(m.group(1))
        tag = f"[PCT:{pct}%]"
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # 中文百分比
    for m in PCT_PATTERNS[1][0].finditer(text):
        try:
            cn = m.group(1)
            pct = _cn_num_to_int(cn)
            tag = f"[PCT:{pct}%]"
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
        except Exception:
            continue

    if tags:
        normalized = normalized.rstrip() + " " + " ".join(tags)

    return normalized, tags


# ============================================================
#  统一归一化入口
# ============================================================

def normalize_text(text: str) -> Tuple[str, dict]:
    """
    对文本执行全部归一化：金额 → 日期 → 百分比。

    Args:
        text: 原始文本

    Returns:
        (归一化后的文本, 归一化统计)
    """
    stats = {
        "amount_tags": [],
        "date_tags": [],
        "pct_tags": [],
        "amount_count": 0,
        "date_count": 0,
        "pct_count": 0,
    }

    # 按顺序执行归一化
    normalized, amount_tags = normalize_amount(text)
    stats["amount_tags"] = amount_tags
    stats["amount_count"] = len(amount_tags)

    normalized, date_tags = normalize_date(normalized)
    stats["date_tags"] = date_tags
    stats["date_count"] = len(date_tags)

    normalized, pct_tags = normalize_percentage(normalized)
    stats["pct_tags"] = pct_tags
    stats["pct_count"] = len(pct_tags)

    return normalized, stats


def normalize_batch(texts: List[str]) -> List[Tuple[str, dict]]:
    """
    批量归一化。

    Args:
        texts: 文本列表

    Returns:
        [(归一化后文本, 统计), ...]
    """
    results = []
    for i, text in enumerate(texts):
        try:
            norm_text, stats = normalize_text(text)
            results.append((norm_text, stats))
        except Exception as e:
            logger.warning(f"文本归一化失败 (index={i}): {e}")
            results.append((text, {"error": str(e)}))
    return results
