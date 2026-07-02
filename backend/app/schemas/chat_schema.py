"""
会话相关 Pydantic 模型
"""
from typing import Optional, List
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """智能问数请求（V1.1 增加 session_id）"""
    question: str
    session_id: Optional[str] = None  # 不传则自动创建新会话


class ChatResponse(BaseModel):
    """智能问数同步响应"""
    answer: str
    session_id: Optional[str] = None


class SessionInfo(BaseModel):
    """会话摘要信息"""
    session_id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionInfo]


class MessageItem(BaseModel):
    """单条消息"""
    role: str
    content: str
    time: Optional[str] = None


class SessionHistoryResponse(BaseModel):
    """会话历史响应"""
    session_id: str
    messages: List[MessageItem]
