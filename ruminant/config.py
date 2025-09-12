"""Configuration management for ruminant."""

import os
from pathlib import Path
from typing import Dict, List, Optional
import tomli
import tomli_w
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GitHubConfig:
    """GitHub API configuration."""
    token: Optional[str] = None


@dataclass
class ClaudeConfig:
    """Claude CLI configuration."""
    command: str = "claude"
    args: List[str] = field(default_factory=lambda: ["-p"])
    parallel_workers: int = 10


@dataclass
class GroupConfig:
    """Repository group configuration."""
    name: str
    description: str
    prompt: str = ""
    repositories: List[str] = field(default_factory=list)


@dataclass
class RepositoryConfig:
    """Individual repository configuration."""
    name: str
    group: str
    custom_prompt: Optional[str] = None


@dataclass
class ReportingConfig:
    """Reporting configuration."""
    default_weeks: int = 1
    auto_annotate: bool = True


@dataclass
class AtomConfig:
    """Atom feed configuration."""
    base_url: str = "https://ocaml.org/ruminant"
    author_name: str = "OCaml Community"
    author_email: str = "community@ocaml.org"
    opml_title: str = "OCaml Community Activity Feeds"


@dataclass
class Config:
    """Main configuration class."""
    project_name: str = "OCaml Community Activity"
    project_description: str = "Weekly reports for OCaml ecosystem projects"
    repositories: List[str] = field(default_factory=list)  # Legacy: list of repo names
    repository_configs: List[RepositoryConfig] = field(default_factory=list)  # New: repo configs with groups
    groups: Dict[str, GroupConfig] = field(default_factory=dict)  # Group definitions
    custom_prompts: Dict[str, str] = field(default_factory=dict)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    atom: AtomConfig = field(default_factory=AtomConfig)
    
    def get_repositories_for_group(self, group_name: str) -> List[str]:
        """Get all repository names for a specific group."""
        return [repo.name for repo in self.repository_configs if repo.group == group_name]
    
    def get_repository_group(self, repo_name: str) -> Optional[str]:
        """Get the group name for a specific repository."""
        for repo in self.repository_configs:
            if repo.name == repo_name:
                return repo.group
        return None


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
            
            # Load groups first
            if "groups" in data:
                for group_key, group_data in data["groups"].items():
                    if isinstance(group_data, dict):
                        group_config = GroupConfig(
                            name=group_data.get("name", group_key),
                            description=group_data.get("description", ""),
                            prompt=group_data.get("prompt", ""),
                            repositories=[]  # Will be populated when loading repos
                        )
                        config.groups[group_key] = group_config
            
            # Load repositories with group assignments
            if "repositories" in data:
                if isinstance(data["repositories"], list):
                    # New format: list of repository configs with groups
                    for repo_data in data["repositories"]:
                        if isinstance(repo_data, dict):
                            repo_name = repo_data.get("name")
                            repo_group = repo_data.get("group")
                            
                            if not repo_name:
                                raise ValueError("Repository missing 'name' field")
                            if not repo_group:
                                raise ValueError(f"Repository '{repo_name}' missing required 'group' field")
                            if repo_group not in config.groups:
                                raise ValueError(f"Repository '{repo_name}' references undefined group '{repo_group}'")
                            
                            repo_config = RepositoryConfig(
                                name=repo_name,
                                group=repo_group,
                                custom_prompt=repo_data.get("custom_prompt")
                            )
                            config.repository_configs.append(repo_config)
                            config.repositories.append(repo_name)  # Maintain backward compatibility
                            
                            # Add repo to its group
                            config.groups[repo_group].repositories.append(repo_name)
                            
                            # Store custom prompt if provided
                            if repo_config.custom_prompt:
                                config.custom_prompts[repo_name] = repo_config.custom_prompt
                
                elif isinstance(data["repositories"], dict):
                    # Legacy format compatibility
                    repos = data["repositories"]
                    legacy_repos = repos.get("repos", [])
                    if legacy_repos:
                        print("Warning: Using legacy repository format without groups. Please update your config.")
                        # Create a default group for legacy repos
                        if "default" not in config.groups:
                            config.groups["default"] = GroupConfig(
                                name="Default",
                                description="Ungrouped repositories",
                                prompt="",
                                repositories=[]
                            )
                        for repo_name in legacy_repos:
                            repo_config = RepositoryConfig(
                                name=repo_name,
                                group="default"
                            )
                            config.repository_configs.append(repo_config)
                            config.repositories.append(repo_name)
                            config.groups["default"].repositories.append(repo_name)
                    
                    config.custom_prompts = repos.get("custom_prompts", {})
            
            # Validate that all groups have at least one repository
            for group_key, group_config in config.groups.items():
                if not group_config.repositories:
                    print(f"Warning: Group '{group_key}' has no repositories assigned")
            
            # Claude config
            if "claude" in data:
                claude = data["claude"]
                config.claude.command = claude.get("command", config.claude.command)
                config.claude.args = claude.get("args", config.claude.args)
                config.claude.parallel_workers = claude.get("parallel_workers", config.claude.parallel_workers)
            
            # Reporting config
            if "reporting" in data:
                reporting = data["reporting"]
                config.reporting.default_weeks = reporting.get("default_weeks", config.reporting.default_weeks)
                config.reporting.auto_annotate = reporting.get("auto_annotate", config.reporting.auto_annotate)
            
            # Atom config
            if "atom" in data:
                atom = data["atom"]
                config.atom.base_url = atom.get("base_url", config.atom.base_url)
                config.atom.author_name = atom.get("author_name", config.atom.author_name)
                config.atom.author_email = atom.get("author_email", config.atom.author_email)
                config.atom.opml_title = atom.get("opml_title", config.atom.opml_title)
                
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
        "groups": {
            "oxcaml": {
                "name": "OCaml Core",
                "description": "Core OCaml language and tooling",
                "prompt": """Focus on language features, compiler improvements, and core tooling changes.
Highlight any breaking changes or deprecations that affect the ecosystem."""
            },
            "mirage": {
                "name": "MirageOS",
                "description": "MirageOS unikernel ecosystem",
                "prompt": """Emphasize unikernel-specific developments, security updates, and deployment improvements.
Track progress on platform support and hardware compatibility."""
            },
            "community": {
                "name": "OCaml Community",
                "description": "Broader OCaml community projects",
                "prompt": """Highlight innovative libraries, new frameworks, and community contributions.
Note adoption trends and emerging patterns in the ecosystem."""
            }
        },
        "repositories": [
            {"name": "ocaml/opam-repository", "group": "oxcaml"},
            {"name": "ocaml/ocaml", "group": "oxcaml"},
            {"name": "mirage/mirage", "group": "mirage"},
            {"name": "janestreet/base", "group": "community"},
            {"name": "ocsigen/lwt", "group": "community"}
        ],
        "claude": {
            "command": "claude",
            "args": ["-p"],
            "parallel_workers": 10
        },
        "reporting": {
            "default_weeks": 1,
            "auto_annotate": True
        },
        "atom": {
            "base_url": "https://ocaml.org/ruminant",
            "author_name": "OCaml Community",
            "author_email": "community@ocaml.org",
            "opml_title": "OCaml Community Activity Feeds"
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