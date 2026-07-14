from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_debug: bool = False

    database_url: str = "postgresql+asyncpg://mive:mive@localhost:5432/mive"

    # Admin account (created on first startup)
    admin_username: str = "admin"
    admin_password: str = "changeme"

    # LLM — model 和 api_key 为必填字段
    # base_url / api_format 可选：填了会覆盖 provider 内置默认值
    llm_provider: str = "anthropic"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_format: str = ""

    # 副模型（SUB_LLM）— 判断/分类类的"简单调用"走更便宜的副模型。
    # 留空 = 不启用，所有调用回落主模型。配了但调用失败会回退主模型重试一次。
    # provider 可与主模型不同（如主 mimo + 副 deepseek）；留空则复用 LLM_PROVIDER。
    # 与主模型一样，model 和 api_key 为必填，base_url / api_format 覆盖 provider 默认值。
    sub_llm_provider: str = ""
    sub_llm_api_key: str = ""
    sub_llm_base_url: str = ""
    sub_llm_model: str = ""
    sub_llm_api_format: str = ""
    # 副模型独立速率门（不与主模型共享配额）
    sub_llm_rpm: int = 0
    sub_llm_max_inflight: int = 5

    tavily_api_key: str = ""

    # M6 — Zep graph integration
    zep_enabled: bool = True
    zep_api_key: str = ""
    zep_base_url: str = ""

    # RateLimitGate 最大重试次数。None = 默认 2 次（首次 + 2 次 = 最多 3 次尝试）；0 = 不重试
    llm_max_retries: int | None = None
    # LLM 速率门（RPM = 每分钟最大请求数）。0 = 不限速
    llm_rpm: int = 0
    # LLM 速率门在飞请求数上限（已发出、未完成的请求数）。<= 0 视为不限制
    llm_max_inflight: int = 5

    # M8 Discord Bridge
    discord_bot_token: str = ""
    discord_application_id: str = ""

    # Matterbridge integration
    matterbridge_enabled: bool = False

    # AES-256-GCM key for encrypting stored secrets (admin config API keys, Matterbridge bindings)
    secret_encryption_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Embedding (vector retrieval)
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1024

    # Retrieval parameters
    retrieval_top_k: int = 10
    retrieval_bm25_top_k: int = 20
    retrieval_vec_top_k: int = 20
    retrieval_bm25_rrf_k: int = 5
    retrieval_vec_rrf_k: int = 60

    # Rerank provider (BGE Rerank via OpenAI-compatible API)
    rerank_api_key: str = ""
    rerank_base_url: str = ""
    rerank_model: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
