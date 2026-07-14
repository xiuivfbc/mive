from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.db.models import M9User
    from src.llm.base import LLMProvider
    from src.llm.embedding_provider import EmbeddingProvider
    from src.services.element_retrieval_service import ElementRetrievalService
    from src.services.extraction_service import ExtractionService
    from src.services.search_service import SearchService

from src.config import settings
from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.chat_session_repo import ChatSessionRepository
from src.db.repositories.event_repo import EventRepository
from src.db.repositories.message_repo import MessageRepository
from src.db.repositories.relation_repo import RelationRepository
from src.db.repositories.version_repo import VersionRepository
from src.db.repositories.world_repo import WorldRepository
from src.db.session import get_session
from src.services.character_service import CharacterService
from src.services.chat_session_service import ChatSessionService
from src.services.dialogue_generation_service import DialogueGenerationService
from src.services.event_service import EventService
from src.services.generation_service import GenerationService
from src.services.material_service import MaterialService
from src.services.matterbridge_service import MatterBridgeService
from src.services.message_service import MessageService
from src.services.relation_service import RelationService
from src.services.version_service import VersionService
from src.services.world_service import WorldService

# ---------------------------------------------------------------------------
# Singleton services (from app.state, set during lifespan)
# ---------------------------------------------------------------------------


def _get_app_state(request: Request, name: str):
    """Safely get a service from app.state. Returns None if not set."""
    return getattr(request.app.state, name, None)


def get_material_service(request: Request) -> MaterialService:
    svc = _get_app_state(request, "material_service")
    if svc is not None:
        return svc
    return MaterialService()


# ---------------------------------------------------------------------------
# Shared dependency graph — avoids repeating repo/service construction
# ---------------------------------------------------------------------------


@dataclass
class _M2Graph:
    """Reusable M2 dependency sub-graph: char_repo + relation_repo + version_service."""

    char_repo: CharacterRepository
    relation_repo: RelationRepository
    version_service: VersionService
    character_service: CharacterService


def _build_m2_graph(session: AsyncSession) -> _M2Graph:
    from src.db.repositories.character_memory_repo import CharacterMemoryRepository

    char_repo = CharacterRepository(session)
    relation_repo = RelationRepository(session)
    character_service = CharacterService(char_repo, session=session)
    version_service = VersionService(
        VersionRepository(session),
        char_repo,
        relation_repo,
        session=session,
        memory_repo=CharacterMemoryRepository(session),
        character_service=character_service,
    )
    return _M2Graph(
        char_repo=char_repo,
        relation_repo=relation_repo,
        version_service=version_service,
        character_service=character_service,
    )


def build_element_retrieval_from_session(
    session: AsyncSession, embedding_provider: EmbeddingProvider | None
) -> ElementRetrievalService | None:
    """Public builder: construct ElementRetrievalService from a session + provider.

    Use this in background tasks and standalone code that doesn't have a Request.
    Returns None if embedding_provider is None.
    """
    if embedding_provider is None:
        return None
    from src.db.repositories.embedding_repo import EmbeddingRepository
    from src.services.element_retrieval_service import ElementRetrievalService

    return ElementRetrievalService(  # type: ignore[return-value]
        embedding_provider=embedding_provider,
        embedding_repo=EmbeddingRepository(session),
        world_repo=WorldRepository(session),
        character_repo=CharacterRepository(session),
        retrieval_top_k=settings.retrieval_top_k,
        retrieval_bm25_top_k=settings.retrieval_bm25_top_k,
        retrieval_vec_top_k=settings.retrieval_vec_top_k,
        retrieval_bm25_rrf_k=settings.retrieval_bm25_rrf_k,
        retrieval_vec_rrf_k=settings.retrieval_vec_rrf_k,
    )


def _build_element_retrieval(request: Request, session: AsyncSession):
    """Shared ElementRetrievalService construction. Returns None if no embedding provider."""
    embedding_provider = _get_app_state(request, "embedding_provider")
    return build_element_retrieval_from_session(session, embedding_provider)


# ---------------------------------------------------------------------------
# Background task service graph — for functions that run outside the request cycle
# ---------------------------------------------------------------------------


@dataclass
class _BGServiceGraph:
    """Service graph for background tasks (world creation, generation, etc.)."""

    char_repo: CharacterRepository
    relation_repo: RelationRepository
    version_service: VersionService
    character_service: CharacterService
    world_service: WorldService


def build_bg_world_services(
    session: AsyncSession,
    *,
    extraction_service: ExtractionService | None = None,
    search_service: SearchService | None = None,
    llm: LLMProvider | None = None,
    user_llm: LLMProvider | None = None,
) -> tuple[WorldService, CharacterRepository]:
    """Build WorldService for background tasks (world creation phase)."""
    effective_llm = user_llm or llm
    if user_llm is not None:
        from src.services.extraction_service import ExtractionService

        extraction = ExtractionService(llm=user_llm)
    else:
        extraction = extraction_service

    world_service = WorldService(
        repo=WorldRepository(session),
        extraction=extraction,
        search=search_service,
        llm=effective_llm,
    )
    char_repo = CharacterRepository(session)
    return world_service, char_repo


