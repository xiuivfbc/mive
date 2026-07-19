"""管理员配置跨 worker 同步服务

负责：
1. AdminConfigSyncService — Redis Pub/Sub 消费者，收到 admin_config:reload 通知后
   立即重新加载 settings 单例并重建对应的 provider（多 worker 进程各自独立热更新）

管理员配置变更是低频人工操作，不需要像快照同步那样 debounce，收到即处理。
"""

from __future__ import annotations

import asyncio
import json
import logging

from redis.asyncio import Redis

from src.services.admin_config_service import (
    _PUBSUB_CHANNEL,
    apply_persisted_overrides,
    rebuild_embedding,
    rebuild_main_llm,
    rebuild_rerank,
    rebuild_sub_llm,
)

logger = logging.getLogger(__name__)


class AdminConfigSyncService:
    """Redis Pub/Sub 消费者，监听 admin_config:reload 频道。

    收到通知后立即从 m21_admin_config 重新加载 settings 单例，
    并重建通知中指定 group 对应的 provider，让每个 worker 进程独立生效。
    """

    def __init__(self, redis: Redis, session_factory, app) -> None:
        self._redis = redis
        self._session_factory = session_factory  # async_session callable
        self._app = app
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="admin_config_sync_consumer")
        logger.info("AdminConfigSyncService started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AdminConfigSyncService stopped")

    async def _run(self) -> None:
        """主消费循环：订阅 Redis Pub/Sub 频道并处理消息，断线自动重连。"""
        backoff = 1
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(_PUBSUB_CHANNEL)
                logger.debug("AdminConfigSyncService subscribed to channel: %s", _PUBSUB_CHANNEL)
                backoff = 1  # 连接成功，重置退避
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    if not isinstance(raw, str):
                        continue
                    await self._handle_message(raw)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(
                    "AdminConfigSyncService consumer error: %s — reconnecting in %ds", exc, backoff
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * 2, 30)
            finally:
                try:
                    await pubsub.unsubscribe(_PUBSUB_CHANNEL)
                except Exception:
                    pass
                try:
                    await pubsub.aclose()
                except Exception:
                    pass

    async def _handle_message(self, raw: str) -> None:
        """解析消息并触发 settings 重新加载 + provider 重建，单条消息失败不影响后续消费。"""
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("AdminConfigSyncService: malformed message, skipping: %r", raw)
            return
        if not isinstance(parsed, dict):
            logger.warning("AdminConfigSyncService: unexpected message shape, skipping: %r", raw)
            return
        group = parsed.get("group")
        if not group:
            logger.warning("AdminConfigSyncService: missing group in message, skipping: %r", raw)
            return

        try:
            async with self._session_factory() as session:
                await apply_persisted_overrides(session)

            if group == "llm":
                await rebuild_main_llm(self._app)
            elif group == "sub_llm":
                await rebuild_sub_llm(self._app)
            elif group == "embedding":
                rebuild_embedding(self._app)
            elif group == "rerank":
                rebuild_rerank(self._app)
            else:
                logger.warning("AdminConfigSyncService: unknown group=%s, skipping rebuild", group)
                return

            logger.info("AdminConfigSyncService: reloaded settings and rebuilt group=%s", group)
        except Exception as exc:
            logger.error("AdminConfigSyncService: failed to sync group=%s: %s", group, exc)
