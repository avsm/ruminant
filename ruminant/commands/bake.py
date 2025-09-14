"""Bake command for running the complete end-to-end generator pipeline."""

import time
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import typer

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list, format_week_range
from ..utils.logging import (
    console, success, error, warning, info, step, 
    operation_summary, print_repo_list
)
from ..utils.paths import get_summary_file_path, parse_repo

# Import the main functions from other commands
from .summarize import summarize_main
from .group import group_main, get_group_summary_file_path
from .summarize_week import summarize_week_main


def check_repo_summary_exists(repo: str, year: int, week: int) -> bool:
    """Check if a repository summary already exists for a given week."""
    summary_file = get_summary_file_path(repo, year, week)
    return summary_file.exists()


def check_group_summary_exists(group: str, year: int, week: int) -> bool:
    """Check if a group summary already exists for a given week."""
    summary_file = get_group_summary_file_path(group, year, week)
    return summary_file.exists()


def check_week_summary_exists(year: int, week: int) -> bool:
    """Check if a weekly summary already exists."""
    summary_file = Path(f"data/weekly/week-{week:02d}-{year}.json")
    return summary_file.exists()


def run_repo_summaries_parallel(
    repos: List[str], 
    weeks_list: List[Tuple[int, int]], 
    config: Any,
    force: bool,
    claude_args: Optional[str] = None,
    parallel_workers: Optional[int] = None
) -> Dict[str, Any]:
    """Run repository summaries in parallel for all repos and weeks."""
    
    # Determine number of parallel workers
    if parallel_workers is None:
        parallel_workers = config.claude.parallel_workers
    
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
        "total_time": 0
    }
    
    start_time = time.time()
    
    # Build list of tasks
    tasks = []
    for repo in repos:
        for year, week in weeks_list:
            if not force and check_repo_summary_exists(repo, year, week):
                results["skipped"].append({
                    "repo": repo,
                    "week": f"{year}-W{week:02d}"
                })
            else:
                tasks.append((repo, year, week))
    
    if not tasks:
        info("All repository summaries already exist (use --force to regenerate)")
        results["total_time"] = time.time() - start_time
        return results
    
    step(f"Generating {len(tasks)} repository summaries with {parallel_workers} parallel workers...")
    
    # Import the generate_summary function from summarize module
    from .summarize import generate_summary
    
    # Run tasks in parallel
    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {}
        for repo, year, week in tasks:
            future = executor.submit(
                generate_summary, 
                repo, year, week, 
                config, 
                claude_args.split() if claude_args else None
            )
            futures[future] = (repo, year, week)
        
        # Process completed futures
        for future in as_completed(futures):
            repo, year, week = futures[future]
            try:
                result = future.result()
                if result["success"]:
                    results["success"].append({
                        "repo": repo,
                        "week": f"{year}-W{week:02d}",
                        "summary_file": str(result.get("summary_file", ""))
                    })
                    success(f"✓ {repo} for week {year}-W{week:02d}")
                else:
                    results["failed"].append({
                        "repo": repo,
                        "week": f"{year}-W{week:02d}",
                        "error": result.get("details", "Unknown error")
                    })
                    error(f"✗ {repo} for week {year}-W{week:02d}: {result.get('details', 'Unknown error')}")
            except Exception as e:
                results["failed"].append({
                    "repo": repo,
                    "week": f"{year}-W{week:02d}",
                    "error": str(e)
                })
                error(f"✗ {repo} for week {year}-W{week:02d}: {e}")
    
    results["total_time"] = time.time() - start_time
    return results


