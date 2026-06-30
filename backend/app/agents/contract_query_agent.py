"""
Agent2: 智能问数 Agent (LangChain Tool-Calling Agent) — 重构版

使用 8 个工具（3层架构）：
  Layer 1 (大模型层):  tools.py    — 8个 @tool 函数 (5查询+1向量+2写)
  Layer 2 (工具路由层): tool_router.py — 格式化 + 聚合
  Layer 3 (数据执行层): data_layer.py  — MySQL DAO

工具清单：
  query_con_sum    : 合同金额查询 / 汇总统计
  query_con_count  : 合同数量统计（多维筛选 + 分组）
  search_con_text  : 关键词搜索 + 公司简称模糊匹配
  get_con_details  : 合同完整详情
  list_contracts   : 合同摘要列表
  search_vector    : 语义向量检索（ChromaDB）
  insert_contract  : 导入合同（MySQL + ChromaDB 写）
  delete_contract  : 删除合同（MySQL + ChromaDB 删）
"""
import logging
from typing import AsyncIterator, Dict, Any

from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models import ChatTongyi

from ..config import DASHSCOPE_API_KEY, LLM_MODEL
from .tools import (
    query_con_sum,
    query_con_count,
    search_con_text,
    get_con_details,
    list_contracts,
    search_vector,
    insert_contract,
    delete_contract,
)

logger = logging.getLogger(__name__)

# ============================================================
#  Tool-Calling Agent Prompt（利用模型原生 Function Calling）
# ============================================================

SYSTEM_PROMPT = """你是一个专业的软件公司合同问数助手。你可以使用工具来查询合同数据库。

**工具使用指南**：

1. **search_con_text** — 关键词搜索 + 公司简称模糊匹配（⭐优先使用）
   - **当用户提到公司名称或简称时，必须优先使用此工具**
   - 一步返回：完整公司名列表 + 金额汇总 + 相关原文片段
   - 示例：keyword="宏达技术" → 自动匹配 party_a 包含"宏达技术"的合同
   - 查条款内容：keyword="违约金"/"保密期限"/"验收标准"

2. **search_vector** — 语义向量检索（结构化查询无结果时使用）
   - 基于语义理解，能理解同义词、近义词
   - 适用场景：结构化字段未覆盖的条款查询

3. **query_con_sum** — 查询合同金额
   - 查单份合同金额：contract_id="CON-xxx"
   - 查所有合同总金额：aggregate=true
   - 查某甲方累计金额：party_a="XX公司", aggregate=true

4. **query_con_count** — 统计合同数量
   - 查总数：不填参数
   - 按甲方分组：by_party=true
   - 按付款方式分组：by_type=true

5. **get_con_details** — 获取合同完整详情（含软件/硬件产品清单）
   - 需要合同编号，先用其他工具找到编号

6. **list_contracts** — 列出合同列表
   - 可按关键词搜索

**回答规则**：
1. 公司名称问题必须用 search_con_text 工具查询，不要凭空编造
2. 金额统一用"元"表示，保留两位小数
3. 回答时注明信息来源（合同编号、甲方等）
4. 如果用户的问题需要多步查询，分步使用工具
5. 如果工具返回无结果，如实告知用户，不要编造数据"""

PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])


class ContractQueryAgent:
    """
    智能问数 Agent (Tool-Calling Agent)

    使用 LangChain create_tool_calling_agent + 8 个 Tools
    利用通义千问原生 Function Calling 能力，比 ReAct 文本格式更可靠
    支持 SSE 流式输出
    """

    def __init__(self):
        self.llm = ChatTongyi(
            model=LLM_MODEL,
            dashscope_api_key=DASHSCOPE_API_KEY,
            temperature=0.3,
        )

        # 8个工具（5个MySQL查询 + 1个向量检索 + 2个写）
        self.tools = [
            query_con_sum,
            query_con_count,
            search_con_text,
            search_vector,
            get_con_details,
            list_contracts,
            insert_contract,
            delete_contract,
        ]

        # 创建 Tool-Calling Agent（利用模型原生 Function Calling）
        self.agent = create_tool_calling_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=PROMPT,
        )

        # 创建 AgentExecutor
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=8,
            return_intermediate_steps=False,
        )

    def query(self, question: str) -> str:
        """同步查询（非流式）"""
        try:
            result = self.agent_executor.invoke({"input": question})
            return result.get("output", "抱歉，我无法回答这个问题。")
        except Exception as e:
            logger.error(f"[QueryAgent] 查询出错: {e}")
            return f"查询出错: {str(e)}"

    async def query_stream(self, question: str) -> AsyncIterator[str]:
        """流式查询（SSE）"""
        try:
            async for event in self.agent_executor.astream_events(
                {"input": question},
                version="v2",
            ):
                kind = event.get("event", "")

                if kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    yield f"\n\n🔍 **正在查询**: {tool_name}...\n\n"

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "")
                    output = event.get("data", {}).get("output", "")
                    if output:
                        if isinstance(output, str) and len(output) > 500:
                            output = output[:500] + "..."
                        yield f"📊 **{tool_name} 结果**:\n{output}\n\n"

                elif kind == "on_chat_model_stream":
                    content = event.get("data", {}).get("chunk", {})
                    if hasattr(content, "content") and content.content:
                        yield content.content

            yield "\n"

        except Exception as e:
            logger.error(f"[QueryAgent] 流式查询出错: {e}")
            try:
                result = self.query(question)
                yield result
            except Exception as e2:
                yield f"查询出错: {str(e2)}"

    async def query_stream_simple(self, question: str) -> AsyncIterator[str]:
        """
        简化版流式查询 — 先同步执行 Agent，再流式输出结果
        更稳定，适合 Demo
        """
        try:
            result = self.agent_executor.invoke(
                {"input": question},
                return_only_outputs=False,
            )

            output = result.get("output", "")
            intermediate_steps = result.get("intermediate_steps", [])

            # 流式输出工具调用过程
            for step in intermediate_steps:
                action = step[0]
                observation = step[1]

                yield f"\n🔍 **查询中**: {action.tool}\n"
                obs_str = str(observation)
                if len(obs_str) > 500:
                    obs_str = obs_str[:500] + "..."
                yield f"📊 **结果**:\n{obs_str}\n\n"

            # 流式输出最终答案
            if output:
                sentences = output.replace('\n', '\n').split('\n')
                for sentence in sentences:
                    if sentence.strip():
                        yield sentence + '\n'
                    else:
                        yield '\n'

        except Exception as e:
            logger.error(f"[QueryAgent] 流式查询出错: {e}")
            yield f"抱歉，查询过程中出现错误: {str(e)}"


# 全局单例
contract_query_agent = ContractQueryAgent()
