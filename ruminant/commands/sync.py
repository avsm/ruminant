"""Sync command for fetching GitHub data."""

import json
import typer
from typing import Optional, List
from datetime import datetime

from ..config import load_config, get_github_token
from ..utils.dates import get_last_complete_week, get_week_list, get_week_date_range
from ..utils.paths import get_cache_file_path, ensure_repo_dirs, parse_repo
from pathlib import Path
import glob as glob_module
from ..utils.logging import (
    success, error, warning, info, step, summary_table, operation_summary,
    repo_progress, print_repo_list
)
from ..utils.github import fetch_issues, fetch_discussions, extract_users_from_data, fetch_user_info, fetch_releases

def load_week_cache(repo: str, year: int, week: int, max_age_hours: int = 24) -> Optional[dict]:
    """Load cached data for a specific repo and week."""
    cache_file = get_cache_file_path(repo, year, week)
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # For now, we'll always return cached data if it exists
            # TODO: Add age checking similar to original implementation
            return data
    except Exception as e:
        warning(f"Error loading cache file {cache_file}: {e}")
        return None


def save_week_cache(repo: str, year: int, week: int, data: dict) -> None:
    """Save data for a specific repo and week."""
    cache_file = get_cache_file_path(repo, year, week)
    ensure_repo_dirs(repo)
    
    # Add metadata
    from ..utils.dates import get_week_date_range
    week_start, week_end = get_week_date_range(year, week)
    cache_data = {
        'metadata': {
            'repo': repo,
            'year': year,
            'week': week,
            'week_start': week_start.strftime('%Y-%m-%d'),
            'week_end': week_end.strftime('%Y-%m-%d'),
            'cached_at': datetime.now().isoformat(),
        },
        'issues': data['issues'],
        'prs': data['prs'],
        'good_first_issues': data['good_first_issues'],
        'discussions': data['discussions'],
        'releases': data.get('releases', [])
    }
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        success(f"Cached data saved to {cache_file}")
    except Exception as e:
        error(f"Error saving cache file {cache_file}: {e}")


def scan_cached_data_for_users(token: Optional[str]) -> set:
    """Scan all cached repository data to find users not yet fetched."""
    all_users = set()
    missing_users = set()
    
    # Find all cached week files
    cache_pattern = "data/gh/*/*/week-*.json"
    cache_files = glob_module.glob(cache_pattern)
    
    info(f"Scanning {len(cache_files)} cached data files for users...")
    
    for cache_file in cache_files:
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Extract users from cached data
                issues = data.get('issues', [])
                prs = data.get('prs', [])
                discussions = data.get('discussions', [])
                
                # Use the extraction function to get all users
                users = extract_users_from_data(issues, prs, discussions)
                all_users.update(users)
                
                # Also add users from the cached users list if present
                cached_users = data.get('users', [])
                all_users.update(cached_users)
                
        except Exception as e:
            warning(f"Error reading cache file {cache_file}: {e}")
            continue
    
    # Check which users don't have data files yet
    user_dir = Path("data/users")
    for username in all_users:
        user_file = user_dir / f"{username}.json"
        if not user_file.exists():
            missing_users.add(username)
    
    if missing_users:
        info(f"Found {len(missing_users)} users without cached data")
    
    return missing_users


def save_user_data(users: set, token: Optional[str]) -> dict:
    """Fetch and save user data for a set of usernames."""
    user_dir = Path("data/users")
    user_dir.mkdir(parents=True, exist_ok=True)
    
    fetched = 0
    skipped = 0
    failed = 0
    
    for username in users:
        user_file = user_dir / f"{username}.json"
        
        # Skip if user data already exists
        if user_file.exists():
            skipped += 1
            continue
        
        # Fetch user data from GitHub
        user_data = fetch_user_info(username, token)
        if user_data:
            try:
                with open(user_file, 'w', encoding='utf-8') as f:
                    json.dump(user_data, f, ensure_ascii=False, indent=2)
                fetched += 1
                info(f"Saved user data for {username}")
            except Exception as e:
                error(f"Failed to save user data for {username}: {e}")
                failed += 1
        else:
            failed += 1
    
    return {
        "total": len(users),
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed
    }


