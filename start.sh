#!/bin/bash
# ContractAgent 启动脚本 (MySQL版)

echo "=== ContractAgent 启动 ==="

# 等待 MySQL 就绪
echo "等待 MySQL 连接..."
until python -c "import pymysql; pymysql.connect(host='${MYSQL_HOST:-mysql}', port=int('${MYSQL_PORT:-3306}'), user='${MYSQL_USER:-root}', password='${MYSQL_PASSWORD:-root123}', database='${MYSQL_DATABASE:-contract_agent}')" 2>/dev/null; do
    echo "MySQL 未就绪，等待..."
    sleep 2
done
echo "MySQL 已就绪"

# 初始化数据库表
python -c "from app.db.mysql_client import init_db; init_db()"
echo "数据库表初始化完成"

# 启动 FastAPI
echo "启动 API 服务 (端口 ${API_PORT:-8000})..."
exec uvicorn app.api_server:app --host 0.0.0.0 --port ${API_PORT:-8000}
