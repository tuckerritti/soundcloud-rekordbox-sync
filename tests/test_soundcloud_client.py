"""Tests for SoundCloud client module."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from sc2rb.config import Tokens
from sc2rb.soundcloud.client import SoundCloudClient


@pytest.fixture
def valid_tokens():
    """Create tokens that won't expire during tests."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    return Tokens(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at=future.isoformat(),
    )


@pytest.fixture
def expired_tokens():
    """Create expired tokens."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    return Tokens(
        access_token="expired_token",
        refresh_token="test_refresh_token",
        expires_at=past.isoformat(),
    )


class TestSoundCloudClientInit:
    def test_creates_client_with_auth_header(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        assert "Authorization" in client._client.headers
        assert client._client.headers["Authorization"] == "OAuth test_access_token"

        client.close()

    def test_context_manager(self, valid_tokens):
        with SoundCloudClient(tokens=valid_tokens) as client:
            assert client._client is not None


class TestTokenRefresh:
    def test_refresh_not_triggered_when_valid(self, valid_tokens):
        client = SoundCloudClient(
            tokens=valid_tokens,
            client_id="test_id",
            client_secret="test_secret",
        )

        with patch("sc2rb.soundcloud.auth.refresh_tokens") as mock_refresh:
            client._ensure_valid_token()
            mock_refresh.assert_not_called()

        client.close()

    def test_refresh_triggered_when_expired(self, expired_tokens, tmp_path):
        tokens_path = tmp_path / "tokens.json"
        expired_tokens.save(tokens_path)

        client = SoundCloudClient(
            tokens=expired_tokens,
            client_id="test_id",
            client_secret="test_secret",
            tokens_path=tokens_path,
        )

        new_future = datetime.now(timezone.utc) + timedelta(hours=1)
        new_tokens = Tokens(
            access_token="new_access_token",
            refresh_token="new_refresh_token",
            expires_at=new_future.isoformat(),
        )

        with patch(
            "sc2rb.soundcloud.auth.refresh_tokens", return_value=new_tokens
        ) as mock_refresh:
            client._ensure_valid_token()

            mock_refresh.assert_called_once_with(
                "test_id", "test_secret", "test_refresh_token"
            )

        assert client._tokens.access_token == "new_access_token"
        assert client._client.headers["Authorization"] == "OAuth new_access_token"

        # Verify tokens were saved
        saved = Tokens.load(tokens_path)
        assert saved.access_token == "new_access_token"

        client.close()

    def test_refresh_raises_without_client_id(self, expired_tokens):
        client = SoundCloudClient(tokens=expired_tokens)

        with pytest.raises(RuntimeError, match="cannot refresh"):
            client._ensure_valid_token()

        client.close()

    def test_refresh_raises_without_refresh_token(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        tokens = Tokens(
            access_token="expired",
            refresh_token=None,
            expires_at=past.isoformat(),
        )

        client = SoundCloudClient(tokens=tokens, client_id="test_id")

        with pytest.raises(RuntimeError, match="cannot refresh"):
            client._ensure_valid_token()

        client.close()


class TestAPIRequests:
    def test_get_me(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 123, "username": "testuser"}

        with patch.object(client._client, "request", return_value=mock_response):
            result = client.get_me()

        assert result["username"] == "testuser"
        client.close()

    def test_retry_on_server_error(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        error_response = MagicMock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=error_response
        )

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch.object(
            client._client, "request", side_effect=[error_response, success_response]
        ):
            with patch("time.sleep"):  # Don't actually sleep
                result = client._request("GET", "/test")

        assert result["success"] is True
        client.close()

    def test_retry_on_rate_limit(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.headers = {"Retry-After": "1"}
        rate_limit_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate Limited", request=MagicMock(), response=rate_limit_response
        )

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch.object(
            client._client, "request", side_effect=[rate_limit_response, success_response]
        ):
            with patch("time.sleep"):
                result = client._request("GET", "/test")

        assert result["success"] is True
        client.close()


class TestPagination:
    def test_paginate_single_page(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "collection": [{"id": 1}, {"id": 2}],
            "next_href": None,
        }

        with patch.object(client._client, "request", return_value=mock_response):
            results = client._paginate("/test")

        assert len(results) == 2
        client.close()

    def test_paginate_multiple_pages(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "collection": [{"id": 1}],
            "next_href": "https://api.soundcloud.com/next",
        }

        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "collection": [{"id": 2}],
            "next_href": None,
        }

        with patch.object(
            client._client, "request", return_value=page1_response
        ):
            with patch.object(
                client._client, "get", return_value=page2_response
            ):
                results = client._paginate("/test")

        assert len(results) == 2
        client.close()

    def test_paginate_simple_list(self, valid_tokens):
        client = SoundCloudClient(tokens=valid_tokens)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]

        with patch.object(client._client, "request", return_value=mock_response):
            results = client._paginate("/test")

        assert len(results) == 2
        client.close()
