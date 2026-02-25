"""SoundCloud API client."""

import time
from pathlib import Path
from typing import Any

import httpx

from sc2rb.config import Tokens
from sc2rb.constants import API_REQUEST_TIMEOUT

API_BASE = "https://api.soundcloud.com"


class SoundCloudClient:
    """HTTP client for SoundCloud API with automatic token refresh."""

    def __init__(
        self,
        tokens: Tokens,
        client_id: str | None = None,
        client_secret: str | None = None,
        tokens_path: Path | None = None,
    ):
        """Initialize SoundCloud client.

        Args:
            tokens: OAuth tokens
            client_id: SoundCloud app client ID (required for token refresh)
            client_secret: SoundCloud app client secret (optional)
            tokens_path: Path to save refreshed tokens (optional)
        """
        self._tokens = tokens
        self._client_id = client_id
        self._client_secret = client_secret
        self._tokens_path = tokens_path
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"OAuth {tokens.access_token}"},
            timeout=API_REQUEST_TIMEOUT,
        )

    def _ensure_valid_token(self) -> None:
        """Refresh token if expired."""
        if not self._tokens.is_expired():
            return

        if not self._client_id or not self._tokens.refresh_token:
            raise RuntimeError(
                "Access token expired and cannot refresh. Run 'sc2rb auth' again."
            )

        from sc2rb.soundcloud.auth import refresh_tokens

        self._tokens = refresh_tokens(
            self._client_id,
            self._client_secret,
            self._tokens.refresh_token,
        )

        # Update client headers
        self._client.headers["Authorization"] = f"OAuth {self._tokens.access_token}"

        # Save refreshed tokens
        if self._tokens_path:
            self._tokens.save(self._tokens_path)

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        max_retries: int = 3,
    ) -> Any:
        """Make an API request with retry and rate limit handling."""
        self._ensure_valid_token()

        retries = 0
        backoff = 1.0

        while True:
            try:
                response = self._client.request(method, path, params=params)

                if response.status_code == 429:
                    # Rate limited - wait and retry
                    retry_after = int(response.headers.get("Retry-After", backoff))
                    time.sleep(retry_after)
                    backoff *= 2
                    retries += 1
                    if retries >= max_retries:
                        response.raise_for_status()
                    continue

                if response.status_code >= 500:
                    # Server error - retry with backoff
                    time.sleep(backoff)
                    backoff *= 2
                    retries += 1
                    if retries >= max_retries:
                        response.raise_for_status()
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException:
                retries += 1
                if retries >= max_retries:
                    raise
                time.sleep(backoff)
                backoff *= 2

    def _paginate(self, path: str, params: dict | None = None) -> list[Any]:
        """Fetch all pages of a paginated endpoint."""
        self._ensure_valid_token()

        params = params or {}
        params.setdefault("limit", 200)

        results = []
        next_href = None

        while True:
            if next_href:
                # next_href is a full URL, need to request it directly with retry logic
                data = self._request_url(next_href)
            else:
                data = self._request("GET", path, params)

            if isinstance(data, list):
                # Simple list response
                results.extend(data)
                break
            elif "collection" in data:
                # Paginated response
                results.extend(data["collection"])
                next_href = data.get("next_href")
                if not next_href:
                    break
            else:
                # Single item
                results.append(data)
                break

        return results

    def _request_url(self, url: str, max_retries: int = 3) -> Any:
        """Make a request to a full URL with retry logic."""
        self._ensure_valid_token()

        retries = 0
        backoff = 1.0

        while True:
            try:
                response = self._client.get(url)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", backoff))
                    time.sleep(retry_after)
                    backoff *= 2
                    retries += 1
                    if retries >= max_retries:
                        response.raise_for_status()
                    continue

                if response.status_code >= 500:
                    time.sleep(backoff)
                    backoff *= 2
                    retries += 1
                    if retries >= max_retries:
                        response.raise_for_status()
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException:
                retries += 1
                if retries >= max_retries:
                    raise
                time.sleep(backoff)
                backoff *= 2

    def get_me(self) -> dict:
        """Get current user info."""
        return self._request("GET", "/me")

    def get_my_playlists(self) -> list[dict]:
        """Get all playlists for current user."""
        return self._paginate("/me/playlists")

    def get_my_liked_tracks(self) -> list[dict]:
        """Get all liked/favorited tracks for current user."""
        items = self._paginate("/me/likes/tracks")
        return [item["track"] if "track" in item else item for item in items]

    def get_playlist(self, playlist_id: str) -> dict:
        """Get a single playlist by ID."""
        return self._request("GET", f"/playlists/{playlist_id}")

    def get_track(self, track_id: str) -> dict:
        """Get a single track by ID."""
        return self._request("GET", f"/tracks/{track_id}")

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "SoundCloudClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
