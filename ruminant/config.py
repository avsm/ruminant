"""Configuration management for ruminant."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import tomli
import tomli_w
from dataclasses import dataclass, field


@dataclass
class GitHubConfig:
    """GitHub API configuration."""
    token: Optional[str] = None


@dataclass
class ClaudeConfig:
    """Claude CLI configuration."""
    command: str = "claude"
    args: List[str] = field(default_factory=lambda: ["-p"])


@dataclass
class ReportingConfig:
    """Reporting configuration."""
    default_weeks: int = 1
    auto_annotate: bool = True


@dataclass
class Config:
    """Main configuration class."""
    project_name: str = "OCaml Community Activity"
    project_description: str = "Weekly reports for OCaml ecosystem projects"
    repositories: List[str] = field(default_factory=list)
    custom_prompts: Dict[str, str] = field(default_factory=dict)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)


def find_config_file() -> Optional[Path]:
    """Find the config file, checking current directory and parents."""
    current = Path.cwd()
    
    # Check current directory and parents
    for parent in [current] + list(current.parents):
        config_path = parent / ".ruminant.toml"
        if config_path.exists():
            return config_path
    
    return None


def find_keys_file() -> Optional[Path]:
    """Find the keys file, checking current directory and parents."""
    current = Path.cwd()
    
    # Check current directory and parents
    for parent in [current] + list(current.parents):
        keys_path = parent / ".ruminant-keys.toml"
        if keys_path.exists():
            return keys_path
    
    return None


def load_config() -> Config:
    """Load configuration from .ruminant.toml and .ruminant-keys.toml files."""
    config = Config()
    
    # Load main config
    config_path = find_config_file()
    if config_path:
        try:
            with open(config_path, "rb") as f:
                data = tomli.load(f)
            
            # Project info
            if "project" in data:
                project = data["project"]
                config.project_name = project.get("name", config.project_name)
                config.project_description = project.get("description", config.project_description)
            
            # Repositories
            if "repositories" in data:
                repos = data["repositories"]
                config.repositories = repos.get("repos", [])
                config.custom_prompts = repos.get("custom_prompts", {})
            
            # Claude config
            if "claude" in data:
                claude = data["claude"]
                config.claude.command = claude.get("command", config.claude.command)
                config.claude.args = claude.get("args", config.claude.args)
            
            # Reporting config
            if "reporting" in data:
                reporting = data["reporting"]
                config.reporting.default_weeks = reporting.get("default_weeks", config.reporting.default_weeks)
                config.reporting.auto_annotate = reporting.get("auto_annotate", config.reporting.auto_annotate)
                
        except Exception as e:
            raise RuntimeError(f"Error loading config from {config_path}: {e}")
    
    # Load keys file
    keys_path = find_keys_file()
    if keys_path:
        try:
            with open(keys_path, "rb") as f:
                keys_data = tomli.load(f)
            
            if "github" in keys_data:
                github = keys_data["github"]
                config.github.token = github.get("token")
                
        except Exception as e:
            raise RuntimeError(f"Error loading keys from {keys_path}: {e}")
    
    # Fall back to environment variables and legacy files
    if not config.github.token:
        # Try environment variable
        config.github.token = os.environ.get("GITHUB_TOKEN")
        
        # Try legacy .gh-key file
        if not config.github.token:
            gh_key_path = Path(".gh-key")
            if gh_key_path.exists():
                try:
                    config.github.token = gh_key_path.read_text().strip()
                except Exception:
                    pass
    
    return config


def create_default_config() -> None:
    """Create a default .ruminant.toml file in the current directory."""
    config_path = Path(".ruminant.toml")
    
    if config_path.exists():
        raise FileExistsError(f"Configuration file {config_path} already exists")
    
    default_config = {
        "project": {
            "name": "OCaml Community Activity",
            "description": "Weekly reports for OCaml ecosystem projects"
        },
        "repositories": {
            "repos": [
                "ocaml/opam-repository",
                "mirage/mirage",
                "janestreet/base",
                "ocsigen/lwt"
            ],
            "custom_prompts": {
                "ocaml/opam-repository": """Focus on package submissions, maintenance updates, and ecosystem changes.
Highlight any breaking changes or major version updates."""
            }
        },
        "claude": {
            "command": "claude",
            "args": ["-p"]
        },
        "reporting": {
            "default_weeks": 1,
            "auto_annotate": True
        }
    }
    
    with open(config_path, "wb") as f:
        tomli_w.dump(default_config, f)


def create_default_keys_file() -> None:
    """Create a default .ruminant-keys.toml file in the current directory."""
    keys_path = Path(".ruminant-keys.toml")
    
    if keys_path.exists():
        raise FileExistsError(f"Keys file {keys_path} already exists")
    
    default_keys = {
        "github": {
            "token": "ghp_your_github_token_here"
        }
    }
    
    with open(keys_path, "wb") as f:
        tomli_w.dump(default_keys, f)


def get_github_token(config: Config) -> Optional[str]:
    """Get GitHub token from config, with fallbacks."""
    return config.github.token