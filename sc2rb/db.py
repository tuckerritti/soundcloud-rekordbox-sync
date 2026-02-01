"""Database connection and queries for sc2rb."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    track_urn TEXT PRIMARY KEY,
    sc_id TEXT,
    title TEXT,
    artist TEXT,
    duration_ms INTEGER,
    permalink_url TEXT,
    canonical_path TEXT,
    sha256 TEXT UNIQUE,
    filesize INTEGER,
    download_status TEXT,
    download_attempts INTEGER DEFAULT 0,
    last_download_attempt TEXT,
    download_error TEXT,
    created_at TEXT,
    updated_at TEXT,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS playlists (
    playlist_urn TEXT PRIMARY KEY,
    sc_id TEXT,
    title TEXT,
    last_modified_at TEXT,
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_urn TEXT,
    track_urn TEXT,
    position INTEGER,
    PRIMARY KEY (playlist_urn, track_urn),
    FOREIGN KEY (playlist_urn) REFERENCES playlists(playlist_urn),
    FOREIGN KEY (track_urn) REFERENCES tracks(track_urn)
);

CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_urn);

CREATE TABLE IF NOT EXISTS file_index (
    sha256 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    filesize INTEGER,
    mtime TEXT
);
"""


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Context manager for database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(db_path: Path) -> None:
    """Initialize database with schema."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# --- Track queries ---


def upsert_track(
    conn: sqlite3.Connection,
    track_urn: str,
    sc_id: str,
    title: str,
    artist: str,
    duration_ms: int,
    permalink_url: str,
) -> None:
    """Insert or update a track from SoundCloud metadata."""
    now = now_iso()
    conn.execute(
        """
        INSERT INTO tracks (track_urn, sc_id, title, artist, duration_ms, permalink_url,
                           created_at, updated_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(track_urn) DO UPDATE SET
            title = excluded.title,
            artist = excluded.artist,
            duration_ms = excluded.duration_ms,
            permalink_url = excluded.permalink_url,
            updated_at = excluded.updated_at,
            last_seen_at = excluded.last_seen_at
        """,
        (track_urn, sc_id, title, artist, duration_ms, permalink_url, now, now, now),
    )


def update_track_download(
    conn: sqlite3.Connection,
    track_urn: str,
    canonical_path: str,
    sha256: str,
    filesize: int,
) -> None:
    """Update track with download completion info."""
    conn.execute(
        """
        UPDATE tracks SET
            canonical_path = ?,
            sha256 = ?,
            filesize = ?,
            download_status = 'completed',
            updated_at = ?
        WHERE track_urn = ?
        """,
        (canonical_path, sha256, filesize, now_iso(), track_urn),
    )


def update_track_status(
    conn: sqlite3.Connection,
    track_urn: str,
    status: str,
    error: str | None = None,
) -> None:
    """Update track download status and optionally error message."""
    now = now_iso()
    if status == "failed":
        conn.execute(
            """
            UPDATE tracks SET
                download_status = ?,
                download_attempts = download_attempts + 1,
                last_download_attempt = ?,
                download_error = ?,
                updated_at = ?
            WHERE track_urn = ?
            """,
            (status, now, error, now, track_urn),
        )
    else:
        conn.execute(
            """
            UPDATE tracks SET
                download_status = ?,
                last_download_attempt = ?,
                updated_at = ?
            WHERE track_urn = ?
            """,
            (status, now, now, track_urn),
        )


def get_tracks_to_download(
    conn: sqlite3.Connection,
    playlist_urn: str | None = None,
    include_failed: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Get tracks that need downloading."""
    conditions = ["download_status IS NULL"]
    params: list = []

    if include_failed:
        conditions = ["(download_status IS NULL OR download_status = 'failed')"]

    if playlist_urn:
        conditions.append(
            "track_urn IN (SELECT track_urn FROM playlist_tracks WHERE playlist_urn = ?)"
        )
        params.append(playlist_urn)

    query = f"SELECT * FROM tracks WHERE {' AND '.join(conditions)}"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    return conn.execute(query, params).fetchall()


def get_resolved_tracks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get all tracks that have local files."""
    return conn.execute(
        "SELECT * FROM tracks WHERE canonical_path IS NOT NULL"
    ).fetchall()


def get_track_by_sha256(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    """Find a track by its file hash."""
    return conn.execute(
        "SELECT * FROM tracks WHERE sha256 = ?", (sha256,)
    ).fetchone()


# --- Playlist queries ---


def upsert_playlist(
    conn: sqlite3.Connection,
    playlist_urn: str,
    sc_id: str,
    title: str,
    last_modified_at: str | None = None,
) -> None:
    """Insert or update a playlist."""
    now = now_iso()
    conn.execute(
        """
        INSERT INTO playlists (playlist_urn, sc_id, title, last_modified_at, last_synced_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(playlist_urn) DO UPDATE SET
            title = excluded.title,
            last_modified_at = excluded.last_modified_at,
            last_synced_at = excluded.last_synced_at
        """,
        (playlist_urn, sc_id, title, last_modified_at, now),
    )


def set_playlist_tracks(
    conn: sqlite3.Connection,
    playlist_urn: str,
    track_urns: list[str],
) -> None:
    """Replace all tracks in a playlist with new list (preserving order)."""
    conn.execute("DELETE FROM playlist_tracks WHERE playlist_urn = ?", (playlist_urn,))
    for position, track_urn in enumerate(track_urns):
        conn.execute(
            "INSERT INTO playlist_tracks (playlist_urn, track_urn, position) VALUES (?, ?, ?)",
            (playlist_urn, track_urn, position),
        )


def get_all_playlists(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get all playlists."""
    return conn.execute("SELECT * FROM playlists ORDER BY title").fetchall()


def get_playlist_tracks(
    conn: sqlite3.Connection, playlist_urn: str
) -> list[sqlite3.Row]:
    """Get all tracks in a playlist, ordered by position."""
    return conn.execute(
        """
        SELECT t.* FROM tracks t
        JOIN playlist_tracks pt ON t.track_urn = pt.track_urn
        WHERE pt.playlist_urn = ?
        ORDER BY pt.position
        """,
        (playlist_urn,),
    ).fetchall()


# --- File index queries ---


def index_file(
    conn: sqlite3.Connection,
    sha256: str,
    path: str,
    filesize: int,
    mtime: str,
) -> None:
    """Add or update a file in the index."""
    conn.execute(
        """
        INSERT INTO file_index (sha256, path, filesize, mtime)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(sha256) DO UPDATE SET
            path = excluded.path,
            filesize = excluded.filesize,
            mtime = excluded.mtime
        """,
        (sha256, path, filesize, mtime),
    )


def get_file_by_sha256(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    """Look up a file by its hash."""
    return conn.execute(
        "SELECT * FROM file_index WHERE sha256 = ?", (sha256,)
    ).fetchone()


# --- Stats queries ---


def get_sync_stats(conn: sqlite3.Connection) -> dict:
    """Get statistics for sync summary."""
    total_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    resolved = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE canonical_path IS NOT NULL"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE download_status IS NULL"
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE download_status = 'failed'"
    ).fetchone()[0]
    playlists = conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]

    return {
        "total_tracks": total_tracks,
        "resolved": resolved,
        "pending": pending,
        "failed": failed,
        "playlists": playlists,
    }


# --- Deletion queries ---


def get_orphaned_tracks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get tracks not in any playlist."""
    return conn.execute(
        """
        SELECT * FROM tracks
        WHERE track_urn NOT IN (SELECT track_urn FROM playlist_tracks)
        """
    ).fetchall()


def get_tracks_only_in_playlists(
    conn: sqlite3.Connection,
    playlist_urns: list[str],
) -> list[sqlite3.Row]:
    """Get tracks ONLY in given playlists (not in any other)."""
    if not playlist_urns:
        return []
    placeholders = ",".join("?" * len(playlist_urns))
    return conn.execute(
        f"""
        SELECT * FROM tracks
        WHERE track_urn IN (
            SELECT track_urn FROM playlist_tracks WHERE playlist_urn IN ({placeholders})
        )
        AND track_urn NOT IN (
            SELECT track_urn FROM playlist_tracks WHERE playlist_urn NOT IN ({placeholders})
        )
        """,
        playlist_urns + playlist_urns,
    ).fetchall()


def delete_tracks(conn: sqlite3.Connection, track_urns: list[str]) -> None:
    """Delete tracks and their playlist associations."""
    if not track_urns:
        return
    placeholders = ",".join("?" * len(track_urns))
    conn.execute(
        f"DELETE FROM playlist_tracks WHERE track_urn IN ({placeholders})",
        track_urns,
    )
    conn.execute(
        f"DELETE FROM tracks WHERE track_urn IN ({placeholders})",
        track_urns,
    )


def delete_playlists(conn: sqlite3.Connection, playlist_urns: list[str]) -> None:
    """Delete playlists and their track associations."""
    if not playlist_urns:
        return
    placeholders = ",".join("?" * len(playlist_urns))
    conn.execute(
        f"DELETE FROM playlist_tracks WHERE playlist_urn IN ({placeholders})",
        playlist_urns,
    )
    conn.execute(
        f"DELETE FROM playlists WHERE playlist_urn IN ({placeholders})",
        playlist_urns,
    )


def count_tracks_with_sha256(conn: sqlite3.Connection, sha256: str) -> int:
    """Count tracks referencing a file hash."""
    return conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE sha256 = ?", (sha256,)
    ).fetchone()[0]


def delete_file_index_entry(conn: sqlite3.Connection, sha256: str) -> None:
    """Remove file from index."""
    conn.execute("DELETE FROM file_index WHERE sha256 = ?", (sha256,))
