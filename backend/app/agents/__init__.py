"""
Agent 模块

三层架构:
  Layer 1 (大模型层):   tools.py              — 5个 @tool 函数
  Layer 2 (工具路由层):  tool_router.py        — 格式化 + 聚合
  Layer 3 (数据执行层):  data_layer.py         — MySQL DAO

Agent:
  contract_parser_agent  — Agent1: 合同解析
  contract_query_agent   — Agent2: 智能问数 (ReAct)
"""
