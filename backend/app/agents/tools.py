"""
大模型层 (Layer 1) — LangChain Tools 定义

这是三层架构的顶层，大模型通过 Function Calling 直接调用这些工具。
每个工具接收自然语言参数，内部调用工具路由层（Layer 2）。

工具清单（8个）：
- query_con_sum     : 合同金额查询 / 汇总
- query_con_count   : 合同数量统计
- search_con_text   : 全文关键词搜索 + 公司简称模糊匹配
- get_con_details   : 合同完整详情
- list_contracts    : 合同列表
- search_vector     : 语义向量检索（ChromaDB）
- insert_contract   : 导入合同（MySQL + ChromaDB 写）
- delete_contract   : 删除合同（MySQL + ChromaDB 删）
"""
import logging
from typing import Optional

from langchain.tools import tool

from .tool_router import (
    route_query_con_sum,
    route_query_con_count,
    route_search_con_text,
    route_get_con_details,
    route_list_contracts,
    route_search_vector,
    route_insert_contract,
    route_delete_contract,
)

logger = logging.getLogger(__name__)


# ============================================================
#  Tool 1: query_con_sum — 合同金额查询/汇总
# ============================================================

@tool
def query_con_sum(
    contract_id: str = "",
    party_a: str = "",
    party_b: str = "",
    aggregate: bool = False,
) -> str:
    """
    查询合同金额。支持两种模式：
    1. 查询指定合同/甲方/乙方的金额明细（aggregate=False）
    2. 汇总统计总金额、平均值、最大值、最小值（aggregate=True）

    使用场景：
    - 用户问"XX合同的金额是多少" → aggregate=False, 填入对应参数
    - 用户问"所有合同的总金额"/"甲方X的累计合同金额" → aggregate=True
    - 用户问"金额最高的合同是哪个" → aggregate=True

    Args:
        contract_id: 合同编号（如 CON-2024-001），不填则查全部
        party_a: 甲方名称关键词（模糊匹配），不填则不限
        party_b: 乙方名称关键词（模糊匹配），不填则不限
        aggregate: 是否汇总统计（默认False=返回明细）
    """
    return route_query_con_sum(
        contract_id=contract_id or None,
        party_a=party_a or None,
        party_b=party_b or None,
        aggregate=aggregate,
    )


# ============================================================
#  Tool 2: query_con_count — 合同数量统计
# ============================================================

@tool
def query_con_count(
    party_a: str = "",
    party_b: str = "",
    file_type: str = "",
    has_trial: str = "",
    has_service: str = "",
    payment_method: str = "",
    by_party: bool = False,
    by_type: bool = False,
) -> str:
    """
    统计合同数量。支持按条件筛选和分组统计。

    使用场景：
    - 用户问"一共有多少份合同" → 不填参数
    - 用户问"甲方X有多少份合同" → party_a="X"
    - 用户问"每个甲方各有多少合同" → by_party=True
    - 用户问"分期付款的合同有多少" → payment_method="分期付款"
    - 用户问"含试用期的合同有多少" → has_trial="true"

    Args:
        party_a: 甲方名称（模糊匹配）
        party_b: 乙方名称（模糊匹配）
        file_type: 文件类型（docx/pdf）
        has_trial: 是否有试用期，"true"=是, "false"=否, ""=不限
        has_service: 是否有售后服务，"true"=是, "false"=否
        payment_method: 付款方式（一次性付款/分期付款/按里程碑付款）
        by_party: 按甲方分组统计
        by_type: 按付款方式分组统计
    """
    return route_query_con_count(
        party_a=party_a or None,
        party_b=party_b or None,
        file_type=file_type or None,
        has_trial=True if has_trial.lower() == "true" else (False if has_trial.lower() == "false" else None),
        has_service=True if has_service.lower() == "true" else (False if has_service.lower() == "false" else None),
        payment_method=payment_method or None,
        by_party=by_party,
        by_type=by_type,
    )


# ============================================================
#  Tool 3: search_con_text — 全文关键词搜索
# ============================================================

@tool
def search_con_text(
    keyword: str = "",
    contract_id: str = "",
) -> str:
    """
    关键词模糊搜索（甲乙方名称 + 合同全文），支持公司简称匹配完整公司名。

    **核心能力**：
    1. 公司简称匹配：用户说"华为"→ 自动匹配"华为技术有限公司"等完整公司名
    2. 合同全文搜索：查找合同内容中的关键词
    3. 自动返回金额汇总：一步返回匹配合同的总金额、合同数量

    使用场景：
    - 用户问"华为公司的合同总金额" → keyword="华为"，一步返回匹配的公司名+金额
    - 用户问"腾讯有哪些合同" → keyword="腾讯"
    - 用户问"合同中关于违约金的条款" → keyword="违约金"
    - 用户问"保密协议的保密期限" → keyword="保密期限"
    - 用户问"验收标准具体怎么写的" → keyword="验收标准"

    **重要**：当用户提到公司简称时，优先用此工具搜索，而不是 query_con_sum。

    Args:
        keyword: 搜索关键词（必填），可以是公司简称、条款关键词等
        contract_id: 限定合同编号，不填则搜索全部合同
    """
    return route_search_con_text(
        keyword=keyword,
        contract_id=contract_id or None,
    )


