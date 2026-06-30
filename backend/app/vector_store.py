"""
ChromaDB 向量存储模块 — 双 Collection 操作

Collection 设计：
- contracts_chunks：合同条款分块（含归一化标记 + 元数据）
- contracts_tables：表格 Markdown 文本（独立 Collection）
"""

import os
import logging
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from ..config import (
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    EMBEDDING_DIM,
    EMBEDDING_DEVICE,
    EMBEDDING_BATCH_SIZE,
    QUERY_INSTRUCTION,
)

logger = logging.getLogger(__name__)

# ============================================================
#  全局单例
# ============================================================

_chroma_client: Optional[chromadb.PersistentClient] = None
_embedding_fn = None


def _get_embedding_fn():
    """懒加载 Embedding 函数"""
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn

    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"加载 Embedding 模型: {EMBEDDING_MODEL}")
        _embedding_fn = SentenceTransformer(
            EMBEDDING_MODEL,
            device=EMBEDDING_DEVICE,
        )
        logger.info(f"Embedding 模型加载完成，维度={_embedding_fn.get_sentence_embedding_dimension()}")
    except Exception as e:
        logger.error(f"加载 Embedding 模型失败: {e}")
        logger.warning("将使用 ChromaDB 内置的默认 Embedding 函数（效果可能不佳）")
        _embedding_fn = None

    return _embedding_fn


