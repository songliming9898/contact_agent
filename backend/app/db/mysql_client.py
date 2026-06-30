"""
MySQL 数据库连接池 + 表初始化
"""
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

import pymysql
from dbutils.pooled_db import PooledDB

from ..config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD,
    MYSQL_DATABASE, MYSQL_POOL_SIZE,
)

logger = logging.getLogger(__name__)

# ==================== 连接池 ====================

_pool: Optional[PooledDB] = None


def get_pool() -> PooledDB:
    global _pool
    if _pool is None:
        _pool = PooledDB(
            creator=pymysql,
            maxconnections=MYSQL_POOL_SIZE,
            mincached=2,
            blocking=True,
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    return _pool


@contextmanager
def get_conn():
    """获取数据库连接（上下文管理器）"""
    pool = get_pool()
    conn = pool.connection()
    try:
        yield conn
    finally:
        conn.close()


# ==================== 建表 DDL ====================

DDL_STATEMENTS = [
    # 合同主表 — 每份合同一行
    """
    CREATE TABLE IF NOT EXISTS contracts (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        contract_id   VARCHAR(64)  NOT NULL UNIQUE COMMENT '合同唯一ID',
        file_name     VARCHAR(256) NOT NULL COMMENT '原始文件名',
        file_type     VARCHAR(16)  COMMENT '文件类型 docx/pdf',
        page_count    INT          DEFAULT 0 COMMENT '页数',

        -- 主体
        party_a       VARCHAR(256) COMMENT '甲方名称',
        party_b       VARCHAR(256) COMMENT '乙方名称',
        project_name  VARCHAR(512) COMMENT '项目/合同名称',

        -- 日期
        sign_date     DATE         COMMENT '签订日期',
        start_date    DATE         COMMENT '开始日期',
        end_date      DATE         COMMENT '结束日期',
        contract_period VARCHAR(128) COMMENT '合同期限描述',

        -- 金额
        total_amount  DECIMAL(16,2) COMMENT '合同总金额（元）',
        currency      VARCHAR(8)   DEFAULT 'CNY' COMMENT '货币类型',

        -- 付款
        payment_method VARCHAR(64) COMMENT '付款方式',
        final_payment_amount DECIMAL(16,2) COMMENT '尾款金额',
        final_payment_trigger TEXT COMMENT '尾款支付条件',

        -- 试用期
        has_trial     TINYINT(1)   DEFAULT 0 COMMENT '是否有试用期',
        trial_days    INT          COMMENT '试用天数',
        trial_trigger TEXT         COMMENT '试用期开始条件',

        -- 售后服务
        has_service   TINYINT(1)   DEFAULT 0 COMMENT '是否有售后服务',
        service_months INT         COMMENT '服务月数',
        service_content TEXT       COMMENT '服务内容',
        service_trigger TEXT       COMMENT '服务开始条件',

        -- 全文
        full_text     LONGTEXT     COMMENT '合同全文',

        -- 原始 JSON
        raw_json      LONGTEXT     COMMENT '原始标准化 JSON',

        -- 解析状态
        parse_status  VARCHAR(32)  DEFAULT 'success' COMMENT '解析状态',
        parse_time    DATETIME     COMMENT '解析时间',
        created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

        INDEX idx_party_a (party_a),
        INDEX idx_party_b (party_b),
        INDEX idx_sign_date (sign_date),
        INDEX idx_total_amount (total_amount)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合同主表';
    """,

    # 分期付款明细表
    """
    CREATE TABLE IF NOT EXISTS contract_installments (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        contract_id   VARCHAR(64)  NOT NULL COMMENT '合同唯一ID',
        stage         VARCHAR(128) COMMENT '付款阶段（首付款/中期款/尾款等）',
        ratio         VARCHAR(32)  COMMENT '付款比例',
        amount        DECIMAL(16,2) COMMENT '付款金额',
        trigger_desc  TEXT         COMMENT '付款触发条件',
        sort_order    INT          DEFAULT 0 COMMENT '排序',

        INDEX idx_contract_id (contract_id),
        FOREIGN KEY (contract_id) REFERENCES contracts(contract_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分期付款明细';
    """,

    # 产品表（软件+硬件，product_type区分）
    """
    CREATE TABLE IF NOT EXISTS contract_products (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        contract_id   VARCHAR(64)  NOT NULL COMMENT '合同唯一ID',
        product_type  ENUM('software','hardware') NOT NULL DEFAULT 'software' COMMENT '产品类型',
        name          VARCHAR(256) COMMENT '产品名称',
        -- 软件专属字段
        version       VARCHAR(64)  COMMENT '版本号',
        license_type  VARCHAR(64)  COMMENT '授权类型',
        -- 硬件专属字段
        model         VARCHAR(200) COMMENT '型号规格',
        quantity      INT          COMMENT '采购数量',
        unit          VARCHAR(50)  COMMENT '单位（台/套/个等）',

        INDEX idx_contract_id (contract_id),
        INDEX idx_product_type (product_type),
        FOREIGN KEY (contract_id) REFERENCES contracts(contract_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合同产品表（软件+硬件）';
    """,

    # 关键条款表
    """
    CREATE TABLE IF NOT EXISTS contract_key_clauses (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        contract_id   VARCHAR(64)  NOT NULL COMMENT '合同唯一ID',
        clause_type   VARCHAR(64)  COMMENT '条款类型（验收标准/违约责任/知识产权等）',
        summary       TEXT         COMMENT '条款摘要',

        INDEX idx_contract_id (contract_id),
        FOREIGN KEY (contract_id) REFERENCES contracts(contract_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='关键条款';
    """,
]


def init_db():
    """初始化数据库：创建库 + 表"""
    # 1. 先创建数据库（如果不存在）
    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
    )
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
            f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.close()

    # 2. 建表
    with get_conn() as conn:
        with conn.cursor() as cur:
            for ddl in DDL_STATEMENTS:
                cur.execute(ddl)
        conn.commit()

    logger.info(f"[DB] 数据库初始化完成: {MYSQL_DATABASE}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("数据库初始化成功！")
