"""Path utilities for ruminant data directories."""

from pathlib import Path
from typing import Tuple


def get_data_dir() -> Path:
    """Get the data directory path."""
    return Path("data")


def get_gh_cache_dir() -> Path:
    """Get the GitHub cache directory path."""
    return get_data_dir() / "gh"


def get_prompts_dir() -> Path:
    """Get the prompts directory path."""
    return get_data_dir() / "prompts"


def get_summaries_dir() -> Path:
    """Get the summaries directory path."""
    return get_data_dir() / "summaries"


def get_reports_dir() -> Path:
    """Get the reports directory path."""
    return get_data_dir() / "reports"


def get_logs_dir() -> Path:
    """Get the logs directory path."""
    return get_data_dir() / "logs"


def get_groups_dir() -> Path:
    """Get the groups directory path."""
    return get_data_dir() / "groups"


def get_group_prompts_dir(group: str) -> Path:
    """Get the prompts directory for a specific group."""
    return get_prompts_dir() / "groups" / group


def get_group_summaries_dir(group: str) -> Path:
    """Get the summaries directory for a specific group."""
    return get_summaries_dir() / "groups" / group


def get_group_reports_dir(group: str) -> Path:
    """Get the reports directory for a specific group."""
    return get_reports_dir() / "groups" / group


def get_repo_cache_dir(repo: str) -> Path:
    """Get the cache directory for a specific repository."""
    owner, name = repo.split("/")
    return get_gh_cache_dir() / owner / name


def get_repo_prompts_dir(repo: str) -> Path:
    """Get the prompts directory for a specific repository."""
    owner, name = repo.split("/")
    return get_prompts_dir() / owner / name


def get_repo_summaries_dir(repo: str) -> Path:
    """Get the summaries directory for a specific repository."""
    owner, name = repo.split("/")
    return get_summaries_dir() / owner / name


def get_repo_reports_dir(repo: str) -> Path:
    """Get the reports directory for a specific repository."""
    owner, name = repo.split("/")
    return get_reports_dir() / owner / name


def get_cache_file_path(repo: str, year: int, week: int) -> Path:
    """Get the cache file path for a specific repo and week."""
    return get_repo_cache_dir(repo) / f"week-{week:02d}-{year}.json"


def get_prompt_file_path(repo: str, year: int, week: int) -> Path:
    """Get the prompt file path for a specific repo and week."""
    return get_repo_prompts_dir(repo) / f"week-{week:02d}-{year}-prompt.txt"


def get_summary_file_path(repo: str, year: int, week: int) -> Path:
    """Get the summary file path for a specific repo and week."""
    return get_repo_summaries_dir(repo) / f"week-{week:02d}-{year}.json"


def get_report_file_path(repo: str, year: int, week: int) -> Path:
    """Get the report file path for a specific repo and week."""
    return get_repo_reports_dir(repo) / f"week-{week:02d}-{year}.json"


def get_session_log_file_path(repo: str, year: int, week: int) -> Path:
    """Get the session log file path for a specific repo and week."""
    owner, name = repo.split("/")
    return get_logs_dir() / owner / name / f"week-{week:02d}-{year}-session.json"


def ensure_repo_dirs(repo: str) -> None:
    """Ensure all directories exist for a repository."""
    get_repo_cache_dir(repo).mkdir(parents=True, exist_ok=True)
    get_repo_prompts_dir(repo).mkdir(parents=True, exist_ok=True)
    get_repo_summaries_dir(repo).mkdir(parents=True, exist_ok=True)
    get_repo_reports_dir(repo).mkdir(parents=True, exist_ok=True)
    # Ensure logs directory for this repo
    owner, name = repo.split("/")
    (get_logs_dir() / owner / name).mkdir(parents=True, exist_ok=True)


def get_group_prompt_file_path(group: str, year: int, week: int) -> Path:
    """Get the group prompt file path for a specific group and week."""
    return get_group_prompts_dir(group) / f"week-{week:02d}-{year}-prompt.txt"


def get_group_summary_file_path(group: str, year: int, week: int) -> Path:
    """Get the group summary file path for a specific group and week."""
    return get_group_summaries_dir(group) / f"week-{week:02d}-{year}.json"


def get_group_report_file_path(group: str, year: int, week: int) -> Path:
    """Get the group report file path for a specific group and week."""
    return get_group_reports_dir(group) / f"week-{week:02d}-{year}.json"


def get_group_session_log_file_path(group: str, year: int, week: int) -> Path:
    """Get the group session log file path for a specific group and week."""
    return get_logs_dir() / "groups" / group / f"week-{week:02d}-{year}-session.json"


def ensure_group_dirs(group: str) -> None:
    """Ensure all directories exist for a group."""
    get_group_prompts_dir(group).mkdir(parents=True, exist_ok=True)
    get_group_summaries_dir(group).mkdir(parents=True, exist_ok=True)
    get_group_reports_dir(group).mkdir(parents=True, exist_ok=True)
    (get_logs_dir() / "groups" / group).mkdir(parents=True, exist_ok=True)


def parse_repo(repo: str) -> Tuple[str, str]:
    """Parse a repository string into owner and name."""
    if "/" not in repo:
        raise ValueError(f"Repository must be in format 'owner/name', got: {repo}")
    
    parts = repo.split("/")
    if len(parts) != 2:
        raise ValueError(f"Repository must be in format 'owner/name', got: {repo}")
    
    owner, name = parts
    if not owner or not name:
        raise ValueError(f"Repository owner and name cannot be empty, got: {repo}")
    
    return owner, name