def get_chroma_client() -> chromadb.PersistentClient:
    """获取 ChromaDB 持久化客户端（单例）"""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    persist_dir = CHROMA_PERSIST_DIR
    if not os.path.isabs(persist_dir):
        # 相对于项目根目录
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        persist_dir = os.path.join(base, "data", "chroma")

    os.makedirs(persist_dir, exist_ok=True)
    logger.info(f"初始化 ChromaDB 客户端: {persist_dir}")

    _chroma_client = chromadb.PersistentClient(
        path=persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return _chroma_client


# ============================================================
#  Collection 管理
# ============================================================

COLLECTION_CHUNKS = "contracts_chunks"
COLLECTION_TABLES = "contracts_tables"


def _get_or_create_collection(name: str) -> chromadb.Collection:
    """获取或创建 Collection"""
    client = get_chroma_client()

    # 获取 embedding function
    ef = None
    emb_model = _get_embedding_fn()
    if emb_model is not None:
        # 使用自定义 embedding function
        class SentenceTransformerEF:
            def __init__(self, model):
                self._model = model
            def __call__(self, input):
                return self._model.encode(input, normalize_embeddings=True).tolist()

        ef = SentenceTransformerEF(emb_model)

    try:
        collection = client.get_collection(name=name, embedding_function=ef)
        logger.info(f"获取已有 Collection: {name} (count={collection.count()})")
    except Exception:
        collection = client.create_collection(
            name=name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"创建新 Collection: {name}")

    return collection


def get_chunks_collection() -> chromadb.Collection:
    """获取 contracts_chunks Collection"""
    return _get_or_create_collection(COLLECTION_CHUNKS)


def get_tables_collection() -> chromadb.Collection:
    """获取 contracts_tables Collection"""
    return _get_or_create_collection(COLLECTION_TABLES)


# ============================================================
#  数据写入
# ============================================================

def add_chunks(chunks: List[Dict[str, Any]]) -> int:
    """
    批量写入合同条款分块到 contracts_chunks。

    Args:
        chunks: text_splitter 输出的 chunk 列表
                [{chunk_id, text, section_title, ..., metadata...}, ...]

    Returns:
        写入的 chunk 数量
    """
    if not chunks:
        return 0

    collection = get_chunks_collection()
    emb_model = _get_embedding_fn()

    ids = []
    documents = []
    metadatas = []

    for c in chunks:
        chunk_id = c.get("chunk_id", "")
        if not chunk_id:
            continue

        ids.append(chunk_id)
        documents.append(c.get("text", ""))

        # 元数据：Chromadb 只接受 str/int/float/bool
        meta = {}
        for k, v in c.items():
            if k in ("chunk_id", "text"):
                continue
            if isinstance(v, (str, int, float, bool)):
                meta[k] = v
            elif isinstance(v, list):
                meta[k] = ", ".join(str(x) for x in v)
            elif v is None:
                continue
            else:
                meta[k] = str(v)
        metadatas.append(meta)

    if not ids:
        return 0

    # 如果使用自定义 Embedding，手动编码
    if emb_model is not None:
        embeddings = emb_model.encode(
            documents,
            normalize_embeddings=True,
            batch_size=EMBEDDING_BATCH_SIZE,
        ).tolist()
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
    else:
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    logger.info(f"写入 contracts_chunks: {len(ids)} 条")
    return len(ids)


def add_tables(
    markdown_texts: List[str],
    contract_id: str,
    table_jsons: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    批量写入表格 Markdown 到 contracts_tables。

    Args:
        markdown_texts: 表格 Markdown 文本列表
        contract_id: 合同编号
        table_jsons: 表格 JSON 结构列表（作为元数据存储）

    Returns:
        写入的表格数量
    """
    if not markdown_texts:
        return 0

    collection = get_tables_collection()
    emb_model = _get_embedding_fn()

    ids = []
    documents = []
    metadatas = []

    for i, md in enumerate(markdown_texts):
        table_id = f"{contract_id}-table-{i:04d}"
        ids.append(table_id)
        documents.append(md)

        meta = {"contract_id": contract_id, "table_index": i}
        if table_jsons and i < len(table_jsons):
            meta["headers"] = ", ".join(table_jsons[i].get("headers", []))
            meta["row_count"] = table_jsons[i].get("row_count", 0)
            meta["context"] = table_jsons[i].get("context", "")[:500]
        metadatas.append(meta)

    if emb_model is not None:
        embeddings = emb_model.encode(
            documents,
            normalize_embeddings=True,
            batch_size=EMBEDDING_BATCH_SIZE,
        ).tolist()
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
    else:
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    logger.info(f"写入 contracts_tables: {len(ids)} 条")
    return len(ids)


# ============================================================
#  语义检索
# ============================================================

def search_chunks(
    query: str,
    n_results: int = 5,
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    在 contracts_chunks 中语义检索。

    Args:
        query: 查询文本
        n_results: 返回结果数
        contract_id: 限定合同编号
        party_a: 限定甲方
        party_b: 限定乙方

    Returns:
        [
            {
                "chunk_id": "...",
                "text": "...",
                "section_title": "...",
                "contract_id": "...",
                "party_a": "...",
                "party_b": "...",
                "semantic_tags": "...",
                "distance": 0.123,
            },
            ...
        ]
    """
    collection = get_chunks_collection()
    emb_model = _get_embedding_fn()

    # 构建过滤条件
    where = None
    conditions = []
    if contract_id:
        conditions.append({"contract_id": contract_id})
    if party_a:
        conditions.append({"party_a": party_a})
    if party_b:
        conditions.append({"party_b": party_b})
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    # BGE 模型 Query 指令前缀
    query_with_instruction = QUERY_INSTRUCTION + query

    # 查询
    if emb_model is not None:
        query_embedding = emb_model.encode(
            [query_with_instruction],
            normalize_embeddings=True,
        ).tolist()
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    else:
        results = collection.query(
            query_texts=[query_with_instruction],
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    # 格式化结果
    formatted = []
    if results and results.get("ids") and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            item = {
                "chunk_id": doc_id,
                "text": results["documents"][0][i] if results.get("documents") else "",
                "distance": results["distances"][0][i] if results.get("distances") else 0,
            }
            if results.get("metadatas") and results["metadatas"][0]:
                meta = results["metadatas"][0][i]
                item["contract_id"] = meta.get("contract_id", "")
                item["party_a"] = meta.get("party_a", "")
                item["party_b"] = meta.get("party_b", "")
                item["section_title"] = meta.get("section_title", "")
                item["clause_level"] = meta.get("clause_level", 0)
                item["semantic_tags"] = meta.get("semantic_tags", "")
                item["sign_date"] = meta.get("sign_date", "")
            formatted.append(item)

    return formatted


def search_tables(
    query: str,
    n_results: int = 3,
    contract_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    在 contracts_tables 中语义检索表格。

    Args:
        query: 查询文本
        n_results: 返回结果数
        contract_id: 限定合同编号

    Returns:
        表格检索结果列表
    """
    collection = get_tables_collection()
    emb_model = _get_embedding_fn()

    where = {"contract_id": contract_id} if contract_id else None

    query_with_instruction = QUERY_INSTRUCTION + query

    if emb_model is not None:
        query_embedding = emb_model.encode(
            [query_with_instruction],
            normalize_embeddings=True,
        ).tolist()
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    else:
        results = collection.query(
            query_texts=[query_with_instruction],
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    formatted = []
    if results and results.get("ids") and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            item = {
                "table_id": doc_id,
                "text": results["documents"][0][i] if results.get("documents") else "",
                "distance": results["distances"][0][i] if results.get("distances") else 0,
            }
            if results.get("metadatas") and results["metadatas"][0]:
                meta = results["metadatas"][0][i]
                item["contract_id"] = meta.get("contract_id", "")
                item["headers"] = meta.get("headers", "")
                item["row_count"] = meta.get("row_count", 0)
                item["context"] = meta.get("context", "")
            formatted.append(item)

    return formatted


# ============================================================
#  数据清理
# ============================================================

def delete_contract_chunks(contract_id: str) -> int:
    """
    删除指定合同的所有 chunks（contracts_chunks + contracts_tables）。

    Args:
        contract_id: 合同编号

    Returns:
        删除的条目总数
    """
    total = 0

    # 删除 contracts_chunks 中的条目
    try:
        chunks_col = get_chunks_collection()
        existing = chunks_col.get(where={"contract_id": contract_id})
        if existing and existing.get("ids"):
            chunks_col.delete(ids=existing["ids"])
            total += len(existing["ids"])
            logger.info(f"删除 contracts_chunks: {len(existing['ids'])} 条 (contract_id={contract_id})")
    except Exception as e:
        logger.warning(f"删除 contracts_chunks 失败: {e}")

    # 删除 contracts_tables 中的条目
    try:
        tables_col = get_tables_collection()
        existing = tables_col.get(where={"contract_id": contract_id})
        if existing and existing.get("ids"):
            tables_col.delete(ids=existing["ids"])
            total += len(existing["ids"])
            logger.info(f"删除 contracts_tables: {len(existing['ids'])} 条 (contract_id={contract_id})")
    except Exception as e:
        logger.warning(f"删除 contracts_tables 失败: {e}")

    return total


def get_collection_stats() -> Dict[str, Any]:
    """获取 ChromaDB 存储统计"""
    try:
        chunks_col = get_chunks_collection()
        tables_col = get_tables_collection()
        return {
            "contracts_chunks": chunks_col.count(),
            "contracts_tables": tables_col.count(),
        }
    except Exception as e:
        return {"error": str(e)}
