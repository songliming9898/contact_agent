"""
标准化合同 JSON Schema 定义
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class ContractSubject(BaseModel):
    """合同主体"""
    party_a: Optional[str] = Field(None, description="甲方名称")
    party_b: Optional[str] = Field(None, description="乙方名称")
    project_name: Optional[str] = Field(None, description="项目/合同名称")


class ContractDate(BaseModel):
    """合同日期"""
    sign_date: Optional[str] = Field(None, description="签订日期 YYYY-MM-DD")
    start_date: Optional[str] = Field(None, description="开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="结束日期 YYYY-MM-DD")
    contract_period: Optional[str] = Field(None, description="合同期限描述")


class ContractAmount(BaseModel):
    """合同金额"""
    total_amount: Optional[float] = Field(None, description="合同总金额（元）")
    currency: Optional[str] = Field("CNY", description="货币类型")


class SoftwareProduct(BaseModel):
    """软件产品"""
    name: Optional[str] = Field(None, description="软件名称")
    version: Optional[str] = Field(None, description="版本号")
    license_type: Optional[str] = Field(None, description="授权类型（永久授权/年度订阅等）")


class HardwareProduct(BaseModel):
    """硬件产品"""
    name: Optional[str] = Field(None, description="硬件名称")
    model: Optional[str] = Field(None, description="型号规格")
    quantity: Optional[int] = Field(None, description="采购数量")
    unit: Optional[str] = Field(None, description="单位（台/套/个等）")


class Installment(BaseModel):
    """付款分期"""
    stage: Optional[str] = Field(None, description="付款阶段名称")
    ratio: Optional[str] = Field(None, description="付款比例")
    amount: Optional[float] = Field(None, description="付款金额")
    trigger: Optional[str] = Field(None, description="付款触发条件")


class PaymentTerms(BaseModel):
    """付款条款"""
    payment_method: Optional[str] = Field(None, description="付款方式：一次性付款/分期付款/按里程碑付款")
    installments: List[Installment] = Field(default_factory=list, description="分期明细")
    final_payment_amount: Optional[float] = Field(None, description="尾款金额")
    final_payment_trigger: Optional[str] = Field(None, description="尾款支付条件")


class TrialPeriod(BaseModel):
    """试用期"""
    has_trial: bool = Field(False, description="是否有试用期")
    duration_days: Optional[int] = Field(None, description="试用天数")
    start_trigger: Optional[str] = Field(None, description="试用期开始条件")


class AfterSalesService(BaseModel):
    """售后服务"""
    has_service: bool = Field(False, description="是否有售后服务")
    duration_months: Optional[int] = Field(None, description="服务月数")
    service_content: Optional[str] = Field(None, description="服务内容")
    start_trigger: Optional[str] = Field(None, description="服务开始条件")


class KeyClause(BaseModel):
    """关键条款"""
    type: str = Field(..., description="条款类型（验收标准/违约责任/知识产权等）")
    summary: str = Field(..., description="条款摘要")


class RawMetadata(BaseModel):
    """原始文件元数据"""
    file_type: Optional[str] = Field(None, description="文件类型 docx/pdf")
    page_count: Optional[int] = Field(None, description="页数")
    parse_time: Optional[str] = Field(None, description="解析时间 ISO格式")


class ContractJson(BaseModel):
    """标准化合同 JSON 结构"""
    contract_id: str = Field(..., description="合同唯一ID")
    file_name: str = Field(..., description="原始文件名")
    contract_subject: ContractSubject = Field(default_factory=ContractSubject)
    contract_date: ContractDate = Field(default_factory=ContractDate)
    contract_amount: ContractAmount = Field(default_factory=ContractAmount)
    software_products: List[SoftwareProduct] = Field(default_factory=list)
    hardware_products: List[HardwareProduct] = Field(default_factory=list)
    payment_terms: PaymentTerms = Field(default_factory=PaymentTerms)
    trial_period: TrialPeriod = Field(default_factory=TrialPeriod)
    after_sales_service: AfterSalesService = Field(default_factory=AfterSalesService)
    key_clauses: List[KeyClause] = Field(default_factory=list)
    raw_metadata: RawMetadata = Field(default_factory=RawMetadata)


# ==================== LangChain Function Calling Schema ====================

CONTRACT_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "contract_subject": {
            "type": "object",
            "description": "合同主体信息",
            "properties": {
                "party_a": {"type": "string", "description": "甲方名称"},
                "party_b": {"type": "string", "description": "乙方名称"},
                "project_name": {"type": "string", "description": "项目/合同名称"}
            }
        },
        "contract_date": {
            "type": "object",
            "description": "合同日期信息",
            "properties": {
                "sign_date": {"type": "string", "description": "签订日期，格式YYYY-MM-DD"},
                "start_date": {"type": "string", "description": "开始日期，格式YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "结束日期，格式YYYY-MM-DD"},
                "contract_period": {"type": "string", "description": "合同期限描述"}
            }
        },
        "contract_amount": {
            "type": "object",
            "description": "合同金额信息",
            "properties": {
                "total_amount": {"type": "number", "description": "合同总金额，单位：人民币元"},
                "currency": {"type": "string", "description": "货币类型，默认CNY"}
            }
        },
        "software_products": {
            "type": "array",
            "description": "采购软件产品清单",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "软件名称"},
                    "version": {"type": "string", "description": "版本号"},
                    "license_type": {"type": "string", "description": "授权类型：永久授权/年度订阅/SaaS订阅/其他"}
                }
            }
        },
        "hardware_products": {
            "type": "array",
            "description": "采购硬件产品清单",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "硬件名称（如应用服务器/存储阵列）"},
                    "model": {"type": "string", "description": "型号规格"},
                    "quantity": {"type": "integer", "description": "采购数量"},
                    "unit": {"type": "string", "description": "单位（台/套/个等）"}
                }
            }
        },
        "payment_terms": {
            "type": "object",
            "description": "付款条款",
            "properties": {
                "payment_method": {"type": "string", "description": "付款方式：一次性付款/分期付款/按里程碑付款"},
                "installments": {
                    "type": "array",
                    "description": "分期付款明细",
                    "items": {
                        "type": "object",
                        "properties": {
                            "stage": {"type": "string", "description": "付款阶段（首付款/中期款/尾款等）"},
                            "ratio": {"type": "string", "description": "付款比例"},
                            "amount": {"type": "number", "description": "付款金额"},
                            "trigger": {"type": "string", "description": "付款触发条件"}
                        }
                    }
                },
                "final_payment_amount": {"type": "number", "description": "尾款金额"},
                "final_payment_trigger": {"type": "string", "description": "尾款支付触发条件"}
            }
        },
        "trial_period": {
            "type": "object",
            "description": "试用期条款",
            "properties": {
                "has_trial": {"type": "boolean", "description": "是否包含试用期"},
                "duration_days": {"type": "integer", "description": "试用天数"},
                "start_trigger": {"type": "string", "description": "试用期开始条件"}
            }
        },
        "after_sales_service": {
            "type": "object",
            "description": "售后服务条款",
            "properties": {
                "has_service": {"type": "boolean", "description": "是否包含售后服务"},
                "duration_months": {"type": "integer", "description": "服务月数"},
                "service_content": {"type": "string", "description": "服务内容描述"},
                "start_trigger": {"type": "string", "description": "服务开始条件"}
            }
        },
        "key_clauses": {
            "type": "array",
            "description": "关键条款摘要",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "条款类型"},
                    "summary": {"type": "string", "description": "条款摘要"}
                }
            }
        }
    },
    "required": ["contract_subject", "contract_amount"]
}
