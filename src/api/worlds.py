import asyncio
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import src.db.session as _db_session_mod
from src.api.conditional_cache import check_not_modified, set_cache_headers
from src.api.deps import (
    build_bg_generation_services,
    build_bg_world_services,
    build_element_retrieval_from_session,
    get_current_user,
    get_session,
    get_world_service,
)
from src.db.models import M9User
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.repositories.world_repo import WorldRepository
from src.debug_logger import wcd
from src.llm.base import user_language
from src.models.character import CreateCharacterRequest
from src.models.scale import DEFAULT_SCALE
from src.models.scale import SCALES as _SCALES
from src.models.world import (
    CheckWikiRequest,
    CreateFromTemplateRequest,
    CreateWorldRequest,
    WikiPreviewRequest,
    WorldDoc,
)
from src.services.snapshot_sync_service import publish_snapshot_dirty
from src.services.world_service import WorldService

logger = logging.getLogger(__name__)

# 按 user_id 串行化世界创建，避免并行创建共享 gate 导致 429 雪崩
_world_creation_locks: dict[str, asyncio.Lock] = {}
_world_creation_locks_meta_lock = asyncio.Lock()


async def _get_user_creation_lock(user_id: str) -> asyncio.Lock:
    async with _world_creation_locks_meta_lock:
        if user_id not in _world_creation_locks:
            _world_creation_locks[user_id] = asyncio.Lock()
        return _world_creation_locks[user_id]


class UpdatePlotSummaryRequest(BaseModel):
    plot_summary: str


class UpdateCommonSenseRequest(BaseModel):
    common_sense: str


class UpdateCoreConflictRequest(BaseModel):
    core_conflict: str


class UpdateToneAndAtmosphereRequest(BaseModel):
    tone_and_atmosphere: str


class UpdatePlotDevelopmentRequest(BaseModel):
    plot_development: str


class UpdateTitleRequest(BaseModel):
    title: str


router = APIRouter(prefix="/api/worlds", tags=["worlds"])


@router.post("/check-wiki")
async def check_wiki(
    req: CheckWikiRequest,
    world_service: WorldService = Depends(get_world_service),
    current_user: M9User = Depends(get_current_user),
):
    """预检维基百科是否有该作品词条。低档位先试 LLM 门控，通过则走快速路径。"""
    user_language.set(current_user.preferred_language)

    # 低档位先试 LLM 门控
    scale = req.scale or DEFAULT_SCALE
    if scale == "standard":
        _char_target = _SCALES.get(scale, _SCALES.get("standard")).char_target
        gate = await world_service.judge_fast_path(
            title=req.title,
            author=req.author,
            description=None,
            scale=scale,
            char_target=_char_target,
        )
        if gate["can_identify"] and gate["can_generate"]:
            return {
                "fast_path": True,
                "found": False,
                "results": [],
                "fast_path_characters": gate.get("characters", []),
            }

    # 正常流程：Tavily 搜索
    result = await world_service.check_wiki(
        title=req.title,
        author=req.author,
        preferred_language=current_user.preferred_language,
        work_language=req.work_language,
    )
    return {"fast_path": False, **result}


@router.post("/wiki-preview")
async def wiki_preview(
    req: WikiPreviewRequest,
    world_service: WorldService = Depends(get_world_service),
):
    """获取候选 wiki URL 的全文预览，供用户在确认候选前查看更完整的内容。

    维基百科链接复用抽取阶段同款抓取（fetch_wiki_api_text）+ 清洗（clean_wiki_text）。
    不做子链接扫描、不套用创建档位预算截断，仅做纯技术性硬字符上限保护。
    """
    result = await world_service.fetch_wiki_full_preview(req.url)
    if result is None:
        raise HTTPException(status_code=404, detail="未能获取该页面内容，请稍后重试")
    content, truncated = result
    return {"content": content, "truncated": truncated}


