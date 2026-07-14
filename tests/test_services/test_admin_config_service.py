"""Tests for AdminConfigService — encryption, persistence, hot-reload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.admin_config_service import (
    AdminConfigService,
    _decrypt,
    _encrypt,
    _is_sensitive,
    _mask_value,
)


def _make_request(app_state: dict | None = None) -> MagicMock:
    """Create a mock Request with an app containing the given state attrs."""
    request = MagicMock()
    app = MagicMock()
    for k, v in (app_state or {}).items():
        setattr(app.state, k, v)
    request.app = app
    return request


@pytest.fixture(autouse=True)
def _reset_env_defaults():
    """Ensure _ENV_DEFAULTS is recalculated for each test."""
    import src.services.admin_config_service as mod

    mod._ENV_DEFAULTS.clear()
    yield


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.app.state.llm = None
    request.app.state.sub_llm = None
    request.app.state.embedding_provider = None
    return request


@pytest.fixture
def mock_repo_cls():
    """Patch AdminConfigRepository so we can control its methods."""
    with patch("src.services.admin_config_service.AdminConfigRepository") as cls:
        repo = AsyncMock()
        repo.list_by_group = AsyncMock(return_value=[])
        cls.return_value = repo
        yield repo


@pytest.fixture
def billing_key():
    """Provide a valid secret-encryption key."""
    return "0" * 64


@pytest.fixture(autouse=True)
def _mock_billing_key(billing_key):
    with patch("src.services.admin_config_service.settings.secret_encryption_key", billing_key):
        yield


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


class TestEncryptionHelpers:
    def test_encrypt_decrypt_roundtrip(self):
        key = b"0" * 32
        plaintext = "sk-test-api-key-12345"
        ct, iv = _encrypt(key, plaintext)
        assert _decrypt(key, ct, iv) == plaintext

    def test_mask_value_short(self):
        assert _mask_value("abc") == "****"

    def test_mask_value_medium(self):
        result = _mask_value("abcdefgh")
        assert result.startswith("ab")
        assert result.endswith("gh")
        assert "*" in result

    def test_mask_value_long(self):
        result = _mask_value("sk-1234567890abcdef")
        assert result.startswith("sk-1")
        assert result.endswith("cdef")
        assert "*" in result

    def test_is_sensitive(self):
        assert _is_sensitive("api_key") is True
        assert _is_sensitive("tavily_api_key") is True
        assert _is_sensitive("model") is False
        assert _is_sensitive("provider") is False
        assert _is_sensitive("base_url") is False


# ---------------------------------------------------------------------------
# Basic service behaviour
# ---------------------------------------------------------------------------


class TestAdminConfigService:
    @pytest.mark.asyncio
    async def test_get_group_unknown_raises(self, mock_session, mock_request):
        svc = AdminConfigService(mock_session, mock_request)
        with pytest.raises(ValueError, match="Unknown group"):
            await svc.get_group("invalid")

    @pytest.mark.asyncio
    async def test_get_group_returns_env_defaults_when_no_overrides(
        self, mock_session, mock_request, mock_repo_cls
    ):
        svc = AdminConfigService(mock_session, mock_request)
        result = await svc.get_group("llm")
        assert result.group == "llm"
        assert len(result.items) > 0
        assert all(item.source == "env_default" for item in result.items)

    @pytest.mark.asyncio
    async def test_reset_group_unknown_raises(self, mock_session, mock_request):
        svc = AdminConfigService(mock_session, mock_request)
        with pytest.raises(ValueError, match="Unknown group"):
            await svc.reset_group("invalid")


# ---------------------------------------------------------------------------
# update_group: snapshot + rebuild-failure restoration
# ---------------------------------------------------------------------------


class TestUpdateGroupSnapshot:
    """update_group must restore settings singleton if _rebuild_providers fails."""

    @pytest.mark.asyncio
    async def test_update_rebuild_failure_restores_settings(
        self, mock_session, mock_repo_cls, billing_key
    ):
        """When _rebuild_providers raises, settings must revert to pre-update values."""
        from src.config import settings

        # Set known starting values
        settings.llm_provider = "openai"
        settings.llm_api_key = "sk-old-key"
        settings.llm_model = "gpt-4"
        settings.llm_rpm = 10

        request = _make_request()
        svc = AdminConfigService(mock_session, request)

        # Make rebuild blow up
        svc._rebuild_providers = AsyncMock(side_effect=RuntimeError("rebuild boom"))

        await svc.update_group(
            "llm",
            {"provider": "anthropic", "api_key": "sk-new-key", "model": "claude-3", "rpm": "50"},
        )

        # DB commit must have happened
        mock_session.commit.assert_awaited_once()

        # Settings must be restored to the snapshot (pre-update values)
        assert settings.llm_provider == "openai"
        assert settings.llm_api_key == "sk-old-key"
        assert settings.llm_model == "gpt-4"
        assert settings.llm_rpm == 10

    @pytest.mark.asyncio
    async def test_update_rebuild_success_keeps_new_settings(
        self, mock_session, mock_repo_cls, billing_key
    ):
        """When rebuild succeeds, settings must reflect the new values."""
        from src.config import settings

        settings.llm_provider = "openai"
        settings.llm_api_key = "sk-old"
        settings.llm_model = "gpt-4"
        settings.llm_rpm = 10

        request = _make_request()
        svc = AdminConfigService(mock_session, request)
        svc._rebuild_providers = AsyncMock()  # succeeds

        await svc.update_group(
            "llm",
            {"provider": "anthropic", "api_key": "sk-new", "model": "claude-3", "rpm": "50"},
        )

        assert settings.llm_provider == "anthropic"
        assert settings.llm_api_key == "sk-new"
        assert settings.llm_model == "claude-3"
        assert settings.llm_rpm == 50


# ---------------------------------------------------------------------------
# reset_group: snapshot + rebuild-failure restoration
# ---------------------------------------------------------------------------


class TestResetGroupSnapshot:
    """reset_group must restore settings singleton if _rebuild_providers fails."""

    @pytest.mark.asyncio
    async def test_reset_rebuild_failure_restores_settings(
        self, mock_session, mock_repo_cls, billing_key
    ):
        """When _rebuild_providers raises during reset, settings must revert to pre-reset values."""
        from src.config import settings

        # Capture env defaults with a known value
        settings.llm_provider = "anthropic"
        settings.llm_api_key = ""
        settings.llm_model = ""
        settings.llm_rpm = 0

        request = _make_request()
        svc = AdminConfigService(mock_session, request)

        # Simulate admin override happened between construction and reset
        settings.llm_provider = "openai"
        settings.llm_api_key = "sk-override"
        settings.llm_model = "gpt-4"
        settings.llm_rpm = 99

        # Make rebuild blow up
        svc._rebuild_providers = AsyncMock(side_effect=RuntimeError("rebuild boom"))

        await svc.reset_group("llm")

        # DB commit must have happened
        mock_session.commit.assert_awaited_once()

        # Settings must be restored to the snapshot (pre-reset = the override values)
        assert settings.llm_provider == "openai"
        assert settings.llm_api_key == "sk-override"
        assert settings.llm_model == "gpt-4"
        assert settings.llm_rpm == 99

    @pytest.mark.asyncio
    async def test_reset_rebuild_success_sets_env_defaults(
        self, mock_session, mock_repo_cls, billing_key
    ):
        """When rebuild succeeds during reset, settings must reflect env defaults."""
        from src.config import settings

        # Capture env defaults first
        settings.llm_provider = "anthropic"
        settings.llm_api_key = ""

        request = _make_request()
        svc = AdminConfigService(mock_session, request)

        # Simulate admin override happened between construction and reset
        settings.llm_provider = "openai"
        settings.llm_api_key = "sk-override"

        svc._rebuild_providers = AsyncMock()

        await svc.reset_group("llm")

        # _ENV_DEFAULTS captured "anthropic" at construction time
        assert settings.llm_provider == "anthropic"
        assert settings.llm_api_key == ""
