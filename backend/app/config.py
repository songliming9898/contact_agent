"""
ContractAgent 配置文件 (重构版 - MySQL 存储)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONTRACTS_DIR = os.path.join(DATA_DIR, "contracts")
JSON_DIR = os.path.join(DATA_DIR, "json")

for d in [DATA_DIR, CONTRACTS_DIR, JSON_DIR]:
    os.makedirs(d, exist_ok=True)

# ==================== MySQL 配置 ====================
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root123")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "contract_agent")
MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "5"))

# ==================== LLM 配置 ====================
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-xxxxxxxxxxxx")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")  # qwen-turbo / qwen-plus / qwen-max

# ==================== Embedding 配置（DashScope API，无需本地模型） ====================
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")  # DashScope 1536维
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))

# Query 指令前缀（DashScope 兼容 BGE 风格）
QUERY_INSTRUCTION = "为这个查询生成表示以用于检索相关合同条款："

# ==================== ChromaDB 配置 ====================
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", os.path.join(DATA_DIR, "chroma"))

# ==================== 后台认证配置 ====================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "contract-agent-secret-key-2026")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# ==================== 服务配置 ====================
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
