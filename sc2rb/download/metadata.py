"""Audio metadata handling with mutagen."""

from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, COMM, WXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4


def read_metadata(path: Path) -> dict[str, Any]:
    """Read metadata from an audio file.

    Args:
        path: Path to audio file

    Returns:
        Dictionary with 'title', 'artist', 'duration_ms' keys
    """
    audio = MutagenFile(path, easy=True)

    if audio is None:
        return {"title": None, "artist": None, "duration_ms": None}

    title = None
    artist = None

    if "title" in audio:
        title = audio["title"][0] if audio["title"] else None
    if "artist" in audio:
        artist = audio["artist"][0] if audio["artist"] else None

    # Duration in milliseconds
    duration_ms = int(audio.info.length * 1000) if audio.info else None

    return {
        "title": title,
        "artist": artist,
        "duration_ms": duration_ms,
    }


def write_metadata(
    path: Path,
    title: str | None = None,
    artist: str | None = None,
    comment: str | None = None,
    url: str | None = None,
) -> None:
    """Write metadata to an audio file.

    Args:
        path: Path to audio file
        title: Track title
        artist: Artist name
        comment: Comment text (e.g., SoundCloud permalink)
        url: URL to embed
    """
    suffix = path.suffix.lower()

    if suffix == ".mp3":
        _write_mp3_metadata(path, title, artist, comment, url)
    elif suffix in (".m4a", ".mp4", ".aac"):
        _write_mp4_metadata(path, title, artist, comment, url)
    else:
        # Try generic mutagen for other formats
        _write_generic_metadata(path, title, artist)


def _write_mp3_metadata(
    path: Path,
    title: str | None,
    artist: str | None,
    comment: str | None,
    url: str | None,
) -> None:
    """Write metadata to MP3 file."""
    try:
        audio = MP3(path, ID3=ID3)
    except Exception:
        audio = MP3(path)
        audio.add_tags()

    if audio.tags is None:
        audio.add_tags()

    # Use EasyID3 for simple tags
    easy = EasyID3(path)
    if title:
        easy["title"] = title
    if artist:
        easy["artist"] = artist
    easy.save()

    # Add comment and URL with full ID3
    audio = MP3(path, ID3=ID3)
    if comment:
        audio.tags.add(COMM(encoding=3, lang="eng", desc="", text=comment))
    if url:
        audio.tags.add(WXXX(encoding=3, desc="SoundCloud", url=url))
    audio.save()


def _write_mp4_metadata(
    path: Path,
    title: str | None,
    artist: str | None,
    comment: str | None,
    url: str | None,
) -> None:
    """Write metadata to MP4/M4A file."""
    audio = MP4(path)

    if title:
        audio["\xa9nam"] = [title]
    if artist:
        audio["\xa9ART"] = [artist]
    if comment:
        audio["\xa9cmt"] = [comment]
    # MP4 doesn't have a standard URL tag, use comment

    audio.save()


def _write_generic_metadata(
    path: Path,
    title: str | None,
    artist: str | None,
) -> None:
    """Write metadata using generic mutagen interface."""
    audio = MutagenFile(path, easy=True)

    if audio is None:
        return

    if title:
        audio["title"] = title
    if artist:
        audio["artist"] = artist

    audio.save()


def embed_soundcloud_url(path: Path, permalink_url: str) -> None:
    """Embed SoundCloud permalink URL in audio file metadata.

    Args:
        path: Path to audio file
        permalink_url: SoundCloud permalink URL
    """
    write_metadata(path, comment=permalink_url, url=permalink_url)
