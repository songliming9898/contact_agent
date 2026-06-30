"""
批量导入合同脚本 — 重构版 (MySQL)
将 ./data/contracts/ 目录下的 Word/PDF 文件批量解析并写入 MySQL
"""
import os
import sys
import json
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import CONTRACTS_DIR, JSON_DIR
from app.document_reader import read_document
from app.agents.contract_parser_agent import contract_parser
from app.agents.data_layer import dao_insert_contract
from app.embedding_pipeline import process_contract_embedding
from app.db.mysql_client import init_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# 初始化数据库
init_db()


def import_contract(file_path: str, skip_embedding: bool = False) -> dict:
    """导入单份合同 → MySQL + ChromaDB（三写）"""
    logger.info(f"开始处理: {file_path}")

    try:
        # 1. 读取文档
        doc_result = read_document(file_path)
        logger.info(f"  读取完成: {len(doc_result['full_text'])} 字符")

        # 2. Agent1 解析
        contract_json = contract_parser.parse(
            full_text=doc_result["full_text"],
            file_name=doc_result["filename"],
            file_type=doc_result["file_type"],
            page_count=doc_result["page_count"],
        )
        contract_id = contract_json.get("contract_id", "UNKNOWN")
        logger.info(f"  解析完成: {contract_id}")

        # 3. 保存 JSON（备份）
        json_path = Path(JSON_DIR) / f"{doc_result['filename']}.json"
        json_data = {k: v for k, v in contract_json.items() if k != "_full_text"}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        # 4. 【写1】写入 MySQL
        contract_id = dao_insert_contract(contract_json)
        logger.info(f"  写入MySQL完成: {contract_id}")

        # 5. 【写2+3】写入 ChromaDB（三写流程中的向量化部分）
        chroma_stats = {"chunks": 0, "tables": 0}
        if not skip_embedding:
            try:
                # 提取合同主体信息用于元数据
                subject = contract_json.get("contract_subject", {})
                dates = contract_json.get("contract_date", {})
                amount = contract_json.get("contract_amount", {})

                chroma_stats = process_contract_embedding(
                    full_text=doc_result["full_text"],
                    contract_id=contract_id,
                    party_a=subject.get("party_a", ""),
                    party_b=subject.get("party_b", ""),
                    sign_date=dates.get("sign_date", ""),
                    total_amount=amount.get("total_amount"),
                    tables=doc_result.get("tables", []),
                    table_contexts=doc_result.get("table_contexts", []),
                )
                logger.info(
                    f"  写入ChromaDB完成: "
                    f"chunks={chroma_stats.get('chunks', 0)}, "
                    f"tables={chroma_stats.get('tables', 0)}"
                )
            except Exception as e:
                logger.warning(f"  ChromaDB写入失败（非致命，MySQL已成功）: {e}")
                chroma_stats = {"error": str(e)}

        return {
            "file": doc_result["filename"],
            "contract_id": contract_id,
            "status": "success",
            "mysql_ok": True,
            "chroma_chunks": chroma_stats.get("chunks", 0),
            "chroma_tables": chroma_stats.get("tables", 0),
        }

    except Exception as e:
        logger.error(f"  处理失败: {e}")
        return {
            "file": os.path.basename(file_path),
            "status": "error",
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="批量导入合同文件到 MySQL")
    parser.add_argument(
        "--dir",
        type=str,
        default=CONTRACTS_DIR,
        help=f"合同文件目录（默认: {CONTRACTS_DIR}）",
    )
    parser.add_argument(
        "--files",
        type=str,
        nargs="+",
        help="指定要导入的文件路径（多个用空格分隔）",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="导入前清空 MySQL 中的合同数据",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="跳过 ChromaDB Embedding 向量化（仅写入 MySQL）",
    )
    args = parser.parse_args()

    # 获取文件列表
    if args.files:
        files = [Path(f) for f in args.files]
    else:
        dir_path = Path(args.dir)
        if not dir_path.exists():
            logger.error(f"目录不存在: {dir_path}")
            sys.exit(1)

        files = list(dir_path.glob("*.docx")) + list(dir_path.glob("*.pdf"))

    if not files:
        logger.warning("没有找到合同文件（.docx/.pdf）")
        return

    logger.info(f"共找到 {len(files)} 个合同文件")

    # 清空 MySQL 数据
    if args.clear:
        logger.info("清空 MySQL 合同数据...")
        from app.db.mysql_client import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                for tbl in ["contract_key_clauses", "contract_products",
                            "contract_installments", "contracts"]:
                    cur.execute(f"DELETE FROM {tbl}")
            conn.commit()
        logger.info("MySQL 数据已清空")

    # 逐个处理
    results = []
    success_count = 0
    error_count = 0

    for i, file_path in enumerate(files):
        logger.info(f"[{i+1}/{len(files)}] {file_path.name}")
        result = import_contract(str(file_path), skip_embedding=args.skip_embedding)
        results.append(result)

        if result["status"] == "success":
            success_count += 1
        else:
            error_count += 1

    # 汇总
    logger.info("=" * 60)
    logger.info(f"导入完成: 成功 {success_count} 个, 失败 {error_count} 个")

    # 保存导入结果
    result_path = Path(CONTRACTS_DIR).parent / "import_results.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"导入结果已保存到: {result_path}")


if __name__ == "__main__":
    main()
