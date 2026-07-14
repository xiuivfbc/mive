import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.conditional_cache import check_not_modified, set_cache_headers
from src.api.deps import (
    get_admin_user,
    get_current_user,
    get_session,
    is_admin,
)
from src.db.models import M1World, M2Character, M9User
from src.db.repositories.welcome_quote_repo import WelcomeQuoteRepository
from src.llm.base import llm_operation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["welcome-quotes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateQuoteRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=40)


class QuoteResponse(BaseModel):
    id: str
    user_id: str
    username: str
    content: str
    status: str
    ai_verdict: str | None = None
    ai_reason: str | None = None
    created_at: str


class EligibilityResponse(BaseModel):
    eligible: bool


class AdminUpdateStatusRequest(BaseModel):
    status: Literal["approved", "rejected"]


# ---------------------------------------------------------------------------
# Public: list approved quotes (no auth)
# ---------------------------------------------------------------------------


@router.get("/api/welcome-quotes", response_model=list[QuoteResponse])
async def list_approved_quotes(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    repo = WelcomeQuoteRepository(session)
    last_mod = await repo.max_approved_updated_at()
    not_mod = check_not_modified(request, last_mod)
    if not_mod:
        return not_mod
    if last_mod:
        set_cache_headers(response, last_mod, public=True)
    quotes = await repo.list_approved(limit=20)

    if not quotes:
        return []

    # Batch-load usernames
    user_ids = list({q.user_id for q in quotes})
    result = await session.execute(
        select(M9User.id, M9User.username).where(M9User.id.in_(user_ids))
    )
    username_map = {row.id: row.username for row in result.all()}

    return [
        QuoteResponse(
            id=str(q.id),
            user_id=str(q.user_id),
            username=username_map.get(q.user_id, "unknown"),
            content=q.content,
            status=q.status,
            ai_verdict=q.ai_verdict,
            ai_reason=q.ai_reason,
            created_at=q.created_at.isoformat() if q.created_at else "",
        )
        for q in quotes
    ]


# ---------------------------------------------------------------------------
# Auth: check eligibility (has character generation record)
# ---------------------------------------------------------------------------


@router.get("/api/welcome-quotes/eligibility", response_model=EligibilityResponse)
async def check_eligibility(
    session: AsyncSession = Depends(get_session),
    current_user: M9User = Depends(get_current_user),
):
    from src.db.models import M1World

    result = await session.execute(
        select(M2Character.id)
        .join(M1World, M1World.id == M2Character.world_id)
        .where(M1World.user_id == current_user.id)
        .limit(1)
    )
    has_record = result.scalar_one_or_none() is not None
    return EligibilityResponse(eligible=has_record)


# ---------------------------------------------------------------------------
# Auth: create quote with AI audit
# ---------------------------------------------------------------------------


@router.post("/api/welcome-quotes", response_model=QuoteResponse, status_code=201)
async def create_quote(
    body: CreateQuoteRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: M9User = Depends(get_current_user),
):
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if len(content) > 40:
        raise HTTPException(status_code=400, detail="内容不能超过 40 个字符")

    repo = WelcomeQuoteRepository(session)

    # Eligibility: check if user has any characters
    result = await session.execute(
        select(M2Character.id)
        .join(M1World, M1World.id == M2Character.world_id)
        .where(M1World.user_id == current_user.id)
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="需要完成角色生成后才能提交感言")

    # Rate limit: max 5 per hour
    recent_count = await repo.count_recent_by_user(current_user.id, hours=1)
    if recent_count >= 5:
        raise HTTPException(status_code=429, detail="提交过于频繁，请稍后再试")

    # Create quote with pending status
    quote = await repo.create(
        user_id=current_user.id,
        content=content,
        status="pending",
    )

    # AI audit
    default_llm = getattr(request.app.state, "llm", None)
    verdict, reason = await _audit_content(request, content, llm=default_llm)
    if verdict is not None:
        status = "approved" if verdict else "rejected"
        await repo.update_status(
            quote.id,
            status=status,
            ai_verdict=status,
            ai_reason=reason,
        )
        quote.status = status
        quote.ai_verdict = status
        quote.ai_reason = reason

    await session.commit()

    return QuoteResponse(
        id=str(quote.id),
        user_id=str(quote.user_id),
        username=current_user.username,
        content=quote.content,
        status=quote.status,
        ai_verdict=quote.ai_verdict,
        ai_reason=quote.ai_reason,
        created_at=quote.created_at.isoformat() if quote.created_at else "",
    )


async def _audit_content(request, content: str, llm=None) -> tuple[bool | None, str | None]:
    """Run AI audit on content. Returns (approved, reason) or (None, None) on failure."""
    if llm is None:
        llm = getattr(request.app.state, "llm", None)
    if llm is None:
        return True, None

    token = llm_operation.set("welcome_quote_audit")
    try:
        system_prompt = (
            "判断以下用户感言是否适合展示在公开欢迎页面。"
            "禁止：政治敏感、人身攻击、色情、广告、垃圾内容、无意义乱码。"
            '返回 JSON: {"approved": bool, "reason": "..."}'
        )
        result = await llm.complete_json(
            system=system_prompt,
            prompt=content,
            max_tokens=256,
            temperature=0.0,
        )
        if isinstance(result, dict):
            approved = bool(result.get("approved", True))
            reason = str(result.get("reason", ""))
        else:
            approved = True
            reason = ""
        return approved, reason
    except Exception:
        logger.exception("Welcome quote AI audit failed, defaulting to approved")
        return True, None
    finally:
        llm_operation.reset(token)


# ---------------------------------------------------------------------------
# Auth: list my quotes
# ---------------------------------------------------------------------------


@router.get("/api/welcome-quotes/mine", response_model=list[QuoteResponse])
async def list_my_quotes(
    session: AsyncSession = Depends(get_session),
    current_user: M9User = Depends(get_current_user),
):
    repo = WelcomeQuoteRepository(session)
    quotes = await repo.list_by_user(current_user.id)
    return [
        QuoteResponse(
            id=str(q.id),
            user_id=str(q.user_id),
            username=current_user.username,
            content=q.content,
            status=q.status,
            ai_verdict=q.ai_verdict,
            ai_reason=q.ai_reason,
            created_at=q.created_at.isoformat() if q.created_at else "",
        )
        for q in quotes
    ]


# ---------------------------------------------------------------------------
# Auth: delete my quote
# ---------------------------------------------------------------------------


@router.delete("/api/welcome-quotes/{quote_id}", status_code=200)
async def delete_quote(
    quote_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: M9User = Depends(get_current_user),
):
    try:
        qid = uuid.UUID(quote_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="无效的感言 ID") from err

    repo = WelcomeQuoteRepository(session)
    quote = await repo.get_by_id(qid)
    if quote is None:
        raise HTTPException(status_code=404, detail="感言不存在")
    if quote.user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="无权操作")

    await repo.delete(qid)
    await session.commit()
    return {"message": "已删除"}


# ---------------------------------------------------------------------------
# Admin: list all quotes
# ---------------------------------------------------------------------------


@router.get("/api/admin/welcome-quotes", response_model=list[QuoteResponse])
async def admin_list_quotes(
    status: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    admin: M9User = Depends(get_admin_user),
):
    repo = WelcomeQuoteRepository(session)
    quotes = await repo.list_all(status=status, limit=limit)

    if not quotes:
        return []

    user_ids = list({q.user_id for q in quotes})
    result = await session.execute(
        select(M9User.id, M9User.username).where(M9User.id.in_(user_ids))
    )
    username_map = {row.id: row.username for row in result.all()}

    return [
        QuoteResponse(
            id=str(q.id),
            user_id=str(q.user_id),
            username=username_map.get(q.user_id, "unknown"),
            content=q.content,
            status=q.status,
            ai_verdict=q.ai_verdict,
            ai_reason=q.ai_reason,
            created_at=q.created_at.isoformat() if q.created_at else "",
        )
        for q in quotes
    ]


# ---------------------------------------------------------------------------
# Admin: update quote status
# ---------------------------------------------------------------------------


@router.patch("/api/admin/welcome-quotes/{quote_id}", status_code=200)
async def admin_update_quote_status(
    quote_id: str,
    body: AdminUpdateStatusRequest,
    session: AsyncSession = Depends(get_session),
    admin: M9User = Depends(get_admin_user),
):
    try:
        qid = uuid.UUID(quote_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="无效的感言 ID") from err

    repo = WelcomeQuoteRepository(session)
    quote = await repo.get_by_id(qid)
    if quote is None:
        raise HTTPException(status_code=404, detail="感言不存在")

    await repo.update_status(qid, status=body.status)
    await session.commit()
    return {"message": "已更新感言状态"}
