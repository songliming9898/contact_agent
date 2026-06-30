"""
合同语义边界切分模块 — 按条款层级而非固定 token 切分

切分策略（4级优先级）：
1. 第一级：条款标题（第X条 / 第X章 / 第X节）
2. 第二级：款（1. / 2. / (一) / (二) / ① / ②）
3. 第三级：自然段（双换行 \n\n）
4. 兜底：512 字符强制截断
"""

import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============================================================
#  条款边界检测模式
# ============================================================

# 第一级：章节条款标题
SECTION_PATTERNS = [
    # 第X章 / 第X节 / 第X条
    re.compile(r'^第[一二三四五六七八九十百\d]+[章节条]'),
    # 第X部分
    re.compile(r'^第[一二三四五六七八九十百\d]+部分'),
    # 附件/附录
    re.compile(r'^(附件|附录|附表)[一二三四五六七八九十\d]*'),
]

# 第二级：款/项
CLAUSE_PATTERNS = [
    # 1. / 1、 / 1)
    re.compile(r'^\d+[\.、\)）]\s'),
    # (一) / （一）
    re.compile(r'^[（(][一二三四五六七八九十\d]+[）)]'),
    # ① ②
    re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩]'),
    # (1) / （1）
    re.compile(r'^[（(]\d+[）)]'),
]

# 条款类型关键词 → 语义标签
CLAUSE_KEYWORDS = {
    "付款": ["付款", "支付", "结算", "费用"],
    "金额": ["金额", "总价", "价款", "合同价格"],
    "首付款": ["首付", "首期", "预付款"],
    "时间节点": ["日期", "期限", "时间", "工期", "交付时间"],
    "违约": ["违约", "罚则", "赔偿"],
    "保密": ["保密", "机密", "非公开"],
    "知识产权": ["知识产权", "著作权", "专利", "商标", "版权"],
    "验收": ["验收", "测试", "上线", "交付"],
    "售后": ["售后", "维护", "保修", "服务期", "技术支持"],
    "试用": ["试用", "测试期", "试运行"],
    "争议": ["争议", "仲裁", "诉讼", "管辖"],
    "变更": ["变更", "修改", "补充协议"],
    "终止": ["终止", "解除", "不可抗力"],
}

# 金额/日期/百分比关键词（用于元数据标注）
AMOUNT_KEYWORDS = ["元", "¥", "￥", "CNY", "RMB", "金额", "费用", "价款"]
DATE_KEYWORDS = ["年", "月", "日", "期限", "日期", "期间"]
PCT_KEYWORDS = ["%", "百分之", "比例"]
TABLE_KEYWORDS = ["如下表", "详见下表", "下表", "清单如下"]


def _detect_semantic_tags(text: str) -> List[str]:
    """检测文本中的语义标签"""
    tags = set()
    text_lower = text.lower()
    for label, keywords in CLAUSE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                tags.add(label)
                break
    return list(tags)


def _detect_special_markers(text: str) -> Dict[str, bool]:
    """检测文本中的特殊标记"""
    return {
        "has_amount": any(kw in text for kw in AMOUNT_KEYWORDS),
        "has_date": any(kw in text for kw in DATE_KEYWORDS),
        "has_percentage": any(kw in text for kw in PCT_KEYWORDS),
        "has_table": any(kw in text for kw in TABLE_KEYWORDS),
    }


def _get_clause_title(line: str) -> Optional[str]:
    """检测是否为条款标题行，返回标题文本"""
    for pat in SECTION_PATTERNS:
        if pat.match(line.strip()):
            return line.strip()
    return None


