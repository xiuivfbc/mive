"""Admin config service — encryption, persistence, runtime hot-reload.

Handles:
1. Reading config with env-var fallback
2. Encrypting sensitive fields (AES-256-GCM)
3. Persisting to m21_admin_config
4. Hot-reloading settings singleton + rebuilding providers/gates
"""

from __future__ import annotations

import json
import logging
import os
from base64 import b64decode, b64encode
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import settings
from src.db.repositories.admin_config_repo import AdminConfigRepository
from src.models.admin_config import AdminConfigGroupResponse, AdminConfigItem

if TYPE_CHECKING:
    from fastapi import Request
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PUBSUB_CHANNEL = "admin_config:reload"

# Fields that contain sensitive data (encrypted at rest)
_SENSITIVE_KEYS = {"api_key", "tavily_api_key"}

# Mapping from group_name to settings attribute prefixes
_GROUP_SETTINGS_MAP: dict[str, dict[str, str]] = {
    "llm": {
        "provider": "llm_provider",
        "api_key": "llm_api_key",
        "model": "llm_model",
        "base_url": "llm_base_url",
        "api_format": "llm_api_format",
        "rpm": "llm_rpm",
        "max_inflight": "llm_max_inflight",
        "max_retries": "llm_max_retries",
    },
    "sub_llm": {
        "provider": "sub_llm_provider",
        "api_key": "sub_llm_api_key",
        "model": "sub_llm_model",
        "base_url": "sub_llm_base_url",
        "api_format": "sub_llm_api_format",
        "rpm": "sub_llm_rpm",
        "max_inflight": "sub_llm_max_inflight",
    },
    "embedding": {
        "api_key": "embedding_api_key",
        "base_url": "embedding_base_url",
        "model": "embedding_model",
        "dim": "embedding_dim",
    },
}


def _get_encryption_key() -> bytes:
    """Get AES-256-GCM key from SECRET_ENCRYPTION_KEY."""
    key_secret = settings.secret_encryption_key
    if not key_secret:
        raise RuntimeError("SECRET_ENCRYPTION_KEY not configured")
    if len(key_secret) == 64:
        return bytes.fromhex(key_secret)
    encoded = key_secret.encode()
    if len(encoded) == 32:
        return encoded
    raise ValueError("SECRET_ENCRYPTION_KEY must be 64 hex chars (32 bytes)")


def _encrypt(key: bytes, plaintext: str) -> tuple[str, str]:
    """Encrypt plaintext. Returns (ciphertext_b64, iv_hex)."""
    iv = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plaintext.encode(), None)
    return b64encode(ct).decode(), iv.hex()


def _decrypt(key: bytes, encrypted_b64: str, iv_hex: str) -> str:
    """Decrypt ciphertext."""
    iv = bytes.fromhex(iv_hex)
    ct = b64decode(encrypted_b64)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ct, None).decode()


def _mask_value(value: str) -> str:
    """Mask sensitive value for display."""
    if len(value) <= 6:
        return "****"
    if len(value) <= 8:
        return value[:2] + "*" * (len(value) - 4) + value[-2:]
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _is_sensitive(key: str) -> bool:
    """Check if a key should be encrypted."""
    return key in _SENSITIVE_KEYS or "key" in key or "secret" in key


# Snapshot of initial settings values (captured at import time)
_ENV_DEFAULTS: dict[str, str] = {}


def _capture_env_defaults() -> None:
    """Capture initial settings values for revert-to-default."""
    global _ENV_DEFAULTS
    if _ENV_DEFAULTS:
        return
    for group_map in _GROUP_SETTINGS_MAP.values():
        for attr_name in group_map.values():
            val = getattr(settings, attr_name, "")
            _ENV_DEFAULTS[attr_name] = str(val) if val is not None else ""


async def apply_persisted_overrides(session: AsyncSession) -> None:
    """启动时把 m21_admin_config 里持久化的管理员配置套用到 settings 单例上。

    不这样做的话，每次进程重启（含 dev 环境的 --reload 自动重启）都会
    静默丢弃管理员在 /api/admin/config 面板保存过的配置，退回 .env 默认值。
    """
    _capture_env_defaults()
    repo = AdminConfigRepository(session)
    enc_key = _get_encryption_key()

    for group_name, group_map in _GROUP_SETTINGS_MAP.items():
        db_items = await repo.list_by_group(group_name)
        for item in db_items:
            attr_name = group_map.get(item.key)
            if attr_name is None:
                continue
            if _is_sensitive(item.key) and item.encrypted_value and item.iv:
                value = _decrypt(enc_key, item.encrypted_value, item.iv)
            else:
                value = item.plain_value or ""
            if attr_name in (
                "llm_rpm",
                "llm_max_inflight",
                "llm_max_retries",
                "sub_llm_rpm",
                "sub_llm_max_inflight",
                "embedding_dim",
            ):
                try:
                    setattr(settings, attr_name, int(value))
                except (ValueError, TypeError):
                    setattr(settings, attr_name, 0)
            else:
                setattr(settings, attr_name, value)


