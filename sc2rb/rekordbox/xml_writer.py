"""Rekordbox XML export."""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sc2rb import db
from sc2rb.config import Config


def track_id_from_hash(sha256: str) -> str:
    """Generate stable track ID from SHA-256 hash.

    Uses first 16 hex chars converted to integer.
    """
    # Use first 16 hex chars (64 bits) as integer
    return str(int(sha256[:16], 16) % (2**31))


def format_duration(ms: int) -> str:
    """Format duration in milliseconds to MM:SS format."""
    seconds = ms // 1000
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


def file_url(path: str) -> str:
    """Convert file path to file:// URL."""
    # Ensure path is absolute
    abs_path = Path(path).resolve()
    # URL-encode the path, but preserve slashes
    encoded = quote(str(abs_path), safe="/")
    return f"file://localhost{encoded}"


def export_rekordbox_xml(config: Config) -> None:
    """Export Rekordbox XML file with all resolved tracks and playlists.

    Args:
        config: Application configuration
    """
    with db.connect(config.db_path) as conn:
        tracks = db.get_resolved_tracks(conn)
        playlists = db.get_all_playlists(conn)

        # Build track lookup by URN
        track_map: dict[str, dict[str, Any]] = {}
        for track in tracks:
            track_map[track["track_urn"]] = dict(track)

        # Create XML structure
        root = ET.Element("DJ_PLAYLISTS")
        root.set("Version", "1.0.0")

        # Product info
        product = ET.SubElement(root, "PRODUCT")
        product.set("Name", "sc2rb")
        product.set("Version", "0.1.0")
        product.set("Company", "")

        # Collection
        collection = ET.SubElement(root, "COLLECTION")
        collection.set("Entries", str(len(tracks)))

        for track in tracks:
            if not track["canonical_path"] or not track["sha256"]:
                continue

            track_elem = ET.SubElement(collection, "TRACK")
            track_id = track_id_from_hash(track["sha256"])

            track_elem.set("TrackID", track_id)
            track_elem.set("Name", track["title"] or "Unknown")
            track_elem.set("Artist", track["artist"] or "Unknown")
            track_elem.set("Kind", _get_file_kind(track["canonical_path"]))
            track_elem.set("Location", file_url(track["canonical_path"]))

            if track["duration_ms"]:
                # TotalTime is in seconds
                track_elem.set("TotalTime", str(track["duration_ms"] // 1000))

            if track["filesize"]:
                track_elem.set("Size", str(track["filesize"]))

            # Comments field for SoundCloud URL
            if track["permalink_url"]:
                track_elem.set("Comments", track["permalink_url"])

        # Playlists
        playlists_elem = ET.SubElement(root, "PLAYLISTS")
        playlists_root = ET.SubElement(playlists_elem, "NODE")
        playlists_root.set("Type", "0")  # Folder
        playlists_root.set("Name", "ROOT")
        playlists_root.set("Count", str(len(playlists)))

        for playlist in playlists:
            playlist_tracks = db.get_playlist_tracks(conn, playlist["playlist_urn"])

            # Filter to only resolved tracks
            resolved_urns = [t["track_urn"] for t in playlist_tracks if t["track_urn"] in track_map]

            if not resolved_urns:
                continue

            playlist_node = ET.SubElement(playlists_root, "NODE")
            playlist_node.set("Type", "1")  # Playlist
            playlist_node.set("Name", playlist["title"])
            playlist_node.set("Entries", str(len(resolved_urns)))
            playlist_node.set("KeyType", "0")

            for urn in resolved_urns:
                track_data = track_map[urn]
                if track_data["sha256"]:
                    track_ref = ET.SubElement(playlist_node, "TRACK")
                    track_ref.set("Key", track_id_from_hash(track_data["sha256"]))

    # Write XML file
    config.exports_dir.mkdir(parents=True, exist_ok=True)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    with open(config.rekordbox_xml_path, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True)


def _get_file_kind(path: str) -> str:
    """Get file kind from extension."""
    ext = Path(path).suffix.lower()
    kinds = {
        ".mp3": "MP3 File",
        ".m4a": "M4A File",
        ".aac": "AAC File",
        ".wav": "WAV File",
        ".aiff": "AIFF File",
        ".aif": "AIFF File",
        ".flac": "FLAC File",
    }
    return kinds.get(ext, "Audio File")


def validate_xml(path: Path) -> list[str]:
    """Validate Rekordbox XML file.

    Args:
        path: Path to XML file

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not path.exists():
        return ["XML file does not exist"]

    try:
        tree = ET.parse(path)
        root = tree.getroot()

        if root.tag != "DJ_PLAYLISTS":
            errors.append(f"Invalid root element: {root.tag}")

        # Check collection exists
        collection = root.find("COLLECTION")
        if collection is None:
            errors.append("Missing COLLECTION element")
        else:
            # Verify track locations exist
            for track in collection.findall("TRACK"):
                location = track.get("Location", "")
                if location.startswith("file://localhost"):
                    # Decode URL-encoded path (e.g., %20 -> space)
                    file_path = unquote(location.replace("file://localhost", ""))
                    if not Path(file_path).exists():
                        errors.append(f"Track file missing: {file_path}")

        # Check playlists
        playlists = root.find("PLAYLISTS")
        if playlists is None:
            errors.append("Missing PLAYLISTS element")

    except ET.ParseError as e:
        errors.append(f"XML parse error: {e}")

    return errors
