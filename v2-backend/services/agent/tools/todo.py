"""todo 组工具 — todo_write + todo_read

State is held in ToolContext, not module globals.
"""


def register(registry, ctx=None):
    """注册 todo 组工具"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    @registry.tool(
        description=(
            "Create, update, or clear a task checklist. "
            "Use this for multi-step tasks to track progress. "
            "Actions: 'add' (requires task), 'update' (requires task_id + status), 'clear'."
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "Action to perform: 'add', 'update', or 'clear'",
            },
            "task": {
                "type": "STRING",
                "description": "Task description (required for 'add')",
                "required": False,
            },
            "task_id": {
                "type": "INTEGER",
                "description": "Task ID to update (required for 'update')",
                "required": False,
            },
            "status": {
                "type": "STRING",
                "description": "New status for 'update': 'pending', 'in_progress', or 'done'",
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
        description="Read the current task checklist to see progress on multi-step tasks.",
        parameters={},
        group="todo",
    )
    def todo_read() -> str:
        """读取当前任务清单"""
        return ctx.todo_format_list()
