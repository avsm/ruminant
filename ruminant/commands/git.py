"""Git repository management command for cloning and updating repositories."""

import subprocess
import typer
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from ..config import load_config
from ..utils.paths import parse_repo, get_data_dir
from ..utils.logging import success, error, warning, info, step, operation_summary


def get_git_repo_path(repo: str) -> Path:
    """Get the path where a git repository should be cloned."""
    owner, name = parse_repo(repo)
    data_dir = get_data_dir()
    git_dir = data_dir / "git" / owner / name
    return git_dir


def clone_or_update_repo(repo: str, verbose: bool = False) -> dict:
    """Clone a repository or update it if it already exists."""
    try:
        owner, name = parse_repo(repo)
        repo_path = get_git_repo_path(repo)
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        
        github_url = f"https://github.com/{owner}/{name}.git"
        
        # Check if this is a mirror clone (bare repository in .git subdirectory)
        mirror_path = repo_path / ".git"
        if mirror_path.exists() and not (repo_path / ".git" / ".git").exists():
            # This is a mirror clone, just update it with fetch
            if verbose:
                info(f"Updating mirror clone {repo}...")
            
            # Simple fetch updates everything in a mirror clone
            result = subprocess.run(
                ["git", "fetch", "--prune"],
                cwd=mirror_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode != 0:
                return {
                    "success": False,
                    "repo": repo,
                    "action": "fetch",
                    "details": f"Failed to fetch: {result.stderr}"
                }
            
            # Count refs for reporting
            branches_result = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
                cwd=mirror_path,
                capture_output=True,
                text=True
            )
            
            tags_result = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname:short)", "refs/tags/"],
                cwd=mirror_path,
                capture_output=True,
                text=True
            )
            
            num_branches = len(branches_result.stdout.splitlines()) if branches_result.returncode == 0 else 0
            num_tags = len(tags_result.stdout.splitlines()) if tags_result.returncode == 0 else 0
            
            return {
                "success": True,
                "repo": repo,
                "action": "updated",
                "details": f"Updated mirror with {num_branches} branches and {num_tags} tags",
                "path": str(repo_path),
                "type": "mirror"
            }
        
        elif repo_path.exists():
            # Regular clone exists, update it normally
            if verbose:
                info(f"Updating regular clone {repo}...")
            
            # Fetch all remotes with tags
            result = subprocess.run(
                ["git", "fetch", "--all", "--tags", "--prune"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode != 0:
                return {
                    "success": False,
                    "repo": repo,
                    "action": "fetch",
                    "details": f"Failed to fetch: {result.stderr}"
                }
            
            # Count branches and tags
            branches_result = subprocess.run(
                ["git", "branch", "-a"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            tags_result = subprocess.run(
                ["git", "tag"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            
            num_branches = len(branches_result.stdout.splitlines()) if branches_result.returncode == 0 else 0
            num_tags = len(tags_result.stdout.splitlines()) if tags_result.returncode == 0 else 0
            
            return {
                "success": True,
                "repo": repo,
                "action": "updated",
                "details": f"Updated with {num_branches} branches and {num_tags} tags",
                "path": str(repo_path),
                "type": "regular"
            }
            
        else:
            # Repository doesn't exist, clone it as a mirror
            if verbose:
                info(f"Cloning {repo} as mirror...")
            
            # Clone as mirror for complete repository copy
            result = subprocess.run(
                ["git", "clone", "--mirror", github_url, str(mirror_path)],
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout for initial clone
            )
            
            if result.returncode != 0:
                return {
                    "success": False,
                    "repo": repo,
                    "action": "clone",
                    "details": f"Failed to clone: {result.stderr}"
                }
            
            # Count refs for reporting
            branches_result = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
                cwd=mirror_path,
                capture_output=True,
                text=True
            )
            
            tags_result = subprocess.run(
                ["git", "for-each-ref", "--format=%(refname:short)", "refs/tags/"],
                cwd=mirror_path,
                capture_output=True,
                text=True
            )
            
            num_branches = len(branches_result.stdout.splitlines()) if branches_result.returncode == 0 else 0
            num_tags = len(tags_result.stdout.splitlines()) if tags_result.returncode == 0 else 0
            
            return {
                "success": True,
                "repo": repo,
                "action": "cloned",
                "details": f"Cloned mirror with {num_branches} branches and {num_tags} tags",
                "path": str(repo_path),
                "type": "mirror"
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "repo": repo,
            "action": "timeout",
            "details": "Operation timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "repo": repo,
            "action": "error",
            "details": str(e)
        }


def git_main(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    all_repos: bool = typer.Option(False, "--all", help="Clone/update all configured repositories"),
    parallel: int = typer.Option(4, "--parallel", help="Number of parallel git operations"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show repository paths after cloning/updating")
) -> None:
    """Clone or update git repositories with full history and all branches."""
    
    try:
        config = load_config()
        
        # Determine repositories to process
        if repos:
            # Validate repo format
            for repo in repos:
                try:
                    parse_repo(repo)
                except ValueError as e:
                    error(str(e))
                    raise typer.Exit(1)
            repositories_to_process = repos
        elif all_repos:
            repositories_to_process = config.repositories
        else:
            error("Specify repositories or use --all flag")
            raise typer.Exit(1)
        
        if not repositories_to_process:
            error("No repositories to process")
            raise typer.Exit(1)
        
        step(f"Processing {len(repositories_to_process)} repositories")
        if verbose:
            for repo in repositories_to_process:
                info(f"  - {repo}")
        
        all_results = []
        start_time = time.time()
        
        if parallel > 1 and len(repositories_to_process) > 1:
            # Process repositories in parallel
            info(f"Using {parallel} parallel workers")
            
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                # Submit all tasks
                future_to_repo = {}
                for repo in repositories_to_process:
                    future = executor.submit(clone_or_update_repo, repo, verbose)
                    future_to_repo[future] = repo
                
                # Process results as they complete
                completed = 0
                for future in as_completed(future_to_repo):
                    repo = future_to_repo[future]
                    completed += 1
                    
                    try:
                        result = future.result()
                        all_results.append(result)
                        
                        if result["success"]:
                            action = result["action"]
                            if action == "cloned":
                                success(f"[{completed}/{len(repositories_to_process)}] ✓ Cloned {repo}: {result['details']}")
                            elif action == "updated":
                                success(f"[{completed}/{len(repositories_to_process)}] ✓ Updated {repo}: {result['details']}")
                            
                            if show_paths:
                                info(f"  Path: {result['path']}")
                        else:
                            error(f"[{completed}/{len(repositories_to_process)}] ✗ Failed {repo}: {result['details']}")
                    
                    except Exception as e:
                        error(f"[{completed}/{len(repositories_to_process)}] ✗ Exception for {repo}: {e}")
                        all_results.append({
                            "success": False,
                            "repo": repo,
                            "action": "error",
                            "details": str(e)
                        })
        else:
            # Process repositories sequentially
            for i, repo in enumerate(repositories_to_process, 1):
                info(f"[{i}/{len(repositories_to_process)}] Processing {repo}...")
                
                result = clone_or_update_repo(repo, verbose)
                all_results.append(result)
                
                if result["success"]:
                    action = result["action"]
                    if action == "cloned":
                        success(f"✓ Cloned {repo}: {result['details']}")
                    elif action == "updated":
                        success(f"✓ Updated {repo}: {result['details']}")
                    
                    if show_paths:
                        info(f"  Path: {result['path']}")
                else:
                    error(f"✗ Failed {repo}: {result['details']}")
        
        # Summary
        elapsed_time = time.time() - start_time
        successful_results = [r for r in all_results if r["success"]]
        failed_results = [r for r in all_results if not r["success"]]
        
        cloned_count = len([r for r in successful_results if r.get("action") == "cloned"])
        updated_count = len([r for r in successful_results if r.get("action") == "updated"])
        
        operation_summary("Git Repository Management", len(all_results), len(successful_results))
        
        if cloned_count > 0:
            info(f"Cloned {cloned_count} new repositories")
        if updated_count > 0:
            info(f"Updated {updated_count} existing repositories")
        
        if failed_results:
            warning(f"Failed to process {len(failed_results)} repositories:")
            for result in failed_results:
                error(f"  - {result['repo']}: {result['details']}")
        
        info(f"Completed in {elapsed_time:.1f} seconds")
        
        if show_paths:
            step("Repository paths:")
            git_dir = get_data_dir() / "git"
            info(f"All repositories are stored in: {git_dir}")
            for result in successful_results:
                if "path" in result:
                    info(f"  {result['repo']}: {result['path']}")
        
        # Exit with error if any operations failed
        if failed_results:
            raise typer.Exit(1)
    
    except KeyboardInterrupt:
        warning("Git operations interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Git operations failed: {e}")
        raise typer.Exit(1)