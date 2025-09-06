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
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to sync"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    force: bool = typer.Option(False, "--force", help="Force refresh cache"),
) -> None:
    """Fetch and cache GitHub repository data."""
    from .commands.sync import sync_main
    sync_main(repos, weeks, year, week, force)

@app.command(help="Generate Claude prompts for weekly summaries")  
def prompt(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to generate prompts for"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show file paths that will be used"),
) -> None:
    """Generate Claude prompts for weekly GitHub activity summaries."""
    from .commands.prompt import prompt_main
    prompt_main(repos, weeks, year, week, show_paths)

@app.command(help="Generate summaries using Claude CLI")
def summarize(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to generate summaries for"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without running Claude CLI"),
) -> None:
    """Generate summaries using Claude CLI."""
    from .commands.summarize import summarize_main
    summarize_main(repos, weeks, year, week, claude_args, dry_run)

# Create annotate subcommands
annotate_app = typer.Typer(help="Annotate reports with GitHub links")

@annotate_app.command(name="main")
def annotate_main_cmd(
    files: Optional[List[str]] = typer.Argument(None, help="Specific files to annotate (supports wildcards)"),
    repos: Optional[List[str]] = typer.Option(None, "--repos", help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to annotate"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    in_place: bool = typer.Option(False, "--in-place", help="Modify files in place instead of creating reports"),
    all_summaries: bool = typer.Option(False, "--all", help="Annotate all summary files"),
) -> None:
    """Annotate markdown reports with GitHub links."""
    from .commands.annotate import annotate_main
    annotate_main(files, repos, weeks, year, week, in_place, all_summaries)

@annotate_app.command()
def clear_cache() -> None:
    """Clear the user cache."""
    from .commands.annotate import clear_cache as annotate_clear_cache
    annotate_clear_cache()

@annotate_app.command()
def stats() -> None:
    """Show user cache statistics."""
    from .commands.annotate import stats as annotate_stats
    annotate_stats()

# Make main the default for annotate
@annotate_app.callback(invoke_without_command=True)
def annotate_callback(
    ctx: typer.Context,
    files: Optional[List[str]] = typer.Argument(None, help="Specific files to annotate (supports wildcards)"),
    repos: Optional[List[str]] = typer.Option(None, "--repos", help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to annotate"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    in_place: bool = typer.Option(False, "--in-place", help="Modify files in place instead of creating reports"),
    all_summaries: bool = typer.Option(False, "--all", help="Annotate all summary files"),
) -> None:
    """Annotate markdown reports with GitHub links."""
    if ctx.invoked_subcommand is None:
        from .commands.annotate import annotate_main
        annotate_main(files, repos, weeks, year, week, in_place, all_summaries)

app.add_typer(annotate_app, name="annotate")

@app.command(help="Run complete end-to-end reporting workflow") 
def report(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to process"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    force_sync: bool = typer.Option(False, "--force-sync", help="Force refresh GitHub data cache"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    skip_sync: bool = typer.Option(False, "--skip-sync", help="Skip the sync step"),
    skip_prompt: bool = typer.Option(False, "--skip-prompt", help="Skip the prompt generation step"),
    skip_summarize: bool = typer.Option(False, "--skip-summarize", help="Skip the summarize step"),
    skip_annotate: bool = typer.Option(False, "--skip-annotate", help="Skip the annotation step"),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="Skip weeks that already have reports"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
) -> None:
    """Run the complete end-to-end reporting workflow."""
    from .commands.report import report_main
    report_main(repos, weeks, year, week, force_sync, claude_args, skip_sync, skip_prompt, skip_summarize, skip_annotate, skip_existing, dry_run)


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