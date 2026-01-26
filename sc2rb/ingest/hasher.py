"""SHA-256 hashing utilities for sc2rb."""

import hashlib
from pathlib import Path

CHUNK_SIZE = 64 * 1024  # 64KB


def hash_file(path: Path) -> str:
    """Compute SHA-256 hash of a file using streaming reads.

    Args:
        path: Path to the file to hash

    Returns:
        Hex-encoded SHA-256 digest
    """
    sha256 = hashlib.sha256()

    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            sha256.update(chunk)

    return sha256.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Compute SHA-256 hash of bytes.

    Args:
        data: Bytes to hash

    Returns:
        Hex-encoded SHA-256 digest
    """
    return hashlib.sha256(data).hexdigest()
