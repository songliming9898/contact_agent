"""
工具路由层 (Layer 2) — 格式化数据执行层结果，适配大模型

这一层负责：
1. 接收工具函数（Layer 1）传来的参数
2. 调用数据执行层（Layer 3）获取原始数据
3. 将原始数据格式化为大模型友好的文本/JSON
4. 做简单的业务聚合（如"甲方X的累计合同金额为Y元"）
"""
import json
import logging
from typing import Optional

from .data_layer import (
    dao_query_amount,
    dao_query_sum_amount,
    dao_query_count,
    dao_query_count_by_party,
    dao_query_count_by_type,
    dao_search_text,
    dao_get_details,
    dao_list_contracts,
    dao_insert_contract,
    dao_delete_contract,
    dao_search_vector,
)

logger = logging.getLogger(__name__)


# ============================================================
#  query_con_sum — 合同金额查询 / 汇总
# ============================================================

def route_query_con_sum(
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    aggregate: bool = False,
) -> str:
    """
    查询合同金额。

    当用户问"XX合同的金额是多少"→ aggregate=False，返回逐条明细
    当用户问"所有合同总金额"/"甲方X的累计合同额"→ aggregate=True，返回汇总

    Args:
        contract_id: 指定合同ID
        party_a: 按甲方筛选
        party_b: 按乙方筛选
        aggregate: 是否返回汇总（总金额/平均值/最大最小）
    """
    if aggregate:
        summary = dao_query_sum_amount(party_a=party_a, party_b=party_b)
        scope = ""
        if party_a:
            scope = f"甲方'{party_a}'的"
        elif party_b:
            scope = f"乙方'{party_b}'的"
        else:
            scope = "所有"

        if summary["count"] == 0:
            return f"暂无{scope}合同数据。"

        return json.dumps({
            "查询范围": scope.strip("的"),
            "合同数量": f"{summary['count']} 份",
            "合同总金额": f"{summary['total']:,.2f} 元",
            "平均金额": f"{summary['avg']:,.2f} 元",
            "最高金额": f"{summary['max']:,.2f} 元",
            "最低金额": f"{summary['min']:,.2f} 元",
        }, ensure_ascii=False, indent=2)

    else:
        rows = dao_query_amount(
            contract_id=contract_id,
            party_a=party_a,
            party_b=party_b,
        )
        if not rows:
            return "未找到匹配的合同金额数据。"

        result = []
        for r in rows:
            result.append({
                "合同编号": r["contract_id"],
                "文件名称": r["file_name"],
                "甲方": r.get("party_a", ""),
                "乙方": r.get("party_b", ""),
                "项目名称": r.get("project_name", ""),
                "合同金额": f"{r['total_amount']:,.2f} 元" if r.get("total_amount") else "未标注",
                "付款方式": r.get("payment_method", ""),
                "签订日期": str(r.get("sign_date", "")) if r.get("sign_date") else "",
            })
        return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================
#  query_con_count — 合同数量统计
# ============================================================

def route_query_con_count(
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    file_type: Optional[str] = None,
    has_trial: Optional[bool] = None,
    has_service: Optional[bool] = None,
    payment_method: Optional[str] = None,
    by_party: bool = False,
    by_type: bool = False,
) -> str:
    """
    统计合同数量。

    当 by_party=True → 按甲方分组统计
    当 by_type=True → 按付款方式分组统计
    否则 → 按筛选条件返回总数
    """
    if by_party:
        rows = dao_query_count_by_party()
        if not rows:
            return "暂无合同数据。"
        result = []
        for r in rows:
            result.append({
                "甲方": r["party_a"],
                "合同数量": f"{r['cnt']} 份",
                "合同总额": f"{r.get('total_amount', 0):,.2f} 元" if r.get("total_amount") else "0 元",
            })
        return json.dumps({"按甲方统计": result}, ensure_ascii=False, indent=2)

    if by_type:
        rows = dao_query_count_by_type()
        if not rows:
            return "暂无合同数据。"
        result = [{"付款方式": r["pm"], "数量": f"{r['cnt']} 份"} for r in rows]
        return json.dumps({"按付款方式统计": result}, ensure_ascii=False, indent=2)

    # 条件统计
    cnt = dao_query_count(
        party_a=party_a,
        party_b=party_b,
        file_type=file_type,
        has_trial=has_trial,
        has_service=has_service,
        payment_method=payment_method,
    )

    # 构建描述
    conditions = []
    if party_a:
        conditions.append(f"甲方包含'{party_a}'")
    if party_b:
        conditions.append(f"乙方包含'{party_b}'")
    if has_trial is True:
        conditions.append("含试用期")
    if has_service is True:
        conditions.append("含售后服务")
    if payment_method:
        conditions.append(f"付款方式为'{payment_method}'")

    desc = "、".join(conditions) if conditions else "全部合同"
    return f"符合条件（{desc}）的合同共 {cnt['count']} 份。"