def build_bg_generation_services(
    session: AsyncSession,
    *,
    extraction_service: ExtractionService | None = None,
    search_service: SearchService | None = None,
    material_service: MaterialService | None = None,
    llm: LLMProvider | None = None,
    user_llm: LLMProvider | None = None,
    redis: Redis | None = None,
) -> tuple[GenerationService, _BGServiceGraph]:
    """Build GenerationService + full graph for background tasks (generation phase)."""
    from src.db.repositories.character_memory_repo import CharacterMemoryRepository

    char_repo = CharacterRepository(session)
    relation_repo = RelationRepository(session)
    version_service = VersionService(
        version_repo=VersionRepository(session),
        character_repo=char_repo,
        relation_repo=relation_repo,
        session=session,
        memory_repo=CharacterMemoryRepository(session),
    )
    character_service = CharacterService(
        repo=char_repo,
        session=session,
        redis=redis,
    )
    world_service = WorldService(
        repo=WorldRepository(session),
        extraction=extraction_service,
        search=search_service,
        llm=user_llm or llm,
    )

    generation_service = GenerationService(
        llm=cast("LLMProvider", user_llm or llm),
        material_service=cast(MaterialService, material_service),
        world_service=world_service,
        character_repo=char_repo,
        relation_repo=relation_repo,
        version_service=version_service,
        session=session,
        search_service=search_service,
        redis=redis,
        character_service=character_service,
    )

    graph = _BGServiceGraph(
        char_repo=char_repo,
        relation_repo=relation_repo,
        version_service=version_service,
        character_service=character_service,
        world_service=world_service,
    )
    return generation_service, graph


# ---------------------------------------------------------------------------
# Per-request services (shared session via Depends(get_session))
# ---------------------------------------------------------------------------


def _build_world_service(request: Request, session: AsyncSession) -> WorldService:
    return WorldService(
        repo=WorldRepository(session),
        extraction=_get_app_state(request, "extraction_service"),
        search=_get_app_state(request, "search_service"),
        llm=_get_app_state(request, "llm"),
        sub_llm=_get_app_state(request, "sub_llm"),
    )


async def get_world_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[WorldService, None]:
    override = _get_app_state(request, "world_service")
    if override is not None:
        yield override
        return
    yield _build_world_service(request, session)


async def get_character_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[CharacterService, None]:
    override = _get_app_state(request, "character_service")
    if override is not None:
        yield override
        return
    yield CharacterService(
        repo=CharacterRepository(session),
        session=session,
        redis=getattr(request.app.state, "redis", None),
    )


async def get_relation_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[RelationService, None]:
    override = _get_app_state(request, "relation_service")
    if override is not None:
        yield override
        return
    yield RelationService(
        repo=RelationRepository(session),
        character_repo=CharacterRepository(session),
    )


async def get_version_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[VersionService, None]:
    override = _get_app_state(request, "version_service")
    if override is not None:
        yield override
        return
    g = _build_m2_graph(session)
    yield g.version_service


async def get_generation_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[GenerationService, None]:
    override = _get_app_state(request, "generation_service")
    if override is not None:
        yield override
        return
    g = _build_m2_graph(session)
    world_svc = _get_app_state(request, "world_service") or _build_world_service(request, session)
    yield GenerationService(
        llm=_get_app_state(request, "llm"),
        material_service=get_material_service(request),
        world_service=world_svc,
        character_repo=g.char_repo,
        relation_repo=g.relation_repo,
        version_service=g.version_service,
        session=session,
        search_service=_get_app_state(request, "search_service"),
        character_service=g.character_service,
    )


async def get_event_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[EventService, None]:
    override = _get_app_state(request, "event_service")
    if override is not None:
        yield override
        return
    yield EventService(
        event_repo=EventRepository(session),
    )


async def get_element_retrieval_service(
    request: Request, session: AsyncSession = Depends(get_session)
):
    """Build ElementRetrievalService with embedding provider from app.state."""
    return _build_element_retrieval(request, session)


