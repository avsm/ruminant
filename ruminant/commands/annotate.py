"""Annotate command for adding GitHub links to reports."""

import typer
from typing import Optional, List
from pathlib import Path
import glob

from ..config import load_config, get_github_token
from ..utils.dates import get_last_complete_week, get_week_list
from ..utils.paths import (
    get_summary_file_path, get_report_file_path, get_summaries_dir, get_reports_dir,
    ensure_repo_dirs, parse_repo
)
from ..utils.logging import (
    success, error, warning, info, step, summary_table, operation_summary,
    print_repo_list
)
from ..utils.annotate import annotate_file, clear_user_cache, get_cache_stats

def find_summary_files(pattern: str = None) -> List[Path]:
    """Find summary files matching the pattern."""
    summaries_dir = get_summaries_dir()
    
    if pattern:
        # Use the provided pattern
        files = glob.glob(pattern, recursive=True)
        return [Path(f) for f in files if f.endswith('.md')]
    else:
        # Find all markdown files in summaries directory
        if summaries_dir.exists():
            return list(summaries_dir.rglob("*.md"))
        return []


def annotate_summary(repo: str, year: int, week: int, token: Optional[str], in_place: bool = False) -> dict:
    """Annotate a single summary file."""
    
    ensure_repo_dirs(repo)
    summary_file = get_summary_file_path(repo, year, week)
    
    if in_place:
        output_file = summary_file
    else:
        output_file = get_report_file_path(repo, year, week)
    
    if not summary_file.exists():
        return {
            "success": False,
            "repo": repo,
            "details": f"Summary file not found: {summary_file}",
            "input_file": summary_file,
            "output_file": output_file
        }
    
    try:
        success = annotate_file(summary_file, output_file, token)
        
        if success:
            file_size = output_file.stat().st_size
            action = "Updated" if in_place else "Created"
            return {
                "success": True,
                "repo": repo,
                "details": f"{action} report ({file_size:,} bytes)",
                "input_file": summary_file,
                "output_file": output_file
            }
        else:
            return {
                "success": False,
                "repo": repo,
                "details": "Annotation failed",
                "input_file": summary_file,
                "output_file": output_file
            }
            
    except Exception as e:
        return {
            "success": False,
            "repo": repo,
            "details": str(e),
            "input_file": summary_file,
            "output_file": output_file
        }


