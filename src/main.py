import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from src.log_filters import AccessLogFilter, ExcludeErrorFilter

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

# backend.log — INFO~WARNING only (ERROR+ goes to errors.log)
_file_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "backend.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)
_file_handler.addFilter(ExcludeErrorFilter())

# errors.log — ERROR and above (tracebacks, unhandled exceptions)
_error_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "errors.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_error_handler.setFormatter(_fmt)
_error_handler.setLevel(logging.ERROR)

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _error_handler])

# llm_tokens.log — JSON Lines，每行一次 LLM 调用的 token 统计
_token_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "llm_tokens.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_token_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_token_lg = logging.getLogger("llm.tokens")
_token_lg.setLevel(logging.INFO)
_token_lg.addHandler(_token_handler)
_token_lg.propagate = False  # 不往 backend.log 里混

# tavily_cache.log — 每行一次 Redis 命中记录
_tavily_cache_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "tavily_cache.log"),
    maxBytes=2 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_tavily_cache_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_tavily_cache_lg = logging.getLogger("tavily.cache")
_tavily_cache_lg.setLevel(logging.INFO)
_tavily_cache_lg.addHandler(_tavily_cache_handler)
_tavily_cache_lg.propagate = False  # 不往 backend.log 里混

logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# 模块级挂载，reloader 进程和 worker 进程均生效
_access_filter = AccessLogFilter()
for _name in ("uvicorn", "uvicorn.access"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.INFO)
    _lg.addFilter(_access_filter)
    if not any(isinstance(h, RotatingFileHandler) for h in _lg.handlers):
        _lg.addHandler(_file_handler)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from src.api import (  # noqa: E402
    admin,
    admin_config,
    auth,
    character_material,
    characters,
    chat_sessions,
    discord_bridge,
    elements,
    events,
    graph,
    graph_command,
    guide,
    import_,
    m6_graph,
    matterbridge,
    memories,
    messages,
    relations,
    versions,
    welcome_quotes,
    worlds,
)
from src.config import settings  # noqa: E402
from src.db.session import async_session as _async_session_factory  # noqa: E402
from src.llm.base import LLMQuotaExhaustedError  # noqa: E402
from src.llm.factory import create_llm_auto  # noqa: E402
from src.services.extraction_service import ExtractionService  # noqa: E402
from src.services.material_service import MaterialService  # noqa: E402
from src.services.search_service import MockSearchService, SearchService  # noqa: E402

_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
_ADMIN_USER_ID = uuid.UUID("b1a2c3d4-e5f6-7890-abcd-0123456789ab")


