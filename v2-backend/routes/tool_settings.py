"""
Tool & Skill settings endpoints — manage AI tool availability and skill templates.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database import get_db
from models import ToolConfig, SkillConfig, User
from routes.auth import get_current_user
from security import require_role

require_admin = require_role("superadmin", "admin")
from schemas import (
    ToolConfigResponse,
    ToolConfigUpdate,
    SkillConfigCreate,
    SkillConfigUpdate,
    SkillConfigResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["tool-settings"])

# ─── Built-in tool seed data ────────────────────────────────

BUILTIN_TOOLS = [
    {"tool_name": "think", "group_name": "reasoning", "display_name": "思考推理", "description": "记录思考过程，用来分析信息、制定计划、反思结果", "is_enabled": True},
    {"tool_name": "query_db", "group_name": "business", "display_name": "数据库查询", "description": "执行只读 SQL 查询获取业务数据", "is_enabled": True},
    {"tool_name": "get_db_schema", "group_name": "business", "display_name": "数据库结构", "description": "获取数据库表结构信息", "is_enabled": True},
    {"tool_name": "calculate", "group_name": "utility", "display_name": "数学计算", "description": "执行数学表达式计算", "is_enabled": True},
    {"tool_name": "get_current_time", "group_name": "utility", "display_name": "当前时间", "description": "获取当前日期和时间", "is_enabled": True},
    {"tool_name": "todo_write", "group_name": "todo", "display_name": "任务写入", "description": "创建/更新任务清单项", "is_enabled": True},
    {"tool_name": "todo_read", "group_name": "todo", "display_name": "任务读取", "description": "读取当前任务清单", "is_enabled": True},
    {"tool_name": "use_skill", "group_name": "skill", "display_name": "使用技能", "description": "调用可复用的 prompt 模板技能", "is_enabled": True},
    {"tool_name": "web_fetch", "group_name": "web", "display_name": "网页抓取", "description": "获取网页内容（HTTP GET）", "is_enabled": False},
    {"tool_name": "web_search", "group_name": "web", "display_name": "网络搜索", "description": "使用搜索引擎查询最新信息（天气、新闻等），免费无需API Key", "is_enabled": True},
    {"tool_name": "search_product_database", "group_name": "business", "display_name": "产品搜索", "description": "按关键词搜索产品数据库", "is_enabled": False},
]


def _seed_builtin_tools(db: DBSession) -> int:
    """Insert missing built-in tools, return count of newly created."""
    created = 0
    for tool_data in BUILTIN_TOOLS:
        existing = db.query(ToolConfig).filter(ToolConfig.tool_name == tool_data["tool_name"]).first()
        if not existing:
            db.add(ToolConfig(**tool_data, is_builtin=True))
            created += 1
    if created:
        db.commit()
    return created


# ─── Tools endpoints ────────────────────────────────────────

@router.get("/tools", response_model=list[ToolConfigResponse])
def list_tools(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all tool configs. Auto-seeds built-in tools on first access."""
    count = db.query(ToolConfig).count()
    if count == 0:
        _seed_builtin_tools(db)
    return db.query(ToolConfig).order_by(ToolConfig.group_name, ToolConfig.tool_name).all()


@router.patch("/tools/{tool_name}", response_model=ToolConfigResponse)
def update_tool(
    tool_name: str,
    body: ToolConfigUpdate,
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Update a tool's enabled state or display info."""
    tool = db.query(ToolConfig).filter(ToolConfig.tool_name == tool_name).first()
    if not tool:
        raise HTTPException(404, f"工具 '{tool_name}' 不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tool, field, value)
    tool.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(tool)
    return tool


@router.post("/tools/seed")
def seed_tools(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Manually seed/resync built-in tools."""
    created = _seed_builtin_tools(db)
    return {"detail": f"已同步内置工具，新增 {created} 个"}


# ─── Skills endpoints ───────────────────────────────────────

@router.get("/skills", response_model=list[SkillConfigResponse])
def list_skills(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all skills."""
    return db.query(SkillConfig).order_by(SkillConfig.is_builtin.desc(), SkillConfig.name).all()


@router.post("/skills", response_model=SkillConfigResponse)
def create_skill(
    body: SkillConfigCreate,
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Create a user-defined skill."""
    existing = db.query(SkillConfig).filter(SkillConfig.name == body.name).first()
    if existing:
        raise HTTPException(409, f"技能名 '{body.name}' 已存在")
    skill = SkillConfig(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        content=body.content,
        is_builtin=False,
        is_enabled=True,
        created_by=current_user.id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.get("/skills/{skill_id}", response_model=SkillConfigResponse)
def get_skill(
    skill_id: int,
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Get a skill by ID."""
    skill = db.query(SkillConfig).filter(SkillConfig.id == skill_id).first()
    if not skill:
        raise HTTPException(404, "技能不存在")
    return skill


@router.patch("/skills/{skill_id}", response_model=SkillConfigResponse)
def update_skill(
    skill_id: int,
    body: SkillConfigUpdate,
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Update a skill."""
    skill = db.query(SkillConfig).filter(SkillConfig.id == skill_id).first()
    if not skill:
        raise HTTPException(404, "技能不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(skill, field, value)
    skill.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/skills/{skill_id}")
def delete_skill(
    skill_id: int,
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Delete a skill (only user-created ones)."""
    skill = db.query(SkillConfig).filter(SkillConfig.id == skill_id).first()
    if not skill:
        raise HTTPException(404, "技能不存在")
    if skill.is_builtin:
        raise HTTPException(403, "内置技能不可删除，只能禁用")
    db.delete(skill)
    db.commit()
    return {"detail": "已删除"}


@router.post("/skills/seed")
def seed_skills(
    current_user: User = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Sync built-in skills from the skills/ directory."""
    from services.agent.tool_context import _parse_skill_md
    from pathlib import Path

    skills_dir = Path(os.path.dirname(os.path.dirname(__file__))) / "skills"
    if not skills_dir.is_dir():
        # Try project root
        skills_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "skills"

    created = 0
    if skills_dir.is_dir():
        for skill_path in skills_dir.glob("**/SKILL.md"):
            parsed = _parse_skill_md(str(skill_path))
            if not parsed:
                continue
            existing = db.query(SkillConfig).filter(SkillConfig.name == parsed.name).first()
            if existing:
                # Update content if changed
                if existing.is_builtin and existing.content != parsed.body:
                    existing.content = parsed.body
                    existing.description = parsed.description
                    existing.updated_at = datetime.utcnow()
                continue
            db.add(SkillConfig(
                name=parsed.name,
                display_name=parsed.name,
                description=parsed.description,
                content=parsed.body,
                is_builtin=True,
                is_enabled=True,
            ))
            created += 1
    if created:
        db.commit()
    return {"detail": f"已同步技能，新增 {created} 个"}
