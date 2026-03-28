"""shell 组工具 — bash 命令执行"""

import os
import signal
import subprocess

from services.tools.registry_loader import ToolMetaInfo

TOOL_META = {
    "bash": ToolMetaInfo(
        display_name="命令执行",
        group="shell",
        description="执行 bash/Python 命令（生成 Excel、数据处理等）",
        prompt_description="执行 bash/Python 命令（可用于生成 Excel、数据处理、代码执行等）",
        summary="执行命令",  # Note: chat_storage uses callable _extract_bash_summary for richer summaries
    ),
}

# 危险命令模式
_BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){",
    "fork bomb",
    "> /dev/sda",
]

# 从环境中移除的敏感变量
_SENSITIVE_ENV_KEYS = [
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "SECRET_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
]

_MAX_OUTPUT = 10000


def register(registry, ctx=None):
    """注册 shell 组工具"""

    @registry.tool(
        description=(
            "执行 bash 命令并返回输出。用于：修改 Excel 文件（openpyxl）、运行 Python 脚本、"
            "文件操作、数据处理等。工作目录已设为 workspace，生成的文件可直接访问。"
            "超时 30 秒，输出截断到 10000 字符。"
        ),
        parameters={
            "command": {
                "type": "STRING",
                "description": "要执行的 bash 命令（支持 Python: python3 -c '...'）",
            },
            "timeout": {
                "type": "NUMBER",
                "description": "超时秒数（默认30，最大120）",
                "required": False,
            },
            "working_directory": {
                "type": "STRING",
                "description": "Working directory for the command (default: current dir)",
                "required": False,
            },
        },
        group="shell",
    )
    def bash(command: str, timeout: int = 30, working_directory: str = "") -> str:
        """执行 bash 命令"""
        cmd_lower = command.lower().strip()
        for pattern in _BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                return f"Error: command blocked by security policy (matched: {pattern})"

        timeout = min(max(int(timeout), 1), 120)

        # Resolve working directory: explicit arg > workspace_dir > None (OS default)
        cwd = working_directory.strip() if working_directory else None
        if not cwd and ctx and ctx.workspace_dir:
            cwd = ctx.workspace_dir
        if cwd:
            os.makedirs(cwd, exist_ok=True)

        env = os.environ.copy()
        for key in _SENSITIVE_ENV_KEYS:
            env.pop(key, None)

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid,
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
                return f"Error: command timed out ({timeout}s), terminated."

            rc = proc.returncode

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            parts = [f"Exit code: {rc}"]
            if out:
                parts.append(f"stdout:\n{out}")
            if err:
                parts.append(f"stderr:\n{err}")

            result = "\n".join(parts)

            if len(result) > _MAX_OUTPUT:
                half = _MAX_OUTPUT // 2
                result = (
                    result[:half]
                    + f"\n\n... [输出被截断，共 {len(result)} 字符，显示前 {half} + 后 {half}] ...\n\n"
                    + result[-half:]
                )

            return result

        except Exception as e:
            return f"Error: command execution failed: {type(e).__name__}: {e}"