def _is_clause_start(line: str) -> bool:
    """检测是否为款/项起始行"""
    stripped = line.strip()
    for pat in CLAUSE_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def split_by_semantic_boundary(
    text: str,
    contract_id: str = "",
    max_chunk_chars: int = 512,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    按合同条款语义边界切分文本。

    Args:
        text: 合同全文
        contract_id: 合同编号
        max_chunk_chars: 单个 chunk 最大字符数（兜底截断）
        metadata: 文档级元数据（party_a, party_b, sign_date, total_amount 等）

    Returns:
        [
            {
                "chunk_id": "CON-001-chunk-001",
                "text": "第三条 付款方式 [AMOUNT:500000.00CNY]",
                "section_title": "第三条 付款方式",
                "clause_type": "付款",
                "clause_level": 1,
                "contract_id": "CON-001",
                "party_a": "...",
                "party_b": "...",
                "semantic_tags": ["付款", "金额"],
                "has_amount": True,
                "has_date": False,
                "has_percentage": True,
                "has_table": False,
                "char_count": 128,
            },
            ...
        ]
    """
    if not text or not text.strip():
        return []

    doc_meta = metadata or {}
    lines = text.split('\n')

    chunks = []
    current_chunk_lines = []
    current_section_title = ""
    current_clause_level = 0
    chunk_index = 0

    def flush_chunk() -> Optional[Dict[str, Any]]:
        """将当前累积的行输出为一个 chunk"""
        nonlocal chunk_index
        if not current_chunk_lines:
            return None

        chunk_text = "\n".join(current_chunk_lines).strip()
        if not chunk_text:
            return None

        # 兜底：超过最大字符数则强制截断
        if len(chunk_text) > max_chunk_chars:
            chunk_text = chunk_text[:max_chunk_chars]

        chunk_index += 1
        semantic_tags = _detect_semantic_tags(chunk_text)
        markers = _detect_special_markers(chunk_text)

        chunk = {
            "chunk_id": f"{contract_id}-chunk-{chunk_index:04d}" if contract_id else f"chunk-{chunk_index:04d}",
            "text": chunk_text,
            "section_title": current_section_title,
            "clause_level": current_clause_level,
            "contract_id": contract_id,
            "party_a": doc_meta.get("party_a", ""),
            "party_b": doc_meta.get("party_b", ""),
            "sign_date": str(doc_meta.get("sign_date", "")),
            "total_amount": doc_meta.get("total_amount"),
            "semantic_tags": semantic_tags,
            **markers,
            "char_count": len(chunk_text),
        }
        return chunk

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 检测条款标题（第一级）
        section_title = _get_clause_title(stripped)
        if section_title:
            # 先输出上一个 chunk
            chunk = flush_chunk()
            if chunk:
                chunks.append(chunk)
            current_chunk_lines = [stripped]
            current_section_title = section_title
            current_clause_level = 1
            continue

        # 检测款/项（第二级）
        if _is_clause_start(stripped):
            chunk = flush_chunk()
            if chunk:
                chunks.append(chunk)
            current_chunk_lines = [stripped]
            current_clause_level = 2
            continue

        # 检测自然段分隔（双换行）
        if current_chunk_lines and current_chunk_lines[-1] == "":
            # 上一个 chunk 已包含空行作为结束标志
            chunk = flush_chunk()
            if chunk:
                chunks.append(chunk)
            current_chunk_lines = [stripped]
            current_clause_level = 3
            continue

        current_chunk_lines.append(stripped)

        # 如果当前 chunk 已超过最大字符数，强制输出
        current_text = "\n".join(current_chunk_lines)
        if len(current_text) > max_chunk_chars:
            chunk = flush_chunk()
            if chunk:
                chunks.append(chunk)
            current_chunk_lines = []

    # 输出最后一个 chunk
    chunk = flush_chunk()
    if chunk:
        chunks.append(chunk)

    logger.info(
        f"语义切分完成: contract_id={contract_id}, "
        f"chunks={len(chunks)}, "
        f"avg_chars={sum(c['char_count'] for c in chunks) // max(len(chunks), 1)}"
    )
    return chunks


def split_contract_full(
    full_text: str,
    contract_id: str,
    party_a: str = "",
    party_b: str = "",
    sign_date: str = "",
    total_amount: Optional[float] = None,
    max_chunk_chars: int = 512,
) -> List[Dict[str, Any]]:
    """
    完整的合同文本语义切分（带文档级元数据）。

    Args:
        full_text: 合同全文
        contract_id: 合同编号
        party_a: 甲方
        party_b: 乙方
        sign_date: 签订日期
        total_amount: 合同总金额
        max_chunk_chars: 最大 chunk 字符数

    Returns:
        chunk 列表
    """
    metadata = {
        "party_a": party_a,
        "party_b": party_b,
        "sign_date": sign_date,
        "total_amount": total_amount,
    }
    return split_by_semantic_boundary(
        text=full_text,
        contract_id=contract_id,
        max_chunk_chars=max_chunk_chars,
        metadata=metadata,
    )


def get_chunk_texts(chunks: List[Dict[str, Any]]) -> List[str]:
    """从 chunk 列表中提取纯文本列表（用于 Embedding）"""
    return [c["text"] for c in chunks]


def get_chunk_metadata_list(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从 chunk 列表中提取元数据列表（用于 ChromaDB 存储）"""
    return [
        {k: v for k, v in c.items() if k != "text"}
        for c in chunks
    ]