def sync_repository_data(repo: str, year: int, week: int, token: Optional[str], force: bool = False) -> dict:
    """Sync repository data for a specific week."""
    week_start, week_end = get_week_date_range(year, week)
    
    # Check if we already have cached data
    if not force:
        cached_data = load_week_cache(repo, year, week, max_age_hours=24)
        if cached_data:
            issues_count = len(cached_data.get('issues', []))
            prs_count = len(cached_data.get('prs', []))
            discussions_count = len(cached_data.get('discussions', []))
            gfi_count = len(cached_data.get('good_first_issues', []))
            releases_count = len(cached_data.get('releases', []))
            
            users_count = len(cached_data.get('users', []))
            
            repo_progress(repo, week, year, 
                         f"{issues_count} issues, {prs_count} PRs, {discussions_count} discussions, {gfi_count} good first issues, {releases_count} releases, {users_count} users (cached)")
            return {
                "success": True,
                "repo": repo,
                "details": f"Cached: {issues_count + prs_count + discussions_count} items",
                "counts": {
                    "issues": issues_count,
                    "prs": prs_count,
                    "discussions": discussions_count,
                    "good_first_issues": gfi_count,
                    "releases": releases_count,
                    "users": users_count
                },
                "users": set(cached_data.get('users', []))
            }
    
    try:
        info(f"Fetching data for {repo} week {week} of {year}")
        
        # Fetch data from GitHub API
        issues, prs, recent_good_first_issues = fetch_issues(repo, token, week_start, week_end)
        discussions = fetch_discussions(repo, token, week_start, week_end)
        releases = fetch_releases(repo, token, week_start, week_end)
        
        # Extract users from the fetched data
        users = extract_users_from_data(issues, prs, discussions)
        info(f"Found {len(users)} unique users in {repo} week {week}/{year}")
        
        # Save the fetched data to cache
        data_to_cache = {
            'issues': issues,
            'prs': prs,
            'good_first_issues': recent_good_first_issues,
            'discussions': discussions,
            'releases': releases,
            'users': list(users)  # Store the list of users in the cache
        }
        save_week_cache(repo, year, week, data_to_cache)
        
        total_items = len(issues) + len(prs) + len(discussions)
        repo_progress(repo, week, year, 
                     f"{len(issues)} issues, {len(prs)} PRs, {len(discussions)} discussions, {len(recent_good_first_issues)} good first issues, {len(releases)} releases")
        
        return {
            "success": True,
            "repo": repo,
            "details": f"Fetched: {total_items} items",
            "counts": {
                "issues": len(issues),
                "prs": len(prs),
                "discussions": len(discussions),
                "good_first_issues": len(recent_good_first_issues),
                "releases": len(releases),
                "users": len(users)
            },
            "users": users
        }
        
    except Exception as e:
        error(f"Failed to sync {repo}: {e}")
        return {
            "success": False,
            "repo": repo,
            "details": str(e),
            "counts": {"issues": 0, "prs": 0, "discussions": 0, "good_first_issues": 0}
        }


