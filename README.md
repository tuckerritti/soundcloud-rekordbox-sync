# sc2rb

Sync your SoundCloud playlists to Rekordbox.

sc2rb fetches your SoundCloud playlists, downloads the tracks using yt-dlp, and exports a Rekordbox-compatible XML file for seamless import into your DJ library.

## Features

- **Playlist sync** - Fetches all your SoundCloud playlists and tracks
- **Selective sync** - Choose which playlists to include
- **Parallel downloads** - Downloads multiple tracks concurrently via yt-dlp
- **Deduplication** - SHA-256 hashing prevents duplicate files
- **Metadata embedding** - Album art, title, artist embedded in downloaded files
- **Manual import** - Ingest existing MP3s you've already downloaded
- **Rekordbox XML export** - Generates `rekordbox.xml` for direct import

## Installation

Requires Python 3.11+ and [yt-dlp](https://github.com/yt-dlp/yt-dlp).

```bash
# Install yt-dlp
brew install yt-dlp  # macOS
# or: pip install yt-dlp

# Clone and install
git clone https://github.com/yourusername/sc2rb.git
cd sc2rb
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

## SoundCloud App Setup

You need to create a SoundCloud app to authenticate:

1. Go to [https://soundcloud.com/you/apps](https://soundcloud.com/you/apps)
2. Click "Register a new application"
3. Fill in the app name (e.g., "sc2rb")
4. Set the **Redirect URI** to: `http://localhost:8080/callback`
5. Save and note your **Client ID** and **Client Secret**

## Quick Start

```bash
# 1. Initialize a sync directory
sc2rb init --root ~/Music/SC_Sync

# 2. Authenticate with SoundCloud (enter your Client ID/Secret when prompted)
sc2rb auth

# 3. Sync playlists and download tracks
sc2rb sync --download

# 4. Import into Rekordbox
#    - Open Rekordbox
#    - Preferences → View → Enable "rekordbox xml" in sidebar
#    - Drag ~/Music/SC_Sync/exports/rekordbox.xml onto Rekordbox
#    - Or: File → Import → rekordbox xml
```

## Commands

### `sc2rb init --root <path>`

Initialize a new sync directory with the required folder structure and database.

```bash
sc2rb init --root ~/Music/SC_Sync
```

Creates:
```
~/Music/SC_Sync/
  config.json      # Configuration
  db.sqlite        # Track/playlist database
  tokens.json      # OAuth tokens (after auth)
  tracks/          # Downloaded audio files
  downloads/       # Temporary download staging
  exports/         # rekordbox.xml output
  logs/            # Log files
```

### `sc2rb auth`

Authenticate with SoundCloud via OAuth. Opens your browser to authorize the app.

```bash
sc2rb auth
```

You'll be prompted for your Client ID and Client Secret on first run.

### `sc2rb sync`

Fetch playlists from SoundCloud and export Rekordbox XML.

```bash
# Interactive playlist selection
sc2rb sync

# Also download missing tracks
sc2rb sync --download

# Verbose output
sc2rb sync -v
```

When run, displays a table of your playlists and prompts you to select which ones to sync:
- Enter numbers: `1,3,5`
- Enter `all` for everything
- Enter `q` to quit

### `sc2rb download`

Download tracks that haven't been downloaded yet.

```bash
# Download all pending tracks
sc2rb download

# Limit to 20 tracks
sc2rb download --limit 20

# Retry previously failed downloads
sc2rb download --retry-failed

# Download from a specific playlist only
sc2rb download --playlist "soundcloud:playlists:123456"
```

Downloads run in parallel (default: 3 concurrent). Tracks over 10 minutes are automatically skipped.

### `sc2rb ingest <path>`

Import existing audio files you've already downloaded elsewhere.

```bash
sc2rb ingest ~/Downloads/Bandcamp
sc2rb ingest ~/Music/SoundCloud\ Downloads -v
```

Supported formats: `.mp3`, `.m4a`, `.aac`, `.wav`, `.aiff`, `.flac`

Files are:
- Hashed for deduplication (skips duplicates)
- Copied to `tracks/` with standardized naming
- Matched against your SoundCloud tracks when possible

### `sc2rb doctor`

Validate your setup and check for issues.

```bash
sc2rb doctor
```

Checks:
- Directory structure exists
- Database is valid
- SoundCloud credentials configured
- OAuth tokens valid
- yt-dlp installed
- No orphaned/missing files

## Configuration

After running `init`, edit `config.json` to customize:

```json
{
  "client_id": "your_soundcloud_client_id",
  "client_secret": "your_soundcloud_client_secret",
  "ytdlp": {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "extract_audio": true,
    "audio_format": "mp3",
    "audio_quality": "0",
    "embed_thumbnail": true,
    "embed_metadata": true,
    "concurrent_downloads": 3,
    "rate_limit": "1M",
    "max_retries": 3,
    "max_track_duration_ms": 600000
  }
}
```

### yt-dlp Options

| Option | Description |
|--------|-------------|
| `format` | yt-dlp format selector |
| `extract_audio` | Convert to audio-only |
| `audio_format` | Output format (mp3, m4a, etc.) |
| `audio_quality` | 0 = best, 9 = worst |
| `embed_thumbnail` | Embed album art |
| `embed_metadata` | Embed title/artist/etc. |
| `concurrent_downloads` | Parallel download count |
| `rate_limit` | Download speed limit |
| `max_retries` | Retry count on failure |
| `max_track_duration_ms` | Skip tracks longer than this (default: 600000 = 10 min) |

## Importing into Rekordbox

### Method 1: Drag and Drop
1. Run `sc2rb sync` to generate the XML
2. Drag `exports/rekordbox.xml` directly onto Rekordbox

### Method 2: XML Import
1. In Rekordbox, go to **Preferences → View → Layout**
2. Enable **rekordbox xml** in the sidebar
3. The XML section appears in the left sidebar
4. Right-click → **Import Playlist** → Select your `rekordbox.xml`

### Method 3: File Menu
1. **File → Import → rekordbox xml**
2. Select `exports/rekordbox.xml`

After importing, your playlists appear under "rekordbox xml" in the sidebar. To add tracks permanently to your collection, right-click and select **Import to Collection**.

## How It Works

1. **Sync**: Fetches playlist/track metadata from SoundCloud API and stores in SQLite
2. **Download**: Uses yt-dlp to download audio from SoundCloud URLs
3. **Dedupe**: SHA-256 hashes prevent storing the same file twice
4. **Organize**: Files renamed to `Artist - Title [hash].mp3` format
5. **Export**: Generates Rekordbox XML with track metadata and playlist structure

## Limitations

- **Geographic restrictions**: Some tracks may be unavailable in your region
- **Private tracks**: Cannot download private or unlisted tracks
- **SoundCloud Go+**: Exclusive tracks may fail to download
- **Rate limits**: SoundCloud may temporarily block requests if you sync too frequently

## Troubleshooting

### "redirect_uri_mismatch" during auth
Your SoundCloud app's redirect URI doesn't match. Set it to exactly:
```
http://localhost:8080/callback
```

### "Could not find sc2rb root"
Run commands from your sync directory, or specify `--root`:
```bash
sc2rb sync --root ~/Music/SC_Sync
```

### Downloads failing
- Check `sc2rb doctor` for issues
- Try `sc2rb download --retry-failed`
- Some tracks may be geo-restricted or removed

### Rekordbox doesn't show XML option
Enable it in Rekordbox: **Preferences → View → Layout → rekordbox xml**

## License

MIT

## Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading
- [Typer](https://typer.tiangolo.com/) for the CLI
- [Rich](https://rich.readthedocs.io/) for terminal output
- [mutagen](https://mutagen.readthedocs.io/) for audio metadata
