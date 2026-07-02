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
from typing import AsyncIterator, Dict, Any, List, Optional

from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
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

SYSTEM_PROMPT = """你是一个专业的软件公司合同问数助手。你**必须使用工具**来查询合同数据库，**绝对禁止**凭记忆或猜测回答任何数据相关问题。

**核心铁律**：
- ⚠️ 任何涉及合同数据的问题（数量、金额、列表、详情、搜索），**必须先调用工具查询**
- ⚠️ 你不知道数据库里有什么，只有工具能告诉你真相
- ⚠️ 严禁说"当前系统中暂无合同数据"除非工具真的返回了空结果
- ⚠️ 严禁回复 "Not Found"、"未找到"、"没有找到" 等话术——你必须先调用工具确认
- ⚠️ 如果用户问"有哪些合同""列出合同""所有合同"等，必须调用 list_contracts 或 search_con_text

**不完整输入的智能理解**：
- ⚠️ 用户可能省略"合同"二字，但只要涉及金额、尾款、付款、公司、日期等概念，都应作为合同查询处理
- 示例："尾款超过3万的" → 理解为"尾款超过3万的合同" → 调用 list_contracts 然后筛选尾款条件
- 示例："华为的" → 理解为"华为公司的合同" → 调用 search_con_text(keyword="华为")
- 示例："上个月签的" → 理解为"上个月签订的合同" → 调用 list_contracts
- **任何不完整的输入，都不要直接说 Not Found，而是先调用工具查询再做判断**

**工具使用指南**：

1. **list_contracts** — 列出合同摘要列表（⭐查"有哪些合同"优先使用，也是默认兜底工具）
   - 用户问"列出所有合同""有哪些合同" → 调用 list_contracts()
   - 用户的问题即使不完整，如果不确定用什么工具，优先调用 list_contracts()
   - 可按关键词筛选：keyword="XX公司"
   - 返回：合同编号、甲方、乙方、项目名称、金额、尾款金额、签订日期

2. **search_con_text** — 关键词搜索 + 公司简称模糊匹配（⭐查公司时优先使用）
   - **当用户提到公司名称或简称时，必须优先使用此工具**
   - 一步返回：完整公司名列表 + 金额汇总 + 相关原文片段
   - 示例：keyword="宏达技术" → 自动匹配 party_a 包含"宏达技术"的合同
   - 查条款内容：keyword="违约金"/"保密期限"/"验收标准"

3. **query_con_count** — 统计合同数量
   - 查总数：不填参数
   - 按甲方分组：by_party=true
   - 按付款方式分组：by_type=true

4. **query_con_sum** — 查询合同金额
   - 查单份合同金额：contract_id="CON-xxx"
   - 查所有合同总金额：aggregate=true
   - 查某甲方累计金额：party_a="XX公司", aggregate=true

5. **get_con_details** — 获取合同完整详情（含软件/硬件产品清单）
   - 需要合同编号，先用其他工具找到编号

6. **search_vector** — 语义向量检索（结构化查询无结果时使用）
   - 基于语义理解，能理解同义词、近义词
   - 适用场景：结构化字段未覆盖的条款查询

**回答规则**：
1. 公司名称问题必须用 search_con_text 工具查询，不要凭空编造
2. 金额统一用"元"表示，保留两位小数
3. 回答时注明信息来源（合同编号、甲方等）
4. 如果用户的问题需要多步查询，分步使用工具
5. 如果工具返回无结果，如实告知用户，不要编造数据
6. 如果用户输入不完整，先按最合理的理解去查询，然后在回答中说明你的理解"""

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

    兜底机制：如果 Agent 没有调用任何工具就返回了"无数据"类答案，
    自动补调 list_contracts 或 search_con_text 获取真实数据。
    """

    # LLM 可能编造的"无数据"话术（中英文都要覆盖）
    NO_DATA_PATTERNS = [
        # 中文
        "暂无合同数据",
        "当前系统中暂无",
        "系统中没有合同",
        "没有找到任何合同",
        "目前没有合同",
        "暂未导入合同",
        "未找到",
        "没有找到",
        "找不到",
        # 英文
        "Not Found",
        "not found",
        "Not found",
        "No data",
        "no data",
        "No results",
        "no results",
        "Nothing found",
    ]

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
            return_intermediate_steps=True,  # 改为 True，检查是否真的调用了工具
        )

    def _format_history(self, chat_history: Optional[List[Dict]]) -> List[BaseMessage]:
        """
        将前端传来的历史消息列表转为 LangChain 消息格式
        输入：[{"role":"user","content":"..."}, {"role":"ai","content":"..."}]
        输出：[HumanMessage(...), AIMessage(...)]
        """
        if not chat_history:
            return []
        messages = []
        for msg in chat_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role in ("ai", "assistant"):
                messages.append(AIMessage(content=content))
        return messages

    def _is_fake_no_data(self, output: str) -> bool:
        """检测 LLM 是否编造了'无数据'答案（而非工具真实返回）"""
        for pattern in self.NO_DATA_PATTERNS:
            if pattern in output:
                return True
        return False

    def _fallback_list_contracts(self) -> str:
        """兜底：直接调用 list_contracts 工具获取真实数据"""
        logger.warning("[QueryAgent] LLM 可能未调用工具，触发兜底查询...")
        try:
            from .tool_router import route_list_contracts
            raw = route_list_contracts()
            # 用 LLM 格式化兜底结果
            if "暂无合同数据" in raw:
                return "当前系统中确实暂无合同数据，请先导入合同。"
            # 用 LLM 总结兜底查询结果
            summary_prompt = f"""根据以下工具返回的合同数据，用简洁的中文回答用户"列出所有合同"的问题。