async def publish_admin_config_reload(redis: Redis, group_name: str) -> None:
    """在 commit 之后发布 admin config reload 通知，让其它 worker 进程同步热更新。"""
    try:
        message = json.dumps({"group": group_name})
        await redis.publish(_PUBSUB_CHANNEL, message)
    except Exception as exc:
        # Pub/Sub 失败不影响主流程——当前 worker 已经本地生效
        logger.warning("publish_admin_config_reload failed group=%s: %s", group_name, exc)


async def rebuild_main_llm(app) -> None:
    """Rebuild main LLM provider and gate."""
    from src.llm.factory import create_llm_auto
    from src.llm.rate_limit_gate import RateLimitGate

    api_key = settings.llm_api_key
    if not api_key:
        app.state.llm = None
        logger.info("[admin-config] Main LLM cleared (no api_key)")
        return

    gate = RateLimitGate(
        rpm=settings.llm_rpm if settings.llm_rpm > 0 else None,
        max_retries=settings.llm_max_retries if settings.llm_max_retries is not None else 2,
        max_inflight=settings.llm_max_inflight if settings.llm_max_inflight > 0 else None,
    )

    llm = await create_llm_auto(
        settings.llm_provider,
        api_key,
        settings.llm_model or None,
        settings.llm_base_url or None,
        max_retries=0,
        gate=gate,
        api_format=settings.llm_api_format or None,
    )
    app.state.llm = llm
    logger.info(
        "[admin-config] Main LLM rebuilt: provider=%s, model=%s",
        settings.llm_provider,
        settings.llm_model,
    )


async def rebuild_sub_llm(app) -> None:
    """Rebuild sub LLM provider."""
    from src.llm.submodel import build_sub_llm

    main_llm = getattr(app.state, "llm", None)
    sub_llm = await build_sub_llm(
        main_llm=main_llm,
        api_key=settings.sub_llm_api_key,
        base_url=settings.sub_llm_base_url,
        model=settings.sub_llm_model,
        provider=settings.sub_llm_provider or settings.llm_provider,
        rpm=settings.sub_llm_rpm,
        max_inflight=settings.sub_llm_max_inflight,
        gate=None,
        api_format=settings.sub_llm_api_format or None,
    )
    app.state.sub_llm = sub_llm
    logger.info(
        "[admin-config] Sub LLM rebuilt: provider=%s, model=%s",
        settings.sub_llm_provider,
        settings.sub_llm_model,
    )


def rebuild_embedding(app) -> None:
    """Rebuild embedding provider."""
    from src.llm.embedding_provider import create_embedding_provider

    embedding = create_embedding_provider(settings)
    app.state.embedding_provider = embedding
    logger.info("[admin-config] Embedding provider rebuilt: model=%s", settings.embedding_model)


