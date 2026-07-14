"""Tests for MatterBridgeService."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.matterbridge_service import (
    MatterBridgeService,
    MatterbridgeMessage,
    _BACKOFF_INITIAL,
    _BACKOFF_MAX,
    _decrypt_token,
    _encrypt_token,
    _mask_token,
    _parse_key_secret,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_KEY_HEX = "0" * 64  # 32-byte key as hex
_TEST_WORLD_ID = "00000000-0000-0000-0000-000000000099"


def _make_binding_row(
    world_id: str = _TEST_WORLD_ID,
    api_url: str = "http://mb.local:4242",
    api_token_encrypted: str = "enc",
    api_token_iv: str = "aabbccdd",
    enabled: bool = True,
    config_json: dict | None = None,
) -> MagicMock:
    """Create a mock DB row that looks like M20MatterbridgeBinding."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.world_id = uuid.UUID(world_id)
    row.api_url = api_url
    row.api_token_encrypted = api_token_encrypted
    row.api_token_iv = api_token_iv
    row.enabled = enabled
    row.config_json = config_json
    row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return row


def _build_service(key_secret: str = _VALID_KEY_HEX) -> tuple[MatterBridgeService, AsyncMock]:
    """Build a MatterBridgeService with a mock repo."""
    mock_repo = AsyncMock()
    svc = MatterBridgeService(repo=mock_repo, key_secret=key_secret)
    return svc, mock_repo


async def _start_service(svc: MatterBridgeService) -> None:
    """Start the service so _client is initialized."""
    await svc.start()


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


class TestParseKeySecret:
    def test_valid_64_hex_chars(self):
        key = _parse_key_secret("a" * 64)
        assert len(key) == 32
        assert key == bytes.fromhex("a" * 64)

    def test_valid_32_raw_bytes(self):
        raw = b"x" * 32
        key = _parse_key_secret(raw.decode("latin-1"))
        assert key == raw

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError, match="64 hex chars"):
            _parse_key_secret("short")


class TestEncryptDecryptToken:
    def test_round_trip(self):
        key = bytes.fromhex(_VALID_KEY_HEX)
        plaintext = "my-secret-token-12345"
        ct, iv_hex = _encrypt_token(key, plaintext)
        assert ct != plaintext
        decrypted = _decrypt_token(key, ct, iv_hex)
        assert decrypted == plaintext

    def test_different_iv_each_time(self):
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct1, iv1 = _encrypt_token(key, "token")
        ct2, iv2 = _encrypt_token(key, "token")
        assert iv1 != iv2  # random nonce each time

    def test_wrong_key_fails(self):
        key1 = bytes.fromhex(_VALID_KEY_HEX)
        key2 = bytes.fromhex("1" * 64)
        ct, iv_hex = _encrypt_token(key1, "token")
        with pytest.raises(Exception):
            _decrypt_token(key2, ct, iv_hex)


class TestMaskToken:
    def test_short_token(self):
        assert _mask_token("abc") == "****"

    def test_medium_token(self):
        result = _mask_token("abcdefgh")
        assert result.startswith("ab")
        assert result.endswith("gh")
        assert "****" not in result or "*" in result

    def test_long_token(self):
        result = _mask_token("abcdefghijklmnop")
        assert result.startswith("abcd")
        assert result.endswith("mnop")
        assert "*" in result


# ---------------------------------------------------------------------------
# MatterbridgeMessage
# ---------------------------------------------------------------------------