def run_group_summaries_parallel(
    groups: List[str],
    weeks_list: List[Tuple[int, int]],
    config: Any,
    force: bool,
    claude_args: Optional[str] = None
) -> Dict[str, Any]:
    """Run group summaries in parallel for all groups and weeks."""
    
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
        "total_time": 0
    }
    
    start_time = time.time()
    
    # Build list of tasks
    tasks = []
    for group in groups:
        for year, week in weeks_list:
            if not force and check_group_summary_exists(group, year, week):
                results["skipped"].append({
                    "group": group,
                    "week": f"{year}-W{week:02d}"
                })
            else:
                tasks.append((group, year, week))
    
    if not tasks:
        info("All group summaries already exist (use --force to regenerate)")
        results["total_time"] = time.time() - start_time
        return results
    
    step(f"Generating {len(tasks)} group summaries...")
    
    # Import the generate_group_summary function from group module
    from .group import generate_group_summary
    
    # Get repositories for each group
    group_repos = {}
    for group_name, group_config in config.groups.items():
        if group_name in groups:
            group_repos[group_name] = group_config.repositories
    
    # Run tasks in parallel
    with ThreadPoolExecutor(max_workers=config.claude.parallel_workers) as executor:
        futures = {}
        for group, year, week in tasks:
            repos = group_repos.get(group, [])
            future = executor.submit(
                generate_group_summary,
                group, year, week, config,
                claude_args.split() if claude_args else None
            )
            futures[future] = (group, year, week)
        
        # Process completed futures
        for future in as_completed(futures):
            group, year, week = futures[future]
            try:
                result = future.result()
                if result["success"]:
                    results["success"].append({
                        "group": group,
                        "week": f"{year}-W{week:02d}",
                        "summary_file": str(result.get("summary_file", ""))
                    })
                    success(f"✓ {group} for week {year}-W{week:02d}")
                else:
                    results["failed"].append({
                        "group": group,
                        "week": f"{year}-W{week:02d}",
                        "error": result.get("details", "Unknown error")
                    })
                    error(f"✗ {group} for week {year}-W{week:02d}: {result.get('details', 'Unknown error')}")
            except Exception as e:
                results["failed"].append({
                    "group": group,
                    "week": f"{year}-W{week:02d}",
                    "error": str(e)
                })
                error(f"✗ {group} for week {year}-W{week:02d}: {e}")
    
    results["total_time"] = time.time() - start_time
    return results


def run_weekly_summaries(
    weeks_list: List[Tuple[int, int]],
    config: Any,
    force: bool,
    claude_args: Optional[str] = None,
    lookback_weeks: int = 3
) -> Dict[str, Any]:
    """Run weekly summaries sequentially (they depend on context from previous weeks)."""
    
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
        "total_time": 0
    }
    
    start_time = time.time()
    
    # Weekly summaries must be run sequentially in chronological order
    # to build proper context
    step(f"Generating {len(weeks_list)} weekly summaries (sequential for context)...")
    
    for year, week in weeks_list:
        if not force and check_week_summary_exists(year, week):
            results["skipped"].append({
                "week": f"{year}-W{week:02d}"
            })
            info(f"Skipping {year}-W{week:02d} (already exists)")
        else:
            try:
                # Call summarize_week_main directly
                summarize_week_main(
                    year=year,
                    week=week,
                    claude_args=claude_args,
                    dry_run=False,
                    prompt_only=False,
                    lookback_weeks=lookback_weeks
                )
                results["success"].append({
                    "week": f"{year}-W{week:02d}",
                    "summary_file": f"data/weekly/week-{week:02d}-{year}.json"
                })
                success(f"✓ Weekly summary for {year}-W{week:02d}")
            except Exception as e:
                results["failed"].append({
                    "week": f"{year}-W{week:02d}",
                    "error": str(e)
                })
                error(f"✗ Weekly summary for {year}-W{week:02d}: {e}")
    
    results["total_time"] = time.time() - start_time
    return results


