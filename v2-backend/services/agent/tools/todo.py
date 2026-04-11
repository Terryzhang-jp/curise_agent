"""todo — consolidated manage_todo tool (add/update/clear/read)"""

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "manage_todo": ToolMetaInfo(
        display_name="任务管理",
        group="todo",
        description="任务清单管理（添加/更新/清空/读取）",
        prompt_description="任务清单管理",
        summary="管理任务清单",
    ),
}


def register(registry, ctx=None):
    """注册 manage_todo 工具"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    @registry.tool(
        description=(
            "任务清单管理，用于多步骤任务的进度追踪。\n"
            "- add: 添加任务 (task=描述)\n"
            "- update: 更新状态 (task_id=N, status=pending/in_progress/done)\n"
            "- clear: 清空全部\n"
            "- read: 查看当前清单"
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作: add | update | clear | read",
            },
            "task": {
                "type": "STRING",
                "description": "任务描述（add 时必填）",
                "required": False,
            },
            "task_id": {
                "type": "INTEGER",
                "description": "任务 ID（update 时必填）",
                "required": False,
            },
            "status": {
                "type": "STRING",
                "description": "新状态: pending / in_progress / done（update 时必填）",
                "required": False,
            },
        },
        group="todo",
    )
    def manage_todo(action: str = "read", task: str = "", task_id: int = 0, status: str = "") -> str:
        if action == "read":
            return ctx.todo_format_list()
        elif action == "add":
            if not task:
                return "Error: add 需要 task 参数"
            item = {"id": ctx.todo_next_id, "task": task, "status": "pending"}
            ctx.todo_items.append(item)
            ctx.todo_next_id += 1
            return f"已添加任务 #{item['id']}: {task}\n\n{ctx.todo_format_list()}"
        elif action == "update":
            task_id = int(task_id) if task_id else 0
            if not task_id:
                return "Error: update 需要 task_id"
            if status not in ("pending", "in_progress", "done"):
                return f"Error: status 必须是 pending/in_progress/done, 收到: '{status}'"
            for item in ctx.todo_items:
                if item["id"] == task_id:
                    item["status"] = status
                    return f"任务 #{task_id} → {status}\n\n{ctx.todo_format_list()}"
            return f"Error: 任务 #{task_id} 不存在"
        elif action == "clear":
            ctx.todo_items.clear()
            return "任务清单已清空。"
        else:
            return f"Error: 未知 action '{action}'。支持: add, update, clear, read"