请列出每份合同的编号、甲方、乙方和金额。

工具返回数据：
{raw}"""
            from langchain_core.messages import HumanMessage
            resp = self.llm.invoke([HumanMessage(content=summary_prompt)])
            return resp.content
        except Exception as e:
            logger.error(f"[QueryAgent] 兜底查询失败: {e}")
            return f"查询出错: {str(e)}"

    def query(self, question: str, chat_history: Optional[List[Dict]] = None) -> str:
        """同步查询（非流式），带兜底检测"""
        try:
            history = self._format_history(chat_history)
            result = self.agent_executor.invoke({
                "input": question,
                "chat_history": history,
            })
            output = result.get("output", "抱歉，我无法回答这个问题。")
            intermediate_steps = result.get("intermediate_steps", [])

            # 检测 LLM 是否编造了"无数据"答案
            if self._is_fake_no_data(output) and not intermediate_steps:
                logger.warning(
                    f"[QueryAgent] 检测到编造的'无数据'答案，中间步骤数={len(intermediate_steps)}，"
                    f"触发兜底查询..."
                )
                return self._fallback_list_contracts()

            return output
        except Exception as e:
            logger.error(f"[QueryAgent] 查询出错: {e}")
            return f"查询出错: {str(e)}"

    async def query_stream(self, question: str, chat_history: Optional[List[Dict]] = None) -> AsyncIterator[str]:
        """流式查询（SSE）"""
        try:
            history = self._format_history(chat_history)
            async for event in self.agent_executor.astream_events(
                {"input": question, "chat_history": history},
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

    async def query_stream_simple(self, question: str, chat_history: Optional[List[Dict]] = None) -> AsyncIterator[str]:
        """
        简化版流式查询 — 先同步执行 Agent，再流式输出结果
        更稳定，适合 Demo。V1.1 增加 chat_history 支持多轮对话。
        """
        try:
            history = self._format_history(chat_history)
            result = self.agent_executor.invoke(
                {"input": question, "chat_history": history},
                return_only_outputs=False,
            )

            output = result.get("output", "")
            intermediate_steps = result.get("intermediate_steps", [])

            # 兜底检测：如果 LLM 没调工具就编造了"无数据"答案
            if self._is_fake_no_data(output) and not intermediate_steps:
                logger.warning(
                    f"[QueryAgent] 检测到编造的'无数据'答案: '{output}'，"
                    f"中间步骤数={len(intermediate_steps)}，触发兜底查询..."
                )
                fallback = self._fallback_list_contracts()
                yield fallback
                return

            # 流式输出最终答案（跳过工具调用过程，只显示结果）
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