class TestMatterbridgeMessage:
    def test_from_dict(self):
        data = {
            "text": "hello",
            "username": "user1",
            "gateway": "gw1",
            "avatar": "http://avatar.png",
            "protocol": "discord",
            "id": "msg-001",
            "timestamp": "2026-01-01T00:00:00Z",
            "event": "",
            "parent_id": "p1",
            "extras": {"key": "value"},
        }
        msg = MatterbridgeMessage.from_dict(data)
        assert msg.text == "hello"
        assert msg.username == "user1"
        assert msg.gateway == "gw1"
        assert msg.msg_id == "msg-001"
        assert msg.extras == {"key": "value"}

    def test_from_dict_defaults(self):
        msg = MatterbridgeMessage.from_dict({})
        assert msg.text == ""
        assert msg.username == ""
        assert msg.msg_id == ""

    def test_to_dict(self):
        msg = MatterbridgeMessage(text="hi", username="u", gateway="gw")
        d = msg.to_dict()
        assert d == {"text": "hi", "username": "u", "gateway": "gw"}

    def test_to_dict_with_optional_fields(self):
        msg = MatterbridgeMessage(
            text="hi", username="u", gateway="gw",
            avatar="http://av.png", msg_id="m1", parent_id="p1",
        )
        d = msg.to_dict()
        assert d["avatar"] == "http://av.png"
        assert d["id"] == "m1"
        assert d["parent_id"] == "p1"

    def test_repr(self):
        msg = MatterbridgeMessage(text="a" * 100, username="u", gateway="gw")
        r = repr(msg)
        assert "gw" in r
        assert "u" in r


# ---------------------------------------------------------------------------
# MatterBridgeService — init
# ---------------------------------------------------------------------------


class TestServiceInit:
    def test_init_with_repo(self):
        repo = MagicMock()
        svc = MatterBridgeService(repo=repo, key_secret=_VALID_KEY_HEX)
        assert svc._repo is repo

    def test_init_with_session_factory(self):
        sf = MagicMock()
        svc = MatterBridgeService(session_factory=sf, key_secret=_VALID_KEY_HEX)
        assert svc._session_factory is sf

    def test_init_without_both_raises(self):
        with pytest.raises(ValueError, match="repo or session_factory"):
            MatterBridgeService(key_secret=_VALID_KEY_HEX)


# ---------------------------------------------------------------------------
# MatterBridgeService — lifecycle
# ---------------------------------------------------------------------------


class TestServiceLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_client(self):
        svc, _ = _build_service()
        await svc.start()
        assert svc._client is not None
        assert svc._started is True
        await svc.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        svc, _ = _build_service()
        await svc.start()
        client1 = svc._client
        await svc.start()
        assert svc._client is client1  # same instance
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_client(self):
        svc, _ = _build_service()
        await svc.start()
        assert svc._client is not None
        await svc.stop()
        assert svc._client is None
        assert svc._started is False


# ---------------------------------------------------------------------------
# MatterBridgeService — register_callback
# ---------------------------------------------------------------------------


class TestRegisterCallback:
    def test_register_callback(self):
        svc, _ = _build_service()
        cb = AsyncMock()
        svc.register_callback(cb)
        assert svc._callback is cb


# ---------------------------------------------------------------------------
# MatterBridgeService — binding CRUD
# ---------------------------------------------------------------------------


