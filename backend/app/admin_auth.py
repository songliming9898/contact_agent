"""
后台固定密码认证模块
"""
import jwt
from datetime import datetime, timedelta
from typing import Optional

from .config import ADMIN_PASSWORD, JWT_SECRET_KEY, JWT_EXPIRE_HOURS


def verify_admin_password(password: str) -> bool:
    """验证后台管理密码"""
    return password == ADMIN_PASSWORD


def create_jwt_token(password: str) -> Optional[str]:
    """
    验证密码并生成 JWT Token
    
    Args:
        password: 用户输入的密码
    
    Returns:
        JWT token 字符串，密码错误返回 None
    """
    if not verify_admin_password(password):
        return None
    
    payload = {
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
    return token


def verify_jwt_token(token: str) -> bool:
    """
    验证 JWT Token 是否有效
    
    Args:
        token: JWT token 字符串
    
    Returns:
        True 表示有效
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        return payload.get("role") == "admin"
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False
