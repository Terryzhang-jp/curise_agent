"""
Error utilities — structured error detection, translation, and logging.

Parses tool error strings into structured metadata for display-layer messages.
Engine-side (agent_parts) messages are NOT affected — LLM still sees raw strings.
"""

from __future__ import annotations

import logging
import re

error_logger = logging.getLogger("agent.tool_errors")

# Common Python exception types → user-friendly Chinese translations
_ERROR_TRANSLATIONS: dict[str, str] = {
    "BadZipFile": "文件格式无效，不是有效的 Excel 文件",
    "InvalidFileException": "文件格式无效，不是有效的 Excel 文件",
    "ConnectionError": "网络连接失败",
    "TimeoutError": "请求超时",
    "PermissionError": "没有权限访问该资源",
    "FileNotFoundError": "文件未找到",
    "ValueError": "数据格式错误",
    "KeyError": "缺少必要的数据字段",
    "JSONDecodeError": "数据解析失败",
    "UnicodeDecodeError": "文件编码格式不支持",
    "OperationalError": "数据库操作失败",
    "IntegrityError": "数据完整性冲突",
    "ResourceExhausted": "API 调用配额已用完，请稍后重试",
    "DeadlineExceeded": "请求超时",
    "InvalidArgument": "请求参数无效",
}

# Recovery hints by exception type or tool name
_RECOVERY_HINTS: dict[str, str] = {
    "BadZipFile": "请确认上传的是 .xlsx 或 .xls 格式的 Excel 文件",
    "InvalidFileException": "请确认上传的是 .xlsx 或 .xls 格式的 Excel 文件",
    "ConnectionError": "请检查网络连接后重试",
    "TimeoutError": "请稍后重试，或尝试减少数据量",
    "PermissionError": "请联系管理员检查权限设置",
    "FileNotFoundError": "请确认文件路径正确",
    "UnicodeDecodeError": "请尝试将文件另存为 UTF-8 编码",
    "ResourceExhausted": "请等待几分钟后重试",
    "DeadlineExceeded": "请稍后重试",
    # Tool-specific hints
    "parse_price_list": "请确认上传的 Excel 文件格式正确，包含产品信息",
    "query_db": "请检查 SQL 语法是否正确",
    "execute_product_upload": "请确认产品数据完整后重试",
}

# Regex to extract "ExcType: message" from "Error: ExcType: message"
_EXC_PATTERN = re.compile(r"^Error:\s*(\w+(?:Error|Exception|Fault|Warning|Exhausted|Exceeded|Argument)?):\s*(.*)", re.DOTALL)


def parse_tool_error(result_text: str, tool_name: str = "") -> dict:
    """Parse a tool error string into structured metadata.

    Args:
        result_text: The raw error string (starts with "Error:")
        tool_name: Name of the tool that produced the error

    Returns:
        Dict with: severity, category, user_message, technical_detail,
                   tool_name, recovery_hint, exc_type
    """
    # Try to extract exception type and message
    match = _EXC_PATTERN.match(result_text)

    if match:
        exc_type = match.group(1)
        exc_msg = match.group(2).strip()
        category = "exception"

        # Translate to user-friendly message
        user_message = _ERROR_TRANSLATIONS.get(exc_type)
        if user_message is None:
            # If the exception message contains Chinese, use it directly
            if _has_chinese(exc_msg):
                user_message = exc_msg
            else:
                user_message = f"操作失败: {exc_msg[:200]}"

        severity = "error"
        technical_detail = result_text

        # Recovery hint: prefer exc_type match, then tool_name match
        recovery_hint = _RECOVERY_HINTS.get(exc_type) or _RECOVERY_HINTS.get(tool_name, "")
    else:
        # No recognized exception pattern — extract message after "Error: "
        msg = result_text[len("Error:"):].strip()
        exc_type = ""
        category = "tool_error"

        if _has_chinese(msg):
            # Tool returned a Chinese error message (friendly, intentional)
            user_message = msg
            severity = "warning"
            technical_detail = ""
        else:
            user_message = f"操作失败: {msg[:200]}"
            severity = "error"
            technical_detail = result_text

        recovery_hint = _RECOVERY_HINTS.get(tool_name, "")

    return {
        "severity": severity,
        "category": category,
        "user_message": user_message,
        "technical_detail": technical_detail,
        "tool_name": tool_name,
        "recovery_hint": recovery_hint,
        "exc_type": exc_type,
    }


def log_tool_error(session_id: str, tool_name: str, error_meta: dict):
    """Log a structured tool error for observability."""
    error_logger.warning(
        "tool_error | session=%s | tool=%s | severity=%s | category=%s | detail=%s",
        session_id, tool_name,
        error_meta.get("severity"), error_meta.get("category"),
        (error_meta.get("technical_detail") or "")[:500],
    )


def _has_chinese(text: str) -> bool:
    """Check if text contains any Chinese characters."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))