# ============================================================
#  Tool 4: get_con_details — 合同详情
# ============================================================

@tool
def get_con_details(contract_id: str = "") -> str:
    """
    获取单份合同的完整详情，包括：
    - 合同主体（甲方、乙方、项目名称）
    - 合同日期（签订/开始/结束）
    - 合同金额、付款方式、分期明细
    - 试用期、售后服务条款
    - 软件产品清单
    - 关键条款摘要

    使用场景：
    - 用户问"合同XXX的详细信息"
    - 用户问"合同XXX的付款节点有哪些"
    - 用户问"合同XXX的售后服务是什么"
    - 在 query_con_sum 找到合同编号后，用此工具获取详细内容

    Args:
        contract_id: 合同编号（必填），如 "CON-2024-001"
    """
    return route_get_con_details(contract_id=contract_id)


# ============================================================
#  Tool 5: list_contracts — 合同列表
# ============================================================

@tool
def list_contracts(keyword: str = "") -> str:
    """
    列出合同摘要列表。可按关键词搜索（甲方、乙方、项目名称）。

    使用场景：
    - 用户问"有哪些合同"
    - 用户问"列出所有和XX公司相关的合同"

    Args:
        keyword: 搜索关键词（甲方、乙方、项目名称模糊匹配），不填则列出全部
    """
    return route_list_contracts(keyword=keyword or None)


# ============================================================
#  Tool 6: search_vector — 语义向量检索
# ============================================================

@tool
def search_vector(
    query: str = "",
    n_results: int = 5,
    contract_id: str = "",
    party_a: str = "",
    party_b: str = "",
) -> str:
    """
    语义向量检索 — 从 ChromaDB 中按意思（而非关键词）搜索合同条款原文。

    与 search_con_text（关键词 LIKE 匹配）不同，此工具：
    - 基于语义理解（Embedding 向量相似度），能理解同义词、近义词
    - 适合查询："保密协议的保密期限" / "违约金怎么算" / "验收标准是什么"
    - 同时检索 contracts_chunks（条款）和 contracts_tables（表格）

    使用场景：
    - 用户问"保密期限是多久" → 结构化字段没有直接答案 → 用向量检索找相关条款
    - 用户问"违约了怎么办" → 语义匹配"违约责任"相关条款
    - 用户问"付款的条件是什么" → 匹配付款条款原文

    注意：此工具需要 ChromaDB 中已有合同的 Embedding 向量数据。
    如果无结果，请改用 search_con_text 做关键词搜索。

    Args:
        query: 查询文本（自然语言，必填）
        n_results: 返回结果数量（默认5条）
        contract_id: 限定合同编号（可选）
        party_a: 限定甲方名称（可选）
        party_b: 限定乙方名称（可选）
    """
    return route_search_vector(
        query=query,
        n_results=n_results,
        contract_id=contract_id or None,
        party_a=party_a or None,
        party_b=party_b or None,
    )


# ============================================================
#  Tool 7: insert_contract — 导入合同（MySQL + ChromaDB 写）
# ============================================================

@tool
def insert_contract(contract_json: str = "") -> str:
    """
    导入新合同到 MySQL 数据库（事务性多表写入）+ ChromaDB 向量化入库。

    执行操作：
    1. INSERT INTO contracts (主表：主体/日期/金额/全文)
    2. INSERT INTO contract_installments (分期付款明细)
    3. INSERT INTO contract_products (软件产品 + 硬件产品，product_type区分)
    4. INSERT INTO contract_key_clauses (关键条款摘要)
    5. 表格处理 + 归一化 + 语义切分 + Embedding → ChromaDB 双Collection写入

    使用场景：
    - 后台管理批量导入合同时调用
    - 重新解析合同后更新数据库

    Args:
        contract_json: 标准化合同 JSON 字符串，需包含 contract_id/file_name 等完整字段
    """
    return route_insert_contract(contract_json)


# ============================================================
#  Tool 8: delete_contract — 删除合同（MySQL + ChromaDB 删）
# ============================================================

@tool
def delete_contract(contract_id: str = "") -> str:
    """
    从 MySQL + ChromaDB 中删除指定合同（级联删除 + 向量同步清理）。

    执行操作：
    1. DELETE FROM contracts WHERE contract_id=xxx
    2. 子表（installments/products/key_clauses）通过 FK ON DELETE CASCADE 自动删除
    3. ChromaDB contracts_chunks + contracts_tables 同步清理

    使用场景：
    - 后台管理删除合同时调用

    Args:
        contract_id: 要删除的合同编号（如 "CON-2024-001"）
    """
    return route_delete_contract(contract_id)
