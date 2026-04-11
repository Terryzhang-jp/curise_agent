"""filesystem — consolidated manage_files tool (read/write/list/edit)"""

import hashlib
import json
import os


def _compute_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def register(registry, ctx=None):
    """注册 manage_files 工具"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    # ── Internal helpers ──

    def _read(file_path: str, offset: int = 0, limit: int = 200) -> str:
        try:
            offset, limit = int(offset), min(int(limit), 500)
            with open(file_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            total = len(all_lines)
            if total == 0:
                return f"文件 {file_path} 为空"
            if offset >= total:
                return f"Error: offset ({offset}) exceeds total lines ({total})"
            end = min(offset + limit, total)
            numbered = [f"{i:>5}\t{line.rstrip()}" for i, line in enumerate(all_lines[offset:end], start=offset + 1)]
            result = "\n".join(numbered)
            if end < total:
                result += f"\n\n[显示第 {offset+1}-{end} 行，共 {total} 行。使用 offset={end} 继续读取]"
            abs_path = os.path.abspath(file_path)
            ctx.file_hashes[abs_path] = _compute_hash("".join(all_lines))
            return result
        except FileNotFoundError:
            return f"Error: file not found: {file_path}"
        except UnicodeDecodeError:
            return f"Error: file is not UTF-8 text: {file_path}"
        except Exception as e:
            return f"Error: read failed: {e}"

    def _list(directory: str) -> str:
        try:
            entries = os.listdir(directory)
            if not entries:
                return f"目录 {directory} 为空"
            result = f"目录 {directory} 包含 {len(entries)} 个条目:\n"
            for entry in sorted(entries):
                full_path = os.path.join(directory, entry)
                if os.path.isdir(full_path):
                    result += f"  [DIR]  {entry}/\n"
                else:
                    result += f"  [FILE] {entry} ({os.path.getsize(full_path)} bytes)\n"
            return result
        except FileNotFoundError:
            return f"Error: directory not found: {directory}"
        except Exception as e:
            return f"Error: list failed: {e}"

    def _write(file_path: str, content: str) -> str:
        try:
            abs_path = os.path.abspath(file_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            ctx.file_hashes[abs_path] = _compute_hash(content)
            n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return f"已写入 {file_path} ({n_lines} 行, {len(content.encode('utf-8'))} bytes)"
        except Exception as e:
            return f"Error: write failed: {e}"

    def _edit(file_path: str, old_string: str, new_string: str) -> str:
        try:
            abs_path = os.path.abspath(file_path)
            if abs_path not in ctx.file_hashes:
                return "Error: must read file before editing (use action=read first)."
            if not os.path.exists(abs_path):
                return f"Error: file not found: {file_path}"
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            if _compute_hash(content) != ctx.file_hashes[abs_path]:
                return "Error: file was modified externally, please read again."
            count = content.count(old_string)
            if count == 0:
                return "Error: old_string not found."
            if count > 1:
                return f"Error: {count} matches found, provide more context."
            new_content = content.replace(old_string, new_string, 1)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            ctx.file_hashes[abs_path] = _compute_hash(new_content)
            line_num = content[:content.index(old_string)].count("\n") + 1
            return f"已编辑 {file_path} (第 {line_num} 行)"
        except Exception as e:
            return f"Error: edit failed: {e}"

    # ── Consolidated tool ──

    @registry.tool(
        description=(
            "文件操作工具。通过 action 参数选择操作:\n"
            "- read: 读取文件内容 (fields: file_path, offset=0, limit=200)\n"
            "- list: 列出目录内容 (fields: directory)\n"
            "- write: 创建/覆盖写入文件 (fields: file_path, content)\n"
            "- edit: str_replace 编辑 (fields: file_path, old_string, new_string)。编辑前必须先 read。\n\n"
            "示例:\n"
            '  manage_files(action="read", fields=\'{"file_path": "output.py"}\')\n'
            '  manage_files(action="list", fields=\'{"directory": "."}\')\n'
            '  manage_files(action="write", fields=\'{"file_path": "out.txt", "content": "hello"}\')\n'
            '  manage_files(action="edit", fields=\'{"file_path": "x.py", "old_string": "foo", "new_string": "bar"}\')'
        ),
        parameters={
            "action": {
                "type": "STRING",
                "description": "操作类型: read | list | write | edit",
            },
            "fields": {
                "type": "STRING",
                "description": "JSON 格式参数 (file_path, content, old_string, new_string, directory, offset, limit)",
            },
        },
        group="filesystem",
    )
    def manage_files(action: str = "", fields: str = "{}") -> str:
        if not action:
            return "Error: 需要 action"
        try:
            p = json.loads(fields) if fields else {}
        except (json.JSONDecodeError, TypeError):
            p = {}

        if action == "read":
            return _read(p.get("file_path", ""), p.get("offset", 0), p.get("limit", 200))
        elif action == "list":
            return _list(p.get("directory", "."))
        elif action == "write":
            return _write(p.get("file_path", ""), p.get("content", ""))
        elif action == "edit":
            return _edit(p.get("file_path", ""), p.get("old_string", ""), p.get("new_string", ""))
        else:
            return f"Error: 未知 action '{action}'。支持: read, list, write, edit"
