"""Tests for Rekordbox XML writer."""

import xml.etree.ElementTree as ET

import pytest

from sc2rb.rekordbox.xml_writer import (
    file_url,
    format_duration,
    track_id_from_hash,
)


class TestTrackIdFromHash:
    def test_returns_string(self):
        result = track_id_from_hash("abc123def456789012345678901234567890123456789012345678901234")
        assert isinstance(result, str)

    def test_deterministic(self):
        hash_val = "abc123def456789012345678901234567890123456789012345678901234"
        assert track_id_from_hash(hash_val) == track_id_from_hash(hash_val)

    def test_different_hashes_different_ids(self):
        hash1 = "abc123def456789012345678901234567890123456789012345678901234"
        hash2 = "def456abc789012345678901234567890123456789012345678901234567"
        assert track_id_from_hash(hash1) != track_id_from_hash(hash2)


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert format_duration(30000) == "0:30"

    def test_minutes_and_seconds(self):
        assert format_duration(185000) == "3:05"

    def test_long_duration(self):
        # 10 minutes, 30 seconds
        assert format_duration(630000) == "10:30"


class TestFileUrl:
    def test_basic_path(self):
        result = file_url("/Users/test/music/song.mp3")
        assert result.startswith("file://localhost/")
        assert "song.mp3" in result

    def test_encodes_spaces(self):
        result = file_url("/Users/test/My Music/song.mp3")
        assert "%20" in result or " " not in result.split("file://localhost")[1]

    def test_preserves_slashes(self):
        result = file_url("/Users/test/music/song.mp3")
        # Should have forward slashes in path
        assert "/Users/" in result or "%2FUsers" not in result
