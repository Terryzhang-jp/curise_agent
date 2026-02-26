"""filesystem 组工具 — read_file + list_files + write_file + edit_file"""

import hashlib
import os


def _compute_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def register(registry, ctx=None):
    """注册 filesystem 组工具"""
    if ctx is None:
        from services.agent.tool_context import ToolContext
        ctx = ToolContext()

    @registry.tool(
        description=(
            "Read the contents of a file. Supports offset and limit for reading "
            "specific portions of large files. Returns file content with line numbers."
        ),
        parameters={
            "file_path": {
                "type": "STRING",
                "description": "Path to the file to read",
            },
            "offset": {
                "type": "NUMBER",
                "description": "Line number to start reading from (0-based, default: 0)",
                "required": False,
            },
            "limit": {
                "type": "NUMBER",
                "description": "Max number of lines to read (default: 200, max: 500)",
                "required": False,
            },
        },
        group="filesystem",
    )
    def read_file(file_path: str, offset: int = 0, limit: int = 200) -> str:
        """读取文件内容，支持分页"""
        try:
            offset = int(offset)
            limit = min(int(limit), 500)

            with open(file_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            total = len(all_lines)
            if total == 0:
                return f"文件 {file_path} 为空"

            if offset >= total:
                return f"Error: offset ({offset}) exceeds total lines ({total})"

            end = min(offset + limit, total)
            selected = all_lines[offset:end]

            numbered = []
            for i, line in enumerate(selected, start=offset + 1):
                numbered.append(f"{i:>5}\t{line.rstrip()}")

            result = "\n".join(numbered)
            if end < total:
                result += f"\n\n[显示第 {offset+1}-{end} 行，共 {total} 行。使用 offset={end} 继续读取]"

            abs_path = os.path.abspath(file_path)
            full_content = "".join(all_lines)
            ctx.file_hashes[abs_path] = _compute_hash(full_content)

            return result

        except FileNotFoundError:
            return f"Error: file not found: {file_path}"
        except UnicodeDecodeError:
            return f"Error: file is not UTF-8 text: {file_path}"
        except Exception as e:
            return f"Error: read_file failed: {e}"

    @registry.tool(
        description="List files and subdirectories in a directory.",
        parameters={
            "directory": {
                "type": "STRING",
                "description": "Path to the directory to list",
            }
        },
        group="filesystem",
    )
    def list_files(directory: str) -> str:
        """列出目录中的文件"""
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
                    size = os.path.getsize(full_path)
                    result += f"  [FILE] {entry} ({size} bytes)\n"
            return result
        except FileNotFoundError:
            return f"Error: directory not found: {directory}"
        except Exception as e:
            return f"Error: list_files failed: {e}"

    @registry.tool(
        description=(
            "Write content to a file. Creates parent directories if needed. "
            "Use this to create new files or overwrite existing ones."
        ),
        parameters={
            "file_path": {
                "type": "STRING",
                "description": "Path to the file to write",
            },
            "content": {
                "type": "STRING",
                "description": "Content to write to the file",
            },
        },
        group="filesystem",
    )
    def write_file(file_path: str, content: str) -> str:
        """创建或覆盖写入文件"""
        try:
            abs_path = os.path.abspath(file_path)
            parent = os.path.dirname(abs_path)
            os.makedirs(parent, exist_ok=True)

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)

            ctx.file_hashes[abs_path] = _compute_hash(content)

            n_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            size = len(content.encode("utf-8"))
            return f"已写入 {file_path} ({n_lines} 行, {size} bytes)"

        except Exception as e:
            return f"Error: write_file failed: {e}"

    @registry.tool(
        description=(
            "Edit a file by replacing an exact string with a new string (str_replace). "
            "You MUST read_file first before editing. The old_string must appear exactly "
            "once in the file. Provide enough context lines to make old_string unique."
        ),
        parameters={
            "file_path": {
                "type": "STRING",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "STRING",
                "description": "The exact string to find and replace (must be unique in the file)",
            },
            "new_string": {
                "type": "STRING",
                "description": "The replacement string",
            },
        },
        group="filesystem",
    )
    def edit_file(file_path: str, old_string: str, new_string: str) -> str:
        """str_replace 模式编辑文件"""
        try:
            abs_path = os.path.abspath(file_path)

            if abs_path not in ctx.file_hashes:
                return "Error: must read_file before editing."

            if not os.path.exists(abs_path):
                return f"Error: file not found: {file_path}"

            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            current_hash = _compute_hash(content)
            if current_hash != ctx.file_hashes[abs_path]:
                return "Error: file was modified externally, please read_file again."

            count = content.count(old_string)
            if count == 0:
                return "Error: old_string not found. Ensure exact match including whitespace and newlines."
            if count > 1:
                return f"Error: found {count} matches, provide more context to make old_string unique."

            new_content = content.replace(old_string, new_string, 1)

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            ctx.file_hashes[abs_path] = _compute_hash(new_content)

            pos = content.index(old_string)
            line_num = content[:pos].count("\n") + 1
            old_lines = old_string.count("\n") + 1
            new_lines = new_string.count("\n") + 1

            summary = f"已编辑 {file_path} (第 {line_num} 行附近)\n"
            summary += f"  替换: {old_lines} 行 → {new_lines} 行\n"

            old_preview = old_string[:100] + ("..." if len(old_string) > 100 else "")
            new_preview = new_string[:100] + ("..." if len(new_string) > 100 else "")
            summary += f"  - {repr(old_preview)}\n"
            summary += f"  + {repr(new_preview)}"

            return summary

        except Exception as e:
            return f"Error: edit_file failed: {e}"
