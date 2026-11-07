"""Read-only skill library plus an interactive skill runner."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import accounts, skills_catalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/skill-library", tags=["skills"])


class RunSkillBody(BaseModel):
    input: str = Field(min_length=2, max_length=8000)


@router.get("")
def list_skills(request: Request):
    accounts.require_user(request)
    return {"groups": skills_catalog.groups(), "skills": skills_catalog.list_all()}


@router.get("/{skill_id}")
def get_skill(skill_id: str, request: Request):
    accounts.require_user(request)
    skill = skills_catalog.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"skill": skill}


@router.post("/{skill_id}/run")
def run_skill(skill_id: str, payload: RunSkillBody, request: Request):
    accounts.require_user(request)
    try:
        return {"status": "success", **skills_catalog.run(skill_id, payload.input)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface provider errors to the UI
        logger.exception("skill run failed: %s", skill_id)
        raise HTTPException(status_code=502, detail=str(exc)[:300] or "技能执行失败") from exc