async def get_event_dialogue_service(
    request: Request, session: AsyncSession = Depends(get_session)
):
    override = _get_app_state(request, "event_dialogue_service")
    if override is not None:
        return override

    from src.db.repositories.character_memory_repo import CharacterMemoryRepository
    from src.db.session import async_session as SessionLocal  # noqa: N812
    from src.services.event_dialogue_service import EventDialogueService

    llm = _get_app_state(request, "llm")
    sub_llm = _get_app_state(request, "sub_llm")

    element_retrieval_svc = _build_element_retrieval(request, session)

    redis = getattr(request.app.state, "redis", None)

    # Shared memory module
    from src.services.memory_module import MemoryModule

    memory_module = MemoryModule(llm=llm, session_factory=SessionLocal, redis=redis)

    # Memory propagation service
    from src.services.memory_propagation_service import MemoryPropagationService

    memory_propagation_service = MemoryPropagationService(
        llm=llm, session_factory=SessionLocal, redis=redis
    )

    # Memory orchestrator
    from src.services.memory_orchestrator import MemoryOrchestrator

    memory_orchestrator = MemoryOrchestrator(
        memory_module=memory_module,
        memory_propagation_service=memory_propagation_service,
    )

    return EventDialogueService(
        llm=llm,
        character_repo=CharacterRepository(session),
        message_repo=MessageRepository(session),
        event_repo=EventRepository(session),
        world_repo=WorldRepository(session),
        session_factory=SessionLocal,
        memory_repo=CharacterMemoryRepository(session),
        redis=redis,
        element_retrieval_service=element_retrieval_svc,
        memory_orchestrator=memory_orchestrator,
        select_llm=sub_llm,
        rerank_llm=sub_llm,
        rerank_provider=_get_app_state(request, "rerank_provider"),
    )


async def get_message_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[MessageService, None]:
    override = _get_app_state(request, "message_service")
    if override is not None:
        yield override
        return
    llm = _get_app_state(request, "llm")
    dialogue_service = None
    if llm:
        from src.db.repositories.character_memory_repo import CharacterMemoryRepository

        element_retrieval_svc = _build_element_retrieval(request, session)

        # 副模型（判断类调用：选角 + 元素精排）。BYOK 短路在 API 层处理（has user ctx）。
        sub_llm = _get_app_state(request, "sub_llm") or llm
        dialogue_service = DialogueGenerationService(
            llm=llm,
            character_repo=CharacterRepository(session),
            message_repo=MessageRepository(session),
            world_repo=WorldRepository(session),
            memory_repo=CharacterMemoryRepository(session),
            relation_repo=RelationRepository(session),
            element_retrieval_service=element_retrieval_svc,
            rerank_llm=sub_llm,
            select_llm=sub_llm,
            rerank_provider=_get_app_state(request, "rerank_provider"),
        )
    from src.db.session import async_session as SessionLocal  # noqa: N812

    redis = getattr(request.app.state, "redis", None)

    # Shared memory module
    from src.services.memory_module import MemoryModule

    memory_module = MemoryModule(llm=llm, session_factory=SessionLocal, redis=redis)

    # Memory propagation service
    from src.services.memory_propagation_service import MemoryPropagationService

    memory_propagation_service = MemoryPropagationService(
        llm=llm, session_factory=SessionLocal, redis=redis
    )

    # Memory orchestrator
    from src.services.memory_orchestrator import MemoryOrchestrator

    memory_orchestrator = MemoryOrchestrator(
        memory_module=memory_module,
        memory_propagation_service=memory_propagation_service,
    )

    yield MessageService(
        message_repo=MessageRepository(session),
        dialogue_service=dialogue_service,
        llm=llm,
        session_factory=SessionLocal,
        chat_session_repo=ChatSessionRepository(session),
        redis=getattr(request.app.state, "redis", None),
        version_repo=VersionRepository(session),
        character_repo=CharacterRepository(session),
        memory_orchestrator=memory_orchestrator,
    )


async def get_chat_session_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AsyncGenerator[ChatSessionService, None]:
    yield ChatSessionService(
        chat_session_repo=ChatSessionRepository(session),
        message_repo=MessageRepository(session),
        character_repo=CharacterRepository(session),
        redis=getattr(request.app.state, "redis", None),
    )


async def get_matterbridge_service(
    request: Request, session: AsyncSession = Depends(get_session)
) -> MatterBridgeService:
    """Build or reuse MatterBridgeService from app.state.

    During lifespan the singleton is stored on app.state.matterbridge_service.
    Fallback: build a per-request instance (e.g. in tests).
    """
    override = _get_app_state(request, "matterbridge_service")
    if override is not None:
        return override
    from src.db.repositories.matterbridge_repo import MatterbridgeBridgeRepository

    return MatterBridgeService(
        repo=MatterbridgeBridgeRepository(session),
        key_secret=settings.secret_encryption_key or ("0" * 64),
        session_factory=None,
    )


# ---------------------------------------------------------------------------
# M9 Auth — simplified JWT verification
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

PERMANENT_ADMIN_USER_ID = uuid.UUID("b1a2c3d4-e5f6-7890-abcd-0123456789ab")


async def get_current_user(
    session: AsyncSession = Depends(get_session),
):
    """开源单人自托管：无需登录，所有请求都以固定的管理员账号身份处理。"""
    from src.db.repositories.user_repo import UserRepository

    user_repo = UserRepository(session)
    user: M9User | None = await user_repo.get_by_id(PERMANENT_ADMIN_USER_ID)
    if user is None:
        raise HTTPException(status_code=503, detail="管理员账号尚未初始化")
    return user


def is_admin(user: M9User) -> bool:
    return user.is_admin


async def get_admin_user(
    current_user: M9User = Depends(get_current_user),
) -> M9User:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user
