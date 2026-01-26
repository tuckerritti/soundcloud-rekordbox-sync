"""Tests for hashing utilities."""

import tempfile
from pathlib import Path

import pytest

from sc2rb.ingest.hasher import hash_bytes, hash_file


class TestHashBytes:
    def test_empty_bytes(self):
        # SHA-256 of empty string
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert hash_bytes(b"") == expected

    def test_known_hash(self):
        # SHA-256 of "hello"
        expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert hash_bytes(b"hello") == expected

    def test_returns_hex_string(self):
        result = hash_bytes(b"test")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestHashFile:
    def test_hashes_file_contents(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
            f.flush()
            path = Path(f.name)

        try:
            expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            assert hash_file(path) == expected
        finally:
            path.unlink()

    def test_streaming_large_file(self):
        # Create a file larger than chunk size (64KB)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * (100 * 1024))  # 100KB
            f.flush()
            path = Path(f.name)

        try:
            result = hash_file(path)
            assert len(result) == 64
        finally:
            path.unlink()
