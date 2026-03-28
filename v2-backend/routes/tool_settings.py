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

# ─── Built-in tool seed data (auto-discovered from TOOL_META) ─

def _get_builtin_tools() -> list[dict]:
    """Get built-in tool seed data from auto-discovered TOOL_META."""
    try:
        from services.tools.registry_loader import get_builtin_tools_seed
        return get_builtin_tools_seed()
    except Exception as e:
        logger.warning("Failed to auto-discover tools, using empty list: %s", e)
        return []


def _seed_builtin_tools(db: DBSession) -> int:
    """Insert missing built-in tools, return count of newly created."""
    created = 0
    for tool_data in _get_builtin_tools():
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
