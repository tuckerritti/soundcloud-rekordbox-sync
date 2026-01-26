"""Constants for sc2rb."""

# Timeouts (in seconds)
OAUTH_CALLBACK_TIMEOUT = 120  # Wait for OAuth callback
API_REQUEST_TIMEOUT = 30  # SoundCloud API requests
DOWNLOAD_TIMEOUT = 300  # yt-dlp download timeout (5 minutes)

# Download limits
DEFAULT_MAX_TRACK_DURATION_MS = 10 * 60 * 1000  # Skip tracks over 10 minutes
DEFAULT_CONCURRENT_DOWNLOADS = 3

# Token refresh buffer (refresh if expiring within this many seconds)
TOKEN_EXPIRY_BUFFER = 300