# ============================================================
#  search_con_text — 全文文本搜索
# ============================================================

def route_search_con_text(
    keyword: str,
    contract_id: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    关键词模糊搜索（含公司简称匹配 + 金额汇总）。

    搜索策略：
    1. 甲乙方 LIKE 匹配：用于公司简称 → 完整公司名
    2. 全文 LIKE 匹配：查找合同内容中的关键词
    3. 合并去重，附带金额汇总

    当用户用简称（如"华为"）提问时，一步返回：
    - 匹配到的完整公司名列表
    - 金额汇总
    - 相关原文片段
    """
    if not keyword or not keyword.strip():
        return "请提供搜索关键词。"

    kw = keyword.strip()
    result = dao_search_text(
        keyword=kw,
        contract_id=contract_id,
        search_in="all",
        limit=limit,
    )

    matched_parties = result.get("matched_parties", [])
    snippets = result.get("snippets", [])
    total_amount = result.get("total_amount", 0)
    count = result.get("count", 0)

    if count == 0:
        # 无结果，提示用户
        return json.dumps({
            "搜索关键词": kw,
            "结果": f"未找到与'{kw}'相关的合同。请尝试其他关键词。",
            "提示": "如果使用的是公司简称，请确认简称是否包含在公司全称中。例如'华为'可匹配'华为技术有限公司'。"
        }, ensure_ascii=False, indent=2)

    output = {
        "搜索关键词": kw,
        "匹配合同数": count,
    }

    # 金额汇总
    if total_amount > 0:
        output["匹配合同总金额"] = f"{total_amount:,.2f} 元"

    # 按甲乙方匹配的公司列表（重点：简称 → 完整公司名）
    if matched_parties:
        party_list = []
        for r in matched_parties:
            item = {
                "合同编号": r["contract_id"],
                "甲方": r.get("party_a", ""),
                "乙方": r.get("party_b", ""),
            }
            if r.get("project_name"):
                item["项目名称"] = r["project_name"]
            if r.get("total_amount"):
                item["合同金额"] = f"{r['total_amount']:,.2f} 元"
            if r.get("payment_method"):
                item["付款方式"] = r["payment_method"]
            party_list.append(item)
        output["匹配到的公司/合同"] = party_list

    # 原文片段（全文搜索匹配）
    if snippets:
        snippet_list = []
        for r in snippets:
            item = {
                "合同编号": r["contract_id"],
                "甲方": r.get("party_a", ""),
                "乙方": r.get("party_b", ""),
                "匹配片段": r.get("snippet", ""),
            }
            snippet_list.append(item)
        output["相关原文片段"] = snippet_list

    return json.dumps(output, ensure_ascii=False, indent=2)


# ============================================================
#  get_con_details — 合同详情
# ============================================================

def route_get_con_details(contract_id: str) -> str:
    """
    获取单份合同的完整详情。
    """
    if not contract_id or not contract_id.strip():
        return "请提供合同编号。"

    detail = dao_get_details(contract_id.strip())
    if not detail:
        return f"未找到合同编号为'{contract_id}'的合同。"

    # 格式化输出
    output = {
        "合同编号": detail["contract_id"],
        "文件名称": detail["file_name"],
        "文件类型": detail.get("file_type", ""),
        "页数": detail.get("page_count", 0),
        "合同主体": {
            "甲方": detail.get("party_a", ""),
            "乙方": detail.get("party_b", ""),
            "项目名称": detail.get("project_name", ""),
        },
        "合同日期": {
            "签订日期": str(detail.get("sign_date", "")) if detail.get("sign_date") else "",
            "开始日期": str(detail.get("start_date", "")) if detail.get("start_date") else "",
            "结束日期": str(detail.get("end_date", "")) if detail.get("end_date") else "",
            "合同期限": detail.get("contract_period", ""),
        },
        "合同金额": {
            "总金额": f"{detail['total_amount']:,.2f} 元" if detail.get("total_amount") else "未标注",
            "币种": detail.get("currency", "CNY"),
        },
        "付款信息": {
            "付款方式": detail.get("payment_method", ""),
            "尾款金额": f"{detail['final_payment_amount']:,.2f} 元" if detail.get("final_payment_amount") else "",
            "尾款条件": detail.get("final_payment_trigger", ""),
            "分期明细": [
                {
                    "阶段": inst.get("stage", ""),
                    "比例": inst.get("ratio", ""),
                    "金额": f"{inst['amount']:,.2f} 元" if inst.get("amount") else "",
                    "触发条件": inst.get("trigger_desc", ""),
                }
                for inst in (detail.get("installments") or [])
            ],
        },
        "试用期": {
            "是否有试用期": "是" if detail.get("has_trial") else "否",
            "试用天数": detail.get("trial_days", ""),
            "开始条件": detail.get("trial_trigger", ""),
        },
        "售后服务": {
            "是否有售后服务": "是" if detail.get("has_service") else "否",
            "服务月数": detail.get("service_months", ""),
            "服务内容": detail.get("service_content", ""),
            "开始条件": detail.get("service_trigger", ""),
        },
        "软件产品": [
            {"名称": p.get("name", ""), "版本": p.get("version", ""), "授权类型": p.get("license_type", "")}
            for p in (detail.get("software_products") or detail.get("products") or [])
        ],
        "硬件产品": [
            {"名称": p.get("name", ""), "型号": p.get("model", ""), "数量": p.get("quantity", ""), "单位": p.get("unit", "")}
            for p in (detail.get("hardware_products") or [])
        ],
        "关键条款": [
            {"类型": c.get("clause_type", ""), "摘要": c.get("summary", "")}
            for c in (detail.get("key_clauses") or [])
        ],
    }

    return json.dumps(output, ensure_ascii=False, indent=2)


# ============================================================
#  list_contracts — 合同列表
# ============================================================

def route_list_contracts(keyword: Optional[str] = None, page: int = 1, page_size: int = 20) -> str:
    """分页列出合同摘要"""
    result = dao_list_contracts(page=page, page_size=page_size, keyword=keyword)
    items = result["items"]

    if not items:
        return "暂无合同数据。"

    formatted = []
    for r in items:
        formatted.append({
            "合同编号": r["contract_id"],
            "文件名称": r["file_name"],
            "甲方": r.get("party_a", ""),
            "乙方": r.get("party_b", ""),
            "项目名称": r.get("project_name", ""),
            "金额": f"{r['total_amount']:,.2f} 元" if r.get("total_amount") else "",
            "签订日期": str(r.get("sign_date", "")) if r.get("sign_date") else "",
        })

    return json.dumps({
        "总数": result["total"],
        "当前页": result["page"],
        "合同列表": formatted,
    }, ensure_ascii=False, indent=2)


# ============================================================
#  insert_contract — 导入合同
# ============================================================

def route_insert_contract(contract_json_str: str) -> str:
    """
    导入新合同到 MySQL（事务性多表写入）

    后台管理批量导入时调用，执行：
    1. INSERT INTO contracts (主表)
    2. INSERT INTO contract_installments (分期付款)
    3. INSERT INTO contract_products (软件+硬件，product_type区分)
    4. INSERT INTO contract_key_clauses (关键条款)

    Args:
        contract_json_str: 标准化合同 JSON 字符串
    """
    try:
        data = json.loads(contract_json_str)
    except json.JSONDecodeError as e:
        return f"合同 JSON 解析失败: {str(e)}"

    try:
        contract_id = dao_insert_contract(data)
        return json.dumps({
            "状态": "成功",
            "合同编号": contract_id,
            "文件名称": data.get("file_name", ""),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[insert_contract] 写入失败: {e}")
        return json.dumps({
            "状态": "失败",
            "错误": str(e),
        }, ensure_ascii=False, indent=2)


# ============================================================
#  search_vector — 语义向量检索
# ============================================================

def route_search_vector(
    query: str,
    n_results: int = 5,
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
) -> str:
    """
    语义向量检索 — 从 ChromaDB 中按意思搜索合同条款原文。

    与 search_con_text（关键词 LIKE 匹配）不同，此工具：
    - 基于语义理解，而非字符匹配
    - 适合"保密期限""违约责任怎么算"等需要理解含义的查询
    - 自动从 contracts_chunks（条款）和 contracts_tables（表格）双 Collection 检索

    Args:
        query: 查询文本（自然语言）
        n_results: 返回结果数（默认5）
        contract_id: 限定合同编号
        party_a: 限定甲方
        party_b: 限定乙方
    """
    if not query or not query.strip():
        return "请提供查询内容。"

    try:
        result = dao_search_vector(
            query=query.strip(),
            n_results=n_results,
            contract_id=contract_id,
            party_a=party_a,
            party_b=party_b,
        )
    except Exception as e:
        logger.error(f"[search_vector] 检索失败: {e}")
        return json.dumps({
            "状态": "失败",
            "错误": str(e),
            "提示": "ChromaDB 可能尚未初始化或未导入合同向量数据。"
        }, ensure_ascii=False, indent=2)

    chunk_results = result.get("chunk_results", [])
    table_results = result.get("table_results", [])

    if not chunk_results and not table_results:
        return json.dumps({
            "查询": query,
            "结果": "未找到语义匹配的合同条款。",
            "建议": "请尝试使用 search_con_text 进行关键词搜索，或更换查询措辞。"
        }, ensure_ascii=False, indent=2)

    output = {
        "查询": query,
        "匹配条款数": len(chunk_results),
    }

    if chunk_results:
        chunks_formatted = []
        for r in chunk_results:
            item = {
                "合同编号": r.get("contract_id", ""),
                "甲方": r.get("party_a", ""),
                "乙方": r.get("party_b", ""),
                "条款标题": r.get("section_title", ""),
                "条款原文": r.get("text", ""),
                "语义标签": r.get("semantic_tags", ""),
                "相似度": f"{1 - r.get('distance', 0):.2%}",
            }
            chunks_formatted.append(item)
        output["条款检索结果"] = chunks_formatted

    if table_results:
        tables_formatted = []
        for r in table_results:
            item = {
                "合同编号": r.get("contract_id", ""),
                "表头": r.get("headers", ""),
                "行数": r.get("row_count", 0),
                "表格内容": r.get("text", ""),
                "相似度": f"{1 - r.get('distance', 0):.2%}",
            }
            tables_formatted.append(item)
        output["表格检索结果"] = tables_formatted

    return json.dumps(output, ensure_ascii=False, indent=2)


# ============================================================
#  delete_contract — 删除合同
# ============================================================

def route_delete_contract(contract_id: str) -> str:
    """
    删除合同（MySQL 级联删除）

    Args:
        contract_id: 要删除的合同编号
    """
    if not contract_id or not contract_id.strip():
        return "请提供合同编号。"

    try:
        success = dao_delete_contract(contract_id.strip())
        if success:
            return json.dumps({
                "状态": "成功",
                "合同编号": contract_id,
                "说明": "已从 MySQL 级联删除（含分期/产品/条款子表数据）",
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "状态": "失败",
                "合同编号": contract_id,
                "说明": "未找到该合同或删除失败",
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[delete_contract] 删除失败: {e}")
        return json.dumps({
            "状态": "失败",
            "错误": str(e),
        }, ensure_ascii=False, indent=2)
