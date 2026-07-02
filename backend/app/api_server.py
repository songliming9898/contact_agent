"""
ContractAgent API 服务 — V1.1 (多轮对话记忆)

端点：
  /api/chat             智能问数（SSE流式，支持session_id）
  /api/chat/sync        智能问数（同步）
  /api/chat/new         创建新会话
  /api/chat/sessions    会话列表
  /api/chat/{id}/history 会话历史
  /api/chat/{id}        删除会话
  /api/admin/login      后台登录
  /api/admin/upload     批量上传合同（→ insert_contract tool → MySQL）
  /api/admin/documents  文档列表
  /api/admin/contracts  合同数据列表
  /api/admin/contract/{id} 合同详情（含软件+硬件产品）
  /api/admin/status     系统状态
  /api/admin/reparse/{filename} 重新解析
  /api/admin/delete/{contract_id} 删除合同（→ delete_contract tool → MySQL级联删除）
"""
import os
import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .config import API_HOST, API_PORT, CORS_ORIGINS, CONTRACTS_DIR, JSON_DIR
from .admin_auth import verify_admin_password, create_jwt_token, verify_jwt_token
from .document_reader import read_document
from .agents.contract_parser_agent import contract_parser
from .agents.contract_query_agent import contract_query_agent
from .agents.data_layer import (
    dao_insert_contract,
    dao_get_details,
    dao_list_contracts,
    dao_delete_contract,
    dao_query_sum_amount,
)
from .db.mysql_client import init_db
from .session_manager import (
    create_session,
    get_history,
    save_messages,
    delete_session,
    list_sessions,
)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# 启动时初始化数据库
init_db()

