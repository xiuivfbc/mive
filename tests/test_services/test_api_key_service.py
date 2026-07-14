"""Tests for ApiKeyService — encrypt/decrypt roundtrip, isolation, deletion."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.api_key_service import ApiKeyService

TEST_SECRET = "a" * 64  # 64 hex chars = 32 bytes


@pytest.fixture
def mock_key_repo():
    return AsyncMock()


@pytest.fixture
def svc(mock_key_repo):
    return ApiKeyService(api_key_repo=mock_key_repo, key_secret=TEST_SECRET)


USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


class TestEncryptDecrypt:
    async def test_roundtrip_returns_plaintext(self, svc, mock_key_repo):
        """save_api_key then get_api_key returns the original key."""
        # Capture what gets stored
        stored = {}

        async def fake_upsert(
            user_id, provider, encrypted_key, iv, model=None, base_url=None, rpm=None
        ):
            stored["encrypted_key"] = encrypted_key
            stored["iv"] = iv
            row = MagicMock()
            row.provider = provider
            row.model = model
            row.encrypted_key = encrypted_key
            row.iv = iv
            return row

        mock_key_repo.upsert.side_effect = fake_upsert

        async def fake_get(user_id):
            if not stored:
                return None
            row = MagicMock()
            row.provider = "anthropic"
            row.model = None
            row.encrypted_key = stored["encrypted_key"]
            row.iv = stored["iv"]
            return row

        mock_key_repo.get_by_user.side_effect = fake_get

        await svc.save_api_key(
            USER_A,
            provider="anthropic",
            key="sk-real-api-key-123",
            model="claude-sonnet-4-20250514",
        )
        result = await svc.get_api_key(USER_A)

        assert result is not None
        assert result["key"] == "sk-real-api-key-123"
        assert result["provider"] == "anthropic"

    async def test_different_users_different_ciphertext(self, svc, mock_key_repo):
        """Same plaintext key for two users produces different ciphertext (different IVs)."""
        stored: dict[uuid.UUID, dict] = {}

        async def fake_upsert(
            user_id, provider, encrypted_key, iv, model=None, base_url=None, rpm=None
        ):
            stored[user_id] = {"encrypted_key": encrypted_key, "iv": iv}
            row = MagicMock()
            row.provider = provider
            row.model = model
            row.encrypted_key = encrypted_key
            row.iv = iv
            return row

        mock_key_repo.upsert.side_effect = fake_upsert

        plaintext = "sk-shared-key"
        await svc.save_api_key(USER_A, provider="openai", key=plaintext, model="gpt-4o")
        await svc.save_api_key(USER_B, provider="openai", key=plaintext, model="gpt-4o")

        assert stored[USER_A]["encrypted_key"] != stored[USER_B]["encrypted_key"]
        assert stored[USER_A]["iv"] != stored[USER_B]["iv"]

    async def test_get_api_key_no_row_returns_none(self, svc, mock_key_repo):
        mock_key_repo.get_by_user.return_value = None
        result = await svc.get_api_key(USER_A)
        assert result is None

    async def test_model_preserved(self, svc, mock_key_repo):
        stored = {}

        async def fake_upsert(
            user_id, provider, encrypted_key, iv, model=None, base_url=None, rpm=None
        ):
            stored["model"] = model
            stored["encrypted_key"] = encrypted_key
            stored["iv"] = iv
            row = MagicMock()
            row.provider = provider
            row.model = model
            row.encrypted_key = encrypted_key
            row.iv = iv
            return row

        mock_key_repo.upsert.side_effect = fake_upsert

        async def fake_get(user_id):
            row = MagicMock()
            row.provider = "qwen"
            row.model = stored.get("model")
            row.encrypted_key = stored["encrypted_key"]
            row.iv = stored["iv"]
            return row

        mock_key_repo.get_by_user.side_effect = fake_get

        await svc.save_api_key(USER_A, provider="qwen", key="qwen-key", model="qwen-turbo")
        result = await svc.get_api_key(USER_A)
        assert result["model"] == "qwen-turbo"


class TestDeleteApiKey:
    async def test_delete_existing_key(self, svc, mock_key_repo):
        mock_key_repo.delete_by_user.return_value = True
        result = await svc.delete_api_key(USER_A)
        assert result is True
        mock_key_repo.delete_by_user.assert_called_once_with(USER_A)

    async def test_delete_nonexistent_key(self, svc, mock_key_repo):
        mock_key_repo.delete_by_user.return_value = False
        result = await svc.delete_api_key(USER_A)
        assert result is False
