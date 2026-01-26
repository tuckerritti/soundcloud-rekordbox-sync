"""yt-dlp wrapper for downloading tracks."""

import subprocess
from pathlib import Path
from typing import Any

from sc2rb.constants import DOWNLOAD_TIMEOUT


def build_ytdlp_args(
    url: str,
    output_template: str,
    config: dict[str, Any],
) -> list[str]:
    """Build yt-dlp command line arguments from config."""
    args = ["yt-dlp"]

    # Output template
    args.extend(["-o", output_template])

    # Format selection
    if "format" in config:
        args.extend(["-f", config["format"]])

    # Audio extraction
    if config.get("extract_audio"):
        args.append("-x")
        if "audio_format" in config:
            args.extend(["--audio-format", config["audio_format"]])
        if "audio_quality" in config:
            args.extend(["--audio-quality", config["audio_quality"]])

    # Metadata and thumbnails
    if config.get("embed_thumbnail"):
        args.append("--embed-thumbnail")
    if config.get("embed_metadata"):
        args.append("--embed-metadata")

    # Rate limiting
    if "rate_limit" in config:
        args.extend(["-r", config["rate_limit"]])

    # Retries
    if "max_retries" in config:
        args.extend(["--retries", str(config["max_retries"])])

    # No playlist (single track)
    args.append("--no-playlist")

    # Quiet mode (we parse output ourselves)
    args.append("--quiet")
    args.append("--no-warnings")

    # Print downloaded filename to stdout
    args.append("--print")
    args.append("after_move:filepath")

    # URL must be last
    args.append(url)

    return args


def download_track(
    url: str,
    output_dir: Path,
    ytdlp_config: dict[str, Any],
) -> Path:
    """Download a track using yt-dlp.

    Args:
        url: SoundCloud permalink URL
        output_dir: Directory to save downloaded file
        ytdlp_config: yt-dlp configuration options

    Returns:
        Path to the downloaded file

    Raises:
        RuntimeError: If download fails
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use a temp filename pattern, let yt-dlp determine extension
    output_template = str(output_dir / "%(id)s.%(ext)s")

    args = build_ytdlp_args(url, output_template, ytdlp_config)

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            timeout=DOWNLOAD_TIMEOUT,
        )

        # Get the output filepath from stdout
        filepath = result.stdout.strip()
        if not filepath:
            raise RuntimeError("yt-dlp did not return output filepath")

        downloaded_path = Path(filepath)
        if not downloaded_path.exists():
            raise RuntimeError(f"Downloaded file not found: {filepath}")

        return downloaded_path

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or str(e)
        raise RuntimeError(f"yt-dlp failed: {error_msg}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Download timed out after {DOWNLOAD_TIMEOUT} seconds")


def check_ytdlp_available() -> bool:
    """Check if yt-dlp is available in PATH."""
    try:
        subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