def bake_main(
    weeks: Optional[int],
    year: Optional[int],
    week: Optional[int],
    force: bool,
    claude_args: Optional[str],
    skip_repos: bool,
    skip_groups: bool,
    skip_weekly: bool,
    dry_run: bool
) -> None:
    """Main function for the bake command."""
    
    config = load_config()
    
    # Use config default if weeks not specified
    if weeks is None:
        if week is not None:
            weeks = 1
        else:
            weeks = config.reporting.default_weeks
    
    # Determine the weeks to process
    if year and week:
        # Specific week provided
        weeks_list = get_week_list(weeks, year, week)
    else:
        # Use last complete week
        current_year, current_week = get_last_complete_week()
        weeks_list = get_week_list(weeks, current_year, current_week)
    
    # Sort weeks chronologically (oldest first)
    weeks_list.sort()
    
    console.print("\n🧁 [bold blue]Starting bake process[/bold blue]")
    console.print(f"📅 Processing {len(weeks_list)} week(s): ", end="")
    week_strs = [f"{y}-W{w:02d}" for y, w in weeks_list]
    console.print(", ".join(week_strs))
    
    if dry_run:
        warning("DRY RUN MODE - No actual processing will occur")
    
    # Get all repositories and groups from config
    all_repos = []
    for group_name, group_config in config.groups.items():
        all_repos.extend(group_config.repositories)
    # Remove duplicates while preserving order
    all_repos = list(dict.fromkeys(all_repos))
    
    all_groups = list(config.groups.keys())
    
    console.print(f"\n📦 Repositories: {len(all_repos)}")
    console.print(f"👥 Groups: {len(all_groups)}")
    
    overall_start = time.time()
    stage_results = {}
    
    # Stage 1: Repository Summaries (Parallel)
    if not skip_repos:
        console.print("\n" + "="*60)
        console.print("[bold cyan]Stage 1: Repository Summaries[/bold cyan]")
        console.print("="*60)
        
        if dry_run:
            info("Would generate repository summaries for:")
            for repo in all_repos[:5]:  # Show first 5 as example
                console.print(f"  • {repo}")
            if len(all_repos) > 5:
                console.print(f"  ... and {len(all_repos) - 5} more")
        else:
            stage_results["repos"] = run_repo_summaries_parallel(
                all_repos, weeks_list, config, force, claude_args,
                config.claude.parallel_workers
            )
            
            # Show summary
            total_repos = len(stage_results["repos"]["success"]) + len(stage_results["repos"]["failed"]) + len(stage_results["repos"]["skipped"])
            operation_summary(
                f"Repository summaries completed in {stage_results['repos']['total_time']:.1f}s",
                total_repos,
                len(stage_results["repos"]["success"])
            )
    
    # Stage 2: Group Summaries (Parallel)
    if not skip_groups:
        console.print("\n" + "="*60)
        console.print("[bold cyan]Stage 2: Group Summaries[/bold cyan]")
        console.print("="*60)
        
        if dry_run:
            info("Would generate group summaries for:")
            for group in all_groups:
                console.print(f"  • {group}")
        else:
            stage_results["groups"] = run_group_summaries_parallel(
                all_groups, weeks_list, config, force, claude_args
            )
            
            # Show summary
            total_groups = len(stage_results["groups"]["success"]) + len(stage_results["groups"]["failed"]) + len(stage_results["groups"]["skipped"])
            operation_summary(
                f"Group summaries completed in {stage_results['groups']['total_time']:.1f}s",
                total_groups,
                len(stage_results["groups"]["success"])
            )
    
    # Stage 3: Weekly Summaries (Sequential for context)
    if not skip_weekly:
        console.print("\n" + "="*60)
        console.print("[bold cyan]Stage 3: Weekly Summaries[/bold cyan]")
        console.print("="*60)
        
        if dry_run:
            info("Would generate weekly summaries for:")
            for y, w in weeks_list:
                console.print(f"  • Week {y}-W{w:02d}")
        else:
            stage_results["weekly"] = run_weekly_summaries(
                weeks_list, config, force, claude_args
            )
            
            # Show summary
            total_weekly = len(stage_results["weekly"]["success"]) + len(stage_results["weekly"]["failed"]) + len(stage_results["weekly"]["skipped"])
            operation_summary(
                f"Weekly summaries completed in {stage_results['weekly']['total_time']:.1f}s",
                total_weekly,
                len(stage_results["weekly"]["success"])
            )
    
    # Final summary
    overall_time = time.time() - overall_start
    console.print("\n" + "="*60)
    console.print(f"[bold green]✨ Bake completed in {overall_time:.1f}s[/bold green]")
    
    if not dry_run and stage_results:
        total_success = sum(len(r.get("success", [])) for r in stage_results.values())
        total_failed = sum(len(r.get("failed", [])) for r in stage_results.values())
        total_skipped = sum(len(r.get("skipped", [])) for r in stage_results.values())
        
        console.print(f"\n📊 Overall Results:")
        console.print(f"  ✅ Success: {total_success}")
        console.print(f"  ❌ Failed: {total_failed}")
        console.print(f"  ⏭️  Skipped: {total_skipped}")
        
        if total_failed > 0:
            warning(f"\n⚠️  {total_failed} operations failed. Check logs for details.")