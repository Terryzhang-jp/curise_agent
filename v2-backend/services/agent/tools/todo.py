"""todo 组工具 — todo_write + todo_read

State is held in ToolContext, not module globals.
"""

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "todo_write": ToolMetaInfo(
        display_name="任务写入",
        group="todo",
        description="创建/更新任务清单项",
        prompt_description="创建/更新任务清单",
        summary="更新任务清单",
    ),
    "todo_read": ToolMetaInfo(
        display_name="任务读取",
        group="todo",
        description="读取当前任务清单",
        prompt_description="读取任务清单",
        summary="读取任务清单",
    ),
}


def register(registry, ctx=None):
    """注册 todo 组工具"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    @registry.tool(
        description=(
            "创建/更新/清空任务清单，用于多步骤任务的进度追踪。"
            "操作：add（添加任务）、update（更新状态）、clear（清空全部）。"
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作类型：add / update / clear",
            },
            "task": {
                "type": "STRING",
                "description": "任务描述（add 时必填）",
                "required": False,
            },
            "task_id": {
                "type": "INTEGER",
                "description": "要更新的任务 ID（update 时必填）",
                "required": False,
            },
            "status": {
                "type": "STRING",
                "description": "新状态：pending / in_progress / done（update 时必填）",
                "required": False,
            },
        },
        group="todo",
    )
    def todo_write(action: str, task: str = "", task_id: int = 0, status: str = "") -> str:
        """创建/更新/清空任务清单"""
        if action == "add":
            if not task:
                return "Error: 'add' requires a task parameter."
            item = {"id": ctx.todo_next_id, "task": task, "status": "pending"}
            ctx.todo_items.append(item)
            ctx.todo_next_id += 1
            return f"已添加任务 #{item['id']}: {task}\n\n{ctx.todo_format_list()}"

        elif action == "update":
            task_id = int(task_id) if task_id else 0
            if not task_id:
                return "Error: 'update' requires a task_id parameter."
            if status not in ("pending", "in_progress", "done"):
                return f"Error: status must be 'pending', 'in_progress', or 'done', got: '{status}'"
            for item in ctx.todo_items:
                if item["id"] == task_id:
                    item["status"] = status
                    return f"任务 #{task_id} 状态已更新为 {status}\n\n{ctx.todo_format_list()}"
            return f"Error: task #{task_id} not found"

        elif action == "clear":
            ctx.todo_items.clear()
            return "任务清单已清空。"

        else:
            return f"Error: unknown action '{action}'. Supported: 'add', 'update', 'clear'"

    @registry.tool(
        description="读取当前任务清单，查看多步骤任务的执行进度。",
        parameters={},
        group="todo",
    )
    def todo_read() -> str:
        """读取当前任务清单"""
        return ctx.todo_format_list()
