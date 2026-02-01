"""CLI entry point for sc2rb."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from sc2rb import db
from sc2rb.config import Config, Tokens, find_root, save_default_root

app = typer.Typer(
    name="sc2rb",
    help="Sync SoundCloud playlists to Rekordbox.",
    no_args_is_help=True,
)
console = Console()


def get_config(root: Path | None = None) -> Config:
    """Load config, finding root automatically if not specified."""
    if root is None:
        root = find_root()
    return Config.load(root)


@app.command()
def init(
    root: Annotated[
        Path,
        typer.Option("--root", "-r", help="Root directory for sc2rb data"),
    ],
) -> None:
    """Initialize sync directory with folders and database."""
    root = root.expanduser().resolve()

    if root.exists() and (root / "db.sqlite").exists():
        console.print(f"[yellow]Already initialized at {root}[/yellow]")
        raise typer.Exit(1)

    # Create directory structure
    root.mkdir(parents=True, exist_ok=True)
    for subdir in ["tracks", "downloads", "exports", "logs"]:
        (root / subdir).mkdir(exist_ok=True)

    # Initialize database
    db.init_schema(root / "db.sqlite")

    # Create default config
    config = Config(root=root)
    config.save()

    # Save as default root for future commands
    save_default_root(root)

    console.print(f"[green]Initialized sc2rb at {root}[/green]")
    console.print("\nNext steps:")
    console.print("  1. Run [bold]sc2rb auth[/bold] to authenticate with SoundCloud")
    console.print("  2. Run [bold]sc2rb sync[/bold] to fetch your playlists")


@app.command()
def auth(
    root: Annotated[
        Optional[Path],
        typer.Option("--root", "-r", help="Root directory (auto-detected if not set)"),
    ] = None,
) -> None:
    """Authenticate with SoundCloud via OAuth."""
    from sc2rb.soundcloud.auth import run_oauth_flow

    config = get_config(root)

    # Prompt for credentials if not set
    if not config.client_id:
        console.print("[bold]SoundCloud OAuth Setup[/bold]")
        console.print("You need a SoundCloud app to authenticate.")
        console.print("Create one at: https://soundcloud.com/you/apps\n")

        config.client_id = typer.prompt("Client ID")
        config.client_secret = typer.prompt("Client Secret")
        config.save()

    tokens = run_oauth_flow(config.client_id, config.client_secret)
    tokens.save(config.tokens_path)

    console.print("[green]Authentication successful![/green]")


@app.command()
def sync(
    root: Annotated[
        Optional[Path],
        typer.Option("--root", "-r", help="Root directory (auto-detected if not set)"),
    ] = None,
    download: Annotated[
        bool,
        typer.Option("--download", "-d", help="Download missing tracks"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
) -> None:
    """Fetch playlists and tracks from SoundCloud, export Rekordbox XML."""
    from rich.prompt import Prompt
    from rich.table import Table

    from sc2rb.rekordbox.xml_writer import export_rekordbox_xml
    from sc2rb.soundcloud.client import SoundCloudClient

    config = get_config(root)
    tokens = Tokens.load(config.tokens_path)

    with SoundCloudClient(
        tokens=tokens,
        client_id=config.client_id,
        client_secret=config.client_secret,
        tokens_path=config.tokens_path,
    ) as client:
        console.print("Fetching playlists from SoundCloud...")
        all_playlists = client.get_my_playlists()

        if not all_playlists:
            console.print("[yellow]No playlists found.[/yellow]")
            return

        # Display playlists for selection
        table = Table(title="Your SoundCloud Playlists")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Playlist", style="white")
        table.add_column("Tracks", justify="right", style="green")

        for i, pl in enumerate(all_playlists, 1):
            track_count = len(pl.get("tracks", []))
            table.add_row(str(i), pl["title"], str(track_count))

        console.print(table)
        console.print("\n[dim]Enter playlist numbers to exclude (comma-separated), or press Enter to sync all[/dim]")

        selection = Prompt.ask("Exclude playlists", default="")

        if selection.lower() == "q":
            return

        if not selection.strip():
            playlists = all_playlists
        else:
            try:
                exclude_indices = {int(x.strip()) - 1 for x in selection.split(",")}
                playlists = [
                    pl for i, pl in enumerate(all_playlists)
                    if i not in exclude_indices
                ]
            except ValueError:
                console.print("[red]Invalid selection[/red]")
                return

        if not playlists:
            console.print("[yellow]No playlists selected.[/yellow]")
            return

    console.print(f"\nSyncing {len(playlists)} playlist(s)...")

    with db.connect(config.db_path) as conn:
        # Identify deselected playlists (in DB, from SoundCloud, but not selected)
        selected_urns = {pl["urn"] for pl in playlists}
        all_urns = {pl["urn"] for pl in all_playlists}
        existing_urns = {pl["playlist_urn"] for pl in db.get_all_playlists(conn)}
        deselected_urns = list((existing_urns & all_urns) - selected_urns)

        if deselected_urns:
            tracks_to_delete = db.get_tracks_only_in_playlists(conn, deselected_urns)
            if tracks_to_delete:
                console.print(f"Removing {len(tracks_to_delete)} tracks from deselected playlists...")
                _delete_track_files(conn, tracks_to_delete, verbose)
                db.delete_tracks(conn, [t["track_urn"] for t in tracks_to_delete])
            db.delete_playlists(conn, deselected_urns)
            console.print(f"Removed {len(deselected_urns)} deselected playlist(s)")

        # Sync selected playlists
        for playlist in playlists:
            if verbose:
                console.print(f"  Syncing playlist: {playlist['title']}")

            db.upsert_playlist(
                conn,
                playlist_urn=playlist["urn"],
                sc_id=str(playlist["id"]),
                title=playlist["title"],
                last_modified_at=playlist.get("last_modified"),
            )

            track_urns = []
            for track in playlist.get("tracks", []):
                track_urn = track["urn"]
                track_urns.append(track_urn)

                db.upsert_track(
                    conn,
                    track_urn=track_urn,
                    sc_id=str(track["id"]),
                    title=track.get("title", "Unknown"),
                    artist=track.get("user", {}).get("username", "Unknown"),
                    duration_ms=track.get("duration", 0),
                    permalink_url=track.get("permalink_url", ""),
                )

            db.set_playlist_tracks(conn, playlist["urn"], track_urns)

        # Clean up orphaned tracks
        orphans = db.get_orphaned_tracks(conn)
        if orphans:
            console.print(f"Cleaning up {len(orphans)} orphaned tracks...")
            _delete_track_files(conn, orphans, verbose)
            db.delete_tracks(conn, [t["track_urn"] for t in orphans])

        stats = db.get_sync_stats(conn)

    console.print(f"\nSynced {stats['playlists']} playlists, {stats['total_tracks']} tracks")
    console.print(f"  Resolved: {stats['resolved']}")
    console.print(f"  Pending download: {stats['pending']}")
    if stats["failed"] > 0:
        console.print(f"  [red]Failed: {stats['failed']}[/red]")

    if download and stats["pending"] > 0:
        console.print("\nDownloading missing tracks...")
        _run_downloads(config, limit=None, playlist_urn=None, retry_failed=False)

    # Export Rekordbox XML
    console.print("\nExporting Rekordbox XML...")
    export_rekordbox_xml(config)
    console.print(f"[green]Exported to {config.rekordbox_xml_path}[/green]")


def _delete_track_files(
    conn,
    tracks: list,
    verbose: bool = False,
) -> dict:
    """Delete files for tracks, handling shared files safely."""
    stats = {"deleted_files": 0, "skipped_shared": 0}

    for track in tracks:
        sha256 = track["sha256"]
        canonical_path = track["canonical_path"]

        if not canonical_path or not sha256:
            continue

        if db.count_tracks_with_sha256(conn, sha256) > 1:
            stats["skipped_shared"] += 1
            if verbose:
                console.print(f"[dim]Skipping shared file: {canonical_path}[/dim]")
            continue

        path = Path(canonical_path)
        if path.exists():
            path.unlink()
            stats["deleted_files"] += 1
            if verbose:
                console.print(f"[dim]Deleted: {canonical_path}[/dim]")

        db.delete_file_index_entry(conn, sha256)

    return stats


@app.command()
def download(
    root: Annotated[
        Optional[Path],
        typer.Option("--root", "-r", help="Root directory (auto-detected if not set)"),
    ] = None,
    playlist: Annotated[
        Optional[str],
        typer.Option("--playlist", "-p", help="Only download from this playlist URN"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", "-l", help="Maximum tracks to download"),
    ] = None,
    retry_failed: Annotated[
        bool,
        typer.Option("--retry-failed", help="Retry previously failed downloads"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
) -> None:
    """Download missing tracks using yt-dlp."""
    config = get_config(root)
    _run_downloads(config, limit, playlist, retry_failed, verbose)


def _download_single_track(
    track: dict,
    config: Config,
) -> dict:
    """Download a single track. Returns result dict for DB update."""
    from sc2rb.download.ytdlp import download_track
    from sc2rb.ingest.hasher import hash_file
    from sc2rb.util.paths import canonical_filename

    result = {
        "track_urn": track["track_urn"],
        "title": track["title"],
        "success": False,
        "error": None,
        "canonical_path": None,
        "file_hash": None,
        "filesize": None,
    }

    try:
        # Download with yt-dlp
        temp_path = download_track(
            url=track["permalink_url"],
            output_dir=config.downloads_dir,
            ytdlp_config=config.ytdlp,
        )

        # Hash the file
        file_hash = hash_file(temp_path)

        # Generate canonical filename and move
        ext = temp_path.suffix
        canonical_name = canonical_filename(
            artist=track["artist"],
            title=track["title"],
            file_hash=file_hash,
            ext=ext,
        )
        final_path = config.tracks_dir / canonical_name

        # Handle case where file already exists (from concurrent download)
        if final_path.exists():
            temp_path.unlink()
        else:
            temp_path.rename(final_path)

        result["success"] = True
        result["canonical_path"] = str(final_path)
        result["file_hash"] = file_hash
        result["filesize"] = final_path.stat().st_size
        result["canonical_name"] = canonical_name

    except Exception as e:
        result["error"] = str(e)

    return result


def _run_downloads(
    config: Config,
    limit: int | None,
    playlist_urn: str | None,
    retry_failed: bool,
    verbose: bool = False,
) -> None:
    """Internal function to run downloads in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn

    from sc2rb.constants import DEFAULT_CONCURRENT_DOWNLOADS, DEFAULT_MAX_TRACK_DURATION_MS

    max_duration_ms = config.ytdlp.get("max_track_duration_ms", DEFAULT_MAX_TRACK_DURATION_MS)
    max_workers = config.ytdlp.get("concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS)

    with db.connect(config.db_path) as conn:
        all_tracks = db.get_tracks_to_download(
            conn, playlist_urn=playlist_urn, include_failed=retry_failed, limit=limit
        )

        # Filter out tracks that are too long
        tracks = []
        for track in all_tracks:
            if track["duration_ms"] and track["duration_ms"] > max_duration_ms:
                if verbose:
                    console.print(f"[yellow]Skipping (too long): {track['title']}[/yellow]")
            else:
                tracks.append(dict(track))  # Convert Row to dict for thread safety

        if not tracks:
            console.print("No tracks to download.")
            return

        console.print(f"Downloading {len(tracks)} tracks ({max_workers} concurrent)...")

        completed = 0
        failed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            main_task = progress.add_task("Downloading...", total=len(tracks))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all downloads
                future_to_track = {
                    executor.submit(_download_single_track, track, config): track
                    for track in tracks
                }

                # Process results as they complete
                for future in as_completed(future_to_track):
                    track = future_to_track[future]
                    result = future.result()

                    # Update database (in main thread)
                    if result["success"]:
                        # Check for duplicate by hash
                        existing = db.get_file_by_sha256(conn, result["file_hash"])
                        if existing and existing["path"] != result["canonical_path"]:
                            # It's a duplicate, link to existing
                            db.update_track_download(
                                conn,
                                result["track_urn"],
                                existing["path"],
                                result["file_hash"],
                                existing["filesize"],
                            )
                            if verbose:
                                console.print(f"[yellow]Duplicate: {result['title']}[/yellow]")
                        else:
                            db.update_track_download(
                                conn,
                                result["track_urn"],
                                result["canonical_path"],
                                result["file_hash"],
                                result["filesize"],
                            )
                            db.index_file(
                                conn,
                                result["file_hash"],
                                result["canonical_path"],
                                result["filesize"],
                                str(Path(result["canonical_path"]).stat().st_mtime_ns),
                            )
                            if verbose:
                                console.print(f"[green]Downloaded: {result.get('canonical_name', result['title'])}[/green]")
                        completed += 1
                    else:
                        db.update_track_status(
                            conn, result["track_urn"], "failed", result["error"]
                        )
                        console.print(f"[red]Failed: {result['title']} - {result['error']}[/red]")
                        failed += 1

                    conn.commit()
                    progress.update(main_task, advance=1)

        console.print(f"\nCompleted: {completed}, Failed: {failed}")


@app.command()
def ingest(
    inbox_path: Annotated[
        Path,
        typer.Argument(help="Directory containing audio files to import"),
    ],
    root: Annotated[
        Optional[Path],
        typer.Option("--root", "-r", help="Root directory (auto-detected if not set)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
) -> None:
    """Import manually acquired audio files."""
    from sc2rb.ingest.scanner import scan_and_ingest

    config = get_config(root)
    inbox_path = inbox_path.expanduser().resolve()

    if not inbox_path.exists():
        console.print(f"[red]Directory not found: {inbox_path}[/red]")
        raise typer.Exit(1)

    stats = scan_and_ingest(config, inbox_path, verbose=verbose)

    console.print(f"\nIngested {stats['added']} files")
    if stats["skipped"] > 0:
        console.print(f"  Skipped (duplicate): {stats['skipped']}")
    if stats["failed"] > 0:
        console.print(f"  [red]Failed: {stats['failed']}[/red]")


@app.command()
def doctor(
    root: Annotated[
        Optional[Path],
        typer.Option("--root", "-r", help="Root directory (auto-detected if not set)"),
    ] = None,
) -> None:
    """Validate setup and check for issues."""
    import shutil

    try:
        config = get_config(root)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    issues = []

    # Check directories
    for name, path in [
        ("tracks", config.tracks_dir),
        ("downloads", config.downloads_dir),
        ("exports", config.exports_dir),
        ("logs", config.logs_dir),
    ]:
        if not path.exists():
            issues.append(f"Missing directory: {name}")

    # Check database
    if not config.db_path.exists():
        issues.append("Database not found")
    else:
        try:
            with db.connect(config.db_path) as conn:
                conn.execute("SELECT 1 FROM tracks LIMIT 1")
        except Exception as e:
            issues.append(f"Database error: {e}")

    # Check credentials
    if not config.client_id:
        issues.append("SoundCloud client_id not configured (run 'sc2rb auth')")

    # Check tokens
    if not config.tokens_path.exists():
        issues.append("Not authenticated (run 'sc2rb auth')")
    else:
        try:
            tokens = Tokens.load(config.tokens_path)
            if not tokens.access_token:
                issues.append("Invalid tokens file")
        except Exception:
            issues.append("Corrupt tokens file")

    # Check yt-dlp
    if not shutil.which("yt-dlp"):
        issues.append("yt-dlp not found in PATH")

    # Check for orphaned files
    with db.connect(config.db_path) as conn:
        resolved = db.get_resolved_tracks(conn)
        for track in resolved:
            if track["canonical_path"] and not Path(track["canonical_path"]).exists():
                issues.append(f"Missing file: {track['canonical_path']}")

    # Report
    if issues:
        console.print("[red]Issues found:[/red]")
        for issue in issues:
            console.print(f"  - {issue}")
        raise typer.Exit(1)
    else:
        console.print("[green]All checks passed![/green]")

        # Show stats
        with db.connect(config.db_path) as conn:
            stats = db.get_sync_stats(conn)
        console.print(f"\nPlaylists: {stats['playlists']}")
        console.print(f"Tracks: {stats['total_tracks']} ({stats['resolved']} resolved)")


if __name__ == "__main__":
    app()