class AdminConfigService:
    def __init__(self, session: AsyncSession, request: Request | None = None):
        self.session = session
        self.repo = AdminConfigRepository(session)
        self.request = request
        _capture_env_defaults()

    async def get_group(self, group_name: str) -> AdminConfigGroupResponse:
        """Get all config items for a group, with env-var fallback."""
        if group_name not in _GROUP_SETTINGS_MAP:
            raise ValueError(f"Unknown group: {group_name}")

        group_map = _GROUP_SETTINGS_MAP[group_name]
        db_items = await self.repo.list_by_group(group_name)
        db_map = {item.key: item for item in db_items}

        items = []
        enc_key = _get_encryption_key()

        for config_key, attr_name in group_map.items():
            if config_key in db_map:
                db_item = db_map[config_key]
                if _is_sensitive(config_key) and db_item.encrypted_value and db_item.iv:
                    raw_value = _decrypt(enc_key, db_item.encrypted_value, db_item.iv)
                    display_value = _mask_value(raw_value)
                else:
                    raw_value = db_item.plain_value or ""
                    display_value = raw_value
                items.append(
                    AdminConfigItem(key=config_key, value=display_value, source="override")
                )
            else:
                env_value = _ENV_DEFAULTS.get(attr_name, "")
                items.append(AdminConfigItem(key=config_key, value=env_value, source="env_default"))

        return AdminConfigGroupResponse(group=group_name, items=items)

    async def update_group(
        self, group_name: str, values: dict[str, str]
    ) -> AdminConfigGroupResponse:
        """Update config values for a group, persist, and hot-reload."""
        if group_name not in _GROUP_SETTINGS_MAP:
            raise ValueError(f"Unknown group: {group_name}")

        group_map = _GROUP_SETTINGS_MAP[group_name]
        enc_key = _get_encryption_key()

        # Snapshot current settings values before mutation
        snapshot: dict[str, object] = {}
        for _, attr_name in group_map.items():
            snapshot[attr_name] = getattr(settings, attr_name, None)

        for config_key, value in values.items():
            if config_key not in group_map:
                continue

            if _is_sensitive(config_key):
                encrypted, iv = _encrypt(enc_key, value)
                await self.repo.upsert(group_name, config_key, encrypted, None, iv)
            else:
                await self.repo.upsert(group_name, config_key, None, value, None)

            # Update settings singleton
            attr_name = group_map[config_key]
            # Convert type if needed (rpm, max_inflight, max_retries, dim are int)
            if attr_name in (
                "llm_rpm",
                "llm_max_inflight",
                "llm_max_retries",
                "sub_llm_rpm",
                "sub_llm_max_inflight",
                "embedding_dim",
            ):
                try:
                    setattr(settings, attr_name, int(value))
                except (ValueError, TypeError):
                    setattr(settings, attr_name, 0)
            else:
                setattr(settings, attr_name, value)

        await self.session.commit()

        # Trigger provider rebuild; restore settings on failure
        try:
            await self._rebuild_providers(group_name)
        except Exception:
            logger.exception(
                "[admin-config] Provider rebuild failed after commit for group=%s; "
                "restoring settings snapshot",
                group_name,
            )
            for attr_name, old_value in snapshot.items():
                setattr(settings, attr_name, old_value)

        # Broadcast to other worker processes so they hot-reload independently
        if self.request is not None:
            redis = getattr(self.request.app.state, "redis", None)
            if redis is not None:
                await publish_admin_config_reload(redis, group_name)

        return await self.get_group(group_name)

    async def reset_group(self, group_name: str) -> AdminConfigGroupResponse:
        """Delete all overrides for a group, revert to env defaults."""
        if group_name not in _GROUP_SETTINGS_MAP:
            raise ValueError(f"Unknown group: {group_name}")

        group_map = _GROUP_SETTINGS_MAP[group_name]

        # Snapshot current settings before mutation
        snapshot: dict[str, object] = {}
        for _, attr_name in group_map.items():
            snapshot[attr_name] = getattr(settings, attr_name, None)

        # Delete from DB
        await self.repo.delete_by_group(group_name)
        await self.session.commit()

        # Restore settings to env defaults
        for _, attr_name in group_map.items():
            env_value = _ENV_DEFAULTS.get(attr_name, "")
            if attr_name in (
                "llm_rpm",
                "llm_max_inflight",
                "llm_max_retries",
                "sub_llm_rpm",
                "sub_llm_max_inflight",
                "embedding_dim",
            ):
                try:
                    setattr(settings, attr_name, int(env_value))
                except (ValueError, TypeError):
                    setattr(settings, attr_name, 0)
            else:
                setattr(settings, attr_name, env_value)

        # Trigger provider rebuild; restore settings on failure
        try:
            await self._rebuild_providers(group_name)
        except Exception:
            logger.exception(
                "[admin-config] Provider rebuild failed after reset for group=%s; "
                "restoring settings snapshot",
                group_name,
            )
            for attr_name, old_value in snapshot.items():
                setattr(settings, attr_name, old_value)

        # Broadcast to other worker processes so they hot-reload independently
        if self.request is not None:
            redis = getattr(self.request.app.state, "redis", None)
            if redis is not None:
                await publish_admin_config_reload(redis, group_name)

        return await self.get_group(group_name)

    async def _rebuild_providers(self, group_name: str) -> None:
        """Rebuild LLM providers/gates after config change."""
        if not self.request:
            return

        app = self.request.app

        if group_name == "llm":
            await rebuild_main_llm(app)
        elif group_name == "sub_llm":
            await rebuild_sub_llm(app)
        elif group_name == "embedding":
            rebuild_embedding(app)