async def _bootstrap_admin() -> None:
    """Create the permanent admin account if it doesn't exist."""
    from src.db.models import M9User

    async with _async_session_factory() as session:
        # Looked up by the fixed permanent ID (not username), since get_current_user
        # always resolves to this ID regardless of what username ended up on the row
        # (e.g. a pre-existing account created under the old registration flow before
        # login was removed).
        admin = await session.get(M9User, _ADMIN_USER_ID)
        if admin is None:
            import bcrypt
            hashed_password = bcrypt.hashpw(_ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
            admin = M9User(
                id=_ADMIN_USER_ID,
                username=_ADMIN_USERNAME,
                email=f"{_ADMIN_USERNAME}@localhost",
                hashed_password=hashed_password,
                preferred_language="zh-CN",
                is_admin=True,
                is_staff=True,
            )
            session.add(admin)
            logging.getLogger(__name__).info("Admin account bootstrapped: %s", _ADMIN_USERNAME)
        else:
            changed = False
            if not admin.is_staff:
                admin.is_staff = True
                changed = True
            if not admin.is_admin:
                admin.is_admin = True
                changed = True
            if changed:
                logging.getLogger(__name__).info(
                    "Admin flags ensured for existing account: %s", admin.username
                )

        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # lifespan 只在 worker 进程里执行，不在 reloader 里执行，避免日志重复
    # uvicorn.error propagate=True 会冒泡到 uvicorn，不需单独挂
    # uvicorn.access propagate=False 需单独挂
    for _name in ("uvicorn", "uvicorn.access", ""):
        _lg = logging.getLogger(_name)
        _lg.setLevel(logging.INFO)
        if not any(h is _file_handler for h in _lg.handlers):
            _lg.addHandler(_file_handler)
        if not any(h is _error_handler for h in _lg.handlers):
            _lg.addHandler(_error_handler)

    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis_client

    # 应用管理员在 /api/admin/config 面板持久化的 LLM/embedding 配置覆盖，
    # 否则每次进程重启都会静默丢弃管理员配置、退回 .env 默认值
    from src.services.admin_config_service import apply_persisted_overrides

    try:
        async with _async_session_factory() as _config_session:
            await apply_persisted_overrides(_config_session)
    except Exception:
        logging.getLogger(__name__).error(
            "加载管理员持久化配置失败，回退到 .env 默认值启动", exc_info=True
        )

    api_key = settings.llm_api_key
    _is_mock = settings.llm_provider == "mock"

    # 主副模型共享 gate：同一 API key 时避免两个独立 gate 合计超过上游 RPM 限制
    from src.llm.rate_limit_gate import RateLimitGate

    _shared_gate: RateLimitGate | None = None
    if api_key and settings.sub_llm_api_key and api_key == settings.sub_llm_api_key:
        _shared_gate = RateLimitGate(
            rpm=settings.llm_rpm if settings.llm_rpm > 0 else None,
            max_retries=settings.llm_max_retries if settings.llm_max_retries is not None else 2,
            max_inflight=settings.llm_max_inflight if settings.llm_max_inflight > 0 else None,
        )
        logging.getLogger(__name__).info(
            "主副模型共享同一 API key，使用共享 RateLimitGate (rpm=%s)",
            _shared_gate.rpm,
        )

    llm = (
        await create_llm_auto(
            settings.llm_provider,
            api_key,
            settings.llm_model or None,
            settings.llm_base_url or None,
            max_retries=0,  # SDK 不重试，由 RateLimitGate 统一管理
            gate=_shared_gate,
            api_format=settings.llm_api_format or None,
        )
        if (api_key or _is_mock)
        else None
    )
    # 副模型（判断/分类类调用）— 空 key 自动回落主模型；独立 gate
    from src.llm.submodel import build_sub_llm

    sub_llm = await build_sub_llm(
        main_llm=llm,
        api_key=settings.sub_llm_api_key,
        base_url=settings.sub_llm_base_url,
        model=settings.sub_llm_model,
        provider=settings.sub_llm_provider or settings.llm_provider,
        rpm=settings.sub_llm_rpm,
        max_inflight=settings.sub_llm_max_inflight,
        gate=_shared_gate,
        api_format=settings.sub_llm_api_format or None,
    )

    extraction = ExtractionService(llm=llm) if llm else None
    if _is_mock:
        search = MockSearchService()
    elif settings.tavily_api_key:
        search = SearchService(api_key=settings.tavily_api_key, redis=redis_client)
    else:
        search = None
    material = MaterialService()

    # Embedding provider for vector retrieval
    from src.llm.embedding_provider import create_embedding_provider

    app.state.embedding_provider = create_embedding_provider(settings)
    if app.state.embedding_provider:
        logging.getLogger(__name__).info(
            "Embedding provider initialized: %s", type(app.state.embedding_provider).__name__
        )

    # Rerank provider for element reranking
    from src.llm.rerank_provider import create_rerank_provider

    app.state.rerank_provider = create_rerank_provider(settings)
    if app.state.rerank_provider:
        logging.getLogger(__name__).info(
            "Rerank provider initialized: %s", type(app.state.rerank_provider).__name__
        )


    # M1 services
    app.state.llm = llm
    app.state.sub_llm = sub_llm
    app.state.extraction_service = extraction
    app.state.search_service = search
    app.state.material_service = material

    # M2 services (per-request in deps.py for production, here for generation_service)
    app.state.generation_service = None  # wired in deps

    # M6 services (Zep graph alignment)
    if settings.zep_enabled and settings.zep_api_key:
        from zep_cloud.client import Zep as ZepClient

        from src.services.graph_builder import GraphBuilderService
        from src.services.ontology_generator import OntologyGenerator
        from src.services.task_manager import TaskManager
        from src.services.zep_entity_reader import ZepEntityReader

        zep = ZepClient(api_key=settings.zep_api_key)
        tm = TaskManager()
        app.state.ontology_generator = OntologyGenerator(llm=llm)
        app.state.graph_builder = GraphBuilderService(
            zep_client=zep,
            session_factory=_async_session_factory,
            task_manager=tm,
        )
        app.state.entity_reader = ZepEntityReader(zep_client=zep)
        app.state.task_manager = tm
    else:
        app.state.ontology_generator = None
        app.state.graph_builder = None
        app.state.entity_reader = None
        app.state.task_manager = None

    # ── Matterbridge integration (conditional) ────────────────────────────
    if settings.matterbridge_enabled and settings.secret_encryption_key:
        from src.services.matterbridge_service import MatterBridgeService

        # session_factory mode: the service creates fresh sessions via _with_repo()
        _mb_service = MatterBridgeService(
            key_secret=settings.secret_encryption_key,
            session_factory=_async_session_factory,
        )
        await _mb_service.start()

        # Wire inbound messages to the SSE relay queues
        from src.api.matterbridge import push_to_stream_queues

        async def _mb_inbound_callback(world_id: str, msg) -> None:
            push_to_stream_queues(
                world_id,
                {
                    "text": msg.text,
                    "username": msg.username,
                    "gateway": msg.gateway,
                    "avatar": msg.avatar,
                    "protocol": msg.protocol,
                    "id": msg.msg_id,
                    "timestamp": msg.timestamp,
                    "event": msg.event,
                    "parent_id": msg.parent_id,
                },
            )

        _mb_service.register_callback(_mb_inbound_callback)

        # Auto-start SSE streams for all enabled bindings
        _started = await _mb_service.start_all_enabled_streams()
        logging.getLogger(__name__).info("Matterbridge enabled: started %d stream(s)", _started)

        app.state.matterbridge_service = _mb_service
    else:
        app.state.matterbridge_service = None
        if settings.matterbridge_enabled:
            logging.getLogger(__name__).warning(
                "Matterbridge enabled but SECRET_ENCRYPTION_KEY not set; skipping"
            )

    # Bootstrap permanent admin account if it doesn't exist yet
    await _bootstrap_admin()

    # Snapshot sync: start background consumer + run startup reconciliation
    from src.services.snapshot_sync_service import SnapshotSyncService, reconcile_all

    snapshot_sync = SnapshotSyncService(
        redis=redis_client,
        session_factory=_async_session_factory,
    )
    await snapshot_sync.start()

    # Admin config sync: broadcast runtime LLM/embedding config changes to all workers
    from src.services.admin_config_sync_service import AdminConfigSyncService

    admin_config_sync = AdminConfigSyncService(
        redis=redis_client,
        session_factory=_async_session_factory,
        app=app,
    )
    await admin_config_sync.start()

    # Reconcile any worlds whose snapshots drifted while the process was down
    try:
        await reconcile_all(_async_session_factory)
    except Exception as _reconcile_exc:
        logging.getLogger(__name__).warning("reconcile_all failed: %s", _reconcile_exc)

    # ── Background task: flush inactive chat sessions (every 60s) ────────
    from src.services.memory_module import MemoryModule
    from src.services.memory_orchestrator import MemoryOrchestrator
    from src.services.memory_propagation_service import MemoryPropagationService
    from src.services.message_service import MessageService

    _memory_module = MemoryModule(
        llm=llm, session_factory=_async_session_factory, redis=redis_client
    )
    _memory_propagation = MemoryPropagationService(
        llm=llm, session_factory=_async_session_factory, redis=redis_client
    )
    _memory_orchestrator = MemoryOrchestrator(
        memory_module=_memory_module, memory_propagation_service=_memory_propagation
    )
    _flush_service = MessageService(
        message_repo=None,  # not used by flush_inactive_sessions
        llm=llm,
        session_factory=_async_session_factory,
        redis=redis_client,
        memory_orchestrator=_memory_orchestrator,
    )

    async def _flush_inactive_loop() -> None:
        _lg = logging.getLogger("flush_inactive")
        while True:
            try:
                await asyncio.sleep(60)
                result = await _flush_service.flush_inactive_sessions()
                if result.get("processed", 0) > 0:
                    _lg.info("Inactive session flush: %s", result)
            except asyncio.CancelledError:
                break
            except Exception:
                _lg.exception("flush_inactive_sessions loop error")

    _flush_task = asyncio.create_task(_flush_inactive_loop())

    yield

    # Shutdown: stop Matterbridge service
    _mb_svc = getattr(app.state, "matterbridge_service", None)
    if _mb_svc is not None:
        await _mb_svc.stop()

    # Shutdown: cancel inactive session flush task
    _flush_task.cancel()
    try:
        await _flush_task
    except asyncio.CancelledError:
        pass

    # Shutdown: stop snapshot sync / admin config sync consumers cleanly before closing Redis
    await snapshot_sync.stop()
    await admin_config_sync.stop()

    await redis_client.aclose()


app = FastAPI(title="MIVE - Virtual World Incarnation Engine", version="0.1.0", lifespan=lifespan)


from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from src.api.error_handlers import register_error_handlers  # noqa: E402

register_error_handlers(app)


@app.exception_handler(LLMQuotaExhaustedError)
async def llm_quota_exhausted_handler(request: Request, exc: LLMQuotaExhaustedError):
    return JSONResponse(
        status_code=402,
        content={
            "detail": {
                "error_code": "LLM_QUOTA_EXHAUSTED",
                "provider": exc.provider,
                "model": exc.model,
            }
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(import_.router)
app.include_router(worlds.router)
app.include_router(elements.router)
app.include_router(character_material.router)
app.include_router(characters.router)
app.include_router(relations.router)
app.include_router(versions.router)
app.include_router(graph.router)
app.include_router(m6_graph.router)
app.include_router(events.router)
app.include_router(messages.router)
app.include_router(chat_sessions.router)
app.include_router(graph_command.router)
app.include_router(guide.router)
app.include_router(memories.router)
app.include_router(welcome_quotes.router)
app.include_router(discord_bridge.router)
app.include_router(matterbridge.router)
app.include_router(admin.router)
app.include_router(admin_config.router)
app.include_router(auth.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
