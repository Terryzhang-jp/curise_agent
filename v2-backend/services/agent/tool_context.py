"""
ToolContext — shared mutable state container for pipeline and general tools.

Extended from agent_design/tool_context.py with pipeline-specific fields
and skill system support.
Each Agent instance creates its own ToolContext, ensuring state isolation.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# Skill data structure
# ============================================================

@dataclass
class SkillDef:
    name: str
    description: str
    body: str
    source_path: str
    references_dir: str | None


# ============================================================
# ToolContext
# ============================================================

@dataclass
class ToolContext:
    """Holds all mutable state that tools need across a pipeline session."""

    # --- Pipeline state ---
    session_data: dict[str, Any] = field(default_factory=dict)   # Phase results (persisted to PipelineSession.phase_results)
    should_pause: bool = False                                    # HITL pause flag
    pause_reason: str = ""
    pause_data: dict[str, Any] = field(default_factory=dict)     # Data for frontend review display
    db: Any = None                                                # SQLAlchemy session (injected at runtime)
    file_bytes: bytes | None = None                               # Uploaded file bytes
    pipeline_session_id: str | None = None
    current_phase: str | None = None

    # --- Agent general state ---
    file_hashes: dict[str, str] = field(default_factory=dict)
    todo_items: list[dict] = field(default_factory=list)
    todo_next_id: int = 1

    # --- Skill state ---
    skills: dict[str, SkillDef] = field(default_factory=dict)
    skill_paths: list[str] = field(default_factory=list)

    # ----------------------------------------------------------
    # Todo helpers
    # ----------------------------------------------------------

    def todo_format_list(self) -> str:
        if not self.todo_items:
            return "任务清单为空。"
        lines = ["当前任务清单:"]
        for item in self.todo_items:
            mark = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}.get(item["status"], "[ ]")
            lines.append(f"  {mark} #{item['id']} {item['task']}")
        done = sum(1 for i in self.todo_items if i["status"] == "done")
        lines.append(f"进度: {done}/{len(self.todo_items)}")
        return "\n".join(lines)

    def todo_state_summary(self) -> str:
        if not self.todo_items:
            return ""
        lines = ["[Todo 状态]"]
        for item in self.todo_items:
            mark = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}.get(item["status"], "[ ]")
            lines.append(f"  {mark} #{item['id']} {item['task']}")
        done = sum(1 for i in self.todo_items if i["status"] == "done")
        lines.append(f"  进度: {done}/{len(self.todo_items)}")
        return "\n".join(lines)

    # ----------------------------------------------------------
    # Skill helpers
    # ----------------------------------------------------------

    def scan_skills(self, extra_paths: list[str] | None = None):
        """Scan skill directories and populate self.skills."""
        self.skills.clear()
        default_dir = os.path.join(os.path.dirname(__file__), ".skills")
        scan_dirs = [default_dir]
        if extra_paths:
            scan_dirs.extend(extra_paths)
        if self.skill_paths:
            scan_dirs.extend(self.skill_paths)
        for d in scan_dirs:
            self._scan_skill_directory(d)

    def _scan_skill_directory(self, directory: str):
        """Scan a directory tree for **/SKILL.md files."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return
        for skill_path in dir_path.glob("**/SKILL.md"):
            skill = _parse_skill_md(str(skill_path))
            if skill and skill.name not in self.skills:
                self.skills[skill.name] = skill

    def get_skill_list_summary(self) -> str:
        """Return skill list summary for system prompt injection."""
        if not self.skills:
            return ""
        lines = ["## Available Skills", ""]
        for sk in self.skills.values():
            lines.append(f"- **/{sk.name}**: {sk.description}")
        lines.append("")
        lines.append(
            "You can invoke a skill with `use_skill` tool or the user can trigger one with `/skill-name args`."
        )
        return "\n".join(lines)

    def resolve_slash_command(self, user_message: str) -> tuple[bool, str]:
        """Check if message starts with /skill-name, expand if matched."""
        msg = user_message.strip()
        if not msg.startswith("/"):
            return False, user_message

        parts = msg.split(None, 1)
        skill_name = parts[0][1:]
        arguments = parts[1] if len(parts) > 1 else ""

        skill = self.skills.get(skill_name)
        if skill is None:
            return False, user_message

        expanded = _expand_template(skill.body, arguments)

        refs_note = ""
        if skill.references_dir:
            try:
                ref_files = [f.name for f in Path(skill.references_dir).iterdir() if f.is_file()]
                if ref_files:
                    refs_note = (
                        "\n\n## Reference Files Available\n"
                        + "\n".join(f"- `{skill.references_dir}/{f}`" for f in sorted(ref_files))
                    )
            except OSError:
                pass

        return True, f"[Skill: {skill.name}]\n\n{expanded}{refs_note}"


# ============================================================
# Standalone helpers (used by ToolContext and tools/skill.py)
# ============================================================

def _parse_skill_md(filepath: str) -> SkillDef | None:
    """Parse a SKILL.md file, return SkillDef or None."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not m:
        return None

    frontmatter_text = m.group(1)
    body = m.group(2).strip()

    fm: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon_idx = line.find(":")
        if colon_idx > 0:
            key = line[:colon_idx].strip()
            value = line[colon_idx + 1:].strip()
            fm[key] = value

    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()
    if not name:
        return None

    skill_dir = os.path.dirname(filepath)
    refs_dir = os.path.join(skill_dir, "references")
    references_dir = refs_dir if os.path.isdir(refs_dir) else None

    return SkillDef(
        name=name,
        description=description,
        body=body,
        source_path=os.path.abspath(filepath),
        references_dir=references_dir,
    )


def _expand_template(body: str, arguments: str = "") -> str:
    """Expand $ARGUMENTS and !`command` patterns in a skill template."""
    result = body.replace("$ARGUMENTS", arguments)

    def _run_cmd(match: re.Match) -> str:
        cmd = match.group(1)
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10,
            )
            output = proc.stdout.strip()
            if proc.returncode != 0 and proc.stderr:
                output += f"\n[stderr: {proc.stderr.strip()}]"
            return output
        except subprocess.TimeoutExpired:
            return f"[command timed out: {cmd}]"
        except Exception as e:
            return f"[command error: {e}]"

    result = re.sub(r"!`([^`]+)`", _run_cmd, result)
    return result
