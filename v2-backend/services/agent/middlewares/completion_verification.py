"""
Completion Verification Middleware — Deterministic anti-hallucination guardrail.

Prevents the Gemini "execution hallucination" bug where the model claims
to have generated a file or completed an action without actually calling
the corresponding tool.

This is a known Gemini issue:
- Google AI Forum: "Critical 'Execution Hallucination' in Gemini API"
- GitHub googleapis/python-genai #813
- arXiv 2603.10060: "Tool Receipts, Not Zero-Knowledge Proofs"

Architecture: Neurosymbolic guardrail (AWS pattern)
- The LLM proposes a response (neural)
- Deterministic code verifies claims against tool execution log (symbolic)
- Cannot be bypassed by prompt injection or model hallucination

Runs in the after_agent hook — checks the final answer before it reaches the user.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from services.agent.hooks import Middleware

logger = logging.getLogger(__name__)


# ============================================================
# Claim patterns: what the agent might say when fabricating
# ============================================================

# Maps claim patterns to the tool(s) that MUST have been called
_CLAIM_TOOL_MAP: list[tuple[re.Pattern, list[str], str]] = [
    # File generation claims → must have called generate_inquiries
    (
        re.compile(
            r"(询价单已生成|已生成.*询价|inquiry.*生成|生成.*xlsx|已为您生成|Excel.*已生成|"
            r"文件已生成|已生成.*文件|generated.*inquiry|file.*generated)",
            re.IGNORECASE,
        ),
        ["generate_inquiries"],
        "询价单生成",
    ),
    # Upload completion claims → must have called execute_upload
    (
        re.compile(
            r"(上传完成|数据已上传|已成功上传|upload.*completed|已导入.*产品)",
            re.IGNORECASE,
        ),
        ["execute_upload"],
        "数据上传",
    ),
    # Fulfillment update claims → must have called update_order_fulfillment
    (
        re.compile(
            r"(状态已更新|已更新.*状态|fulfillment.*updated|订单.*已.*更新)",
            re.IGNORECASE,
        ),
        ["update_order_fulfillment", "record_delivery_receipt"],
        "订单状态更新",
    ),
]


class CompletionVerificationMiddleware(Middleware):
    """Verify that agent claims of completion are backed by actual tool calls.

    Runs in after_agent: scans the final answer for completion claims,
    then cross-references against the actual tool call log in step_log.
    If a claim is made without corresponding tool execution, the claim
    is replaced with an honest statement.
    """

    def after_agent(self, final_answer: str, ctx: Any) -> str:
        if not final_answer:
            return final_answer

        # Get the tool execution log from the engine
        # The engine stores this in step_log on the agent instance,
        # but we can access the tool call history via ctx
        executed_tools = _get_executed_tools(ctx)

        corrections = []
        for pattern, required_tools, claim_label in _CLAIM_TOOL_MAP:
            if pattern.search(final_answer):
                # Check if ANY of the required tools were actually called
                tool_was_called = any(t in executed_tools for t in required_tools)
                if not tool_was_called:
                    logger.warning(
                        "CompletionVerification: agent claimed '%s' but tools %s were never called",
                        claim_label, required_tools,
                    )
                    corrections.append(claim_label)

        if not corrections:
            return final_answer  # All claims are backed by tool calls ✅

        # Replace fabricated claims with honest correction
        correction_text = (
            "\n\n---\n"
            "⚠️ **修正**: 上述回答中关于「" + "、".join(corrections) + "」的内容不准确。"
            "相关操作实际上**尚未执行**。"
            "请告诉我是否需要现在执行，我会调用相应工具完成操作。"
        )

        logger.info("CompletionVerification: appended correction for %s", corrections)
        return final_answer + correction_text


def _get_executed_tools(ctx: Any) -> set[str]:
    """Extract the set of tool names that were actually executed in this session.

    Looks at the conversation log stored on ctx by the engine.
    """
    executed = set()

    # Method 1: Check _conversation_log for tool call entries
    conv_log = getattr(ctx, '_conversation_log', '') or ''
    for match in re.finditer(r'工具\[(\w+)\]:', conv_log):
        executed.add(match.group(1))

    # Method 2: Check step_log if available (set by engine)
    step_log = getattr(ctx, '_step_log', None) or []
    for step in step_log:
        if step.get('type') == 'tool_call':
            tool_name = step.get('tool_name', '')
            if tool_name:
                executed.add(tool_name)
        elif step.get('type') == 'tool_result':
            tool_name = step.get('tool_name', '')
            if tool_name and not step.get('content', '').startswith('Error:'):
                executed.add(tool_name)

    return executed
