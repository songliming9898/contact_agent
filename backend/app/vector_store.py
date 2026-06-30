"""
ChromaDB 向量存储模块 — 双 Collection 操作（DashScope Embedding API 版）

Collection 设计：
- contracts_chunks：合同条款分块（含归一化标记 + 元数据）
- contracts_tables：表格 Markdown 文本（独立 Collection）

Embedding 统一走阿里云 DashScope text-embedding API，无需本地 GPU/模型。
"""

# 修复 CentOS 7/8 自带 sqlite3 版本过低问题（ChromaDB 需要 >= 3.35.0）
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import os
import logging
import time
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.types import EmbeddingFunction, Embeddings

from .config import (
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    EMBEDDING_DIM,
    EMBEDDING_BATCH_SIZE,
    QUERY_INSTRUCTION,
    DASHSCOPE_API_KEY,
)

logger = logging.getLogger(__name__)

# ============================================================
#  DashScope Embedding 封装（API 调用，无本地模型）
# ============================================================

class DashScopeEmbeddingFunction(EmbeddingFunction):
    """
    基于阿里云 DashScope text-embedding API 的 Embedding 函数。

    使用 text-embedding-v2 模型（中文最优，1536维），
    与 ChromaDB 原生接口兼容，无需本地 GPU/模型下载。
    """

    def __init__(
        self,
        api_key: str = DASHSCOPE_API_KEY,
        model: str = "text-embedding-v2",
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ):
        self._api_key = api_key
        self._model = model
        self._batch_size = batch_size

    def __call__(self, input: List[str]) -> Embeddings:
        """批量编码文本列表 → 向量列表"""
        if not input:
            return []

        all_embeddings = []
        for i in range(0, len(input), self._batch_size):
            batch = input[i : i + self._batch_size]
            embeddings = self._embed_batch(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """调用 DashScope API 编码一批文本"""
        import dashscope
        from http import HTTPStatus

        resp = dashscope.TextEmbedding.call(
            model=self._model,
            input=texts,
            api_key=self._api_key,
        )

        if resp.status_code == HTTPStatus.OK:
            return [emb["embedding"] for emb in resp.output["embeddings"]]
        else:
            logger.error(f"DashScope Embedding API 错误: code={resp.code}, msg={resp.message}")
            # 返回零向量作为降级（维度 1536）
            return [[0.0] * 1536 for _ in texts]

    def encode_query(self, query: str) -> List[float]:
        """编码单条查询文本（带 BGE 指令前缀）"""
        return self._embed_batch([query])[0]

    def encode_documents(self, texts: List[str]) -> List[List[float]]:
        """编码文档列表"""
        return self(list(texts))


# ============================================================
#  全局单例
# ============================================================

_chroma_client: Optional[chromadb.PersistentClient] = None
_embedding_fn: Optional[DashScopeEmbeddingFunction] = None


def get_embedding_fn() -> DashScopeEmbeddingFunction:
    """获取 DashScope Embedding 函数（单例）"""
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = DashScopeEmbeddingFunction()
        logger.info("DashScope Embedding API 就绪 (text-embedding-v2, dim=1536)")
    return _embedding_fn


def get_chroma_client() -> chromadb.PersistentClient:
    """获取 ChromaDB 持久化客户端（单例）"""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    persist_dir = CHROMA_PERSIST_DIR
    if not os.path.isabs(persist_dir):
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
    """获取或创建 Collection（使用 DashScope Embedding）"""
    client = get_chroma_client()
    ef = get_embedding_fn()

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
    return _get_or_create_collection(COLLECTION_CHUNKS)


def get_tables_collection() -> chromadb.Collection:
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
    ef = get_embedding_fn()

    ids = []
    documents = []
    metadatas = []

    for c in chunks:
        chunk_id = c.get("chunk_id", "")
        if not chunk_id:
            continue

        ids.append(chunk_id)
        documents.append(c.get("text", ""))

        # 元数据：ChromaDB 只接受 str/int/float/bool
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

    # DashScope API 编码
    embeddings = ef.encode_documents(documents)
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
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
    """
    if not markdown_texts:
        return 0

    collection = get_tables_collection()
    ef = get_embedding_fn()

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

    embeddings = ef.encode_documents(documents)
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )

    logger.info(f"写入 contracts_tables: {len(ids)} 条")
    return len(ids)


# ============================================================
#  语义检索
# ============================================================

def _build_where(
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
) -> Optional[Dict]:
    """构建 ChromaDB where 过滤条件"""
    conditions = []
    if contract_id:
        conditions.append({"contract_id": contract_id})
    if party_a:
        conditions.append({"party_a": party_a})
    if party_b:
        conditions.append({"party_b": party_b})
    if len(conditions) == 1:
        return conditions[0]
    elif len(conditions) > 1:
        return {"$and": conditions}
    return None


def search_chunks(
    query: str,
    n_results: int = 5,
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    在 contracts_chunks 中语义检索。
    """
    collection = get_chunks_collection()
    ef = get_embedding_fn()
    where = _build_where(contract_id, party_a, party_b)

    # DashScope Embedding 查询编码
    query_embedding = ef.encode_query(QUERY_INSTRUCTION + query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, collection.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

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
    """
    collection = get_tables_collection()
    ef = get_embedding_fn()
    where = {"contract_id": contract_id} if contract_id else None

    query_embedding = ef.encode_query(QUERY_INSTRUCTION + query)

    results = collection.query(
        query_embeddings=[query_embedding],
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
    """
    total = 0

    for col_fn in [get_chunks_collection, get_tables_collection]:
        try:
            col = col_fn()
            existing = col.get(where={"contract_id": contract_id})
            if existing and existing.get("ids"):
                col.delete(ids=existing["ids"])
                total += len(existing["ids"])
                logger.info(f"删除 {len(existing['ids'])} 条 (contract_id={contract_id})")
        except Exception as e:
            logger.warning(f"删除失败: {e}")

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
