"""
Redis 客户端 — 连接池封装
"""
import os
import logging
from typing import Optional

import redis
from redis import ConnectionPool

logger = logging.getLogger(__name__)

# Redis 配置（从环境变量读取，默认本地）
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))

# 会话过期时间（秒），默认7天
SESSION_TTL = int(os.getenv("SESSION_TTL", "604800"))

_pool: Optional[ConnectionPool] = None
_client: Optional[redis.Redis] = None


def get_pool() -> ConnectionPool:
    """获取 Redis 连接池（懒加载单例）"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            max_connections=REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )
        logger.info(f"[Redis] 连接池已创建: {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
    return _pool


def get_client() -> redis.Redis:
    """获取 Redis 客户端（单例）"""
    global _client
    if _client is None:
        _client = redis.Redis(connection_pool=get_pool())
    return _client


def is_available() -> bool:
    """检查 Redis 是否可用"""
    try:
        client = get_client()
        client.ping()
        return True
    except Exception as e:
        logger.warning(f"[Redis] 不可用: {e}")
        return False
