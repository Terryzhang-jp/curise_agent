"""search 组工具 — grep + glob_search"""

import subprocess
from pathlib import Path

# 自动过滤的目录
_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv",
    ".agent_data", ".trae", "dist", "build", ".next",
}


def register(registry, ctx=None):
    """注册 search 组工具"""

    @registry.tool(
        description=(
            "Search file contents using regex pattern (powered by ripgrep). "
            "Use this to find code definitions, usages, error messages, etc. "
            "Returns matching lines with file path and line number."
        ),
        parameters={
            "explanation": {
                "type": "STRING",
                "description": "Why you are searching — what you hope to find",
            },
            "pattern": {
                "type": "STRING",
                "description": "Regex pattern to search for (ripgrep syntax)",
            },
            "path": {
                "type": "STRING",
                "description": "Directory or file to search in (default: current dir)",
                "required": False,
            },
            "file_type": {
                "type": "STRING",
                "description": "Filter by file extension, e.g. 'py', 'ts', 'json' (optional)",
                "required": False,
            },
            "context_lines": {
                "type": "NUMBER",
                "description": "Number of context lines before/after match (default: 0)",
                "required": False,
            },
            "limit": {
                "type": "NUMBER",
                "description": "Max result lines to return (default: 50)",
                "required": False,
            },
        },
        group="search",
    )
    def grep(
        explanation: str = "",
        pattern: str = "",
        path: str = ".",
        file_type: str = "",
        context_lines: int = 0,
        limit: int = 50,
    ) -> str:
        """正则内容搜索（基于 ripgrep，fallback 到 grep）"""
        if not pattern:
            return "Error: pattern parameter is required"

        limit = int(limit)
        context_lines = int(context_lines)

        cmd = ["rg", "--no-heading", "--line-number", "--color=never"]
        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])
        if file_type:
            cmd.extend(["--type", file_type])
        for d in _IGNORE_DIRS:
            cmd.extend(["--glob", f"!{d}"])
        cmd.extend([pattern, path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
            )
            output = result.stdout
        except FileNotFoundError:
            cmd_fallback = ["grep", "-rn", "--color=never"]
            if file_type:
                cmd_fallback.extend(["--include", f"*.{file_type}"])
            for d in _IGNORE_DIRS:
                cmd_fallback.extend(["--exclude-dir", d])
            cmd_fallback.extend([pattern, path])
            try:
                result = subprocess.run(
                    cmd_fallback, capture_output=True, text=True, timeout=15,
                )
                output = result.stdout
            except Exception as e:
                return f"Error: search failed: {e}"
        except subprocess.TimeoutExpired:
            return "Error: search timed out (15s limit)"
        except Exception as e:
            return f"Error: search failed: {e}"

        if not output.strip():
            return f"未找到匹配 '{pattern}' 的结果"

        lines = output.rstrip("\n").split("\n")
        total = len(lines)
        if total > limit:
            lines = lines[:limit]
            return "\n".join(lines) + f"\n\n[截断: 显示 {limit}/{total} 行]"
        return "\n".join(lines)

    @registry.tool(
        description=(
            "Search for files by glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
            "Returns matching file paths sorted by modification time (newest first). "
            "Use this to find files by name pattern."
        ),
        parameters={
            "explanation": {
                "type": "STRING",
                "description": "Why you are searching — what files you hope to find",
            },
            "pattern": {
                "type": "STRING",
                "description": "Glob pattern (e.g. '**/*.py', 'src/**/test_*.ts')",
            },
            "path": {
                "type": "STRING",
                "description": "Base directory to search from (default: current dir)",
                "required": False,
            },
            "limit": {
                "type": "NUMBER",
                "description": "Max number of files to return (default: 30)",
                "required": False,
            },
        },
        group="search",
    )
    def glob_search(
        explanation: str = "",
        pattern: str = "",
        path: str = ".",
        limit: int = 30,
    ) -> str:
        """文件名模式搜索（基于 pathlib.glob）"""
        if not pattern:
            return "Error: pattern parameter is required"

        limit = int(limit)
        base = Path(path).resolve()
        if not base.exists():
            return f"Error: path not found: {path}"

        try:
            matches = []
            for p in base.glob(pattern):
                parts = p.relative_to(base).parts
                if any(part in _IGNORE_DIRS for part in parts):
                    continue
                if p.is_file():
                    matches.append(p)

            if not matches:
                return f"未找到匹配 '{pattern}' 的文件"

            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            total = len(matches)
            matches = matches[:limit]

            lines = []
            for p in matches:
                try:
                    rel = p.relative_to(base)
                except ValueError:
                    rel = p
                size = p.stat().st_size
                lines.append(f"{rel}  ({size} bytes)")

            result = "\n".join(lines)
            if total > limit:
                result += f"\n\n[截断: 显示 {limit}/{total} 个文件]"
            return result

        except Exception as e:
            return f"Error: search failed: {e}"
