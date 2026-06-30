"""
Agent1: 合同解析 Agent — 重构版
使用 LLM Function Calling 将合同文本提取为标准化 JSON → 写入 MySQL
"""
import json
import re
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatTongyi

from ..config import DASHSCOPE_API_KEY, LLM_MODEL
from ..schemas.contract_schema import CONTRACT_LLM_SCHEMA

logger = logging.getLogger(__name__)

CONTRACT_PARSER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一个专业的软件公司合同解析专家。请从以下合同文本中提取关键信息，严格按照指定的 JSON Schema 返回结果。

**解析要求**：
1. **合同主体（contract_subject）**：必须从合同正文中提取甲方(party_a)和乙方(party_b)的全称。通常在合同开头有"甲方：XXX""乙方：XXX"或落款处有"甲方（盖章）：XXX"等字样。
2. 合同金额统一为人民币"元"单位（如合同写"50万元"，则 total_amount 为 500000.00）
3. 日期格式统一为 YYYY-MM-DD
4. 如果合同中没有某个字段，该字段填 null，不要编造
5. 付款方式识别：一次性付款 / 分期付款 / 按里程碑付款
6. 特别关注：尾款金额、尾款支付条件、试用期条款、售后服务条款
7. 提取关键条款摘要（验收标准、违约责任、知识产权等）
8. software_products 识别合同中涉及的软件产品名称和版本
9. hardware_products 识别合同中涉及的硬件产品（名称/型号/数量/单位）

**合同文本**：
{contract_text}

