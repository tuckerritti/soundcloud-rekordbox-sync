"""Configuration handling for sc2rb."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sc2rb.constants import (
    DEFAULT_CONCURRENT_DOWNLOADS,
    DEFAULT_MAX_TRACK_DURATION_MS,
    TOKEN_EXPIRY_BUFFER,
)

DEFAULT_YTDLP_CONFIG = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "extract_audio": True,
    "audio_format": "mp3",
    "audio_quality": "0",
    "embed_thumbnail": True,
    "embed_metadata": True,
    "concurrent_downloads": DEFAULT_CONCURRENT_DOWNLOADS,
    "rate_limit": "1M",
    "max_retries": 3,
    "max_track_duration_ms": DEFAULT_MAX_TRACK_DURATION_MS,
}


@dataclass
class Config:
    """Application configuration."""

    root: Path
    client_id: str | None = None
    client_secret: str | None = None
    ytdlp: dict[str, Any] = field(default_factory=lambda: DEFAULT_YTDLP_CONFIG.copy())
    excluded_playlist_urns: list[str] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.root / "db.sqlite"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def tokens_path(self) -> Path:
        return self.root / "tokens.json"

    @property
    def tracks_dir(self) -> Path:
        return self.root / "tracks"

    @property
    def downloads_dir(self) -> Path:
        return self.root / "downloads"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def rekordbox_xml_path(self) -> Path:
        return self.exports_dir / "rekordbox.xml"

    def save(self) -> None:
        """Save configuration to config.json."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "ytdlp": self.ytdlp,
            "excluded_playlist_urns": self.excluded_playlist_urns,
        }
        self.config_path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, root: Path) -> "Config":
        """Load configuration from root directory."""
        config_path = root / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config not found at {config_path}. Run 'sc2rb init' first."
            )

        data = json.loads(config_path.read_text())
        return cls(
            root=root,
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            ytdlp=data.get("ytdlp", DEFAULT_YTDLP_CONFIG.copy()),
            excluded_playlist_urns=data.get("excluded_playlist_urns", []),
        )


@dataclass
class Tokens:
    """OAuth tokens."""

    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None  # ISO 8601 timestamp

    def is_expired(self, buffer_seconds: int = TOKEN_EXPIRY_BUFFER) -> bool:
        """Check if access token is expired or will expire soon.

        Args:
            buffer_seconds: Consider expired if within this many seconds of expiry

        Returns:
            True if expired or expiring soon, False if valid or no expiry set
        """
        if not self.expires_at:
            return False

        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            remaining = (expiry - now).total_seconds()
            return remaining < buffer_seconds
        except (ValueError, TypeError, AttributeError):
            # Invalid format - treat as expired to trigger re-auth
            return True

    def save(self, path: Path) -> None:
        """Save tokens to file."""
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Tokens":
        """Load tokens from file."""
        if not path.exists():
            raise FileNotFoundError(
                f"Tokens not found at {path}. Run 'sc2rb auth' first."
            )
        data = json.loads(path.read_text())
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
        )

    @classmethod
    def from_oauth_response(cls, token_data: dict) -> "Tokens":
        """Create Tokens from OAuth API response.

        Args:
            token_data: Response from /oauth2/token endpoint

        Returns:
            Tokens instance with calculated expiry time
        """
        expires_at = None
        if "expires_in" in token_data:
            expires_in = int(token_data["expires_in"])
            expiry_time = datetime.now(timezone.utc).timestamp() + expires_in
            expires_at = datetime.fromtimestamp(expiry_time, timezone.utc).isoformat()

        return cls(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
        )


GLOBAL_CONFIG_PATH = Path.home() / ".sc2rb"


def save_default_root(root: Path) -> None:
    """Save root path to global config so it can be found later."""
    GLOBAL_CONFIG_PATH.write_text(json.dumps({"root": str(root)}))


def find_root() -> Path:
    """Find the sc2rb root directory.

    Search order:
    1. Current directory and parents (up to home)
    2. Global config file (~/.sc2rb)
    """
    cwd = Path.cwd()
    home = Path.home()

    # Check current directory and parents
    for path in [cwd] + list(cwd.parents):
        if (path / "config.json").exists() and (path / "db.sqlite").exists():
            return path
        if path == home:
            break

    # Check global config
    if GLOBAL_CONFIG_PATH.exists():
        data = json.loads(GLOBAL_CONFIG_PATH.read_text())
        root = Path(data.get("root", "")).expanduser()
        if root.exists() and (root / "db.sqlite").exists():
            return root

    raise FileNotFoundError(
        "Could not find sc2rb root. Run 'sc2rb init --root <path>' first, "
        "or run sc2rb from within an initialized directory."
    )
