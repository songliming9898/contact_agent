"""
数据执行层 (Layer 3) — 直接操作 MySQL 的 DAO

这是三层架构的最底层，提供原子化的数据库查询操作。
每个函数只做一件事：接收参数 → 执行 SQL → 返回原始数据。
不做任何业务逻辑判断、不做自然语言理解。
"""
import json
import logging
from typing import List, Dict, Any, Optional
from decimal import Decimal

from ..db.mysql_client import get_conn

logger = logging.getLogger(__name__)


# ============================================================
#  合同金额查询
# ============================================================

def dao_query_amount(
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    查询合同金额（单份 / 按甲方 / 按乙方 / 全部）
    """
    sql = """
        SELECT contract_id, file_name, party_a, party_b, project_name,
               total_amount, currency, payment_method,
               sign_date, start_date, end_date
        FROM contracts WHERE 1=1
    """
    params = []
    if contract_id:
        sql += " AND contract_id = %s"
        params.append(contract_id)
    if party_a:
        sql += " AND party_a LIKE %s"
        params.append(f"%{party_a}%")
    if party_b:
        sql += " AND party_b LIKE %s"
        params.append(f"%{party_b}%")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    # Decimal → float
    for r in rows:
        for k, v in r.items():
            if isinstance(v, Decimal):
                r[k] = float(v)
    return rows


def dao_query_sum_amount(
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
) -> Dict[str, Any]:
    """
    汇总合同金额：总金额、合同数量、平均值、最大/最小值
    """
    sql = "SELECT COUNT(*) AS cnt FROM contracts WHERE total_amount IS NOT NULL"
    params = []

    if party_a:
        sql += " AND party_a LIKE %s"
        params.append(f"%{party_a}%")
    if party_b:
        sql += " AND party_b LIKE %s"
        params.append(f"%{party_b}%")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cnt_row = cur.fetchone()

    cnt = cnt_row["cnt"] if cnt_row else 0

    if cnt == 0:
        return {"count": 0, "total": 0, "avg": 0, "max": 0, "min": 0}

    agg_sql = """
        SELECT
            SUM(total_amount) AS total,
            AVG(total_amount) AS avg,
            MAX(total_amount) AS max_val,
            MIN(total_amount) AS min_val
        FROM contracts
        WHERE total_amount IS NOT NULL
    """
    agg_params = []
    if party_a:
        agg_sql += " AND party_a LIKE %s"
        agg_params.append(f"%{party_a}%")
    if party_b:
        agg_sql += " AND party_b LIKE %s"
        agg_params.append(f"%{party_b}%")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(agg_sql, agg_params)
            agg = cur.fetchone()

    def dec(val):
        return round(float(val), 2) if val is not None else 0

    return {
        "count": cnt,
        "total": dec(agg["total"]) if agg else 0,
        "avg": dec(agg["avg"]) if agg else 0,
        "max": dec(agg["max_val"]) if agg else 0,
        "min": dec(agg["min_val"]) if agg else 0,
    }


# ============================================================
#  合同统计查询
# ============================================================

def dao_query_count(
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    file_type: Optional[str] = None,
    has_trial: Optional[bool] = None,
    has_service: Optional[bool] = None,
    payment_method: Optional[str] = None,
) -> Dict[str, Any]:
    """
    统计合同数量（支持多维度筛选）
    """
    sql = "SELECT COUNT(*) AS cnt FROM contracts WHERE 1=1"
    params = []

    if party_a:
        sql += " AND party_a LIKE %s"
        params.append(f"%{party_a}%")
    if party_b:
        sql += " AND party_b LIKE %s"
        params.append(f"%{party_b}%")
    if file_type:
        sql += " AND file_type = %s"
        params.append(file_type)
    if has_trial is not None:
        sql += " AND has_trial = %s"
        params.append(1 if has_trial else 0)
    if has_service is not None:
        sql += " AND has_service = %s"
        params.append(1 if has_service else 0)
    if payment_method:
        sql += " AND payment_method = %s"
        params.append(payment_method)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

    return {"count": row["cnt"] if row else 0}


def dao_query_count_by_party() -> List[Dict[str, Any]]:
    """按甲方统计合同数量"""
    sql = """
        SELECT party_a, COUNT(*) AS cnt, SUM(total_amount) AS total_amount
        FROM contracts
        WHERE party_a IS NOT NULL AND party_a != ''
        GROUP BY party_a
        ORDER BY cnt DESC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    for r in rows:
        if r.get("total_amount"):
            r["total_amount"] = round(float(r["total_amount"]), 2)
    return rows


def dao_query_count_by_type() -> List[Dict[str, Any]]:
    """按合同类型（payment_method）统计"""
    sql = """
        SELECT COALESCE(payment_method, '未分类') AS pm,
               COUNT(*) AS cnt
        FROM contracts
        GROUP BY payment_method
        ORDER BY cnt DESC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


# ============================================================
#  文本搜索
# ============================================================

def dao_search_text(
    keyword: str,
    contract_id: Optional[str] = None,
    search_in: str = "all",  # full_text / raw_json / party / all
    limit: int = 10,
) -> Dict[str, Any]:
    """
    关键词搜索（含公司简称模糊匹配 + 金额汇总）

    搜索策略：
    1. 甲乙方 LIKE 匹配: WHERE party_a LIKE '%keyword%' OR party_b LIKE '%keyword%'
       返回 contract_id, party_a, party_b, total_amount
    2. 全文 LIKE 匹配: WHERE full_text LIKE '%keyword%'
       返回 contract_id, party_a, party_b, 匹配片段(前后50字)
    3. 合并去重，计算总金额

    Returns:
        {
            "matched_parties": [...],   # 按甲乙方匹配到的合同
            "snippets": [...],          # 全文搜索匹配片段
            "total_amount": float,      # 匹配合同的总金额
            "count": int,               # 去重后的合同数量
        }
    """
    matched_parties = []
    snippets = []
    seen_ids = set()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. 甲乙方模糊匹配
            kw = f"%{keyword}%"
            party_sql = """
                SELECT contract_id, party_a, party_b, project_name,
                       total_amount, sign_date, payment_method
                FROM contracts
                WHERE (party_a LIKE %s OR party_b LIKE %s)
            """
            party_params = [kw, kw]
            if contract_id:
                party_sql += " AND contract_id = %s"
                party_params.append(contract_id)
            party_sql += " LIMIT %s"
            party_params.append(limit)

            cur.execute(party_sql, party_params)
            for row in cur.fetchall():
                for k, v in row.items():
                    if isinstance(v, Decimal):
                        row[k] = float(v)
                matched_parties.append(row)
                seen_ids.add(row["contract_id"])

            # 2. 全文搜索（合同内容）
            if search_in in ("full_text", "all"):
                text_sql = """
                    SELECT contract_id, party_a, party_b, project_name,
                           total_amount, sign_date,
                           SUBSTRING(full_text, 1, 3000) AS full_text_preview
                    FROM contracts
                    WHERE full_text LIKE %s
                """
                text_params = [kw]
                if contract_id:
                    text_sql += " AND contract_id = %s"
                    text_params.append(contract_id)
                text_sql += " LIMIT %s"
                text_params.append(limit)

                cur.execute(text_sql, text_params)
                for row in cur.fetchall():
                    for k, v in row.items():
                        if isinstance(v, Decimal):
                            row[k] = float(v)
                    # 提取关键词上下文片段
                    full_preview = row.get("full_text_preview", "") or ""
                    idx = full_preview.find(keyword)
                    if idx >= 0:
                        start = max(0, idx - 100)
                        end = min(len(full_preview), idx + len(keyword) + 100)
                        snippet = full_preview[start:end]
                        if start > 0:
                            snippet = "..." + snippet
                        if end < len(full_preview):
                            snippet = snippet + "..."
                        row["snippet"] = snippet
                    else:
                        row["snippet"] = full_preview[:200]

                    snippets.append(row)
                    seen_ids.add(row["contract_id"])

    # 3. 计算汇总金额
    total_amount = 0.0
    for row in matched_parties:
        if row.get("total_amount"):
            total_amount += float(row["total_amount"])

    return {
        "matched_parties": matched_parties,
        "snippets": snippets,
        "total_amount": round(total_amount, 2),
        "count": len(seen_ids),
    }


def dao_search_text_with_snippet(
    keyword: str,
    contract_id: Optional[str] = None,
    limit: int = 10,
    snippet_len: int = 200,
) -> List[Dict[str, Any]]:
    """
    全文搜索 + 关键词上下文片段提取
    """
    rows = dao_search_text(keyword, contract_id=contract_id, search_in="full_text", limit=limit)

    for row in rows:
        full = row.get("full_text_preview", "") or ""
        # 找到关键词位置，截取上下文
        idx = full.find(keyword)
        if idx >= 0:
            start = max(0, idx - snippet_len // 2)
            end = min(len(full), idx + len(keyword) + snippet_len // 2)
            snippet = full[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(full):
                snippet = snippet + "..."
            row["snippet"] = snippet
        else:
            row["snippet"] = full[:snippet_len * 2]

    return rows


# ============================================================
#  合同详情
# ============================================================

def dao_get_details(contract_id: str) -> Optional[Dict[str, Any]]:
    """
    获取单份合同的完整详情（主表 + 分期 + 产品 + 关键条款）
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 主表
            cur.execute("SELECT * FROM contracts WHERE contract_id = %s", (contract_id,))
            contract = cur.fetchone()
            if not contract:
                return None

            for k, v in contract.items():
                if isinstance(v, Decimal):
                    contract[k] = float(v)
                elif hasattr(v, "isoformat"):
                    contract[k] = v.isoformat()

            # 分期付款
            cur.execute(
                "SELECT stage, ratio, amount, trigger_desc FROM contract_installments "
                "WHERE contract_id = %s ORDER BY sort_order",
                (contract_id,),
            )
            installments = cur.fetchall()
            for inst in installments:
                if inst.get("amount") is not None:
                    inst["amount"] = float(inst["amount"])
            contract["installments"] = installments

            # 产品（软件+硬件）
            cur.execute(
                "SELECT product_type, name, version, license_type, model, quantity, unit "
                "FROM contract_products WHERE contract_id = %s",
                (contract_id,),
            )
            all_products = cur.fetchall()
            contract["software_products"] = [
                {"name": p["name"], "version": p["version"], "license_type": p["license_type"]}
                for p in all_products if p["product_type"] == "software"
            ]
            contract["hardware_products"] = [
                {"name": p["name"], "model": p["model"], "quantity": p["quantity"], "unit": p["unit"]}
                for p in all_products if p["product_type"] == "hardware"
            ]
            contract["products"] = all_products  # 向后兼容

            # 关键条款
            cur.execute(
                "SELECT clause_type, summary FROM contract_key_clauses "
                "WHERE contract_id = %s",
                (contract_id,),
            )
            contract["key_clauses"] = cur.fetchall()

    return contract


def dao_list_contracts(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
) -> Dict[str, Any]:
    """
    分页列出合同摘要
    """
    base_sql = "FROM contracts WHERE 1=1"
    params = []

    if keyword:
        base_sql += " AND (party_a LIKE %s OR party_b LIKE %s OR project_name LIKE %s OR contract_id LIKE %s)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw])

    with get_conn() as conn:
        with conn.cursor() as cur:
            # count
            cur.execute(f"SELECT COUNT(*) AS cnt {base_sql}", params)
            total = cur.fetchone()["cnt"]

            # data
            offset = (page - 1) * page_size
            cur.execute(
                f"SELECT contract_id, file_name, party_a, party_b, project_name, "
                f"total_amount, sign_date, parse_status "
                f"{base_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [page_size, offset],
            )
            rows = cur.fetchall()

    for r in rows:
        for k, v in r.items():
            if isinstance(v, Decimal):
                r[k] = float(v)
            elif hasattr(v, "isoformat"):
                r[k] = v.isoformat()

    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def dao_delete_contract(contract_id: str) -> bool:
    """删除合同（级联删除关联表 + ChromaDB 向量清理）"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM contracts WHERE contract_id = %s", (contract_id,))
            affected = cur.rowcount
        conn.commit()

    # 同步清理 ChromaDB 向量数据
    if affected > 0:
        try:
            from ..vector_store import delete_contract_chunks
            deleted = delete_contract_chunks(contract_id)
            logger.info(f"ChromaDB 向量清理: {deleted} 条 (contract_id={contract_id})")
        except Exception as e:
            logger.warning(f"ChromaDB 清理失败（非致命）: {e}")

    return affected > 0


# ============================================================
#  语义向量检索 (ChromaDB)
# ============================================================

def dao_search_vector(
    query: str,
    n_results: int = 5,
    contract_id: Optional[str] = None,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    search_tables: bool = True,
) -> Dict[str, Any]:
    """
    语义向量检索 — 从 ChromaDB 双 Collection 中检索。

    Args:
        query: 查询文本
        n_results: 返回结果数
        contract_id: 限定合同编号
        party_a: 限定甲方
        party_b: 限定乙方
        search_tables: 是否同时检索表格

    Returns:
        {
            "chunk_results": [...],   # 条款级检索结果
            "table_results": [...],   # 表格检索结果
            "query": "...",
        }
    """
    from ..vector_store import search_chunks, search_tables

    chunk_results = search_chunks(
        query=query,
        n_results=n_results,
        contract_id=contract_id,
        party_a=party_a,
        party_b=party_b,
    )

    table_results = []
    if search_tables:
        table_results = search_tables(
            query=query,
            n_results=max(1, n_results // 2),
            contract_id=contract_id,
        )

    return {
        "query": query,
        "chunk_results": chunk_results,
        "table_results": table_results,
        "total_chunks": len(chunk_results),
        "total_tables": len(table_results),
    }


def dao_insert_contract(data: Dict[str, Any]) -> str:
    """
    插入 / 更新合同主表 + 关联表
    返回 contract_id
    """
    contract_id = data["contract_id"]

    # 主表字段映射
    main_fields = {
        "contract_id": contract_id,
        "file_name": data.get("file_name", ""),
        "file_type": (data.get("raw_metadata") or {}).get("file_type", ""),
        "page_count": (data.get("raw_metadata") or {}).get("page_count", 0),
        "full_text": data.get("_full_text", ""),
        "raw_json": json.dumps(data, ensure_ascii=False),
        "parse_status": "success",
        "parse_time": (data.get("raw_metadata") or {}).get("parse_time"),
    }

    # 主体
    subject = data.get("contract_subject") or {}
    main_fields["party_a"] = subject.get("party_a", "")
    main_fields["party_b"] = subject.get("party_b", "")
    main_fields["project_name"] = subject.get("project_name", "")

    # 日期
    dates = data.get("contract_date") or {}
    main_fields["sign_date"] = dates.get("sign_date") or None
    main_fields["start_date"] = dates.get("start_date") or None
    main_fields["end_date"] = dates.get("end_date") or None
    main_fields["contract_period"] = dates.get("contract_period", "")

    # 金额
    amount = data.get("contract_amount") or {}
    main_fields["total_amount"] = amount.get("total_amount")
    main_fields["currency"] = amount.get("currency", "CNY")

    # 付款
    payment = data.get("payment_terms") or {}
    main_fields["payment_method"] = payment.get("payment_method", "")
    main_fields["final_payment_amount"] = payment.get("final_payment_amount")
    main_fields["final_payment_trigger"] = payment.get("final_payment_trigger", "")

    # 试用期
    trial = data.get("trial_period") or {}
    main_fields["has_trial"] = 1 if trial.get("has_trial") else 0
    main_fields["trial_days"] = trial.get("duration_days")
    main_fields["trial_trigger"] = trial.get("start_trigger", "")

    # 售后服务
    service = data.get("after_sales_service") or {}
    main_fields["has_service"] = 1 if service.get("has_service") else 0
    main_fields["service_months"] = service.get("duration_months")
    main_fields["service_content"] = service.get("service_content", "")
    main_fields["service_trigger"] = service.get("start_trigger", "")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # UPSERT
            columns = ", ".join(f"`{k}`" for k in main_fields.keys())
            placeholders = ", ".join(["%s"] * len(main_fields))
            updates = ", ".join(f"`{k}` = VALUES(`{k}`)" for k in main_fields if k != "contract_id")

            sql = (
                f"INSERT INTO contracts ({columns}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
            cur.execute(sql, list(main_fields.values()))

            # 清空旧的关联数据
            for tbl in ["contract_installments", "contract_products", "contract_key_clauses"]:
                cur.execute(f"DELETE FROM {tbl} WHERE contract_id = %s", (contract_id,))

            # 插入分期付款
            installments = payment.get("installments", []) or []
            for i, inst in enumerate(installments):
                cur.execute(
                    "INSERT INTO contract_installments (contract_id, stage, ratio, amount, trigger_desc, sort_order) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        contract_id,
                        inst.get("stage", ""),
                        inst.get("ratio", ""),
                        inst.get("amount"),
                        inst.get("trigger", ""),
                        i,
                    ),
                )

            # 插入软件产品
            software_products = data.get("software_products", []) or []
            for prod in software_products:
                cur.execute(
                    "INSERT INTO contract_products "
                    "(contract_id, product_type, name, version, license_type) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        contract_id,
                        "software",
                        prod.get("name", ""),
                        prod.get("version", ""),
                        prod.get("license_type", ""),
                    ),
                )

            # 插入硬件产品
            hardware_products = data.get("hardware_products", []) or []
            for prod in hardware_products:
                cur.execute(
                    "INSERT INTO contract_products "
                    "(contract_id, product_type, name, model, quantity, unit) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        contract_id,
                        "hardware",
                        prod.get("name", ""),
                        prod.get("model", ""),
                        prod.get("quantity"),
                        prod.get("unit", ""),
                    ),
                )

            # 插入关键条款
            clauses = data.get("key_clauses", []) or []
            for cl in clauses:
                cur.execute(
                    "INSERT INTO contract_key_clauses (contract_id, clause_type, summary) "
                    "VALUES (%s, %s, %s)",
                    (contract_id, cl.get("type", ""), cl.get("summary", "")),
                )

        conn.commit()

    return contract_id
