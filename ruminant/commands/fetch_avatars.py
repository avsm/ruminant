#!/usr/bin/env python3

import json
import os
import requests
import time
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlparse

import rich
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()


def fetch_avatars(users_json_path: str = "website-json/users.json", output_dir: str = "website-json/thumbs", limit: int = 0):
    """
    Fetch GitHub avatars from users.json and save them locally.

    Args:
        users_json_path: Path to the users.json file
        output_dir: Directory to save avatar images
        limit: Maximum number of avatars to fetch (0 for all)
    """
    # Load users data
    users_path = Path(users_json_path)
    if not users_path.exists():
        console.print(f"[red]Error: {users_json_path} not found. Run 'ruminant json' first.[/red]")
        return

    with open(users_path, 'r') as f:
        users_data = json.load(f)

    # Create output directory
    thumbs_dir = Path(output_dir)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    # Apply limit if specified
    users_to_process = list(users_data.items())
    if limit > 0:
        users_to_process = users_to_process[:limit]
        console.print(f"[yellow]Limiting to first {limit} users[/yellow]")

    console.print(f"[green]📥 Fetching avatars for {len(users_to_process)} users...[/green]")

    # Track statistics
    downloaded = 0
    skipped = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Downloading avatars...", total=len(users_to_process))

        for username, user_info in users_to_process:
            avatar_url = user_info.get('avatar_url')

            if not avatar_url:
                progress.update(task, advance=1, description=f"[yellow]Skipping {username} (no avatar URL)")
                skipped += 1
                continue

            # Extract file extension from URL if possible, default to .jpg
            ext = '.jpg'
            parsed = urlparse(avatar_url)
            if '.' in parsed.path:
                ext = os.path.splitext(parsed.path)[1]
                if not ext or ext == '.':
                    ext = '.jpg'

            # Save avatar with username as filename
            avatar_path = thumbs_dir / f"{username}{ext}"

            # Skip if already exists
            if avatar_path.exists():
                progress.update(task, advance=1, description=f"[dim]Already exists: {username}")
                skipped += 1
                continue

            try:
                # Add size parameter for consistent sizing (200x200)
                # GitHub avatars support size parameter
                if 'avatars.githubusercontent.com' in avatar_url:
                    # Remove any existing size parameter
                    if '?' in avatar_url:
                        avatar_url = avatar_url.split('?')[0]
                    avatar_url = f"{avatar_url}?s=200"

                progress.update(task, description=f"[green]Downloading {username}...")

                # Download avatar with timeout
                response = requests.get(avatar_url, timeout=10, headers={
                    'User-Agent': 'Ruminant/1.0 (https://github.com/avsm/ruminant)'
                })
                response.raise_for_status()

                # Save avatar
                with open(avatar_path, 'wb') as f:
                    f.write(response.content)

                downloaded += 1
                progress.update(task, advance=1, description=f"[green]✓ Downloaded {username}")

                # Small delay to be respectful to GitHub's servers
                time.sleep(0.1)

            except requests.exceptions.RequestException as e:
                failed += 1
                progress.update(task, advance=1, description=f"[red]✗ Failed: {username}")
                console.print(f"[red]Error downloading avatar for {username}: {str(e)}[/red]")
            except Exception as e:
                failed += 1
                progress.update(task, advance=1, description=f"[red]✗ Error: {username}")
                console.print(f"[red]Unexpected error for {username}: {str(e)}[/red]")

    # Print summary
    console.print("\n[bold]Avatar Fetch Summary:[/bold]")
    console.print(f"  [green]✓ Downloaded: {downloaded}[/green]")
    console.print(f"  [yellow]⊘ Skipped (existing or no URL): {skipped}[/yellow]")
    if failed > 0:
        console.print(f"  [red]✗ Failed: {failed}[/red]")
    console.print(f"\n[green]✅ Avatars saved to {thumbs_dir}[/green]")

    # Create an avatars index file for the website
    avatars_index = {}
    for avatar_file in thumbs_dir.glob("*"):
        if avatar_file.is_file() and not avatar_file.name.startswith('.'):
            username = avatar_file.stem  # Remove extension
            avatars_index[username] = f"thumbs/{avatar_file.name}"

    index_path = thumbs_dir.parent / "avatars.json"
    with open(index_path, 'w') as f:
        json.dump(avatars_index, f, indent=2)

    console.print(f"[green]✅ Created avatars index at {index_path}[/green]")


if __name__ == "__main__":
    import sys
    users_path = sys.argv[1] if len(sys.argv) > 1 else "website-json/users.json"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "website-json/thumbs"
    fetch_avatars(users_path, output_dir)