"""Tests for configuration module."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sc2rb.config import Config, Tokens, find_root, save_default_root
from sc2rb.constants import TOKEN_EXPIRY_BUFFER


class TestConfig:
    def test_save_and_load(self, tmp_path):
        config = Config(
            root=tmp_path,
            client_id="test_id",
            client_secret="test_secret",
        )
        config.save()

        loaded = Config.load(tmp_path)

        assert loaded.client_id == "test_id"
        assert loaded.client_secret == "test_secret"

    def test_load_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Config.load(tmp_path)

    def test_paths(self, tmp_path):
        config = Config(root=tmp_path)

        assert config.db_path == tmp_path / "db.sqlite"
        assert config.config_path == tmp_path / "config.json"
        assert config.tokens_path == tmp_path / "tokens.json"
        assert config.tracks_dir == tmp_path / "tracks"
        assert config.downloads_dir == tmp_path / "downloads"
        assert config.exports_dir == tmp_path / "exports"
        assert config.logs_dir == tmp_path / "logs"
        assert config.rekordbox_xml_path == tmp_path / "exports" / "rekordbox.xml"

    def test_default_ytdlp_config(self, tmp_path):
        config = Config(root=tmp_path)

        assert config.ytdlp["format"] == "bestaudio[ext=m4a]/bestaudio/best"
        assert config.ytdlp["extract_audio"] is True
        assert config.ytdlp["embed_thumbnail"] is True
        assert config.ytdlp["embed_metadata"] is True


class TestTokens:
    def test_save_and_load(self, tmp_path):
        tokens_path = tmp_path / "tokens.json"

        tokens = Tokens(
            access_token="test_token",
            refresh_token="refresh_token",
            expires_at="2025-01-01T00:00:00+00:00",
        )
        tokens.save(tokens_path)

        loaded = Tokens.load(tokens_path)

        assert loaded.access_token == "test_token"
        assert loaded.refresh_token == "refresh_token"
        assert loaded.expires_at == "2025-01-01T00:00:00+00:00"

    def test_load_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Tokens.load(tmp_path / "nonexistent.json")

    def test_is_expired_no_expiry(self):
        tokens = Tokens(access_token="test")
        assert tokens.is_expired() is False

    def test_is_expired_future(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        tokens = Tokens(
            access_token="test",
            expires_at=future.isoformat(),
        )
        assert tokens.is_expired() is False

    def test_is_expired_past(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        tokens = Tokens(
            access_token="test",
            expires_at=past.isoformat(),
        )
        assert tokens.is_expired() is True

    def test_is_expired_within_buffer(self):
        # Token expires in 60 seconds (within default 300s buffer)
        soon = datetime.now(timezone.utc) + timedelta(seconds=60)
        tokens = Tokens(
            access_token="test",
            expires_at=soon.isoformat(),
        )
        assert tokens.is_expired() is True

    def test_is_expired_outside_buffer(self):
        # Token expires in 10 minutes (outside default 300s buffer)
        later = datetime.now(timezone.utc) + timedelta(minutes=10)
        tokens = Tokens(
            access_token="test",
            expires_at=later.isoformat(),
        )
        assert tokens.is_expired() is False

    def test_is_expired_custom_buffer(self):
        # Token expires in 60 seconds
        soon = datetime.now(timezone.utc) + timedelta(seconds=60)
        tokens = Tokens(
            access_token="test",
            expires_at=soon.isoformat(),
        )
        # With 30s buffer, should not be expired
        assert tokens.is_expired(buffer_seconds=30) is False
        # With 120s buffer, should be expired
        assert tokens.is_expired(buffer_seconds=120) is True

    def test_from_oauth_response(self):
        response = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
        }

        tokens = Tokens.from_oauth_response(response)

        assert tokens.access_token == "access_123"
        assert tokens.refresh_token == "refresh_456"
        assert tokens.expires_at is not None

        # Check expiry is roughly 1 hour from now
        expiry = datetime.fromisoformat(tokens.expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (expiry - now).total_seconds()
        assert 3500 < diff < 3700  # Allow some tolerance

    def test_from_oauth_response_no_expiry(self):
        response = {
            "access_token": "access_123",
        }

        tokens = Tokens.from_oauth_response(response)

        assert tokens.access_token == "access_123"
        assert tokens.refresh_token is None
        assert tokens.expires_at is None

    def test_is_expired_invalid_format_returns_true(self):
        # Invalid format should return True to trigger re-auth
        tokens = Tokens(
            access_token="test",
            expires_at="invalid",
        )
        assert tokens.is_expired() is True


class TestFindRoot:
    def test_finds_root_in_current_dir(self, tmp_path, monkeypatch):
        # Create required files
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "db.sqlite").write_text("")

        monkeypatch.chdir(tmp_path)
        root = find_root()

        assert root == tmp_path

    def test_finds_root_in_parent(self, tmp_path, monkeypatch):
        # Create root structure
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "db.sqlite").write_text("")

        # Create and chdir to subdir
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        root = find_root()

        assert root == tmp_path

    def test_raises_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Remove global config if exists
        global_config = Path.home() / ".sc2rb"
        if global_config.exists():
            original = global_config.read_text()
            global_config.unlink()
            try:
                with pytest.raises(FileNotFoundError):
                    find_root()
            finally:
                global_config.write_text(original)
        else:
            with pytest.raises(FileNotFoundError):
                find_root()


class TestSaveDefaultRoot:
    def test_saves_root(self, tmp_path, monkeypatch):
        # Use a temp file for global config
        global_config = tmp_path / ".sc2rb"
        monkeypatch.setattr("sc2rb.config.GLOBAL_CONFIG_PATH", global_config)

        save_default_root(tmp_path / "my_root")

        data = json.loads(global_config.read_text())
        assert data["root"] == str(tmp_path / "my_root")
