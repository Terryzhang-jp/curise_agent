"""utility 组工具 — calculate + get_current_time"""

from datetime import datetime, timezone


def register(registry, ctx=None):
    """注册 utility 组工具"""

    @registry.tool(
        description="计算数学表达式。支持加减乘除、幂运算等。例如 '17.5 * 23.8' 或 '2 ** 10'",
        parameters={
            "expression": {
                "type": "STRING",
                "description": "要计算的数学表达式",
            }
        },
        group="utility",
    )
    def calculate(expression: str) -> str:
        """安全地计算数学表达式"""
        allowed = set("0123456789+-*/.() %")
        if not all(c in allowed for c in expression.replace(" ", "")):
            return f"Error: expression contains disallowed characters: {expression}"
        try:
            result = eval(expression)
            return f"{expression} = {result}"
        except Exception as e:
            return f"Error: calculation failed: {e}"

    @registry.tool(
        description="获取当前日期和时间（UTC）",
        parameters={},
        group="utility",
    )
    def get_current_time() -> str:
        """返回当前UTC时间"""
        now = datetime.now(timezone.utc)
        return f"当前UTC时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})"
