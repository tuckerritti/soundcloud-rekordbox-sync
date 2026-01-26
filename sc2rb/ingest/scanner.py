"""Directory scanner for audio file ingestion."""

import shutil
from pathlib import Path

from rich.console import Console

from sc2rb import db
from sc2rb.config import Config
from sc2rb.download.metadata import read_metadata
from sc2rb.ingest.hasher import hash_file
from sc2rb.util.paths import canonical_filename

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif", ".flac"}

console = Console()


def find_audio_files(directory: Path) -> list[Path]:
    """Recursively find all audio files in a directory.

    Args:
        directory: Root directory to search

    Returns:
        List of paths to audio files
    """
    files = []
    for ext in AUDIO_EXTENSIONS:
        files.extend(directory.rglob(f"*{ext}"))
        files.extend(directory.rglob(f"*{ext.upper()}"))
    return sorted(set(files))


def scan_and_ingest(
    config: Config,
    inbox_path: Path,
    verbose: bool = False,
) -> dict[str, int]:
    """Scan directory and ingest audio files.

    Args:
        config: Application configuration
        inbox_path: Directory to scan for audio files
        verbose: Whether to print verbose output

    Returns:
        Statistics dict with 'added', 'skipped', 'failed' counts
    """
    stats = {"added": 0, "skipped": 0, "failed": 0}

    files = find_audio_files(inbox_path)

    if not files:
        console.print("No audio files found.")
        return stats

    console.print(f"Found {len(files)} audio files")

    with db.connect(config.db_path) as conn:
        for file_path in files:
            try:
                # Compute hash
                file_hash = hash_file(file_path)

                # Check if already indexed
                existing = db.get_file_by_sha256(conn, file_hash)
                if existing:
                    if verbose:
                        console.print(f"[yellow]Skipped (duplicate): {file_path.name}[/yellow]")
                    stats["skipped"] += 1
                    continue

                # Read metadata
                metadata = read_metadata(file_path)
                title = metadata.get("title") or file_path.stem
                artist = metadata.get("artist") or "Unknown"

                # Generate canonical filename
                ext = file_path.suffix
                new_name = canonical_filename(artist, title, file_hash, ext)
                dest_path = config.tracks_dir / new_name

                # Copy file to tracks directory
                shutil.copy2(file_path, dest_path)

                # Index the file
                filesize = dest_path.stat().st_size
                mtime = str(dest_path.stat().st_mtime_ns)
                db.index_file(conn, file_hash, str(dest_path), filesize, mtime)

                # Try to match against unresolved SoundCloud tracks
                _try_match_track(conn, file_hash, str(dest_path), filesize, title, artist)

                if verbose:
                    console.print(f"[green]Added: {new_name}[/green]")

                stats["added"] += 1

            except Exception as e:
                console.print(f"[red]Failed: {file_path.name} - {e}[/red]")
                stats["failed"] += 1

    return stats


def _try_match_track(
    conn,
    file_hash: str,
    canonical_path: str,
    filesize: int,
    title: str,
    artist: str,
) -> bool:
    """Try to match an ingested file to an unresolved SoundCloud track.

    Uses fuzzy matching on title/artist.

    Args:
        conn: Database connection
        file_hash: SHA-256 of the file
        canonical_path: Path to the file
        filesize: File size in bytes
        title: Track title from metadata
        artist: Artist from metadata

    Returns:
        True if a match was found and linked
    """
    # Normalize for matching
    title_lower = title.lower().strip()
    artist_lower = artist.lower().strip()

    # Get all unresolved tracks
    unresolved = conn.execute(
        "SELECT * FROM tracks WHERE canonical_path IS NULL"
    ).fetchall()

    best_match = None
    best_score = 0

    for track in unresolved:
        track_title = (track["title"] or "").lower().strip()
        track_artist = (track["artist"] or "").lower().strip()

        # Simple matching: check if titles are similar
        score = 0

        # Exact title match
        if track_title == title_lower:
            score += 3
        # Title contains match
        elif title_lower in track_title or track_title in title_lower:
            score += 2

        # Artist match
        if track_artist == artist_lower:
            score += 2
        elif artist_lower in track_artist or track_artist in artist_lower:
            score += 1

        if score > best_score:
            best_score = score
            best_match = track

    # Require at least title similarity to match
    if best_match and best_score >= 2:
        db.update_track_download(
            conn,
            best_match["track_urn"],
            canonical_path,
            file_hash,
            filesize,
        )
        return True

    return False