请严格按 JSON Schema 返回解析结果。"""),
])


class ContractParserAgent:
    """
    合同解析 Agent

    功能：Word/PDF 原始文本 → LLM 提取 → 标准化 JSON → MySQL
    """

    def __init__(self):
        self.llm = ChatTongyi(
            model=LLM_MODEL,
            dashscope_api_key=DASHSCOPE_API_KEY,
            temperature=0.1,
        )

    def parse(
        self,
        full_text: str,
        file_name: str,
        file_type: str,
        page_count: int = 0,
    ) -> Dict[str, Any]:
        """
        解析合同文本为标准化 JSON

        Args:
            full_text: 合同全文
            file_name: 原始文件名
            file_type: 文件类型 (docx/pdf)
            page_count: 页数

        Returns:
            标准化合同 JSON（含 _full_text 用于入库）
        """
        logger.info(f"[ContractParser] 开始解析: {file_name}")
        t_start = time.time()

        # 文本预处理
        MAX_TEXT_LENGTH = 25000
        if len(full_text) > MAX_TEXT_LENGTH:
            logger.warning(f"[ContractParser] 文本过长 ({len(full_text)} 字符)，截取前 {MAX_TEXT_LENGTH} 字符")
            text_for_llm = full_text[:MAX_TEXT_LENGTH]
        else:
            text_for_llm = full_text

        try:
            messages = CONTRACT_PARSER_PROMPT.format_messages(contract_text=text_for_llm)
            response = self.llm.invoke(messages)
            raw_output = response.content

            parsed_json = self._extract_json(raw_output)

            contract_id = self._generate_contract_id(file_name)
            parsed_json["contract_id"] = contract_id
            parsed_json["file_name"] = file_name
            parsed_json["raw_metadata"] = {
                "file_type": file_type,
                "page_count": page_count,
                "parse_time": datetime.now().isoformat(),
            }

            # 附带全文，用于入库
            parsed_json["_full_text"] = full_text

            parsed_json = self._validate_and_fix(parsed_json)

            # Fallback: 如果 LLM 没提取到甲方/乙方，从正文中正则提取
            self._extract_parties_from_text(parsed_json, full_text, file_name)

            elapsed = time.time() - t_start
            logger.info(f"[ContractParser] 解析完成: {file_name} -> {contract_id} (耗时 {elapsed:.2f}s)")

            return parsed_json

        except Exception as e:
            logger.error(f"[ContractParser] 解析失败 {file_name}: {e}")
            raise

    def _extract_json(self, raw_output: str) -> Dict[str, Any]:
        """从 LLM 输出中提取 JSON"""
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError:
            pass

        json_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_output)
        if json_block:
            try:
                return json.loads(json_block.group(1))
            except json.JSONDecodeError:
                pass

        brace_match = re.search(r'\{[\s\S]*\}', raw_output)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法从 LLM 输出中提取有效 JSON: {raw_output[:500]}")

    def _generate_contract_id(self, file_name: str) -> str:
        """生成合同唯一 ID"""
        match = re.search(r'(CON|NDA|CONTRACT)[-_]?\d+', file_name, re.IGNORECASE)
        if match:
            return match.group(0).upper()

        import hashlib
        name_hash = hashlib.md5(file_name.encode()).hexdigest()[:8].upper()
        return f"CON-{name_hash}"

    def _extract_parties_from_text(self, data: Dict[str, Any], full_text: str, file_name: str):
        """如果 LLM 未提取到甲方/乙方，从合同正文和文件名中正则提取"""
        subject = data.get("contract_subject", {})
        if not isinstance(subject, dict):
            subject = {}
            data["contract_subject"] = subject

        # 如果 party_a 为空，从正文提取
        if not subject.get("party_a"):
            # 匹配 "甲方：XXX" 或 "甲方（盖章）：XXX"
            m = re.search(r'甲方[（(]?盖章[）)]?\s*[：:]\s*([^\s\n]+)', full_text)
            if not m:
                m = re.search(r'甲方\s*[：:]\s*([^\s\n]+)', full_text)
            if m:
                subject["party_a"] = m.group(1).strip()
                logger.info(f"[ContractParser] 从正文提取甲方: {subject['party_a']}")

        # 如果 party_b 为空，从正文提取
        if not subject.get("party_b"):
            m = re.search(r'乙方[（(]?盖章[）)]?\s*[：:]\s*([^\s\n]+)', full_text)
            if not m:
                m = re.search(r'乙方\s*[：:]\s*([^\s\n]+)', full_text)
            if m:
                subject["party_b"] = m.group(1).strip()
                logger.info(f"[ContractParser] 从正文提取乙方: {subject['party_b']}")

        # 如果正文也没提取到，从文件名提取（文件名格式: 甲方名_合同名_合同号.docx）
        if not subject.get("party_a"):
            parts = file_name.replace('.docx', '').replace('.pdf', '').split('_')
            if len(parts) >= 1:
                subject["party_a"] = parts[0]
                logger.info(f"[ContractParser] 从文件名提取甲方: {subject['party_a']}")

    def _validate_and_fix(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """校验和修复 JSON 数据"""
        # 确保 dict 类型字段
        dict_fields = [
            "contract_subject", "contract_date", "contract_amount",
            "payment_terms", "trial_period", "after_sales_service",
        ]
        for field in dict_fields:
            if field not in data or not isinstance(data[field], dict):
                data[field] = {}

        # 确保 list 类型字段
        list_fields = ["software_products", "hardware_products", "key_clauses"]
        for field in list_fields:
            if field not in data or not isinstance(data[field], list):
                data[field] = []

        # 试用期默认值
        trial = data.get("trial_period", {})
        if not isinstance(trial, dict):
            trial = {}
            data["trial_period"] = trial
        trial["has_trial"] = bool(trial.get("has_trial", False))

        # 售后服务默认值
        service = data.get("after_sales_service", {})
        if not isinstance(service, dict):
            service = {}
            data["after_sales_service"] = service
        service["has_service"] = bool(service.get("has_service", False))

        # 金额转换
        amount = data.get("contract_amount", {})
        if isinstance(amount, dict) and amount.get("total_amount"):
            try:
                amount["total_amount"] = float(amount["total_amount"])
            except (ValueError, TypeError):
                amount["total_amount"] = None

        # 付款分期
        payment = data.get("payment_terms", {})
        if isinstance(payment, dict) and not isinstance(payment.get("installments"), list):
            payment["installments"] = []

        return data


# 全局单例
contract_parser = ContractParserAgent()
