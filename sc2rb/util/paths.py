"""Path and filename utilities for sc2rb."""

import re
import unicodedata

MAX_FILENAME_LENGTH = 120
UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Remove filesystem-hostile characters and normalize unicode."""
    # Normalize unicode to NFC
    name = unicodedata.normalize("NFC", name)

    # Replace unsafe characters with underscore
    name = UNSAFE_CHARS.sub("_", name)

    # Collapse multiple underscores/spaces
    name = re.sub(r"[_\s]+", " ", name)

    # Strip leading/trailing whitespace and dots
    name = name.strip(" .")

    return name


def canonical_filename(artist: str, title: str, file_hash: str, ext: str) -> str:
    """Generate canonical filename: {artist} - {title} [{hash8}].{ext}"""
    artist = sanitize_filename(artist)
    title = sanitize_filename(title)
    hash8 = file_hash[:8]

    # Ensure extension starts with dot
    if not ext.startswith("."):
        ext = f".{ext}"

    # Build base name
    base = f"{artist} - {title}"

    # Truncate if needed (leaving room for hash and extension)
    suffix = f" [{hash8}]{ext}"
    max_base = MAX_FILENAME_LENGTH - len(suffix)

    if len(base) > max_base:
        base = base[: max_base - 3].rstrip() + "..."

    return f"{base}{suffix}"


def safe_path_join(base: str, *parts: str) -> str:
    """Join path parts safely, preventing directory traversal."""
    from pathlib import Path

    base_path = Path(base).resolve()
    result = base_path

    for part in parts:
        # Sanitize each part
        safe_part = sanitize_filename(part)
        result = result / safe_part

    # Ensure result is still under base
    result = result.resolve()
    if not str(result).startswith(str(base_path)):
        raise ValueError(f"Path traversal detected: {result}")

    return str(result)