async def _run_world_creation(
    request: Request,
    world_id: str,
    user_id: str,
    title: str,
    author: str | None,
    world_type: str | None,
    description: str | None,
    urls: list[str],
    scale: str,
    detected_work_type: str | None,
    preferred_language: str,
    confirmed_wiki_url: str | None,
    fast_path: bool = False,
    user_llm=None,
    fast_path_characters: list[str] | None = None,
):
    """后台任务：执行元素提取/剧情生成，完成后将世界状态设为 active。"""
    t0 = time.monotonic()
    is_fast = fast_path
    wcd(
        f'[后台任务] ─── 开始 ─── world_id={world_id} | title="{title}" | scale={scale} | '
        f'path={"快速路径" if is_fast else "正常路径"} | wiki_url="{confirmed_wiki_url}"'
    )
    logger.info(
        "_run_world_creation START | world_id=%s | title=%s | user_id=%s | scale=%s | "
        "path=%s | wiki_url=%s | author=%s | has_desc=%s | urls_count=%d | "
        "detected_work_type=%s",
        world_id,
        title,
        user_id,
        scale,
        "fast" if is_fast else "normal",
        confirmed_wiki_url or "none",
        author or "none",
        bool(description),
        len(urls),
        detected_work_type or "none",
    )
    user_language.set(preferred_language)
    try:
        user_lock = await _get_user_creation_lock(user_id)
        async with user_lock:
            async with _db_session_mod.async_session() as session:
                logger.debug(
                    "_run_world_creation | Building WorldService (session=%s)", id(session)
                )
                world_service, _char_repo = build_bg_world_services(
                    session,
                    extraction_service=request.app.state.extraction_service,
                    search_service=request.app.state.search_service,
                    llm=request.app.state.llm,
                    user_llm=user_llm,
                )

                t_build_start = time.monotonic()
                if is_fast:
                    wcd("[后台任务] 决策: 走快速路径 → build_world_content_fast()")
                    logger.info(
                        "_run_world_creation | DECISION: fast_path=true | world=%s | scale=%s | "
                        "reason=scale+no_wiki+has_input",
                        world_id,
                        scale,
                    )
                    wcd("[_run_world_creation] 快速路径激活")
                    try:
                        world_doc = await world_service.build_world_content_fast(
                            world_id=world_id,
                            title=title,
                            author=author,
                            type=world_type,
                            description=description,
                            urls=urls,
                            user_id=user_id,
                            scale=scale,
                            detected_work_type=detected_work_type,
                            preferred_language=preferred_language,
                            fast_path_characters=fast_path_characters or None,
                        )
                        # 存储 char_candidates 到 Redis 供 generation 阶段使用
                        if world_doc.char_candidates:
                            import json as _json

                            try:
                                _redis = request.app.state.redis
                                await _redis.set(
                                    f"char_candidates:{world_id}",
                                    _json.dumps(world_doc.char_candidates, ensure_ascii=False),
                                    ex=3600,
                                )
                            except Exception:
                                logger.warning(
                                    "_run_world_creation | Redis write char_candidates FAILED | "
                                    "world=%s | fallback=generation will use extraction",
                                    world_id,
                                )
                        t_build_elapsed = time.monotonic() - t_build_start
                        wcd(f"[后台任务] 快速路径完成 ✓ 耗时={t_build_elapsed:.1f}s")
                        logger.info(
                            "_run_world_creation | build_world_content_fast COMPLETED | "
                            "world=%s | elapsed_sec=%.1f",
                            world_id,
                            t_build_elapsed,
                        )
                    except Exception as e:
                        t_build_elapsed = time.monotonic() - t_build_start
                        wcd(
                            f"[后台任务] 快速路径失败 ✗ 耗时={t_build_elapsed:.1f}s | "
                            f"error={type(e).__name__}: {e}"
                        )
                        logger.exception(
                            "_run_world_creation | build_world_content_fast FAILED | "
                            "world=%s | elapsed_sec=%.1f | error_type=%s",
                            world_id,
                            t_build_elapsed,
                            type(e).__name__,
                        )
                        raise
                else:
                    wcd("[后台任务] 决策: 走正常路径 → build_world_content()")
                    logger.info(
                        "_run_world_creation | DECISION: fast_path=false | world=%s | scale=%s",
                        world_id,
                        scale,
                    )
                    wcd("[_run_world_creation] 正常路径激活")
                    try:
                        world_doc = await world_service.build_world_content(
                            world_id=world_id,
                            title=title,
                            author=author,
                            type=world_type,
                            description=description,
                            urls=urls,
                            user_id=user_id,
                            scale=scale,
                            detected_work_type=detected_work_type,
                            preferred_language=preferred_language,
                            confirmed_wiki_url=confirmed_wiki_url,
                        )
                        # 存储 char_candidates 到 Redis 供 generation 阶段使用
                        if world_doc.char_candidates:
                            import json as _json

                            try:
                                _redis = request.app.state.redis
                                await _redis.set(
                                    f"char_candidates:{world_id}",
                                    _json.dumps(world_doc.char_candidates, ensure_ascii=False),
                                    ex=3600,
                                )
                            except Exception:
                                logger.warning(
                                    "_run_world_creation | Redis write char_candidates FAILED | "
                                    "world=%s | fallback=generation will use extraction",
                                    world_id,
                                )
                        t_build_elapsed = time.monotonic() - t_build_start
                        wcd(f"[后台任务] 正常路径完成 ✓ 耗时={t_build_elapsed:.1f}s")
                        logger.info(
                            "_run_world_creation | build_world_content COMPLETED | "
                            "world=%s | elapsed_sec=%.1f",
                            world_id,
                            t_build_elapsed,
                        )
                    except Exception as e:
                        t_build_elapsed = time.monotonic() - t_build_start
                        logger.exception(
                            "_run_world_creation | build_world_content FAILED | "
                            "world=%s | elapsed_sec=%.1f | error_type=%s",
                            world_id,
                            t_build_elapsed,
                            type(e).__name__,
                        )
                        raise

                logger.debug(
                    "_run_world_creation | Setting world status to active | world=%s", world_id
                )
                wcd("[后台任务] 世界内容构建成功，设置状态为 active...")
                world_repo = WorldRepository(session)
                await world_repo.set_status(world_id, "active")
                await session.commit()

                elapsed = time.monotonic() - t0
                extracted_char_candidates = world_doc.char_candidates
                wcd(f"[后台任务] 状态已设为 active | 累计耗时={elapsed:.1f}s | 下一步: 角色生成")
                logger.info(
                    "_run_world_creation | CONTENT_BUILD_SUCCESS | world=%s | elapsed_sec=%.1f | "
                    "next_step=auto_generation",
                    world_id,
                    elapsed,
                )
                wcd(
                    f"[_run_world_creation] 内容构建完成: world_id={world_id}, "
                    f"总耗时={elapsed:.1f}s"
                )

            # 世界创建成功后，自动触发角色生成（同一后台任务链，不依赖前端）
            t_gen_start = time.monotonic()
            try:
                logger.info(
                    "_run_world_creation | AUTO_GENERATION_START | world=%s | scale=%s",
                    world_id,
                    scale,
                )
                wcd(f"[_run_world_creation] 自动触发角色生成: world_id={world_id}, scale={scale}")

                async with _db_session_mod.async_session() as session:
                    gen_service, _gen_graph = build_bg_generation_services(
                        session,
                        extraction_service=request.app.state.extraction_service,
                        search_service=request.app.state.search_service,
                        material_service=request.app.state.material_service,
                        llm=request.app.state.llm,
                        user_llm=user_llm,
                        redis=getattr(request.app.state, "redis", None),
                    )

                    logger.debug(
                        "_run_world_creation | Calling gen_service.generate | world=%s", world_id
                    )
                    try:
                        await request.app.state.redis.set(
                            f"gen_status:{world_id}", "generating", ex=3600
                        )
                    except Exception:
                        pass
                    # 同一后台任务内直接复用提取阶段的结果，不再依赖 Redis 传递
                    # （避免 Redis 短暂故障导致候选丢失、退化成凭空生成角色）
                    gen_result = await gen_service.generate(
                        world_id, scale=scale, char_candidates=extracted_char_candidates
                    )
                    await session.commit()
                    # 通知快照同步服务：generation 已更新
                    try:
                        await publish_snapshot_dirty(
                            request.app.state.redis, world_id, "world_generation"
                        )
                    except Exception:
                        pass

                    # Rebuild embeddings after successful generation
                    embeddings_built = False
                    embedding_provider = getattr(request.app.state, "embedding_provider", None)
                    if embedding_provider:
                        try:
                            async with _db_session_mod.async_session() as emb_session:
                                retrieval_svc = build_element_retrieval_from_session(
                                    emb_session, embedding_provider
                                )
                                embeddings_built = await retrieval_svc.rebuild_embeddings(world_id)
                                await emb_session.commit()
                        except Exception as emb_err:
                            logger.warning(
                                "_run_world_creation | embedding rebuild failed (non-fatal) | "
                                "world=%s | error_type=%s",
                                world_id,
                                type(emb_err).__name__,
                            )

                    t_gen_elapsed = time.monotonic() - t_gen_start
                    gen_elapsed = time.monotonic() - t0
                    char_count = gen_result.get("characters", 0)
                    rel_count = gen_result.get("relations", 0)
                    failed_rel_batches = gen_result.get("failed_rel_batches", 0)

                    if failed_rel_batches > 0:
                        logger.warning(
                            "_run_world_creation | RELATION_BATCHES_FAILED | world=%s | "
                            "failed_batches=%d | note=some_relations_may_be_missing",
                            world_id,
                            failed_rel_batches,
                        )

                    wcd(
                        f"[后台任务] 角色生成完成 ✓ {char_count}个角色, {rel_count}条关系"
                        f"{f', {failed_rel_batches}批关系失败' if failed_rel_batches else ''} | "
                        f"生成耗时={t_gen_elapsed:.1f}s | 总耗时={gen_elapsed:.1f}s"
                    )
                    wcd(f"[后台任务] ─── 完成 ─── world_id={world_id}")
                    logger.info(
                        "_run_world_creation | AUTO_GENERATION_SUCCESS | world=%s | "
                        "characters=%d | relations=%d | failed_rel_batches=%d | "
                        "embeddings_built=%s | "
                        "gen_elapsed_sec=%.1f | total_elapsed_sec=%.1f",
                        world_id,
                        char_count,
                        rel_count,
                        failed_rel_batches,
                        embeddings_built,
                        t_gen_elapsed,
                        gen_elapsed,
                    )
                    wcd(
                        f"[_run_world_creation] 角色生成完成: world_id={world_id}, "
                        f"characters={char_count}, relations={rel_count}, 总耗时={gen_elapsed:.1f}s"
                    )
                    try:
                        await request.app.state.redis.set(
                            f"gen_status:{world_id}", "completed", ex=3600
                        )
                    except Exception:
                        pass
            except Exception as e:
                t_gen_elapsed = time.monotonic() - t_gen_start
                gen_elapsed = time.monotonic() - t0
                wcd(f"[后台任务] 角色生成失败 ✗ {type(e).__name__}: {e}")
                wcd(f"[后台任务] ─── 完成(角色生成失败，世界本身已成功) ─── world_id={world_id}")
                logger.exception(
                    "_run_world_creation | AUTO_GENERATION_FAILED | world=%s | "
                    "elapsed_sec=%.1f | total_elapsed_sec=%.1f | error_type=%s | "
                    "note=world_creation_itself_succeeded",
                    world_id,
                    t_gen_elapsed,
                    gen_elapsed,
                    type(e).__name__,
                )
                wcd(f"[_run_world_creation] 角色生成失败: world_id={world_id} (世界创建本身已成功)")
                try:
                    await request.app.state.redis.set(f"gen_status:{world_id}", "failed", ex=3600)
                except Exception:
                    pass
    except Exception as e:
        elapsed = time.monotonic() - t0
        wcd(f"[后台任务] 世界内容构建失败 ✗ {type(e).__name__}: {e}")
        logger.exception(
            "_run_world_creation | CONTENT_BUILD_FAILED | world=%s | elapsed_sec=%.1f | "
            "error_type=%s | next_step=set_world_status_failed",
            world_id,
            elapsed,
            type(e).__name__,
        )
        wcd(f"[_run_world_creation] 失败: world_id={world_id}, 总耗时={elapsed:.1f}s")
        try:
            logger.debug(
                "_run_world_creation | Attempting to set world status to failed | world=%s",
                world_id,
            )
            async with _db_session_mod.async_session() as session:
                await WorldRepository(session).set_status(world_id, "failed")
                await session.commit()
                logger.info("_run_world_creation | STATUS_SET_FAILED | world=%s", world_id)
        except Exception as status_err:
            logger.exception(
                "_run_world_creation | FAILED_TO_SET_STATUS | world=%s | error_type=%s",
                world_id,
                type(status_err).__name__,
            )


