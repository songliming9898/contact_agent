"""
Embedding 流水线主控 — 6步编排

将合同全文 + 解析JSON → 经过完整的 Embedding 流水线 → 写入 ChromaDB。

流水线步骤：
1. 表格检测与提取（从 document_reader 结果）
2. 表格处理 → Markdown + JSON 双写
3. 特殊内容归一化（金额/日期/百分比）
4. 语义边界切分（按条款层级）
5. Embedding 向量化
6. 双 Collection 写入 ChromaDB
"""

import logging
from typing import Dict, Any, Optional, List

from .document_reader import read_document
from .table_processor import extract_and_process_tables
from .normalizer import normalize_text
from .text_splitter import split_contract_full, get_chunk_texts
from .vector_store import add_chunks, add_tables, delete_contract_chunks

logger = logging.getLogger(__name__)


def process_contract_embedding(
    full_text: str,
    contract_id: str,
    party_a: str = "",
    party_b: str = "",
    sign_date: str = "",
    total_amount: Optional[float] = None,
    tables: Optional[List[List[List[str]]]] = None,
    table_contexts: Optional[List[str]] = None,
    max_chunk_chars: int = 512,
) -> Dict[str, Any]:
    """
    处理单份合同的完整 Embedding 流水线。

    Args:
        full_text: 合同全文
        contract_id: 合同编号
        party_a: 甲方名称
        party_b: 乙方名称
        sign_date: 签订日期
        total_amount: 合同总金额
        tables: 表格列表（来自 document_reader）
        table_contexts: 表格上下文列表
        max_chunk_chars: 最大 chunk 字符数

    Returns:
        {
            "contract_id": "...",
            "chunks": 156,
            "tables": 23,
            "amounts_normalized": 45,
            "dates_normalized": 32,
            "percentages_normalized": 18,
        }
    """
    logger.info(f"开始 Embedding 流水线: contract_id={contract_id}")

    # 1. 表格处理（如果提供了表格数据）
    tables_count = 0
    if tables and len(tables) > 0:
        markdown_texts, table_jsons = extract_and_process_tables(
            tables_from_doc=tables,
            table_contexts=table_contexts or [],
            full_text=full_text,
        )
        # 写入 contracts_tables
        tables_count = add_tables(
            markdown_texts=markdown_texts,
            contract_id=contract_id,
            table_jsons=table_jsons,
        )
    else:
        markdown_texts = []
        table_jsons = []

    # 2. 归一化
    total_amounts_norm = 0
    total_dates_norm = 0
    total_pcts_norm = 0

    # 对全文执行归一化
    normalized_text, norm_stats = normalize_text(full_text)
    total_amounts_norm += norm_stats.get("amount_count", 0)
    total_dates_norm += norm_stats.get("date_count", 0)
    total_pcts_norm += norm_stats.get("pct_count", 0)

    # 3. 语义切分
    chunks = split_contract_full(
        full_text=normalized_text,
        contract_id=contract_id,
        party_a=party_a,
        party_b=party_b,
        sign_date=sign_date,
        total_amount=total_amount,
        max_chunk_chars=max_chunk_chars,
    )

    # 对每个 chunk 再执行一次归一化（捕获切分后的局部信息）
    chunks_count = len(chunks)
    for chunk in chunks:
        chunk_text = chunk.get("text", "")
        if not chunk_text:
            continue
        # 已经在全文层面归一化了，这里做补充
        # 每个 chunk 的归一化标记会在 text_splitter 切分后保留
        pass

    # 4. 写入 contracts_chunks
    written_chunks = add_chunks(chunks)

    result = {
        "contract_id": contract_id,
        "chunks": written_chunks,
        "tables": tables_count,
        "amounts_normalized": total_amounts_norm,
        "dates_normalized": total_dates_norm,
        "percentages_normalized": total_pcts_norm,
    }

    logger.info(
        f"Embedding 流水线完成: contract_id={contract_id}, "
        f"chunks={written_chunks}, tables={tables_count}, "
        f"amounts={total_amounts_norm}, dates={total_dates_norm}, pcts={total_pcts_norm}"
    )
    return result


def process_contract_from_file(
    file_path: str,
    contract_id: str,
    party_a: str = "",
    party_b: str = "",
    sign_date: str = "",
    total_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """
    从合同文件直接执行完整 Embedding 流水线（含文档读取）。

    Args:
        file_path: 合同文件路径 (.docx/.pdf)
        contract_id: 合同编号
        party_a: 甲方名称
        party_b: 乙方名称
        sign_date: 签订日期
        total_amount: 合同总金额

    Returns:
        embedding 流水线统计结果
    """
    # 读取文档
    doc_result = read_document(file_path)
    full_text = doc_result.get("full_text", "")
    tables = doc_result.get("tables", [])
    table_contexts = doc_result.get("table_contexts", [])

    if not full_text:
        logger.warning(f"文档内容为空: {file_path}")
        return {"contract_id": contract_id, "error": "文档内容为空", "chunks": 0, "tables": 0}

    return process_contract_embedding(
        full_text=full_text,
        contract_id=contract_id,
        party_a=party_a,
        party_b=party_b,
        sign_date=sign_date,
        total_amount=total_amount,
        tables=tables,
        table_contexts=table_contexts,
    )


def reprocess_contract(
    contract_id: str,
    full_text: str,
    party_a: str = "",
    party_b: str = "",
    sign_date: str = "",
    total_amount: Optional[float] = None,
    tables: Optional[List[List[List[str]]]] = None,
    table_contexts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    重新处理合同（先删除旧向量数据，再写入新数据）。

    Args:
        contract_id: 合同编号
        full_text: 合同全文
        ... 其他参数同 process_contract_embedding

    Returns:
        embedding 流水线统计结果
    """
    # 清理旧数据
    deleted = delete_contract_chunks(contract_id)
    logger.info(f"清理旧向量数据: {deleted} 条 (contract_id={contract_id})")

    # 重新处理
    return process_contract_embedding(
        full_text=full_text,
        contract_id=contract_id,
        party_a=party_a,
        party_b=party_b,
        sign_date=sign_date,
        total_amount=total_amount,
        tables=tables,
        table_contexts=table_contexts,
    )


def batch_process_contracts(
    contracts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    批量处理合同 Embedding。

    Args:
        contracts: [
            {
                "contract_id": "...",
                "full_text": "...",
                "party_a": "...",
                "party_b": "...",
                "sign_date": "...",
                "total_amount": 100000.00,
                "tables": [...],
                "table_contexts": [...],
            },
            ...
        ]

    Returns:
        每个合同的处理结果列表
    """
    results = []
    for i, c in enumerate(contracts):
        try:
            result = process_contract_embedding(
                full_text=c.get("full_text", ""),
                contract_id=c.get("contract_id", f"CON-{i:04d}"),
                party_a=c.get("party_a", ""),
                party_b=c.get("party_b", ""),
                sign_date=c.get("sign_date", ""),
                total_amount=c.get("total_amount"),
                tables=c.get("tables"),
                table_contexts=c.get("table_contexts"),
            )
            results.append(result)
        except Exception as e:
            logger.error(f"批量处理失败 [{c.get('contract_id', i)}]: {e}")
            results.append({"contract_id": c.get("contract_id", str(i)), "error": str(e)})

    success = sum(1 for r in results if "error" not in r)
    logger.info(f"批量 Embedding 完成: 成功 {success}/{len(contracts)}")
    return results
