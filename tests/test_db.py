"""Tests for database module."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from sc2rb import db


@pytest.fixture
def test_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = Path(f.name)

    db.init_schema(db_path)
    yield db_path
    db_path.unlink()


class TestInitSchema:
    def test_creates_tables(self, test_db):
        with db.connect(test_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}

            assert "tracks" in table_names
            assert "playlists" in table_names
            assert "playlist_tracks" in table_names
            assert "file_index" in table_names


class TestTrackOperations:
    def test_upsert_track_creates_new(self, test_db):
        with db.connect(test_db) as conn:
            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:123",
                sc_id="123",
                title="Test Track",
                artist="Test Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test/track",
            )

            track = conn.execute(
                "SELECT * FROM tracks WHERE track_urn = ?",
                ("soundcloud:tracks:123",),
            ).fetchone()

            assert track["title"] == "Test Track"
            assert track["artist"] == "Test Artist"
            assert track["duration_ms"] == 180000

    def test_upsert_track_updates_existing(self, test_db):
        with db.connect(test_db) as conn:
            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:123",
                sc_id="123",
                title="Original Title",
                artist="Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test/track",
            )

            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:123",
                sc_id="123",
                title="Updated Title",
                artist="Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test/track",
            )

            track = conn.execute(
                "SELECT * FROM tracks WHERE track_urn = ?",
                ("soundcloud:tracks:123",),
            ).fetchone()

            assert track["title"] == "Updated Title"

    def test_update_track_download(self, test_db):
        with db.connect(test_db) as conn:
            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:123",
                sc_id="123",
                title="Test",
                artist="Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test",
            )

            db.update_track_download(
                conn,
                track_urn="soundcloud:tracks:123",
                canonical_path="/path/to/file.mp3",
                sha256="abc123",
                filesize=1000000,
            )

            track = conn.execute(
                "SELECT * FROM tracks WHERE track_urn = ?",
                ("soundcloud:tracks:123",),
            ).fetchone()

            assert track["canonical_path"] == "/path/to/file.mp3"
            assert track["sha256"] == "abc123"
            assert track["download_status"] == "completed"

    def test_get_tracks_to_download(self, test_db):
        with db.connect(test_db) as conn:
            # Create tracks with different statuses
            for i, status in enumerate([None, None, "completed", "failed"]):
                db.upsert_track(
                    conn,
                    track_urn=f"soundcloud:tracks:{i}",
                    sc_id=str(i),
                    title=f"Track {i}",
                    artist="Artist",
                    duration_ms=180000,
                    permalink_url=f"https://soundcloud.com/test/{i}",
                )
                if status:
                    db.update_track_status(conn, f"soundcloud:tracks:{i}", status)

            # Only pending (NULL status) tracks
            pending = db.get_tracks_to_download(conn)
            assert len(pending) == 2

            # Include failed
            with_failed = db.get_tracks_to_download(conn, include_failed=True)
            assert len(with_failed) == 3

    def test_get_tracks_to_download_with_limit(self, test_db):
        with db.connect(test_db) as conn:
            for i in range(5):
                db.upsert_track(
                    conn,
                    track_urn=f"soundcloud:tracks:{i}",
                    sc_id=str(i),
                    title=f"Track {i}",
                    artist="Artist",
                    duration_ms=180000,
                    permalink_url=f"https://soundcloud.com/test/{i}",
                )

            limited = db.get_tracks_to_download(conn, limit=2)
            assert len(limited) == 2


class TestPlaylistOperations:
    def test_upsert_playlist(self, test_db):
        with db.connect(test_db) as conn:
            db.upsert_playlist(
                conn,
                playlist_urn="soundcloud:playlists:456",
                sc_id="456",
                title="Test Playlist",
            )

            playlist = conn.execute(
                "SELECT * FROM playlists WHERE playlist_urn = ?",
                ("soundcloud:playlists:456",),
            ).fetchone()

            assert playlist["title"] == "Test Playlist"

    def test_set_playlist_tracks(self, test_db):
        with db.connect(test_db) as conn:
            # Create playlist and tracks
            db.upsert_playlist(
                conn,
                playlist_urn="soundcloud:playlists:1",
                sc_id="1",
                title="Playlist",
            )
            for i in range(3):
                db.upsert_track(
                    conn,
                    track_urn=f"soundcloud:tracks:{i}",
                    sc_id=str(i),
                    title=f"Track {i}",
                    artist="Artist",
                    duration_ms=180000,
                    permalink_url=f"https://soundcloud.com/test/{i}",
                )

            # Set playlist tracks
            db.set_playlist_tracks(
                conn,
                "soundcloud:playlists:1",
                ["soundcloud:tracks:0", "soundcloud:tracks:1", "soundcloud:tracks:2"],
            )

            # Verify order is preserved
            tracks = db.get_playlist_tracks(conn, "soundcloud:playlists:1")
            assert len(tracks) == 3
            assert tracks[0]["track_urn"] == "soundcloud:tracks:0"
            assert tracks[2]["track_urn"] == "soundcloud:tracks:2"

    def test_set_playlist_tracks_replaces_existing(self, test_db):
        with db.connect(test_db) as conn:
            db.upsert_playlist(
                conn,
                playlist_urn="soundcloud:playlists:1",
                sc_id="1",
                title="Playlist",
            )
            for i in range(3):
                db.upsert_track(
                    conn,
                    track_urn=f"soundcloud:tracks:{i}",
                    sc_id=str(i),
                    title=f"Track {i}",
                    artist="Artist",
                    duration_ms=180000,
                    permalink_url=f"https://soundcloud.com/test/{i}",
                )

            # Set initial tracks
            db.set_playlist_tracks(
                conn,
                "soundcloud:playlists:1",
                ["soundcloud:tracks:0", "soundcloud:tracks:1"],
            )

            # Replace with new set
            db.set_playlist_tracks(
                conn,
                "soundcloud:playlists:1",
                ["soundcloud:tracks:2"],
            )

            tracks = db.get_playlist_tracks(conn, "soundcloud:playlists:1")
            assert len(tracks) == 1
            assert tracks[0]["track_urn"] == "soundcloud:tracks:2"


class TestFileIndex:
    def test_index_file(self, test_db):
        with db.connect(test_db) as conn:
            db.index_file(
                conn,
                sha256="abc123",
                path="/path/to/file.mp3",
                filesize=1000000,
                mtime="123456789",
            )

            file = db.get_file_by_sha256(conn, "abc123")
            assert file["path"] == "/path/to/file.mp3"
            assert file["filesize"] == 1000000

    def test_index_file_updates_existing(self, test_db):
        with db.connect(test_db) as conn:
            db.index_file(
                conn, sha256="abc123", path="/old/path.mp3", filesize=1000, mtime="1"
            )

            db.index_file(
                conn, sha256="abc123", path="/new/path.mp3", filesize=2000, mtime="2"
            )

            file = db.get_file_by_sha256(conn, "abc123")
            assert file["path"] == "/new/path.mp3"
            assert file["filesize"] == 2000


class TestSyncStats:
    def test_get_sync_stats(self, test_db):
        with db.connect(test_db) as conn:
            # Create some data
            db.upsert_playlist(
                conn, playlist_urn="soundcloud:playlists:1", sc_id="1", title="Playlist"
            )

            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:1",
                sc_id="1",
                title="Pending",
                artist="Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test/1",
            )

            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:2",
                sc_id="2",
                title="Completed",
                artist="Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test/2",
            )
            db.update_track_download(
                conn, "soundcloud:tracks:2", "/path/file.mp3", "hash", 1000
            )

            db.upsert_track(
                conn,
                track_urn="soundcloud:tracks:3",
                sc_id="3",
                title="Failed",
                artist="Artist",
                duration_ms=180000,
                permalink_url="https://soundcloud.com/test/3",
            )
            db.update_track_status(conn, "soundcloud:tracks:3", "failed", "error")

            stats = db.get_sync_stats(conn)

            assert stats["playlists"] == 1
            assert stats["total_tracks"] == 3
            assert stats["resolved"] == 1
            assert stats["pending"] == 1
            assert stats["failed"] == 1
