"""
会话管理器 — Redis 热数据 + MySQL 异步持久化

核心流程：
  读：Redis → 未命中 → MySQL → 回填 Redis
  写：Redis (实时) → MySQL (异步 background task)
"""
import json
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional

from .redis_client import get_client, SESSION_TTL, is_available
from .db.mysql_client import get_pool

logger = logging.getLogger(__name__)

# 每个会话最多保留的消息条数（20轮 = 40条）
MAX_MESSAGES = 40


def _redis_key(session_id: str) -> str:
    return f"session:{session_id}:history"


# ==================== Redis 读写 ====================

def _redis_get_history(session_id: str) -> List[Dict]:
    """从 Redis 读取会话历史（时间正序）"""
    try:
        if not is_available():
            return []
        client = get_client()
        key = _redis_key(session_id)
        raw = client.lrange(key, 0, -1)
        # Redis List 是先进后出（LPUSH），反转得时间正序
        messages = []
        for item in reversed(raw):
            try:
                messages.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return messages
    except Exception as e:
        logger.error(f"[SessionManager] Redis 读取失败: {e}")
        return []


def _redis_append_messages(session_id: str, messages: List[Dict]):
    """向 Redis 追加消息，并裁剪到 MAX_MESSAGES"""
    try:
        if not is_available():
            return
        client = get_client()
        key = _redis_key(session_id)
        for msg in messages:
            client.lpush(key, json.dumps(msg, ensure_ascii=False))
        # 裁剪到最多 MAX_MESSAGES 条
        client.ltrim(key, 0, MAX_MESSAGES - 1)
        # 刷新 TTL
        client.expire(key, SESSION_TTL)
    except Exception as e:
        logger.error(f"[SessionManager] Redis 写入失败: {e}")


def _redis_delete_session(session_id: str):
    """删除 Redis 中的会话"""
    try:
        if not is_available():
            return
        client = get_client()
        client.delete(_redis_key(session_id))
    except Exception as e:
        logger.error(f"[SessionManager] Redis 删除失败: {e}")


# ==================== MySQL 读写（持久化） ====================

def _mysql_get_history(session_id: str) -> List[Dict]:
    """从 MySQL 读取最近消息"""
    try:
        pool = get_pool()
        conn = pool.connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content, seq, created_at FROM chat_messages "
            "WHERE session_id = %s ORDER BY seq DESC LIMIT %s",
            (session_id, MAX_MESSAGES),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # 反转为时间正序
        messages = []
        for row in reversed(rows):
            messages.append({
                "role": row[0],
                "content": row[1],
                "time": row[3].isoformat() if isinstance(row[3], datetime) else str(row[3]),
            })
        return messages
    except Exception as e:
        logger.error(f"[SessionManager] MySQL 读取失败: {e}")
        return []


def _mysql_save_messages(session_id: str, title: str, messages: List[Dict]):
    """向 MySQL 写入消息"""
    try:
        pool = get_pool()
        conn = pool.connection()
        cursor = conn.cursor()

        # 1. 插入或更新 session
        cursor.execute(
            "INSERT INTO chat_sessions (session_id, title, message_count, is_active) "
            "VALUES (%s, %s, %s, 1) "
            "ON DUPLICATE KEY UPDATE title=VALUES(title), message_count=message_count+%s, updated_at=NOW()",
            (session_id, title, len(messages), len(messages)),
        )

        # 2. 获取当前最大 seq
        cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM chat_messages WHERE session_id = %s",
            (session_id,),
        )
        max_seq = cursor.fetchone()[0]

        # 3. 批量插入新消息
        for i, msg in enumerate(messages):
            seq = max_seq + i + 1
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, content, seq) "
                "VALUES (%s, %s, %s, %s)",
                (session_id, msg["role"], msg["content"], seq),
            )

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"[SessionManager] MySQL 写入成功: {session_id}, +{len(messages)}条")
    except Exception as e:
        logger.error(f"[SessionManager] MySQL 写入失败: {e}")


def _mysql_delete_session(session_id: str):
    """从 MySQL 删除会话（CASCADE 自动删消息）"""
    try:
        pool = get_pool()
        conn = pool.connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_sessions WHERE session_id = %s", (session_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"[SessionManager] MySQL 删除失败: {e}")


def _mysql_list_sessions() -> List[Dict]:
    """获取会话列表"""
    try:
        pool = get_pool()
        conn = pool.connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, title, message_count, created_at, updated_at "
            "FROM chat_sessions WHERE is_active = 1 "
            "ORDER BY updated_at DESC LIMIT 50"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        return [
            {
                "session_id": row[0],
                "title": row[1],
                "message_count": row[2],
                "created_at": row[3].isoformat() if isinstance(row[3], datetime) else str(row[3]),
                "updated_at": row[4].isoformat() if isinstance(row[4], datetime) else str(row[4]),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"[SessionManager] 获取会话列表失败: {e}")
        return []


# ==================== 对外接口 ====================

def create_session() -> str:
    """创建新会话，返回 session_id"""
    return str(uuid.uuid4())


def get_history(session_id: str) -> List[Dict]:
    """
    获取会话历史（时间正序）
    优先从 Redis 读取，未命中则从 MySQL 读取并回填 Redis
    """
    # 1. 从 Redis 读取
    messages = _redis_get_history(session_id)

    if messages:
        logger.debug(f"[SessionManager] Redis 命中: {session_id}, {len(messages)}条")
        return messages

    # 2. Redis 未命中，从 MySQL 读取
    messages = _mysql_get_history(session_id)

    if messages:
        # 回填 Redis
        logger.info(f"[SessionManager] Redis 未命中，从 MySQL 回填: {session_id}, {len(messages)}条")
        # 注意：_redis_append_messages 是 LPUSH 的，需要反转顺序
        _redis_append_messages(session_id, messages)

    return messages


def save_messages(session_id: str, user_msg: str, ai_msg: str, title: str = ""):
    """
    保存一轮对话（用户消息 + AI 回复）
    实时写 Redis，异步写 MySQL
    """
    now = datetime.now().isoformat()
    messages = [
        {"role": "user", "content": user_msg, "time": now},
        {"role": "ai", "content": ai_msg, "time": now},
    ]

    # 实时写入 Redis
    _redis_append_messages(session_id, messages)

    # 异步写入 MySQL（使用 FastAPI BackgroundTasks 或直接同步写）
    # 这里用同步写，因为数据量小且需要保证持久化
    try:
        _mysql_save_messages(session_id, title or _generate_title(user_msg), messages)
    except Exception as e:
        logger.error(f"[SessionManager] MySQL 异步写入异常: {e}")


def delete_session(session_id: str):
    """删除会话（Redis + MySQL）"""
    _redis_delete_session(session_id)
    _mysql_delete_session(session_id)


def list_sessions() -> List[Dict]:
    """获取会话列表"""
    return _mysql_list_sessions()


def _generate_title(question: str) -> str:
    """根据首条问题生成会话标题（截取前30字）"""
    title = question.strip()
    if len(title) > 30:
        title = title[:30] + "..."
    return title
