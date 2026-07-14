"""API key encryption/decryption using AES-256-GCM."""

import asyncio
import ipaddress
import logging
import os
import uuid
from base64 import b64decode, b64encode
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.db.repositories.api_key_repo import ApiKeyRepository

logger = logging.getLogger(__name__)

# Validation timeout in seconds
_VALIDATION_TIMEOUT = 10


def _validate_base_url(url: str) -> str | None:
    """Validate base_url for SSRF safety. Returns error message or None if OK."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "URL 格式无效"

    if parsed.scheme not in ("http", "https"):
        return "URL 必须使用 http 或 https 协议"

    hostname = parsed.hostname
    if not hostname:
        return "URL 缺少主机名"

    # Block localhost aliases
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return "不允许使用本地地址"

    # Block private/internal IP ranges
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "不允许使用内网地址"
    except ValueError:
        # hostname is a domain name, not an IP — that's fine
        pass

    return None


def _parse_secret(key_secret: str) -> bytes:
    """Accept a 64-char hex string (32 bytes) or a raw 32-byte key."""
    if len(key_secret) == 64:
        return bytes.fromhex(key_secret)
    encoded = key_secret.encode()
    if len(encoded) == 32:
        return encoded
    raise ValueError("SECRET_ENCRYPTION_KEY must be 64 hex chars (32 bytes)")


class ApiKeyService:
    def __init__(self, api_key_repo: ApiKeyRepository, key_secret: str):
        self._repo = api_key_repo
        self._key = _parse_secret(key_secret)

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        """Return (encrypted_key_b64, iv_hex)."""
        iv = os.urandom(12)  # 96-bit nonce for GCM
        aesgcm = AESGCM(self._key)
        ct = aesgcm.encrypt(iv, plaintext.encode(), None)
        return b64encode(ct).decode(), iv.hex()

    def _decrypt(self, encrypted_key_b64: str, iv_hex: str) -> str:
        iv = bytes.fromhex(iv_hex)
        ct = b64decode(encrypted_key_b64)
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(iv, ct, None).decode()

    async def validate_api_key(
        self,
        provider: str,
        key: str,
        base_url: str | None = None,
        api_format: str | None = None,
        model: str | None = None,
    ) -> tuple[bool, str | None]:
        """Validate API key by making a minimal LLM call.

        Returns (is_valid, error_message).
        model 为空时自动探测可用模型。
        Note: LLM client connections are managed by the SDK and will be
        reclaimed by garbage collection after this method returns.
        """
        # SSRF protection: validate base_url before making any outbound request
        if base_url:
            ssrf_error = _validate_base_url(base_url)
            if ssrf_error:
                return False, ssrf_error

        from src.llm.factory import create_llm_auto

        try:
            llm = await create_llm_auto(
                provider, key, model=model, base_url=base_url, max_retries=0, api_format=api_format
            )
            # Make a minimal call to verify the key works, with timeout
            await asyncio.wait_for(
                llm.complete("", "Hi", max_tokens=1),
                timeout=_VALIDATION_TIMEOUT,
            )
            return True, None
        except TimeoutError:
            logger.warning("API key validation timed out for provider %s", provider)
            return False, "验证超时，请检查网络连接"
        except Exception as e:
            error_str = str(e).lower()
            # Check for authentication errors
            auth_kw = ("401", "403", "unauthorized", "invalid_api_key", "authentication")
            if any(kw in error_str for kw in auth_kw):
                logger.warning("API key invalid for provider %s: %s", provider, e)
                return False, "API key 无效，请检查是否正确"
            # Network or connection errors
            net_kw = ("connection", "network", "dns", "ssl", "timeout")
            if any(kw in error_str for kw in net_kw):
                logger.warning("Network error during validation for provider %s: %s", provider, e)
                return False, "网络连接失败，请检查网络"
            # Other errors — log full traceback server-side, return generic message
            logger.warning(
                "API key validation failed for provider %s: %s",
                provider,
                e,
                exc_info=True,
            )
            return False, "验证失败，请稍后重试"

    async def save_api_key(
        self,
        user_id: uuid.UUID,
        provider: str,
        key: str,
        model: str,
        base_url: str | None = None,
        rpm: int | None = None,
        api_format: str | None = None,
    ) -> None:
        encrypted_key, iv = self._encrypt(key)
        await self._repo.upsert(
            user_id=user_id,
            provider=provider,
            encrypted_key=encrypted_key,
            iv=iv,
            model=model,
            base_url=base_url,
            rpm=rpm,
            api_format=api_format,
        )

    async def get_api_key(self, user_id: uuid.UUID) -> dict | None:
        row = await self._repo.get_by_user(user_id)
        if row is None:
            return None
        decrypted = self._decrypt(row.encrypted_key, row.iv)
        return {
            "key": decrypted,
            "provider": row.provider,
            "model": row.model,
            "base_url": row.base_url,
            "rpm": row.rpm,
            "api_format": row.api_format,
        }

    async def get_api_key_config(self, user_id: uuid.UUID) -> dict | None:
        """Return BYOK config with masked key for UI display."""
        row = await self._repo.get_by_user(user_id)
        if row is None:
            return None
        # Decrypt to get the actual key, then mask it
        try:
            decrypted = self._decrypt(row.encrypted_key, row.iv)
            key_len = len(decrypted)
            # For very short keys (<=6 chars), just show asterisks
            if key_len <= 6:
                masked_key = "****"
            elif key_len <= 8:
                masked_key = decrypted[:2] + "*" * (key_len - 4) + decrypted[-2:]
            else:
                masked_key = decrypted[:4] + "*" * (key_len - 8) + decrypted[-4:]
        except Exception as e:
            logger.warning("Failed to decrypt key for masking: %s", e)
            masked_key = "****"
        return {
            "provider": row.provider,
            "key_preview": masked_key,
            "model": row.model,
            "base_url": row.base_url,
            "rpm": row.rpm,
            "api_format": row.api_format,
        }

    async def delete_api_key(self, user_id: uuid.UUID) -> bool:
        return await self._repo.delete_by_user(user_id)