@router.post("", status_code=202)
async def create_world(
    req: CreateWorldRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    world_service: WorldService = Depends(get_world_service),
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    t_start = time.monotonic()
    scale = req.scale or DEFAULT_SCALE
    user_language.set(current_user.preferred_language)

    wcd("[创建世界] ═══════════════════════════════════════")
    wcd(
        f'[创建世界] 请求入口 | user_id={current_user.id} | scale={scale} | title="{req.title}" | '
        f'author="{req.author}" | wiki_url="{req.confirmed_wiki_url}" | '
        f"desc_len={len(req.description) if req.description else 0}"
    )

    logger.info(
        "create_world POST START | user_id=%s | scale=%s | title=%s | author=%s | "
        "has_description=%s | has_wiki_url=%s | urls_count=%d | type=%s",
        current_user.id,
        scale,
        req.title,
        req.author or "none",
        bool(req.description),
        bool(req.confirmed_wiki_url),
        len(req.urls or []),
        req.type or "none",
    )

    try:
        logger.debug("create_world | Fetching existing worlds for user | user=%s", current_user.id)
        world_repo = WorldRepository(session)
        worlds = await world_repo.list_by_user(str(current_user.id))
        logger.debug("create_world | User has %d existing worlds", len(worlds))

        # 快速检测 LLM 可用性，失败时在返回 202 之前报错
        wcd("[创建世界] LLM 可用性检测...")
        logger.debug("create_world | Checking LLM availability")
        await world_service.check_llm_available()
        wcd("[创建世界] LLM 可用性检测通过")
        logger.debug("create_world | LLM availability check passed")

        # 创建空存根世界记录（status=creating），立即返回 world_id
        import uuid as _uuid

        world_id = str(_uuid.uuid4())
        wcd(f"[创建世界] 生成 world_id={world_id}")
        logger.info("create_world | Generated world_id | world=%s", world_id)

        source_info = {
            "title": req.title,
            "author": req.author,
            "type": req.type,
            "references": req.urls or [],
        }
        logger.debug("create_world | Creating stub world record | world=%s", world_id)
        await world_repo.create_stub(
            world_id, str(current_user.id), req.title, source_info, scale=req.scale
        )
        logger.debug("create_world | Stub created | world=%s", world_id)

        # 创建世界用户角色（名字/头像随账号，默认人设提示）
        logger.debug(
            "create_world | Creating user character | world=%s | user=%s", world_id, current_user.id
        )
        char_repo = CharacterRepository(session)
        user_char = await char_repo.create(
            world_id,
            CreateCharacterRequest(
                name=current_user.username,
                portrait_url=current_user.avatar_url,
                profile={
                    "brief": (
                        "这是用户在这个世界中的个体。"
                        "请开始构建你与他们的联系吧，或者当一个安静的旁观者窥探他们的世界。"
                    ),
                    "basic": {"tier": "extra"},
                },
            ),
        )
        logger.debug(
            "create_world | User character created | world=%s | char_id=%s", world_id, user_char.id
        )

        logger.debug(
            "create_world | Binding user character to world | world=%s | char_id=%s",
            world_id,
            user_char.id,
        )
        await world_repo.set_user_character(world_id, str(user_char.id))

        # 必须在返回 202 之前显式 commit，否则依赖清理要等 background task 完成后才执行，
        # 导致存根记录对其他 session 不可见，creation-status 轮询持续 404。
        logger.debug("create_world | Committing session before background task")
        await session.commit()
        logger.debug("create_world | Session committed")

        wcd(f"[创建世界] 存根已创建，后台任务入队 → world_id={world_id}")
        logger.debug(
            "create_world | Adding background task for content building | world=%s", world_id
        )
        background_tasks.add_task(
            _run_world_creation,
            request,
            world_id,
            str(current_user.id),
            req.title,
            req.author,
            req.type,
            req.description,
            req.urls or [],
            scale,
            req.detected_work_type,
            current_user.preferred_language,
            req.confirmed_wiki_url,
            req.fast_path,
            None,  # user_llm (no BYOK)
            req.fast_path_characters or None,
        )
        logger.debug("create_world | Background task queued | world=%s", world_id)

        t_elapsed = time.monotonic() - t_start
        logger.info(
            "create_world POST COMPLETED (202) | world=%s | elapsed_sec=%.2f | "
            "status=queued_for_background_processing",
            world_id,
            t_elapsed,
        )
        return {"world_id": world_id}

    except Exception as e:
        t_elapsed = time.monotonic() - t_start
        wcd(f"[创建世界] 请求失败 ✗ {type(e).__name__}: {e}")
        logger.exception(
            "create_world POST FAILED | user=%s | scale=%s | elapsed_sec=%.2f | error_type=%s",
            current_user.id,
            scale,
            t_elapsed,
            type(e).__name__,
        )
        raise


@router.get("/{world_id}/creation-status")
async def get_creation_status(
    world_id: str,
    session: AsyncSession = Depends(get_session),
):
    logger.debug("get_creation_status | POLL START | world=%s", world_id)
    db_status = await WorldRepository(session).get_status(world_id)
    if db_status is None:
        logger.warning("get_creation_status | WORLD_NOT_FOUND | world=%s", world_id)
        raise HTTPException(status_code=404, detail="World not found")
    logger.debug(
        "get_creation_status | DB_STATUS_RETRIEVED | world=%s | db_status=%s", world_id, db_status
    )
    if db_status == "active":
        logger.debug("get_creation_status | POLL_RESULT | world=%s | result=ready", world_id)
        return {"status": "ready"}
    if db_status == "failed":
        logger.warning("get_creation_status | POLL_RESULT | world=%s | result=failed", world_id)
        return {"status": "failed"}
    logger.debug("get_creation_status | POLL_RESULT | world=%s | result=creating", world_id)
    return {"status": "creating"}


@router.get("/templates")
async def list_world_templates(
    world_service: WorldService = Depends(get_world_service),
):
    """返回模板列表，无需认证。"""
    return world_service.list_templates()


@router.post("/create-from-template", response_model=WorldDoc, status_code=201)
async def create_from_template(
    req: CreateFromTemplateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    world_service: WorldService = Depends(get_world_service),
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """从模板创建世界，需认证。"""
    scale = req.scale or DEFAULT_SCALE
    user_language.set(current_user.preferred_language)
    world_repo = WorldRepository(session)

    # Create repos for template preset data
    char_repo = CharacterRepository(session)
    rel_repo = RelationRepository(session)

    world = await world_service.create_from_template(
        template_id=req.template_id,
        scale=scale,
        user_id=str(current_user.id),
        preferred_language=current_user.preferred_language,
        char_repo=char_repo,
        rel_repo=rel_repo,
    )

    # Create the world's user character (represents the user in this world)
    user_char = await char_repo.create(
        world.world_id,
        CreateCharacterRequest(
            name=current_user.username,
            portrait_url=current_user.avatar_url,
            profile={
                "brief": (
                    "这是用户在这个世界中的个体。"
                    "请开始构建你与他们的联系吧，或者当一个安静的旁观者窥探他们的世界。"
                ),
                "basic": {"tier": "extra"},
            },
        ),
    )
    await world_repo.set_user_character(world.world_id, str(user_char.id))
    world.user_character_id = str(user_char.id)

    await session.commit()

    # 后台补全：common_sense + 快照 + 嵌入向量
    background_tasks.add_task(
        _run_template_post_creation,
        request,
        world.world_id,
        world.source.plot_summary or "",
        scale,
        current_user.preferred_language,
    )

    return world


async def _run_template_post_creation(
    request: Request,
    world_id: str,
    plot_summary: str,
    scale: str,
    preferred_language: str = "zh-CN",
):
    """后台任务：模板世界创建后补全快照、嵌入向量。全程无 LLM 调用。"""
    from src.db.repositories.character_memory_repo import CharacterMemoryRepository
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.relation_repo import RelationRepository
    from src.db.repositories.version_repo import VersionRepository
    from src.services.snapshot_sync_service import bump_generation_sql, publish_snapshot_dirty
    from src.services.version_service import VersionService

    user_language.set(preferred_language)
    try:
        async with _db_session_mod.async_session() as session:
            # 1. 补全 common_sense（模板世界直接用 plot_summary，无需 LLM）
            world_repo = WorldRepository(session)
            world_doc = await world_repo.get(world_id)
            if world_doc and not world_doc.source.common_sense and plot_summary:
                world_doc.source.common_sense = plot_summary
                await world_repo.save(world_doc, None)
                await session.commit()
                logger.info(
                    "_run_template_post_creation | common_sense set from plot_summary | "
                    "world=%s | len=%d",
                    world_id,
                    len(plot_summary),
                )

            # 2. 创建初始快照
            try:
                char_repo = CharacterRepository(session)
                rel_repo = RelationRepository(session)
                mem_repo = CharacterMemoryRepository(session)
                version_repo = VersionRepository(session)
                version_service = VersionService(
                    version_repo=version_repo,
                    character_repo=char_repo,
                    relation_repo=rel_repo,
                    session=session,
                    memory_repo=mem_repo,
                )
                await bump_generation_sql(world_id, session)
                await version_service.create_snapshot(
                    world_id, created_by="template", summary="从模板创建世界"
                )
                await session.commit()
                logger.info("_run_template_post_creation | snapshot created | world=%s", world_id)
            except Exception:
                logger.warning(
                    "_run_template_post_creation | snapshot creation failed | world=%s",
                    world_id,
                    exc_info=True,
                )

        # 3. 重建嵌入向量（独立 session）
        embedding_provider = getattr(request.app.state, "embedding_provider", None)
        if embedding_provider:
            try:
                async with _db_session_mod.async_session() as emb_session:
                    retrieval_svc = build_element_retrieval_from_session(
                        emb_session, embedding_provider
                    )
                    await retrieval_svc.rebuild_embeddings(world_id)
                    await emb_session.commit()
                    logger.info(
                        "_run_template_post_creation | embeddings rebuilt | world=%s", world_id
                    )
            except Exception:
                logger.warning(
                    "_run_template_post_creation | embedding rebuild failed | world=%s",
                    world_id,
                    exc_info=True,
                )

        # 4. 通知快照同步服务
        try:
            await publish_snapshot_dirty(request.app.state.redis, world_id, "template_creation")
        except Exception:
            pass

    except Exception:
        logger.warning(
            "_run_template_post_creation | failed | world=%s",
            world_id,
            exc_info=True,
        )


async def _run_background_generation(
    request: Request, world_id: str, scale: str, language: str = "zh-CN", user_llm=None
):
    """Generate characters with its own DB session."""
    t0 = time.monotonic()
    user_language.set(language)
    redis = request.app.state.redis
    _gen_ttl = 3600  # 1 hour
    logger.info(
        "_run_background_generation START | world=%s | scale=%s | language=%s",
        world_id,
        scale,
        language,
    )
    try:
        await redis.set(f"gen_status:{world_id}", "generating", ex=_gen_ttl)
        logger.debug(
            "_run_background_generation | Redis status set to generating | world=%s", world_id
        )
    except Exception as redis_err:
        logger.warning(
            "_run_background_generation | Redis unavailable | world=%s | error_type=%s",
            world_id,
            type(redis_err).__name__,
        )
    try:
        logger.debug("_run_background_generation | Creating DB session | world=%s", world_id)
        async with _db_session_mod.async_session() as session:
            t_build_start = time.monotonic()
            logger.debug(
                "_run_background_generation | Initializing repositories and services | world=%s",
                world_id,
            )
            generation_service, _gen_graph = build_bg_generation_services(
                session,
                extraction_service=request.app.state.extraction_service,
                search_service=request.app.state.search_service,
                material_service=request.app.state.material_service,
                llm=request.app.state.llm,
                user_llm=user_llm,
                redis=getattr(request.app.state, "redis", None),
            )

            logger.debug(
                "_run_background_generation | Calling generation_service.generate() | world=%s",
                world_id,
            )
            # 从 Redis 读取 char_candidates（由 build_world_content 写入）
            char_candidates = None
            try:
                import json as _json

                raw = await redis.get(f"char_candidates:{world_id}")
                if raw:
                    char_candidates = _json.loads(raw)
                    logger.debug(
                        "_run_background_generation | Loaded char_candidates from Redis | "
                        "world=%s | count=%d",
                        world_id,
                        len(char_candidates),
                    )
            except Exception:
                pass
            result = await generation_service.generate(
                world_id, scale=scale, char_candidates=char_candidates
            )
            t_gen_elapsed = time.monotonic() - t_build_start
            logger.debug(
                "_run_background_generation | generation_service.generate() completed | "
                "world=%s | elapsed_sec=%.1f",
                world_id,
                t_gen_elapsed,
            )

            logger.debug("_run_background_generation | Committing session | world=%s", world_id)
            await session.commit()
            # 通知快照同步服务：generation 已更新
            try:
                await publish_snapshot_dirty(redis, world_id, "world_generation")
            except Exception:
                pass

            # Rebuild embeddings after successful character re-generation
            embedding_provider = getattr(request.app.state, "embedding_provider", None)
            if embedding_provider:
                try:
                    async with _db_session_mod.async_session() as emb_session:
                        retrieval_svc = build_element_retrieval_from_session(
                            emb_session, embedding_provider
                        )
                        await retrieval_svc.rebuild_embeddings(world_id)
                        await emb_session.commit()
                except Exception as emb_err:
                    logger.warning(
                        "_run_background_generation | embedding rebuild failed (non-fatal) | "
                        "world=%s | error_type=%s",
                        world_id,
                        type(emb_err).__name__,
                    )

            char_count = result.get("characters", 0)
            rel_count = result.get("relations", 0)
            failed_rel_batches = result.get("failed_rel_batches", 0)

            if failed_rel_batches > 0:
                logger.warning(
                    "_run_background_generation | RELATION_BATCHES_FAILED | world=%s | "
                    "failed_batches=%d | note=some_relations_may_be_missing",
                    world_id,
                    failed_rel_batches,
                )

            try:
                await redis.set(f"gen_status:{world_id}", "completed", ex=_gen_ttl)
                logger.debug(
                    "_run_background_generation | Redis status set to completed | world=%s",
                    world_id,
                )
            except Exception as redis_err:
                logger.warning(
                    "_run_background_generation | Failed to set Redis "
                    "completion status | world=%s | error_type=%s",
                    world_id,
                    type(redis_err).__name__,
                )

            elapsed = time.monotonic() - t0
            logger.info(
                "_run_background_generation COMPLETED | world=%s | characters=%d | relations=%d | "
                "failed_rel_batches=%d | gen_elapsed_sec=%.1f | total_elapsed_sec=%.1f",
                world_id,
                char_count,
                rel_count,
                failed_rel_batches,
                t_gen_elapsed,
                elapsed,
            )
    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.exception(
            "_run_background_generation FAILED | world=%s | elapsed_sec=%.1f | error_type=%s",
            world_id,
            elapsed,
            type(e).__name__,
        )
        try:
            await redis.set(f"gen_status:{world_id}", "failed", ex=_gen_ttl)
            logger.debug(
                "_run_background_generation | Redis status set to failed | world=%s", world_id
            )
        except Exception as redis_err:
            logger.warning(
                "_run_background_generation | Failed to set Redis "
                "failure status | world=%s | error_type=%s",
                world_id,
                type(redis_err).__name__,
            )


@router.post("/{world_id}/generate-characters", status_code=202)
async def generate_characters_background(
    world_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    scale: str = Query(DEFAULT_SCALE),
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    t_start = time.monotonic()
    logger.info(
        "generate_characters_background POST START | world=%s | user=%s | scale=%s | language=%s",
        world_id,
        current_user.id,
        scale,
        current_user.preferred_language,
    )

    try:
        logger.debug(
            "generate_characters_background | Checking LLM configuration | world=%s", world_id
        )
        if not request.app.state.llm:
            logger.error("generate_characters_background | LLM not configured | world=%s", world_id)
            raise HTTPException(status_code=503, detail="LLM not configured")
        logger.debug("generate_characters_background | LLM configured")

        logger.debug(
            "generate_characters_background | Fetching existing characters | world=%s", world_id
        )
        char_repo = CharacterRepository(session)
        existing = await char_repo.list_by_world(world_id)
        logger.debug(
            "generate_characters_background | Existing characters count | world=%s | count=%d",
            world_id,
            len(existing),
        )

        # 使用默认 LLM
        default_llm = getattr(request.app.state, "llm", None)

        logger.debug(
            "generate_characters_background | Queuing background task | world=%s | scale=%s",
            world_id,
            scale,
        )
        background_tasks.add_task(
            _run_background_generation,
            request,
            world_id,
            scale,
            current_user.preferred_language,
            default_llm,
        )

        t_elapsed = time.monotonic() - t_start
        logger.info(
            "generate_characters_background POST COMPLETED (202) "
            "| world=%s | user=%s | elapsed_sec=%.2f | "
            "status=queued_for_generation",
            world_id,
            current_user.id,
            t_elapsed,
        )
        return {"status": "generating", "world_id": world_id}
    except Exception as e:
        t_elapsed = time.monotonic() - t_start
        logger.exception(
            "generate_characters_background POST FAILED | world=%s | user=%s | scale=%s | "
            "elapsed_sec=%.2f | error_type=%s",
            world_id,
            current_user.id,
            scale,
            t_elapsed,
            type(e).__name__,
        )
        raise


@router.get("/{world_id}/generate-characters/status")
async def get_generation_status(world_id: str, request: Request):
    logger.debug("get_generation_status | STATUS_POLL_START | world=%s", world_id)
    try:
        val = await request.app.state.redis.get(f"gen_status:{world_id}")
        if val is None:
            logger.debug(
                "get_generation_status | STATUS_POLL_RESULT | world=%s | result=idle", world_id
            )
            return {"status": "idle"}
        status = val.decode() if isinstance(val, bytes) else val
        logger.debug(
            "get_generation_status | STATUS_POLL_RESULT | world=%s | result=%s", world_id, status
        )
        return {"status": status}
    except Exception as e:
        logger.exception(
            "get_generation_status | REDIS_POLL_FAILED | world=%s | error_type=%s",
            world_id,
            type(e).__name__,
        )
        logger.debug("get_generation_status | Returning fallback idle status | world=%s", world_id)
        return {"status": "idle"}


@router.post("/{world_id}/copy", response_model=WorldDoc, status_code=201)
async def copy_world(
    world_id: str,
    request: Request,
    world_service: WorldService = Depends(get_world_service),
    current_user: M9User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    world_repo = WorldRepository(session)
    try:
        result = await world_service.copy_world(world_id, user_id=str(current_user.id))
        # Trigger async embedding rebuild for the new world
        embedding_provider = getattr(request.app.state, "embedding_provider", None)
        if embedding_provider and result:
            import asyncio as _asyncio

            async def _rebuild_clone_embeddings(new_world_id: str):
                try:
                    async with _db_session_mod.async_session() as emb_session:
                        retrieval_svc = build_element_retrieval_from_session(
                            emb_session, embedding_provider
                        )
                        await retrieval_svc.rebuild_embeddings(new_world_id)
                        await emb_session.commit()
                except Exception:
                    logger.warning(
                        "clone embedding rebuild failed (non-fatal) world=%s",
                        new_world_id,
                        exc_info=True,
                    )

            _asyncio.create_task(_rebuild_clone_embeddings(result.world_id))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("", response_model=list[WorldDoc])
async def list_worlds(
    world_service: WorldService = Depends(get_world_service),
    current_user: M9User = Depends(get_current_user),
):
    return await world_service.list_worlds(user_id=str(current_user.id))


@router.get("/{world_id}", response_model=WorldDoc)
async def get_world(
    world_id: str,
    request: Request,
    response: Response,
    world_service: WorldService = Depends(get_world_service),
):
    result = await world_service.get_world_with_updated_at(world_id)
    if result is None:
        raise HTTPException(status_code=404, detail="World not found")
    world, last_mod = result
    not_mod = check_not_modified(request, last_mod)
    if not_mod:
        return not_mod
    set_cache_headers(response, last_mod, public=True)
    return world


@router.patch("/{world_id}/plot-summary", status_code=204)
async def update_plot_summary(
    world_id: str,
    req: UpdatePlotSummaryRequest,
    world_service: WorldService = Depends(get_world_service),
):
    ok = await world_service.update_plot_summary(world_id, req.plot_summary)
    if not ok:
        raise HTTPException(status_code=404, detail="World not found")


@router.patch("/{world_id}/common-sense", status_code=204)
async def update_common_sense(
    world_id: str,
    req: UpdateCommonSenseRequest,
    world_service: WorldService = Depends(get_world_service),
):
    ok = await world_service.update_common_sense(world_id, req.common_sense)
    if not ok:
        raise HTTPException(status_code=404, detail="World not found")


@router.patch("/{world_id}/core-conflict", status_code=204)
async def update_core_conflict(
    world_id: str,
    req: UpdateCoreConflictRequest,
    world_service: WorldService = Depends(get_world_service),
):
    ok = await world_service.update_core_conflict(world_id, req.core_conflict)
    if not ok:
        raise HTTPException(status_code=404, detail="World not found")


@router.patch("/{world_id}/tone-and-atmosphere", status_code=204)
async def update_tone_and_atmosphere(
    world_id: str,
    req: UpdateToneAndAtmosphereRequest,
    world_service: WorldService = Depends(get_world_service),
):
    ok = await world_service.update_tone_and_atmosphere(world_id, req.tone_and_atmosphere)
    if not ok:
        raise HTTPException(status_code=404, detail="World not found")


@router.patch("/{world_id}/plot-development", status_code=204)
async def update_plot_development(
    world_id: str,
    req: UpdatePlotDevelopmentRequest,
    world_service: WorldService = Depends(get_world_service),
):
    ok = await world_service.update_plot_development(world_id, req.plot_development)
    if not ok:
        raise HTTPException(status_code=404, detail="World not found")


@router.patch("/{world_id}/title", status_code=204)
async def update_world_title(
    world_id: str,
    req: UpdateTitleRequest,
    world_service: WorldService = Depends(get_world_service),
):
    ok = await world_service.update_title(world_id, req.title)
    if not ok:
        raise HTTPException(status_code=404, detail="World not found")


@router.delete("/{world_id}", status_code=204)
async def delete_world(
    world_id: str,
    world_service: WorldService = Depends(get_world_service),
):
    deleted = await world_service.delete_world(world_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="World not found")