def sync_main(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to sync"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    force: bool = typer.Option(False, "--force", help="Force refresh cache"),
    scan_only: bool = typer.Option(False, "--scan-only", help="Only scan cached data for missing users"),
) -> None:
    """Fetch and cache GitHub repository data."""
    
    try:
        config = load_config()
        token = get_github_token(config)
        
        if not token:
            warning("No GitHub token found. API rate limits will be lower.")
            warning("Set token in .ruminant-keys.toml or GITHUB_TOKEN environment variable")
        
        # Determine repositories to sync
        if repos:
            # Validate repo format
            for repo in repos:
                try:
                    parse_repo(repo)
                except ValueError as e:
                    error(str(e))
                    raise typer.Exit(1)
            repositories_to_sync = repos
        else:
            repositories_to_sync = config.repositories
        
        if not repositories_to_sync:
            error("No repositories specified. Use arguments or configure in .ruminant.toml")
            raise typer.Exit(1)
        
        # If scan-only mode, just scan cached data and fetch missing users
        if scan_only:
            step("Scanning cached data for missing users (scan-only mode)...")
            missing_users = scan_cached_data_for_users(token)
            
            if missing_users:
                step(f"Found {len(missing_users)} users without cached data")
                user_result = save_user_data(missing_users, token)
                success(f"User data: {user_result['fetched']} fetched, {user_result['skipped']} cached, {user_result['failed']} failed")
            else:
                success("All users in cached data have been fetched")
            
            return
        
        print_repo_list(repositories_to_sync)
        
        # Determine time range
        if year and week:
            target_year, target_week = year, week
        else:
            target_year, target_week = get_last_complete_week()
        
        # Get list of weeks to sync
        if weeks > 1:
            week_list = get_week_list(weeks, target_year, target_week)
            step(f"Syncing {len(repositories_to_sync)} repositories for {weeks} weeks")
        else:
            week_list = [(target_year, target_week)]
            step(f"Syncing {len(repositories_to_sync)} repositories for week {target_week} of {target_year}")
        
        # Sync data for all repos and weeks
        all_results = []
        all_users = set()
        total_operations = len(repositories_to_sync) * len(week_list)
        current_operation = 0
        
        for repo in repositories_to_sync:
            for w_year, w_week in week_list:
                current_operation += 1
                info(f"[{current_operation}/{total_operations}] Processing {repo} week {w_week}/{w_year}")
                
                result = sync_repository_data(repo, w_year, w_week, token, force)
                all_results.append(result)
                
                # Collect users from this repo/week
                if result["success"] and "users" in result:
                    all_users.update(result["users"])
        
        # Print summary
        successful_results = [r for r in all_results if r["success"]]
        failed_results = [r for r in all_results if not r["success"]]
        
        if successful_results:
            # Calculate totals
            total_issues = sum(r["counts"]["issues"] for r in successful_results)
            total_prs = sum(r["counts"]["prs"] for r in successful_results)
            total_discussions = sum(r["counts"]["discussions"] for r in successful_results)
            total_gfis = sum(r["counts"]["good_first_issues"] for r in successful_results)
            
            success(f"Synced {len(successful_results)}/{len(all_results)} operations")
            info(f"Total items: {total_issues} issues, {total_prs} PRs, {total_discussions} discussions, {total_gfis} good first issues")
            
            # Fetch and save user data for newly found users
            if all_users:
                step(f"Fetching user data for {len(all_users)} unique users from current sync...")
                user_result = save_user_data(all_users, token)
                success(f"User data: {user_result['fetched']} fetched, {user_result['skipped']} cached, {user_result['failed']} failed")
            
            # Scan all cached data for any missing users
            step("Scanning cached data for any missing users...")
            missing_users = scan_cached_data_for_users(token)
            if missing_users:
                step(f"Fetching data for {len(missing_users)} missing users from cached data...")
                missing_result = save_user_data(missing_users, token)
                success(f"Missing user data: {missing_result['fetched']} fetched, {missing_result['skipped']} cached, {missing_result['failed']} failed")
            else:
                info("No missing users found in cached data")
        
        if failed_results:
            warning(f"Failed operations: {len(failed_results)}")
            summary_table("Failed Operations", failed_results)
        
        operation_summary("Sync", len(all_results), len(successful_results))
        
        # Exit with error if any operations failed
        if failed_results:
            raise typer.Exit(1)
            
    except KeyboardInterrupt:
        warning("Sync interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Sync failed: {e}")
        raise typer.Exit(1)


