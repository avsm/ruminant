"""Rich console logging utilities."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from typing import List, Dict, Any

# Global console instance
console = Console()


def success(message: str) -> None:
    """Print a success message."""
    console.print(f"✅ {message}")


def error(message: str) -> None:
    """Print an error message."""
    console.print(f"❌ {message}", style="red")


def warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"⚠️  {message}", style="yellow")


def info(message: str) -> None:
    """Print an info message."""
    console.print(f"ℹ️  {message}", style="blue")


def step(message: str) -> None:
    """Print a step message."""
    console.print(f"📥 {message}", style="cyan")


def summary_table(title: str, results: List[Dict[str, Any]]) -> None:
    """Print a summary table of results."""
    table = Table(title=title)
    table.add_column("Repository", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")
    
    for result in results:
        repo = result.get("repo", "Unknown")
        status = "✅ Success" if result.get("success", False) else "❌ Failed"
        details = result.get("details", "")
        
        table.add_row(repo, status, details)
    
    console.print(table)


def operation_summary(operation: str, total: int, success: int) -> None:
    """Print an operation summary."""
    if success == total:
        emoji = "🎉"
        style = "green"
    elif success > 0:
        emoji = "📊"
        style = "yellow"
    else:
        emoji = "💥"
        style = "red"
    
    message = f"{emoji} {operation} Summary: {success}/{total} completed successfully"
    console.print(Panel(message, style=style))


def repo_progress(repo: str, week: int, year: int, details: str) -> None:
    """Print repository progress."""
    console.print(f"  {repo} │ Week {week} ({year}): {details}")


def print_config_info(config) -> None:
    """Print configuration information."""
    info_text = Text()
    info_text.append("Configuration loaded:\n", style="bold")
    info_text.append(f"  Project: {config.project_name}\n")
    info_text.append(f"  Repositories: {len(config.repositories)} configured\n")
    info_text.append(f"  GitHub token: {'✅ Found' if config.github.token else '❌ Missing'}\n")
    info_text.append(f"  Claude command: {config.claude.command}")
    
    console.print(Panel(info_text, title="Ruminant Configuration"))


def print_repo_list(repos: List[str]) -> None:
    """Print a formatted list of repositories."""
    if not repos:
        warning("No repositories configured")
        return
    
    console.print(f"\n📋 Repositories ({len(repos)}):")
    for repo in repos:
        console.print(f"  • {repo}")
    console.print()


def confirm_operation(message: str) -> bool:
    """Ask for confirmation before proceeding."""
    response = console.input(f"{message} [y/N]: ")
    return response.lower().startswith('y')


def print_file_paths(title: str, paths: Dict[str, str]) -> None:
    """Print file paths in a formatted way."""
    table = Table(title=title)
    table.add_column("Type", style="cyan")
    table.add_column("Path", style="dim")
    
    for path_type, path in paths.items():
        table.add_row(path_type, str(path))
    
    console.print(table)