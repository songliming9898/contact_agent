# ContractAgent Dockerfile — 后端 (MySQL版)
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ .

# 创建数据目录
RUN mkdir -p data/contracts data/json

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "app.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
