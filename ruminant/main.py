"""Main CLI application for ruminant."""

import typer
from pathlib import Path
from typing import Optional, List

from .config import load_config, create_default_config, create_default_keys_file
from .utils.logging import console, success, error, info, print_config_info
# Command modules are imported locally in each command function to avoid naming conflicts

# Create the main Typer app
app = typer.Typer(
    name="ruminant",
    help="A CLI tool for tracking activity across OCaml community projects",
    no_args_is_help=True,
)

# Add subcommands
@app.command(help="Fetch and cache GitHub repository data")
def sync(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: Optional[int] = typer.Option(None, "--weeks", help="Number of weeks to sync (defaults to config value)"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    force: bool = typer.Option(False, "--force", help="Force refresh cache"),
    scan_only: bool = typer.Option(False, "--scan-only", help="Only scan cached data for missing users"),
    releases_only: bool = typer.Option(False, "--releases-only", help="Only sync GitHub releases data"),
) -> None:
    """Fetch and cache GitHub repository data."""
    from .commands.sync import sync_main
    
    # Use config default if weeks not specified
    # But if a specific week is given, default to 1 week
    if weeks is None:
        if week is not None:
            weeks = 1
        else:
            config = load_config()
            weeks = config.reporting.default_weeks
    
    sync_main(repos, weeks, year, week, force, scan_only, releases_only)

@app.command(help="Generate summaries using Claude CLI")
def summarize(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: Optional[int] = typer.Option(None, "--weeks", help="Number of weeks to generate summaries for (defaults to config value)"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without running Claude CLI"),
    prompt_only: bool = typer.Option(False, "--prompt-only", help="Only generate prompts without running Claude CLI"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show file paths that will be used"),
    parallel_workers: Optional[int] = typer.Option(None, "--parallel-workers", help="Number of parallel Claude instances (default from config)"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--force", help="Skip weeks that already have summaries (default: skip)"),
) -> None:
    """Generate summaries using Claude CLI."""
    from .commands.summarize import summarize_main
    
    # Use config default if weeks not specified
    # But if a specific week is given, default to 1 week
    if weeks is None:
        if week is not None:
            weeks = 1
        else:
            config = load_config()
            weeks = config.reporting.default_weeks
    
    summarize_main(repos, weeks, year, week, claude_args, dry_run, prompt_only, show_paths, parallel_workers, skip_existing)

@app.command(help="Run complete end-to-end reporting workflow") 
def report(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: Optional[int] = typer.Option(None, "--weeks", help="Number of weeks to process (defaults to config value)"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    force_sync: bool = typer.Option(False, "--force-sync", help="Force refresh GitHub data cache"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    skip_sync: bool = typer.Option(False, "--skip-sync", help="Skip the sync step"),
    skip_summarize: bool = typer.Option(False, "--skip-summarize", help="Skip the summarize step"),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="Skip weeks that already have reports"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
) -> None:
    """Run the complete end-to-end reporting workflow."""
    from .commands.report import report_main
    
    # Use config default if weeks not specified
    if weeks is None:
        config = load_config()
        weeks = config.reporting.default_weeks
    
    report_main(repos, weeks, year, week, force_sync, claude_args, skip_sync, skip_summarize, skip_existing, dry_run)


@app.command(help="Generate group summaries from individual repository summaries")
def group(
    group: Optional[str] = typer.Argument(None, help="Group name to generate summary for"),
    weeks: Optional[int] = typer.Option(None, "--weeks", help="Number of weeks to process (defaults to config value)"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    all_groups: bool = typer.Option(False, "--all", help="Generate summaries for all configured groups"),
    prompt_only: bool = typer.Option(False, "--prompt-only", help="Only generate prompts without running Claude"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--force", help="Skip groups that already have summaries (default: skip)"),
) -> None:
    """Generate group summaries from individual repository summaries."""
    from .commands.group import group_main
    
    # Use config default if weeks not specified
    # But if a specific week is given, default to 1 week
    if weeks is None:
        if week is not None:
            weeks = 1
        else:
            config = load_config()
            weeks = config.reporting.default_weeks
    
    group_main(group, weeks, year, week, all_groups, prompt_only, claude_args, dry_run, skip_existing)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing configuration files")
) -> None:
    """Initialize a new ruminant project with default configuration."""
    config_path = Path(".ruminant.toml")
    keys_path = Path(".ruminant-keys.toml")
    
    try:
        # Create config file
        if config_path.exists() and not force:
            error(f"Configuration file {config_path} already exists. Use --force to overwrite.")
            raise typer.Exit(1)
        
        if force and config_path.exists():
            config_path.unlink()
        
        create_default_config()
        success(f"Created configuration file: {config_path}")
        
        # Create keys file
        if keys_path.exists() and not force:
            info(f"Keys file {keys_path} already exists, skipping.")
        else:
            if force and keys_path.exists():
                keys_path.unlink()
            
            create_default_keys_file()
            success(f"Created keys file: {keys_path}")
            info("Please edit .ruminant-keys.toml to add your GitHub token")
        
        # Create data directories
        from .utils.paths import get_data_dir
        data_dir = get_data_dir()
        data_dir.mkdir(exist_ok=True)
        (data_dir / "gh").mkdir(exist_ok=True)
        (data_dir / "prompts").mkdir(exist_ok=True)
        (data_dir / "summaries").mkdir(exist_ok=True)
        (data_dir / "reports").mkdir(exist_ok=True)
        success("Created data directory structure")
        
        # Create .gitignore if it doesn't exist
        gitignore_path = Path(".gitignore")
        gitignore_content = ""
        
        if gitignore_path.exists():
            gitignore_content = gitignore_path.read_text()
        
        entries_to_add = []
        if ".ruminant-keys.toml" not in gitignore_content:
            entries_to_add.append(".ruminant-keys.toml")
        if ".gh-key" not in gitignore_content:
            entries_to_add.append(".gh-key")
        
        if entries_to_add:
            with open(gitignore_path, "a") as f:
                if gitignore_content and not gitignore_content.endswith("\n"):
                    f.write("\n")
                f.write("\n# Ruminant keys and secrets\n")
                for entry in entries_to_add:
                    f.write(f"{entry}\n")
            success("Updated .gitignore to exclude keys file")
        
        console.print("\n🎉 Ruminant project initialized!")
        console.print("\nNext steps:")
        console.print("1. Edit .ruminant-keys.toml to add your GitHub token")
        console.print("2. Edit .ruminant.toml to configure your repositories")
        console.print("3. Run 'ruminant sync' to fetch GitHub data")
        
    except FileExistsError as e:
        error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        error(f"Failed to initialize project: {e}")
        raise typer.Exit(1)


@app.command(help="Export summaries as JSON for JavaScript frontend")
def json(
    output_dir: Optional[str] = typer.Option("website-json", "--output", "-o", help="Output directory for JSON files"),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print JSON output"),
) -> None:
    """Generate JSON files for JavaScript frontend consumption."""
    from .commands.website_json import website_json_main
    website_json_main(output_dir, pretty)


@app.command(help="Generate Atom feeds and OPML from JSON summaries")
def atom(
    output_dir: Optional[str] = typer.Option("website-atom", "--output", "-o", help="Output directory for Atom feeds"),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print XML output"),
) -> None:
    """Generate Atom feeds for each group and an OPML container."""
    from .commands.atom import atom_main
    atom_main(output_dir, pretty)


@app.command("summarize-week", help="Generate comprehensive weekly summary across all groups")
def summarize_week(
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    weeks: Optional[int] = typer.Option(None, "--weeks", help="Process multiple weeks in chronological order (defaults to config value)"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate prompt without calling Claude"),
    prompt_only: bool = typer.Option(False, "--prompt-only", help="Only generate prompt without running Claude"),
    lookback_weeks: int = typer.Option(3, "--lookback", help="Number of previous weeks to include for context"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--force", help="Skip weeks that already have summaries"),
) -> None:
    """
    Generate comprehensive weekly summaries with release tracking and cross-group insights.
    
    When --weeks is specified, summaries are generated in chronological order (oldest first)
    to ensure proper context building for newer summaries.
    """
    from .commands.summarize_week_batch import summarize_weeks_batch_main
    from .commands.summarize_week import summarize_week_main
    
    # Use config default if weeks not specified
    if weeks is None:
        if week is not None:
            weeks = 1  # Single specific week
        else:
            config = load_config()
            weeks = config.reporting.default_weeks
    
    if weeks > 1:
        # Batch mode: process multiple weeks in chronological order
        summarize_weeks_batch_main(weeks, year, week, claude_args, dry_run, skip_existing, lookback_weeks)
    else:
        # Single week mode
        summarize_week_main(year, week, claude_args, dry_run, prompt_only, lookback_weeks)


@app.command()
def config(
    show_keys: bool = typer.Option(False, "--show-keys", help="Show sensitive configuration (GitHub token)")
) -> None:
    """Show current configuration."""
    try:
        config = load_config()
        print_config_info(config)
        
        if show_keys and config.github.token:
            console.print(f"\n🔑 GitHub token: {config.github.token[:8]}...")
        elif not config.github.token:
            console.print("\n⚠️  No GitHub token configured!")
            console.print("Edit .ruminant-keys.toml or set GITHUB_TOKEN environment variable")
            
    except Exception as e:
        error(f"Failed to load configuration: {e}")
        raise typer.Exit(1)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output")
) -> None:
    """Ruminant: Track activity across OCaml community projects."""
    if verbose:
        # Enable verbose logging
        import logging
        logging.basicConfig(level=logging.DEBUG)


if __name__ == "__main__":
    app()