# ContractAgent — 软件公司合同智能问数系统 (v4.2)

基于 **LangChain ReAct Agent** + **MySQL + ChromaDB 双存储** 的合同智能问数系统。支持合同解析入库、自然语言问答、公司简称模糊匹配、语义向量检索。

## 设计理念：双存储架构

| 存储 | 定位 | 擅长 |
|------|------|------|
| **MySQL** | 结构化精确查询 | 金额汇总、合同统计、按甲乙方筛选、分组统计 |
| **ChromaDB** | 非结构化语义检索 | 条款原文搜索、模糊匹配、跨字段语义理解 |

> 两个存储互为补充，Agent 根据问题类型自动选择合适的工具。

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                  用户交互层 (Vue3 + Vant4)            │
│  ┌──────────────┐  ┌──────────────────┐             │
│  │ 合同问答聊天  │  │ 后台管理(密码登录)│             │
│  └──────┬───────┘  └────────┬─────────┘             │
└─────────┼───────────────────┼───────────────────────┘
          │                   │
┌─────────▼───────────────────▼───────────────────────┐
│                  FastAPI 服务层                       │
│  /api/chat (SSE流式)    /api/admin/* (JWT认证)       │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│              LangChain Agent 引擎层                   │
│                                                      │
│  ┌────────────────────┐  ┌────────────────────────┐ │
│  │ Agent1: 合同解析    │  │ Agent2: 智能问数(ReAct) │ │
│  │ LLM → 标准化JSON    │  │ 8个Tools → 综合回答     │ │
│  └────────┬───────────┘  └───────────┬────────────┘ │
│           │                          │               │
│           └──────────┬───────────────┘               │
│                      ▼                               │
│           ┌──────────────────┐                      │
│           │   LLM (通义千问)  │                      │
│           │ + Embedding 模型  │                      │
│           └──────────────────┘                      │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│           数据存储层 (MySQL + ChromaDB 双存储)         │
│                                                      │
│  ┌────────────────────────┐  ┌────────────────────┐ │
│  │     MySQL 8.0           │  │   ChromaDB          │ │
│  │  contracts              │  │   contracts_chunks  │ │
│  │  contract_installments  │  │   (条款向量+元数据)  │ │
│  │  contract_products      │  │                     │ │
│  │  contract_key_clauses   │  │   contracts_tables  │ │
│  │                         │  │   (表格向量)         │ │
│  └────────────────────────┘  └────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## 工具三层架构

```
大模型层 (Layer 1)          工具路由层 (Layer 2)         数据执行层 (Layer 3)
┌──────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│ query_con_sum    │────▶│ route_query_con_sum   │────▶│ dao_query_amount │
│                  │     │ (格式化 + 汇总聚合)    │     │ (MySQL)          │
│ query_con_count  │────▶│ route_query_con_count │────▶│ dao_query_count  │
│                  │     │ (多维筛选 + 分组)      │     │ (MySQL)          │
│ search_con_text  │────▶│ route_search_con_text │────▶│ dao_search_text  │
│                  │     │ (公司简称匹配+金额汇总) │     │ (MySQL)          │
│ get_con_details  │────▶│ route_get_con_details │────▶│ dao_get_details  │
│                  │     │ (详情聚合)            │     │ (MySQL)          │
│ list_contracts   │────▶│ route_list_contracts  │────▶│ dao_list_        │
│                  │     │ (分页列表)            │     │ contracts(MySQL) │
│ search_vector    │────▶│ route_search_vector   │────▶│ dao_search_vector│
│                  │     │ (语义检索结果格式化)    │     │ (ChromaDB)      │
│ insert_contract  │────▶│ route_insert_contract │────▶│ dao_insert_      │
│                  │     │ (JSON校验+事务写入)    │     │ contract(MySQL)  │
│ delete_contract  │────▶│ route_delete_contract │────▶│ dao_delete_      │
│                  │     │ (MySQL级联+Chroma清理) │     │ contract(双存储)  │
└──────────────────┘     └──────────────────────┘     └──────────────────┘
    LangChain @tool          纯 Python 函数           pymysql + chromadb
```

## 工具清单（8个）

| 工具 | 类型 | 数据源 | 功能 | 典型问法 |
|------|------|--------|------|----------|
| `query_con_sum` | 读 | MySQL | 合同金额查询/汇总 | "合同总金额是多少" |
| `query_con_count` | 读 | MySQL | 合同数量统计 | "分期付款的合同有几份" |
| `search_con_text` | 读 | MySQL | 关键词搜索+公司简称模糊匹配 | "华为公司的合同" / "违约金条款" |
| `get_con_details` | 读 | MySQL | 合同完整详情(含软件+硬件产品) | "CON-001的详细信息" |
| `list_contracts` | 读 | MySQL | 合同列表 | "列出所有合同" |
| `search_vector` | 读 | ChromaDB | **语义向量检索**，按意思搜索条款原文 | "保密协议的保密期限" / "违约金怎么算" |
| `insert_contract` | 写 | MySQL+ChromaDB | 导入合同(事务性多表写入+向量化入库) | 后台批量导入时调用 |
| `delete_contract` | 写 | MySQL+ChromaDB | 删除合同(级联删除+向量同步清理) | 后台管理删除时调用 |

### 核心特性 1：公司简称模糊匹配

`search_con_text` 工具内置智能匹配逻辑，支持用公司简称查询：

```
用户问："华为公司的合同总金额是多少？"
  → search_con_text("华为")
  → 数据库 LIKE 匹配: party_a LIKE '%华为%' OR party_b LIKE '%华为%'
  → 一步返回：完整公司名列表 + 金额汇总 + 合同数量
  → 无需额外工具调用
```

如果 `search_con_text` 无结果（如用户说"鹅厂"），Agent 的 LLM 知识可推理出对应公司名重试。

### 核心特性 2：语义向量检索（ChromaDB）

`search_vector` 工具实现**按意思搜索**，而非简单关键词匹配。典型 ReAct 推理流程：

```
用户: "保密协议的保密期限是多久？"

Agent Thought: 用户问保密期限，需要从合同中查找。
               先用结构化查询看有没有直接数据。

Action: get_con_details("保密协议")
Observation: [{"contract_id":"NDA-001","after_sales_service":null,...}]
             结构化字段没有直接命中保密期限

Agent Thought: 结构化数据未覆盖保密期限字段，
               需要向量检索找相关条款原文。

Action: search_vector("保密协议的保密期限")
Observation: ["第5条 保密期限：本协议保密期限为合同终止后5年...",
              "第6条 违约责任..."]

Agent Thought: 找到了保密期限为5年，综合回答。

Final Answer: 根据保密协议（NDA-001）第5条，
             保密期限为合同终止后5年。
```

## 合同 Embedding 向量化流水线（核心设计）

> ✅ **状态**：代码已实现（Phase 3 完成）。

### 为什么合同需要专用 Embedding？

合同文档不是普通文档，直接按固定 token 数切分 + 通用向量化效果很差。合同有明确的条款结构、大量的金额/日期/百分比，必须做**专项处理**才能实现高精度语义检索。

### 流水线概览

```
合同文本 + 解析JSON
  │
  ├─ 1. 表格检测与提取
  │     ├─ 检测 Word 表格 (python-docx table)
  │     ├─ 检测 PDF 表格 (PyMuPDF + 启发式规则)
  │     └─ 表格 → Markdown(向量检索) + JSON(精确查询) 双写
  │
  ├─ 2. 特殊内容归一化
  │     ├─ 金额归一化 → [AMOUNT:数字CNY]
  │     │    "伍拾万元整（¥500,000）" → 都标记为 [AMOUNT:500000.00CNY]
  │     ├─ 日期归一化 → [DATE:YYYY-MM-DD]
  │     │    "2024年3月15日" / "2024/03/15" → 都标记为 [DATE:2024-03-15]
  │     └─ 百分比归一化 → [PCT:X%]
  │          "百分之三十" / "30%" → 都标记为 [PCT:30%]
  │
  ├─ 3. 语义边界切分（非固定 token 切分！）
  │     ├─ 第一级：条款标题（第X条 / 第X章）
  │     ├─ 第二级：款（1. / 2. / (一) / (二)）
  │     ├─ 第三级：自然段（\n\n）
  │     └─ 兜底：512 token 强制截断
  │
  ├─ 4. 元数据标注（每个 Chunk 携带）
  │     ├─ 文档级：contract_id, party_a, party_b, sign_date, total_amount
  │     ├─ Chunk级：section_title, clause_type, clause_level
  │     ├─ 语义标签：["付款", "金额", "首付款", "时间节点"]
  │     └─ 特殊标记：has_amount, has_date, has_percentage, has_table
  │
  ├─ 5. Embedding 向量化
  │     ├─ 模型：BAAI/bge-base-zh-v1.5（768维，中文法律/合同语义好）
  │     ├─ Query 指令前缀："为这个查询生成表示以用于检索相关合同条款："
  │     └─ 设备：CPU（阿里云2C4G环境）
  │
  ├─ 6. 双 Collection 写入 ChromaDB
  │     ├─ contracts_chunks（条款级向量 + 元数据）
  │     └─ contracts_tables（表格向量，独立 Collection）
  │
  └─ 7. 输出统计
        {chunks: 156, tables: 23, amounts_normalized: 45, dates_normalized: 32}
```

### 语义切分示例

```
原始合同：
  第三条 付款方式
  1. 本合同总金额为人民币伍拾万元整（¥500,000.00）
  2. 首付款：合同签订后7个工作日内，甲方向乙方支付合同总额的30%
  3. 中期款：系统上线验收通过后10个工作日内，支付合同总额的40%
  4. 尾款：试运行期满后30日内，支付合同总额的30%

切分结果（按条款层级，而非固定字数）：
  Chunk 1: "第三条 付款方式"
  Chunk 2: "1. 本合同总金额为人民币伍拾万元整 [AMOUNT:500000.00CNY]"
  Chunk 3: "2. 首付款：合同签订后7个工作日内，支付30% [PCT:30%]"
  Chunk 4: "3. 中期款：系统上线验收通过后10个工作日内，支付40% [PCT:40%]"
  Chunk 5: "4. 尾款：试运行期满后30日内，支付30% [PCT:30%]"
```

### 金额归一化效果

| 原始文本 | 归一化后 |
|----------|----------|
| `合同总金额为人民币伍拾万元整（¥500,000.00）` | `...伍拾万元整（¥500,000.00）[AMOUNT:500000.00CNY]` |
| `合同价款：50万元` | `合同价款：50万元 [AMOUNT:500000.00CNY]` |
| `总价：500,000.00 CNY` | `总价：500,000.00 CNY [AMOUNT:500000.00CNY]` |

> 归一化后，三种不同写法的金额在向量空间中距离更近，检索精度大幅提升。

### 日期归一化效果

| 原始文本 | 归一化后 |
|----------|----------|
| `本合同自2024年3月15日起生效` | `...2024年3月15日起生效 [DATE:2024-03-15]` |
| `签订日期：二〇二四年三月十五日` | `签订日期：二〇二四年三月十五日 [DATE:2024-03-15]` |
| `交付期限：2024/03/15 - 2024/09/20` | `交付期限：2024/03/15-2024/09/20 [DATE:2024-03-15] [DATE:2024-09-20]` |
| `付款时间：合同生效后30个工作日内` | `付款时间：合同生效后30个工作日内 [DURATION:30_working_days]` |

### Embedding 模型选型

| 模型 | 维度 | 大小 | 中文效果 | 选型 |
|------|------|------|----------|------|
| **BAAI/bge-base-zh-v1.5** | 768 | ~400MB | ⭐⭐⭐⭐ | **Demo 默认** |
| BAAI/bge-large-zh-v1.5 | 1024 | ~1.3GB | ⭐⭐⭐⭐⭐ | 生产推荐 |
| BAAI/bge-small-zh-v1.5 | 512 | ~100MB | ⭐⭐⭐ | 轻量备选 |

### ChromaDB 配置

- 持久化路径：`./data/chroma/`
- Embedding 维度：768
- 距离度量：cosine
- 双 Collection：
  - `contracts_chunks` — 合同条款分块（含归一化标记+元数据）
  - `contracts_tables` — 表格 Markdown 文本（独立 Collection）

### 三写流程（上传合同时触发）

```
POST /api/admin/upload
  │
  ├─ 1. 保存原始文件 → ./contracts/
  ├─ 2. 提取文本 + 表格检测
  ├─ 3. LLM 解析为标准化 JSON
  │
  ├─ 4. 【写1】MySQL 事务写入:
  │     contracts + installments + products + key_clauses
  │
  ├─ 5. 【写2】ChromaDB contracts_chunks:
  │     表格处理 → 归一化 → 语义切分 → 元数据标注 → Embedding → 写入
  │
  ├─ 6. 【写3】ChromaDB contracts_tables:
  │     表格 Markdown → Embedding → 写入
  │
  └─ 7. 返回 { mysql_ok, chroma_chunks: N, chroma_tables: N }
```

### 已实现的模块文件

| 文件 | 功能 | 状态 |
|------|------|------|
| `backend/app/embedding_pipeline.py` | Embedding 流水线主控（6步编排） | ✅ 已实现 |
| `backend/app/text_splitter.py` | 合同语义边界切分（按条款层级） | ✅ 已实现 |
| `backend/app/normalizer.py` | 金额/日期/百分比归一化 | ✅ 已实现 |
| `backend/app/table_processor.py` | 表格检测→Markdown+JSON双写 | ✅ 已实现 |
| `backend/app/vector_store.py` | ChromaDB 双 Collection 操作 | ✅ 已实现 |

### 相关配置项

```bash
# .env 中需新增
EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
EMBEDDING_DIM=768
EMBEDDING_DEVICE=cpu
EMBEDDING_BATCH_SIZE=8
CHROMA_PERSIST_DIR=./data/chroma
```

```txt
# requirements.txt 中需新增
chromadb==0.5.0
sentence-transformers==2.7.0
```

## 快速启动

### 1. 启动 MySQL 并建表
```bash
# 方式一：Docker 启动 MySQL
docker run -d --name contract_mysql \
  -e MYSQL_ROOT_PASSWORD=root123 \
  -p 3306:3306 \
  mysql:8.0

# 执行建表 SQL
mysql -u root -proot123 < init_database.sql
```

### 2. 配置环境变量
```bash
cd backend
cp .env.example .env
# 编辑 .env 填写 DASHSCOPE_API_KEY 和 MySQL 配置
```

### 3. 安装依赖
```bash
cd backend
pip install -r requirements.txt
```

### 4. 导入合同
```bash
# 将 Word/PDF 合同放入 contracts/ 目录
python backend/scripts/import_contracts.py --dir ./contracts/
```

### 5. 启动服务
```bash
cd backend
uvicorn app.api_server:app --host 0.0.0.0 --port 8000
```

### Docker 一键部署
```bash
docker-compose up -d
```

## 项目结构

```
contract_agent/
├── init_database.sql                    # 数据库建表 SQL
├── backend/
│   ├── app/
│   │   ├── api_server.py               # FastAPI 入口 (v4.2)
│   │   ├── admin_auth.py               # JWT 认证
│   │   ├── config.py                   # 配置 (LLM + MySQL + Embedding)
│   │   ├── document_reader.py          # Word/PDF 读取 + 表格检测
│   │   ├── embedding_pipeline.py       # Embedding 流水线主控
│   │   ├── text_splitter.py            # 合同语义边界切分
│   │   ├── normalizer.py               # 金额/日期/百分比归一化
│   │   ├── table_processor.py          # 表格→MD+JSON双写
│   │   ├── vector_store.py             # ChromaDB 双Collection操作
│   │   ├── db/
│   │   │   └── mysql_client.py         # MySQL 连接池 + 建表 DDL
│   │   ├── agents/
│   │   │   ├── tools.py                # Layer 1: 大模型层 (8个Tool)
│   │   │   ├── tool_router.py          # Layer 2: 工具路由层
│   │   │   ├── data_layer.py           # Layer 3: 数据执行层 (DAO)
│   │   │   ├── contract_parser_agent.py   # Agent1: 合同解析
│   │   │   └── contract_query_agent.py    # Agent2: 智能问数(ReAct)
│   │   └── schemas/
│   │       └── contract_schema.py      # 标准化 JSON Schema (含 HardwareProduct)
│   ├── data/
│   │   └── chroma/                     # ChromaDB 持久化目录
│   ├── scripts/
│   │   └── import_contracts.py         # 批量导入 + 自动解析 + 三写入库
│   └── requirements.txt
├── contracts/                           # 合同原始文件存放目录
├── frontend/                            # Vue3 + Vant4 移动端
├── docker-compose.yml
├── Dockerfile
├── nginx.conf
├── start.sh
└── README.md
```

## 数据库表结构

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `contracts` | 合同主表 | contract_id, party_a/b, total_amount, sign_date, full_text 等 30+ 字段 |
| `contract_installments` | 分期付款明细 | stage, ratio, amount, trigger_desc (FK→contracts CASCADE) |
| `contract_products` | 产品表(软件+硬件) | product_type(software/hardware), name, version/model, quantity, unit |
| `contract_key_clauses` | 关键条款 | clause_type, summary (FK→contracts CASCADE) |

> 建表 SQL 见 `init_database.sql`，引擎 InnoDB，字符集 utf8mb4。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Agent 框架 | LangChain ReAct Agent | 工具调用链 + ReAct 推理 |
| LLM | 阿里云 DashScope (通义千问) | 中文能力强，API 调用方便 |
| Web 框架 | FastAPI | 高性能异步，SSE 流式输出 |
| 结构化存储 | MySQL 8.0 | 金额汇总/统计/精确查询 |
| 向量存储 | ChromaDB | 语义检索，轻量级本地部署 |
| Embedding | BAAI/bge-base-zh-v1.5 | 768维，中文法律/合同语义效果好 |
| 文本分块 | LangChain TextSplitter | 按合同条款层级语义切分 |
| 文档解析 | python-docx + PyMuPDF | Word/PDF 文本提取 + 表格检测 |
| 前端 | Vue3 + Vant4 | 移动端优先 UI |
| 部署 | Docker Compose | 一键部署 MySQL + 后端 + 前端 |

## 开发阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 文档读取 + LLM 合同解析 Agent + JSON Schema | ✅ 已完成 |
| Phase 2 | MySQL 建表 + DAO 数据执行层 + 3层工具架构（7个Tool） | ✅ 已完成 |
| **Phase 3** | **Embedding 流水线 + ChromaDB 向量存储 + search_vector 工具** | ✅ 已完成 |
| Phase 4 | LangChain ReAct 问数 Agent + 8个Tools（含向量检索） | ✅ 已完成 |
| Phase 5 | FastAPI 后端（对话+管理接口+三写流水线） | ✅ 已完成 |
| Phase 6 | Vue3 + Vant4 移动端前端 | ✅ 已完成 |
| Phase 7 | 合同导入 + 解析验证 + 问答测试 | ⬜ 待测试 |
| Phase 8 | 阿里云环境部署 + Nginx 配置 + 联调 | ⬜ 待部署 |

## v4.2 更新说明

- **工具扩展**：从 5 个扩展到 **7 个**（当前已实现），设计目标 **8 个**（含 `search_vector` 待 Phase 3 实现）
- **产品表重构**：`contract_products` 合并软件+硬件，通过 `product_type` 字段区分
- **硬件产品支持**：合同解析 Agent 新增硬件产品识别（名称/型号/数量/单位）
- **公司简称匹配**：`search_con_text` 内置 LIKE 模糊匹配，支持"华为"→"华为技术有限公司"等简称查全称
- **独立建表 SQL**：新增 `init_database.sql`，可脱离 Python 直接建表
- **README 补全**：新增 ChromaDB / Embedding 向量化流水线完整设计文档