def annotate_main(
    files: Optional[List[str]] = typer.Argument(None, help="Specific files to annotate (supports wildcards)"),
    repos: Optional[List[str]] = typer.Option(None, "--repos", help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to annotate"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    in_place: bool = typer.Option(False, "--in-place", help="Modify summary files in place instead of creating reports"),
    all_summaries: bool = typer.Option(False, "--all", help="Annotate all summary files"),
) -> None:
    """Annotate markdown reports with GitHub links."""
    
    try:
        config = load_config()
        token = get_github_token(config)
        
        if not token:
            warning("No GitHub token found. User lookups will be limited.")
            warning("Set token in .ruminant-keys.toml or GITHUB_TOKEN environment variable")
        
        # Determine what files to process
        files_to_process = []
        
        if files:
            # Process specific files with wildcards
            step("Finding files matching patterns...")
            for pattern in files:
                found_files = find_summary_files(pattern)
                files_to_process.extend(found_files)
                info(f"Pattern '{pattern}': {len(found_files)} files")
        elif all_summaries:
            # Process all summary files
            step("Finding all summary files...")
            files_to_process = find_summary_files()
        else:
            # Process based on repos/weeks parameters
            if repos:
                # Validate repo format
                for repo in repos:
                    try:
                        parse_repo(repo)
                    except ValueError as e:
                        error(str(e))
                        raise typer.Exit(1)
                repositories_to_process = repos
            else:
                repositories_to_process = config.repositories
            
            if not repositories_to_process:
                error("No repositories specified. Use --repos, configure in .ruminant.toml, or use --all")
                raise typer.Exit(1)
            
            print_repo_list(repositories_to_process)
            
            # Determine time range
            if year and week:
                target_year, target_week = year, week
            else:
                target_year, target_week = get_last_complete_week()
            
            # Get list of weeks to process
            if weeks > 1:
                week_list = get_week_list(weeks, target_year, target_week)
                step(f"Annotating {len(repositories_to_process)} repositories for {weeks} weeks")
            else:
                week_list = [(target_year, target_week)]
                step(f"Annotating {len(repositories_to_process)} repositories for week {target_week} of {target_year}")
            
            # Convert to file list
            for repo in repositories_to_process:
                for w_year, w_week in week_list:
                    summary_file = get_summary_file_path(repo, w_year, w_week)
                    if summary_file.exists():
                        files_to_process.append(summary_file)
        
        if not files_to_process:
            warning("No files found to annotate")
            info("Make sure you have generated summaries first with 'ruminant summarize'")
            raise typer.Exit(0)
        
        # Remove duplicates
        files_to_process = list(set(files_to_process))
        info(f"Found {len(files_to_process)} files to annotate")
        
        action = "Updating in place" if in_place else "Creating annotated reports"
        step(f"{action} for {len(files_to_process)} files...")
        
        # Process files
        all_results = []
        
        for i, file_path in enumerate(files_to_process, 1):
            info(f"[{i}/{len(files_to_process)}] Processing {file_path.name}")
            
            # Try to extract repo info from path for better results
            from ..utils.annotate import extract_repo_from_path
            repo_from_path = extract_repo_from_path(file_path)
            
            try:
                if in_place:
                    output_file = file_path
                else:
                    # Try to extract repo info and construct proper report path
                    repo_from_path = extract_repo_from_path(file_path)
                    if repo_from_path:
                        # Extract year and week from filename: week-NN-YYYY.md
                        filename = file_path.stem  # removes .md
                        parts = filename.split('-')
                        if len(parts) == 3 and parts[0] == 'week':
                            try:
                                week_num = int(parts[1])
                                year_num = int(parts[2])
                                output_file = get_report_file_path(repo_from_path, year_num, week_num)
                            except ValueError:
                                # Fallback to manual path construction
                                output_file = get_reports_dir() / file_path.relative_to(get_summaries_dir())
                        else:
                            # Fallback to manual path construction
                            output_file = get_reports_dir() / file_path.relative_to(get_summaries_dir())
                    else:
                        # Fallback to manual path construction
                        output_file = get_reports_dir() / file_path.relative_to(get_summaries_dir())
                
                if annotate_file(file_path, output_file, token):
                    file_size = output_file.stat().st_size
                    result = {
                        "success": True,
                        "repo": repo_from_path or file_path.parent.parent.name + "/" + file_path.parent.name,
                        "details": f"Annotated ({file_size:,} bytes)",
                        "input_file": file_path,
                        "output_file": output_file
                    }
                    success(f"Annotated: {output_file}")
                else:
                    result = {
                        "success": False,
                        "repo": repo_from_path or file_path.parent.parent.name + "/" + file_path.parent.name,
                        "details": "Annotation failed",
                        "input_file": file_path,
                        "output_file": output_file
                    }
                
                all_results.append(result)
                
            except Exception as e:
                result = {
                    "success": False,
                    "repo": repo_from_path or "unknown",
                    "details": str(e),
                    "input_file": file_path,
                    "output_file": None
                }
                all_results.append(result)
                error(f"Failed to annotate {file_path.name}: {e}")
        
        # Print summary
        successful_results = [r for r in all_results if r["success"]]
        failed_results = [r for r in all_results if not r["success"]]
        
        if successful_results:
            action_past = "Updated" if in_place else "Created"
            success(f"{action_past} {len(successful_results)}/{len(all_results)} annotated files")
        
        if failed_results:
            warning(f"Failed to annotate {len(failed_results)} files")
            summary_table("Failed Annotations", failed_results)
        
        operation_summary("Annotation", len(all_results), len(successful_results))
        
        # Show cache stats
        cache_stats = get_cache_stats()
        if cache_stats["count"] > 0:
            info(f"User cache now contains {cache_stats['count']} users ({cache_stats['size']:,} bytes)")
        
        # Exit with error if any operations failed
        if failed_results:
            raise typer.Exit(1)
            
    except KeyboardInterrupt:
        warning("Annotation interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Annotation failed: {e}")
        raise typer.Exit(1)


def clear_cache() -> None:
    """Clear the user cache."""
    try:
        count = clear_user_cache()
        if count > 0:
            success(f"Cleared user cache: {count} files removed")
        else:
            info("No user cache to clear")
    except Exception as e:
        error(f"Failed to clear cache: {e}")
        raise typer.Exit(1)


def stats() -> None:
    """Show user cache statistics."""
    try:
        cache_stats = get_cache_stats()
        
        if cache_stats["count"] == 0:
            info("No user cache found")
            return
        
        info("User cache statistics:")
        info(f"  Cached users: {cache_stats['count']}")
        info(f"  Total size: {cache_stats['size']:,} bytes ({cache_stats['size']/1024:.1f} KB)")
        
        if cache_stats["users"]:
            info("\nSample cached users:")
            for user in cache_stats["users"]:
                info(f"  @{user['username']} -> {user['name']}")
            
            if cache_stats["count"] > len(cache_stats["users"]):
                info(f"  ... and {cache_stats['count'] - len(cache_stats['users'])} more")
                
    except Exception as e:
        error(f"Failed to get cache stats: {e}")
        raise typer.Exit(1)