# 创建 FastAPI 应用
app = FastAPI(
    title="ContractAgent API",
    description="软件公司合同智能问数系统 (MySQL版)",
    version="2.0.0",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS.split(",") if CORS_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 请求/响应模型 ====================

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None  # V1.1: 会话ID，不传则自动创建


class ChatResponse(BaseModel):
    answer: str
    session_id: Optional[str] = None  # V1.1: 返回会话ID


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str = ""


class DocumentInfo(BaseModel):
    contract_id: str
    file_name: str
    file_type: str = ""
    party_a: str = ""
    party_b: str = ""
    total_amount: Optional[float] = None
    sign_date: str = ""
    parse_status: str = "success"


# ==================== 依赖注入 ====================

async def verify_admin(request: Request):
    """后台管理 JWT 认证依赖"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header.replace("Bearer ", "")
    if not verify_jwt_token(token):
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")

    return True


# ==================== API 端点 ====================

# --- 智能问数 ---

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """智能问数接口（SSE 流式返回），V1.1 支持多轮对话记忆"""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 获取或创建 session_id
    session_id = request.session_id or create_session()

    # 读取历史
    history = get_history(session_id)

    # 用于收集完整 AI 回复
    ai_full_response = []

    async def event_generator():
        nonlocal ai_full_response
        try:
            async for chunk in contract_query_agent.query_stream_simple(
                request.question,
                chat_history=history,
            ):
                ai_full_response.append(chunk)
                yield {
                    "event": "message",
                    "data": chunk,
                }
            # 保存本轮对话到 Redis + MySQL
            full_answer = "".join(ai_full_response)
            save_messages(session_id, request.question, full_answer)

            yield {
                "event": "done",
                "data": json.dumps({"status": "done", "session_id": session_id}),
            }
        except Exception as e:
            logger.error(f"/api/chat 错误: {e}")
            yield {
                "event": "error",
                "data": f"查询出错: {str(e)}",
            }

    return EventSourceResponse(event_generator())


@app.post("/api/chat/sync")
async def chat_sync(request: ChatRequest):
    """智能问数接口（同步版本）"""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    session_id = request.session_id or create_session()
    history = get_history(session_id)

    try:
        answer = contract_query_agent.query(request.question, chat_history=history)
        save_messages(session_id, request.question, answer)
        return ChatResponse(answer=answer, session_id=session_id)
    except Exception as e:
        logger.error(f"/api/chat/sync 错误: {e}")
        return ChatResponse(answer=f"查询出错: {str(e)}", session_id=session_id)


# --- 会话管理（V1.1 新增） ---

@app.post("/api/chat/new")
async def chat_new():
    """创建新会话"""
    session_id = create_session()
    return {"session_id": session_id}


@app.get("/api/chat/sessions")
async def chat_sessions():
    """获取会话列表"""
    sessions = list_sessions()
    return {"sessions": sessions}


@app.get("/api/chat/{session_id}/history")
async def chat_history(session_id: str):
    """获取会话历史"""
    messages = get_history(session_id)
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/chat/{session_id}")
async def chat_delete(session_id: str):
    """删除会话"""
    delete_session(session_id)
    return {"message": "已删除"}


# --- 后台管理 ---

@app.post("/api/admin/login")
async def admin_login(request: LoginRequest):
    """后台管理登录（固定密码）"""
    token = create_jwt_token(request.password)
    if token:
        return LoginResponse(success=True, token=token, message="登录成功")
    else:
        return LoginResponse(success=False, message="密码错误")


@app.post("/api/admin/upload")
async def admin_upload(
    files: List[UploadFile] = File(...),
    _: bool = Depends(verify_admin),
):
    """批量上传合同文件 → 解析 → 写入 MySQL"""
    if not files:
        raise HTTPException(status_code=400, detail="请选择文件")

    results = []

    for file in files:
        try:
            # 1. 保存原始文件
            file_path = Path(CONTRACTS_DIR) / file.filename
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)

            # 2. 文档读取
            doc_result = read_document(str(file_path))

            # 3. 合同解析 Agent
            contract_json = contract_parser.parse(
                full_text=doc_result["full_text"],
                file_name=doc_result["filename"],
                file_type=doc_result["file_type"],
                page_count=doc_result["page_count"],
            )

            # 4. 保存标准化 JSON（备份）
            json_path = Path(JSON_DIR) / f"{doc_result['filename']}.json"
            # 去掉 _full_text 再存 JSON 文件
            json_data = {k: v for k, v in contract_json.items() if k != "_full_text"}
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)

            # 5. 写入 MySQL
            contract_id = dao_insert_contract(contract_json)

            results.append({
                "filename": file.filename,
                "contract_id": contract_id,
                "status": "success",
            })

            logger.info(f"[Upload] 成功处理: {file.filename} -> {contract_id}")

        except Exception as e:
            logger.error(f"[Upload] 处理 {file.filename} 失败: {e}")
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e),
            })

    return {"results": results}


@app.get("/api/admin/documents")
async def admin_documents(
    _: bool = Depends(verify_admin),
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
):
    """获取合同列表（从 MySQL）"""
    result = dao_list_contracts(page=page, page_size=page_size, keyword=keyword or None)
    return result


@app.get("/api/admin/contracts")
async def admin_contracts(_: bool = Depends(verify_admin)):
    """获取所有合同（向后兼容）"""
    result = dao_list_contracts(page=1, page_size=1000)
    return {"contracts": result["items"], "total": result["total"]}


@app.get("/api/admin/contract/{contract_id}")
async def admin_contract_detail(contract_id: str, _: bool = Depends(verify_admin)):
    """获取单份合同的完整详情"""
    detail = dao_get_details(contract_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"合同 {contract_id} 未找到")
    return detail


@app.get("/api/admin/status")
async def admin_status(_: bool = Depends(verify_admin)):
    """系统状态"""
    # 合同统计
    from .agents.data_layer import dao_query_count
    total = dao_query_count()
    summary = dao_query_sum_amount()

    return {
        "contracts_total": total.get("count", 0),
        "amount_total": summary.get("total", 0),
        "amount_avg": summary.get("avg", 0),
        "amount_max": summary.get("max", 0),
        "amount_min": summary.get("min", 0),
    }


@app.post("/api/admin/reparse/{filename}")
async def admin_reparse(filename: str, _: bool = Depends(verify_admin)):
    """重新解析指定合同"""
    file_path = Path(CONTRACTS_DIR) / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 未找到")

    try:
        doc_result = read_document(str(file_path))

        contract_json = contract_parser.parse(
            full_text=doc_result["full_text"],
            file_name=doc_result["filename"],
            file_type=doc_result["file_type"],
            page_count=doc_result["page_count"],
        )

        # 更新 JSON 文件
        json_path = Path(JSON_DIR) / f"{doc_result['filename']}.json"
        json_data = {k: v for k, v in contract_json.items() if k != "_full_text"}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        # 更新 MySQL
        contract_id = dao_insert_contract(contract_json)

        return {
            "filename": filename,
            "contract_id": contract_id,
            "status": "success",
        }

    except Exception as e:
        logger.error(f"[Reparse] 重新解析 {filename} 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/delete/{contract_id}")
async def admin_delete(contract_id: str, _: bool = Depends(verify_admin)):
    """删除合同（MySQL + 文件）"""
    # 先从 MySQL 删除
    detail = dao_get_details(contract_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"合同 {contract_id} 未找到")

    deleted = []

    # 删除 MySQL 记录
    if dao_delete_contract(contract_id):
        deleted.append("数据库记录")

    # 删除 JSON 文件
    file_name = detail.get("file_name", "")
    if file_name:
        json_path = Path(JSON_DIR) / f"{file_name}.json"
        if json_path.exists():
            json_path.unlink()
            deleted.append("JSON文件")

        # 删除原始文件
        file_path = Path(CONTRACTS_DIR) / file_name
        if file_path.exists():
            file_path.unlink()
            deleted.append("原始文件")

    return {"message": f"已删除: {', '.join(deleted)}"}


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.api_server:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
