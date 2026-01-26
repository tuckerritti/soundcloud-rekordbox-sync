"""Tests for path utilities."""

import pytest

from sc2rb.util.paths import canonical_filename, sanitize_filename


class TestSanitizeFilename:
    def test_removes_unsafe_chars(self):
        assert sanitize_filename("file/name") == "file name"
        assert sanitize_filename("file:name") == "file name"
        assert sanitize_filename("file\\name") == "file name"
        assert sanitize_filename("file?name") == "file name"

    def test_normalizes_whitespace(self):
        assert sanitize_filename("file   name") == "file name"
        assert sanitize_filename("file___name") == "file name"
        assert sanitize_filename("file _ _ name") == "file name"

    def test_strips_leading_trailing(self):
        assert sanitize_filename("  filename  ") == "filename"
        assert sanitize_filename("..filename..") == "filename"

    def test_unicode_normalization(self):
        # Composed vs decomposed unicode
        assert sanitize_filename("café") == sanitize_filename("cafe\u0301")


class TestCanonicalFilename:
    def test_basic_format(self):
        result = canonical_filename(
            artist="Test Artist",
            title="Test Song",
            file_hash="abc123def456",
            ext=".mp3",
        )
        assert result == "Test Artist - Test Song [abc123de].mp3"

    def test_handles_missing_dot(self):
        result = canonical_filename(
            artist="Artist",
            title="Title",
            file_hash="abcdef12",
            ext="mp3",
        )
        assert result.endswith(".mp3")

    def test_truncates_long_names(self):
        long_title = "A" * 200
        result = canonical_filename(
            artist="Artist",
            title=long_title,
            file_hash="abc123def456",
            ext=".mp3",
        )
        assert len(result) <= 120

    def test_sanitizes_input(self):
        result = canonical_filename(
            artist="Artist/Name",
            title="Song:Title",
            file_hash="abc123",
            ext=".mp3",
        )
        assert "/" not in result
        assert ":" not in result
