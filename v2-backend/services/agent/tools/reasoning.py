"""reasoning 组工具 — think"""


def register(registry, ctx=None):
    """注册 reasoning 组工具"""

    @registry.tool(
        description=(
            "Use this tool to think, reflect, or plan before taking action. "
            "Call this tool when: (1) you need to analyze complex information, "
            "(2) you want to plan your next steps, (3) you need to reflect on "
            "whether your previous tool results are correct or sufficient, "
            "(4) you are uncertain and need to reason through options. "
            "This tool does not execute anything — it is a scratchpad for your reasoning."
        ),
        parameters={
            "thought": {
                "type": "STRING",
                "description": "Your reasoning, reflection, or plan",
            }
        },
        group="reasoning",
    )
    def think(thought: str) -> str:
        """Agent的思考/反思/规划工具 — 不执行任何操作，只记录思考"""
        return "[Thought recorded]"