class TestBindingCRUD:
    @pytest.mark.asyncio
    async def test_create_or_update_binding(self):
        svc, repo = _build_service()
        row = _make_binding_row()
        repo.upsert_binding.return_value = row

        result = await svc.create_or_update_binding(
            world_id=_TEST_WORLD_ID,
            api_url="http://mb.local:4242/",
            api_token="secret-token-123",
        )

        assert result["api_url"] == "http://mb.local:4242"  # trailing slash stripped
        assert result["api_token_preview"] != "secret-token-123"  # masked
        assert result["enabled"] is True
        repo.upsert_binding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_binding_found(self):
        svc, repo = _build_service()
        # Encrypt a real token so _decrypt_token works
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "real-token-abc")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        result = await svc.get_binding(_TEST_WORLD_ID)
        assert result is not None
        assert result["world_id"] == _TEST_WORLD_ID
        assert "real" in result["api_token_preview"] or "*" in result["api_token_preview"]

    @pytest.mark.asyncio
    async def test_get_binding_not_found(self):
        svc, repo = _build_service()
        repo.get_binding.return_value = None

        result = await svc.get_binding(_TEST_WORLD_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_binding(self):
        svc, repo = _build_service()
        repo.delete_binding.return_value = True

        result = await svc.delete_binding(_TEST_WORLD_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_update_binding_field_with_token(self):
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "updated-token")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.update_binding.return_value = row

        result = await svc.update_binding_field(_TEST_WORLD_ID, api_token="updated-token")
        assert result is not None
        # repo should have received encrypted fields, not plaintext
        call_kwargs = repo.update_binding.call_args[1]
        assert "api_token" not in call_kwargs
        assert "api_token_encrypted" in call_kwargs

    @pytest.mark.asyncio
    async def test_update_binding_field_not_found(self):
        svc, repo = _build_service()
        repo.update_binding.return_value = None

        result = await svc.update_binding_field(_TEST_WORLD_ID, enabled=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_enabled_bindings(self):
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "token-1")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.list_enabled.return_value = [row]

        result = await svc.list_enabled_bindings()
        assert len(result) == 1
        assert result[0]["world_id"] == _TEST_WORLD_ID


# ---------------------------------------------------------------------------
# MatterBridgeService — send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_success(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(svc._client, "post", new_callable=AsyncMock, return_value=mock_response):
            ok = await svc.send_message(
                world_id=_TEST_WORLD_ID,
                text="hello world",
                username="bot",
                gateway="gw1",
            )
        assert ok is True
        await svc.stop()

    @pytest.mark.asyncio
    async def test_send_message_no_binding(self):
        svc, repo = _build_service()
        await _start_service(svc)
        repo.get_binding.return_value = None

        ok = await svc.send_message(
            world_id=_TEST_WORLD_ID, text="hi", username="u", gateway="gw",
        )
        assert ok is False
        await svc.stop()

    @pytest.mark.asyncio
    async def test_send_message_http_error(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(svc._client, "post", new_callable=AsyncMock, return_value=mock_response):
            ok = await svc.send_message(
                world_id=_TEST_WORLD_ID, text="hi", username="u", gateway="gw",
            )
        assert ok is False
        await svc.stop()

    @pytest.mark.asyncio
    async def test_send_message_network_error(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        with patch.object(
            svc._client, "post", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("connection refused"),
        ):
            ok = await svc.send_message(
                world_id=_TEST_WORLD_ID, text="hi", username="u", gateway="gw",
            )
        assert ok is False
        await svc.stop()

    @pytest.mark.asyncio
    async def test_send_message_not_started(self):
        svc, repo = _build_service()
        # Don't call start() — _client is None
        ok = await svc.send_message(
            world_id=_TEST_WORLD_ID, text="hi", username="u", gateway="gw",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# MatterBridgeService — get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_get_history_success(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        messages_data = [
            {"text": "msg1", "username": "u1", "gateway": "gw", "id": "1"},
            {"text": "msg2", "username": "u2", "gateway": "gw", "id": "2"},
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = messages_data

        with patch.object(svc._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await svc.get_history(_TEST_WORLD_ID, gateway="gw")

        assert len(result) == 2
        assert result[0].text == "msg1"
        await svc.stop()

    @pytest.mark.asyncio
    async def test_get_history_no_binding(self):
        svc, repo = _build_service()
        await _start_service(svc)
        repo.get_binding.return_value = None

        result = await svc.get_history(_TEST_WORLD_ID, gateway="gw")
        assert result == []
        await svc.stop()

    @pytest.mark.asyncio
    async def test_get_history_404(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(svc._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await svc.get_history(_TEST_WORLD_ID, gateway="gw")
        assert result == []
        await svc.stop()

    @pytest.mark.asyncio
    async def test_get_history_network_error(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        with patch.object(
            svc._client, "get", new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timeout"),
        ):
            result = await svc.get_history(_TEST_WORLD_ID, gateway="gw")
        assert result == []
        await svc.stop()


# ---------------------------------------------------------------------------
# MatterBridgeService — health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(svc._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await svc.health_check(_TEST_WORLD_ID)
        assert result["status"] == "ok"
        await svc.stop()

    @pytest.mark.asyncio
    async def test_health_check_no_binding(self):
        svc, repo = _build_service()
        await _start_service(svc)
        repo.get_binding.return_value = None

        result = await svc.health_check(_TEST_WORLD_ID)
        assert result["status"] == "error"
        assert "No binding" in result["detail"]
        await svc.stop()

    @pytest.mark.asyncio
    async def test_health_check_server_error(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch.object(svc._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await svc.health_check(_TEST_WORLD_ID)
        assert result["status"] == "error"
        assert "503" in result["detail"]
        await svc.stop()

    @pytest.mark.asyncio
    async def test_health_check_network_error(self):
        svc, repo = _build_service()
        await _start_service(svc)

        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        with patch.object(
            svc._client, "get", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("refused"),
        ):
            result = await svc.health_check(_TEST_WORLD_ID)
        assert result["status"] == "error"
        await svc.stop()


# ---------------------------------------------------------------------------
# MatterBridgeService — message deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_first_message_not_duplicate(self):
        svc, _ = _build_service()
        msg = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="m1")
        assert svc._is_duplicate(msg) is False

    def test_second_message_is_duplicate(self):
        svc, _ = _build_service()
        msg = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="m1")
        svc._is_duplicate(msg)
        assert svc._is_duplicate(msg) is True

    def test_different_ids_not_duplicate(self):
        svc, _ = _build_service()
        msg1 = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="m1")
        msg2 = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="m2")
        svc._is_duplicate(msg1)
        assert svc._is_duplicate(msg2) is False

    def test_different_gateways_same_id_not_duplicate(self):
        svc, _ = _build_service()
        msg1 = MatterbridgeMessage(text="hi", username="u", gateway="gw1", msg_id="m1")
        msg2 = MatterbridgeMessage(text="hi", username="u", gateway="gw2", msg_id="m1")
        svc._is_duplicate(msg1)
        assert svc._is_duplicate(msg2) is False

    def test_empty_id_never_duplicate(self):
        svc, _ = _build_service()
        msg = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="")
        svc._is_duplicate(msg)
        assert svc._is_duplicate(msg) is False

    def test_clear_dedup_specific_gateway(self):
        svc, _ = _build_service()
        msg = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="m1")
        svc._is_duplicate(msg)
        svc.clear_dedup("gw")
        assert svc._is_duplicate(msg) is False

    def test_clear_dedup_all(self):
        svc, _ = _build_service()
        msg = MatterbridgeMessage(text="hi", username="u", gateway="gw", msg_id="m1")
        svc._is_duplicate(msg)
        svc.clear_dedup()
        assert svc._is_duplicate(msg) is False


# ---------------------------------------------------------------------------
# MatterBridgeService — message format conversion
# ---------------------------------------------------------------------------


class TestMessageConversion:
    def test_to_mive_message(self):
        msg = MatterbridgeMessage(
            text="hello",
            username="discord_user",
            gateway="gw1",
            protocol="discord",
            msg_id="msg-001",
            timestamp="2026-01-15T10:30:00Z",
        )
        result = MatterBridgeService.to_mive_message(msg, world_id=_TEST_WORLD_ID)

        assert result["world_id"] == _TEST_WORLD_ID
        assert result["type"] == "dialogue"
        assert result["sender_type"] == "user"
        assert result["sender_name"] == "discord_user"
        assert result["content"] == "hello"
        assert result["is_key_message"] is False
        assert result["user_participated"] is False
        # sender_id should be a deterministic UUID
        assert uuid.UUID(result["sender_id"])  # valid UUID

    def test_to_mive_message_deterministic_sender(self):
        msg = MatterbridgeMessage(text="t", username="alice", gateway="gw", protocol="telegram")
        r1 = MatterBridgeService.to_mive_message(msg, world_id=_TEST_WORLD_ID)
        r2 = MatterBridgeService.to_mive_message(msg, world_id=_TEST_WORLD_ID)
        assert r1["sender_id"] == r2["sender_id"]

    def test_to_mive_message_different_users_different_ids(self):
        msg1 = MatterbridgeMessage(text="t", username="alice", gateway="gw", protocol="discord")
        msg2 = MatterbridgeMessage(text="t", username="bob", gateway="gw", protocol="discord")
        r1 = MatterBridgeService.to_mive_message(msg1, world_id=_TEST_WORLD_ID)
        r2 = MatterBridgeService.to_mive_message(msg2, world_id=_TEST_WORLD_ID)
        assert r1["sender_id"] != r2["sender_id"]

    def test_to_mive_message_invalid_timestamp(self):
        msg = MatterbridgeMessage(
            text="t", username="u", gateway="gw", timestamp="not-a-date",
        )
        result = MatterBridgeService.to_mive_message(msg, world_id=_TEST_WORLD_ID)
        assert result["real_time"] is None

    def test_to_mive_message_with_session_id(self):
        msg = MatterbridgeMessage(text="t", username="u", gateway="gw")
        sid = str(uuid.uuid4())
        result = MatterBridgeService.to_mive_message(msg, world_id=_TEST_WORLD_ID, session_id=sid)
        assert result["session_id"] == sid

    def test_from_mive_message(self):
        mive_msg = {
            "id": "m1",
            "content": "test content",
            "sender_name": "char_name",
        }
        result = MatterBridgeService.from_mive_message(mive_msg, gateway="gw1")
        assert result.text == "test content"
        assert result.username == "char_name"
        assert result.gateway == "gw1"
        assert result.msg_id == "m1"

    def test_from_mive_message_defaults(self):
        result = MatterBridgeService.from_mive_message({}, gateway="gw")
        assert result.text == ""
        assert result.username == "MIVE"


# ---------------------------------------------------------------------------
# MatterBridgeService — SSE stream
# ---------------------------------------------------------------------------


class TestStreamLifecycle:
    @pytest.mark.asyncio
    async def test_start_stream_creates_task(self):
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        # Mock _connect_and_listen to avoid real SSE connection
        with patch.object(svc, "_connect_and_listen", new_callable=AsyncMock):
            started = await svc.start_stream(_TEST_WORLD_ID)
        assert started is True
        assert svc.is_stream_running(_TEST_WORLD_ID)

        await svc.stop_stream(_TEST_WORLD_ID)
        assert not svc.is_stream_running(_TEST_WORLD_ID)

    @pytest.mark.asyncio
    async def test_start_stream_no_binding(self):
        svc, repo = _build_service()
        repo.get_binding.return_value = None

        started = await svc.start_stream(_TEST_WORLD_ID)
        assert started is False

    @pytest.mark.asyncio
    async def test_start_stream_already_running(self):
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        with patch.object(svc, "_connect_and_listen", new_callable=AsyncMock):
            await svc.start_stream(_TEST_WORLD_ID)
            # Second start should return True without creating a new task
            started = await svc.start_stream(_TEST_WORLD_ID)
        assert started is True

        await svc.stop_stream(_TEST_WORLD_ID)

    @pytest.mark.asyncio
    async def test_stop_stream_when_not_running(self):
        svc, _ = _build_service()
        # Should not raise
        await svc.stop_stream("nonexistent-world")


class TestSSEEventProcessing:
    @pytest.mark.asyncio
    async def test_process_valid_message(self):
        svc, _ = _build_service()
        callback = AsyncMock()
        svc.register_callback(callback)

        data = json.dumps({
            "text": "hello",
            "username": "user1",
            "gateway": "gw",
            "id": "msg-001",
            "protocol": "discord",
        })
        await svc._process_sse_event(_TEST_WORLD_ID, data)
        callback.assert_awaited_once()
        _, msg = callback.call_args[0]
        assert msg.text == "hello"
        assert msg.username == "user1"

    @pytest.mark.asyncio
    async def test_process_duplicate_ignored(self):
        svc, _ = _build_service()
        callback = AsyncMock()
        svc.register_callback(callback)

        data = json.dumps({"text": "hi", "username": "u", "gateway": "gw", "id": "dup1"})
        await svc._process_sse_event(_TEST_WORLD_ID, data)
        await svc._process_sse_event(_TEST_WORLD_ID, data)  # duplicate
        assert callback.await_count == 1

    @pytest.mark.asyncio
    async def test_process_invalid_json(self):
        svc, _ = _build_service()
        callback = AsyncMock()
        svc.register_callback(callback)

        await svc._process_sse_event(_TEST_WORLD_ID, "not-json")
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_non_dict_json(self):
        svc, _ = _build_service()
        callback = AsyncMock()
        svc.register_callback(callback)

        await svc._process_sse_event(_TEST_WORLD_ID, '"just a string"')
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_empty_text_no_event_skipped(self):
        svc, _ = _build_service()
        callback = AsyncMock()
        svc.register_callback(callback)

        data = json.dumps({"text": "", "username": "u", "gateway": "gw", "id": "e1", "event": ""})
        await svc._process_sse_event(_TEST_WORLD_ID, data)
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_system_event_delivered(self):
        svc, _ = _build_service()
        callback = AsyncMock()
        svc.register_callback(callback)

        data = json.dumps({"text": "", "username": "u", "gateway": "gw", "id": "e2", "event": "join"})
        await svc._process_sse_event(_TEST_WORLD_ID, data)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_propagate(self):
        svc, _ = _build_service()
        callback = AsyncMock(side_effect=RuntimeError("callback boom"))
        svc.register_callback(callback)

        data = json.dumps({"text": "hi", "username": "u", "gateway": "gw", "id": "cb1"})
        # Should not raise
        await svc._process_sse_event(_TEST_WORLD_ID, data)
        callback.assert_awaited_once()


# ---------------------------------------------------------------------------
# MatterBridgeService — stream status
# ---------------------------------------------------------------------------


class TestStreamStatus:
    def test_get_stream_status_empty(self):
        svc, _ = _build_service()
        assert svc.get_stream_status() == {}

    @pytest.mark.asyncio
    async def test_start_all_enabled_streams(self):
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.list_enabled.return_value = [row]
        # start_stream also calls _get_credentials -> repo.get_binding
        repo.get_binding.return_value = row

        with patch.object(svc, "_connect_and_listen", new_callable=AsyncMock):
            count = await svc.start_all_enabled_streams()
        assert count == 1

        await svc.stop_stream(_TEST_WORLD_ID)


# ---------------------------------------------------------------------------
# MatterBridgeService — SSE reconnection backoff
# ---------------------------------------------------------------------------


class TestStreamReconnection:
    @pytest.mark.asyncio
    async def test_reconnect_on_transient_error(self):
        """Verify the stream loop retries after a transient error with backoff."""
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        call_count = 0

        async def _mock_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")
            # On 3rd call, wait for cancel
            cancel_event = args[3] if len(args) > 3 else kwargs.get("cancel_event")
            if cancel_event:
                await cancel_event.wait()

        with patch.object(svc, "_connect_and_listen", side_effect=_mock_connect):
            started = await svc.start_stream(_TEST_WORLD_ID)
            assert started is True
            # Backoff is 1s initial, then 2s — need enough time for 2 retries
            await asyncio.sleep(4)
            await svc.stop_stream(_TEST_WORLD_ID)

        assert call_count >= 2  # at least 2 retries happened

    @pytest.mark.asyncio
    async def test_stream_loop_stops_on_cancel(self):
        """Verify stop_stream cleanly exits the loop."""
        svc, repo = _build_service()
        key = bytes.fromhex(_VALID_KEY_HEX)
        ct, iv = _encrypt_token(key, "tok")
        row = _make_binding_row(api_token_encrypted=ct, api_token_iv=iv)
        repo.get_binding.return_value = row

        async def _mock_connect(world_id, url, headers, cancel_event):
            await cancel_event.wait()

        with patch.object(svc, "_connect_and_listen", side_effect=_mock_connect):
            await svc.start_stream(_TEST_WORLD_ID)
            assert svc.is_stream_running(_TEST_WORLD_ID)
            await svc.stop_stream(_TEST_WORLD_ID)
            assert not svc.is_stream_running(_TEST_WORLD_ID)
