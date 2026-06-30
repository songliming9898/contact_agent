"""
表格处理模块 — 表格检测 → Markdown + JSON 双写

双写目的：
- Markdown 格式：送入 ChromaDB 做语义向量检索
- JSON 格式：保留结构化数据，供精确查询
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


def table_to_markdown(table: List[List[str]], context: str = "") -> str:
    """
    将二维表格转为 Markdown 格式文本。

    Args:
        table: 二维数组 [[cell, cell, ...], ...]
        context: 表格上下文（前面的段落文本）

    Returns:
        Markdown 格式字符串
    """
    if not table:
        return ""

    lines = []
    if context:
        lines.append(f"**{context.strip()}**")
        lines.append("")

    # 表头
    if len(table) >= 1:
        header = table[0]
        lines.append("| " + " | ".join(str(c) if c else " " for c in header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    # 数据行
    for row in table[1:]:
        # 补齐列数
        padded = list(row) + [""] * (len(table[0]) - len(row))
        lines.append("| " + " | ".join(str(c) if c else " " for c in padded[:len(table[0])]) + " |")

    return "\n".join(lines)


def table_to_json(
    table: List[List[str]],
    context: str = "",
    table_index: int = 0,
) -> Dict[str, Any]:
    """
    将二维表格转为 JSON 结构。

    Args:
        table: 二维数组
        context: 表格上下文
        table_index: 表格序号

    Returns:
        {
            "table_index": 0,
            "context": "...",
            "headers": [...],
            "rows": [{...}, ...],
            "row_count": N,
            "col_count": M,
        }
    """
    if not table:
        return {"table_index": table_index, "context": context, "headers": [], "rows": [], "row_count": 0, "col_count": 0}

    headers = [str(c).strip() for c in table[0]]
    rows = []
    for row in table[1:]:
        row_dict = {}
        for i, cell in enumerate(row):
            key = headers[i] if i < len(headers) else f"col_{i}"
            row_dict[key] = str(cell).strip() if cell else ""
        rows.append(row_dict)

    return {
        "table_index": table_index,
        "context": context,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "col_count": len(headers),
    }


def process_tables(
    tables: List[List[List[str]]],
    table_contexts: List[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    批量处理表格：生成 Markdown 和 JSON。

    Args:
        tables: 表格列表（每个表格是二维数组）
        table_contexts: 表格上下文列表（一一对应）

    Returns:
        (markdown_texts, json_objects)
    """
    markdown_texts = []
    json_objects = []

    for i, table in enumerate(tables):
        if not table:
            continue

        context = table_contexts[i] if i < len(table_contexts) else ""

        # Markdown
        md = table_to_markdown(table, context)
        markdown_texts.append(md)

        # JSON
        j = table_to_json(table, context, table_index=i)
        json_objects.append(j)

    logger.info(f"表格处理完成: {len(tables)} 个原始表格 → {len(markdown_texts)} 个 Markdown + {len(json_objects)} 个 JSON")
    return markdown_texts, json_objects


def extract_tables_from_text(text: str) -> Tuple[List[List[List[str]]], List[str]]:
    """
    从纯文本中启发式检测表格（用于 PDF 无结构化表格时）。

    检测规则：
    - 连续多行包含相同的分隔符（如 | / \t / 多个空格）
    - 行以数字开头且包含相同列数的数据

    Args:
        text: 文本内容

    Returns:
        (tables, contexts)
    """
    tables = []
    contexts = []

    lines = text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 检测 | 分隔的表格
        if '|' in line and line.count('|') >= 2:
            table_lines = []
            context = lines[i - 1].strip() if i > 0 else ""
            while i < len(lines) and '|' in lines[i]:
                parts = [p.strip() for p in lines[i].split('|')]
                # 去掉首尾空
                parts = [p for p in parts if p]
                if parts:
                    table_lines.append(parts)
                i += 1
            if len(table_lines) >= 2:
                tables.append(table_lines)
                contexts.append(context)
            continue

        # 检测制表符分隔的表格
        if '\t' in line and line.count('\t') >= 2:
            table_lines = []
            context = lines[i - 1].strip() if i > 0 else ""
            col_count = line.count('\t') + 1
            while i < len(lines) and '\t' in lines[i] and lines[i].count('\t') + 1 == col_count:
                table_lines.append([c.strip() for c in lines[i].split('\t')])
                i += 1
            if len(table_lines) >= 2:
                tables.append(table_lines)
                contexts.append(context)
            continue

        i += 1

    return tables, contexts


def extract_and_process_tables(
    tables_from_doc: List[List[List[str]]],
    table_contexts: List[str],
    full_text: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    综合处理：结构化表格 + 文本启发式检测。

    Args:
        tables_from_doc: document_reader 返回的表格
        table_contexts: document_reader 返回的表格上下文
        full_text: 合同全文

    Returns:
        (all_markdown_texts, all_json_objects)
    """
    # 处理结构化表格
    md_texts, json_objs = process_tables(tables_from_doc, table_contexts)

    # 启发式检测额外表格
    heuristic_tables, heuristic_contexts = extract_tables_from_text(full_text)
    if heuristic_tables:
        extra_md, extra_json = process_tables(heuristic_tables, heuristic_contexts)
        md_texts.extend(extra_md)
        json_objs.extend(extra_json)

    return md_texts, json_objs
