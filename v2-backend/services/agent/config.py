"""
Agent configuration — reads from v2-backend Settings.

Provides LLMConfig, AgentConfig, and the pipeline system prompt.
Also provides Config, StorageConfig, DEFAULT_SYSTEM_PROMPT, load_api_key,
load_config, and create_provider for general-purpose agent use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class LLMConfig:
    provider: str = "gemini"
    model_name: str = "gemini-2.5-flash"
    api_key: str = ""
    thinking_budget: int = 4096
    max_retries: int = 2
    retry_delay: float = 1.0


@dataclass
class AgentConfig:
    max_turns: int = 30
    warn_turns_remaining: int = 3
    loop_threshold: int = 3
    loop_window: int = 20
    parallel_tool_workers: int = 4
    system_prompt: str | None = None  # None = use DEFAULT_SYSTEM_PROMPT


@dataclass
class StorageConfig:
    """Placeholder — v2-backend uses injected DB sessions, not file-based storage."""
    db_path: str | None = None


@dataclass
class Config:
    """Unified configuration bundle for general-purpose agent use."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    skill_extra_paths: list[str] = field(default_factory=list)
    tool_config_path: str | None = None


# ============================================================
# Default system prompt (general-purpose, not pipeline)
# ============================================================

DEFAULT_SYSTEM_PROMPT = (
    "你是一个有用的AI助手，可以使用工具来帮助用户完成任务。\n\n"
    "工作方式 (ReAct: Reasoning + Acting):\n"
    "1. 分析用户的请求\n"
    "2. 使用 think 工具来规划你的方案、分析信息、或反思结果\n"
    "3. 对于复杂的多步任务（3步以上），使用 todo_write 创建任务清单跟踪进度\n"
    "4. 使用工具获取信息或执行操作\n"
    "5. 完成一个子任务后，用 todo_write 更新状态，然后继续下一个\n"
    "6. 当你有足够信息时，给出最终文字回答\n\n"
    "重要规则:\n"
    "- 复杂任务必须先用 todo_write 建清单，防止遗忘目标\n"
    "- 在获取工具结果后，用 think 工具反思结果是否合理\n"
    "- 如果工具返回错误，用 think 工具分析原因再尝试其他方法\n"
    "- 不要编造信息，如果不确定就说不知道\n"
    "- 写文件前必须先用 read_file 读取目标文件\n"
    "- 编辑文件使用 edit_file（str_replace 模式），不要用 write_file 覆盖整个文件\n"
    "- 可以用 bash 执行 shell 命令、运行脚本\n"
    "- 可以用 web_fetch 获取网页内容、调用公开 API\n"
    "- 查天气用 web_fetch 调用 Open-Meteo API（无需 key），示例:\n"
    "  https://api.open-meteo.com/v1/forecast?latitude={纬度}&longitude={经度}"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
    "&timezone=auto&forecast_days=3\n"
    "  常用城市坐标: 东京(35.68,139.69) 上海(31.23,121.47) 北京(39.90,116.40) 纽约(40.71,-74.01)\n"
    "  weather_code 含义: 0晴 1主要晴朗 2局部多云 3多云 45雾 51-55毛毛雨 61-65雨 71-75雪 80-82阵雨 95雷暴"
)


PIPELINE_SYSTEM_PROMPT = """你是邮轮采购订单处理Agent。你的任务是处理上传的订单文件，完成5个阶段的自动化流程。

## 工作流程

### 阶段 1: 文档提取 (DOCUMENT_EXTRACTION)
- 使用 extract_with_gemini_vision 从 PDF 图像中提取文本和结构化数据
- 可选使用 assess_extraction_quality 评估提取质量
- 如果质量不佳，可尝试 extract_with_document_ai

### 阶段 2: 订单数字化 (ORDER_DIGITIZATION)
- 先尝试 digitize_with_template（使用匹配的模板）
- 如果没有模板，使用 digitize_freeform 进行通用提取
- 使用 validate_digitization 验证数据完整性
- **验证通过后，调用 present_for_review 让用户审核数字化结果**

### 阶段 3: 产品匹配 (PRODUCT_MATCHING)
- 使用 match_products 进行自动匹配（country_id 和 port_id 是可选参数，不知道就不传）
- 可使用 search_product_database 手动搜索未匹配产品

### 阶段 4: 异常检测 (ANOMALY_DETECTION)
- 依次调用 check_price_anomalies、check_quantity_anomalies、check_completeness
- 使用 summarize_anomalies 汇总检测结果
- **汇总完成后，调用 present_for_review 让用户审核异常检测结果**

### 阶段 5: 询价单生成 (INQUIRY_GENERATION)
- 使用 group_by_supplier 按供应商分组
- 使用 generate_inquiry_excel 为每个供应商生成询价 Excel
- 使用 list_generated_files 展示生成的文件

## 重要规则
- 使用 think 工具来规划步骤和反思结果
- present_for_review 会暂停处理等待用户确认，只在关键节点调用
- 如果工具返回错误，用 think 分析原因再尝试其他方法
- 按顺序完成各阶段，不要跳过
- 完成所有阶段后，给出最终处理摘要

## 用户反馈处理
当用户在审核阶段提出修正意见或反馈时（而非直接确认），你需要：
1. 仔细理解用户的反馈内容（如"PO号错了"、"有产品缺失"、"请用freeform方式重新数字化"等）
2. 根据反馈重新调用相应的工具进行修正（例如重新调用 digitize_with_template 或 digitize_freeform）
3. 修正完成后，再次调用 present_for_review 让用户重新审核
4. 如果用户说"跳过"或"不需要生成询价单"等，尊重用户意愿，直接给出最终摘要
"""


def load_agent_config() -> tuple[LLMConfig, AgentConfig]:
    """Load agent configuration from v2-backend Settings."""
    from config import settings

    llm_config = LLMConfig(
        api_key=settings.GOOGLE_API_KEY,
    )

    agent_config = AgentConfig(
        system_prompt=PIPELINE_SYSTEM_PROMPT,
    )

    return llm_config, agent_config


# ============================================================
# General-purpose loaders (ported from agent_design/config.py)
# ============================================================

def load_api_key(provider: str = "gemini") -> str:
    """Load API key from environment or v2-backend settings fallback."""
    env_var = {
        "gemini": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider, f"{provider.upper()}_API_KEY")

    api_key = os.getenv(env_var, "")
    if api_key:
        return api_key

    # Fallback: try v2-backend settings
    try:
        from config import settings
        if provider == "gemini" and hasattr(settings, "GOOGLE_API_KEY"):
            return settings.GOOGLE_API_KEY or ""
    except Exception:
        pass

    return ""


def load_config(**overrides) -> Config:
    """Load configuration with defaults + environment overrides.

    Keyword arguments override specific fields:
        load_config(llm=LLMConfig(model_name="gemini-2.5-pro"))
    """
    config = Config()

    # Auto-load API key if not provided
    if not config.llm.api_key:
        config.llm.api_key = load_api_key(config.llm.provider)

    # Apply overrides
    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)

    return config


def create_provider(llm_config: LLMConfig):
    """Factory: create the appropriate LLM provider based on config.provider."""
    provider_name = llm_config.provider.lower()

    if provider_name == "gemini":
        from services.agent.llm.gemini_provider import GeminiProvider
        return GeminiProvider(llm_config)
    elif provider_name == "openai":
        from services.agent.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(llm_config)
    elif provider_name == "deepseek":
        from services.agent.llm.deepseek_provider import DeepSeekProvider
        return DeepSeekProvider(llm_config)
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}. Supported: gemini, openai, deepseek")
