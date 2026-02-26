"""shell 组工具 — bash 命令执行"""

import os
import signal
import subprocess

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
            "Execute a bash command and return its output (stdout + stderr). "
            "Use this for: running scripts, installing packages, git operations, "
            "file manipulation, and any shell task. "
            "Commands have a 30-second timeout. Output is truncated to 10000 chars."
        ),
        parameters={
            "command": {
                "type": "STRING",
                "description": "The bash command to execute",
            },
            "timeout": {
                "type": "NUMBER",
                "description": "Timeout in seconds (default: 30, max: 120)",
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

        cwd = working_directory.strip() if working_directory else None
        if cwd and not os.path.isdir(cwd):
            return f"Error: working directory not found: {cwd}"

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
