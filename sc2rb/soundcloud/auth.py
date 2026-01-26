"""SoundCloud OAuth authentication."""

import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from sc2rb.config import Tokens
from sc2rb.constants import OAUTH_CALLBACK_TIMEOUT

AUTHORIZE_URL = "https://api.soundcloud.com/connect"
TOKEN_URL = "https://api.soundcloud.com/oauth2/token"
REDIRECT_URI = "http://localhost:8080/callback"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to receive OAuth callback."""

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        """Handle GET request from OAuth callback."""
        parsed = urlparse(self.path)

        if parsed.path == "/callback":
            params = parse_qs(parsed.query)

            if "error" in params:
                OAuthCallbackHandler.error = params["error"][0]
            elif "code" in params:
                OAuthCallbackHandler.auth_code = params["code"][0]
                OAuthCallbackHandler.state = params.get("state", [None])[0]

            # Send response
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            if OAuthCallbackHandler.error:
                html = f"<html><body><h1>Authentication Failed</h1><p>{OAuthCallbackHandler.error}</p></body></html>"
            else:
                html = "<html><body><h1>Authentication Successful!</h1><p>You can close this window.</p></body></html>"

            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:
        """Suppress HTTP logging."""
        pass


def run_oauth_flow(client_id: str, client_secret: str | None) -> Tokens:
    """Run the OAuth flow and return tokens.

    1. Start local HTTP server for callback
    2. Open browser to SoundCloud authorization URL
    3. Wait for callback with auth code
    4. Exchange code for tokens
    """
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Build authorization URL
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }
    auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"

    # Reset handler state
    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.state = None
    OAuthCallbackHandler.error = None

    # Start server
    server = HTTPServer(("localhost", 8080), OAuthCallbackHandler)
    server.timeout = OAUTH_CALLBACK_TIMEOUT

    print(f"Opening browser for authentication...")
    print(f"If browser doesn't open, visit: {auth_url}")
    webbrowser.open(auth_url)

    # Wait for callback
    while OAuthCallbackHandler.auth_code is None and OAuthCallbackHandler.error is None:
        server.handle_request()

    server.server_close()

    if OAuthCallbackHandler.error:
        raise RuntimeError(f"OAuth error: {OAuthCallbackHandler.error}")

    if OAuthCallbackHandler.state != state:
        raise RuntimeError("OAuth state mismatch - possible CSRF attack")

    # Exchange code for tokens
    return exchange_code(
        client_id=client_id,
        client_secret=client_secret,
        code=OAuthCallbackHandler.auth_code,
    )


def exchange_code(client_id: str, client_secret: str | None, code: str) -> Tokens:
    """Exchange authorization code for access tokens."""
    data = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    if client_secret:
        data["client_secret"] = client_secret

    response = httpx.post(TOKEN_URL, data=data)
    response.raise_for_status()

    return Tokens.from_oauth_response(response.json())


def refresh_tokens(client_id: str, client_secret: str | None, refresh_token: str) -> Tokens:
    """Refresh expired access token."""
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    if client_secret:
        data["client_secret"] = client_secret

    response = httpx.post(TOKEN_URL, data=data)
    response.raise_for_status()

    token_data = response.json()
    # Preserve original refresh_token if not returned
    if "refresh_token" not in token_data:
        token_data["refresh_token"] = refresh_token

    return Tokens.from_oauth_response(token_data)
