"""Summarize command for generating reports using Claude CLI."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import typer
from datetime import datetime
import time
from typing import Optional, List
from pathlib import Path

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list, format_week_range
from ..utils.paths import (
    get_prompt_file_path, get_summary_file_path, get_session_log_file_path,
    ensure_repo_dirs, parse_repo
)
from ..utils.logging import (
    success, error, warning, info, step, summary_table, operation_summary,
    print_repo_list, print_file_paths
)
from ..utils.claude import run_claude_cli, validate_summary_file
from .prompt import generate_prompt


def get_session_log_file_path(repo: str, year: int, week: int) -> Path:
    """Get a unique session log file path for this run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    owner, name = parse_repo(repo)
    log_dir = Path(f"data/logs/{owner}/{name}")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"week-{week:02d}-{year}-{timestamp}.json"


def generate_summary(repo: str, year: int, week: int, config, claude_args: Optional[List[str]] = None, max_retries: int = 3) -> dict:
    """Generate a summary using Claude CLI for a specific repo and week with automatic retry."""
    
    # Get file paths
    ensure_repo_dirs(repo)
    prompt_file = get_prompt_file_path(repo, year, week)
    summary_file = get_summary_file_path(repo, year, week)
    log_file = get_session_log_file_path(repo, year, week)
    week_range_str = format_week_range(year, week)
    
    # Check if prompt file exists
    if not prompt_file.exists():
        return {
            "success": False,
            "repo": repo,
            "details": f"Prompt file not found: {prompt_file}",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }
    
    # Use custom Claude args if provided, otherwise use config
    cmd_args = claude_args if claude_args else config.claude.args
    
    # Retry logic
    for attempt in range(1, max_retries + 1):
        try:
            # Clean up any invalid summary file from previous attempt
            if summary_file.exists() and not validate_summary_file(summary_file):
                warning(f"Removing invalid summary file from previous attempt: {summary_file}")
                summary_file.unlink()
            
            # Update log file path for each attempt
            if attempt > 1:
                log_file = get_session_log_file_path(repo, year, week).with_suffix(f".attempt{attempt}.json")
                info(f"Retry attempt {attempt}/{max_retries} for {repo} week {week}/{year}")
                time.sleep(2)  # Brief delay between retries
            
            # Run Claude CLI with logging
            claude_result = run_claude_cli(prompt_file, config.claude.command, cmd_args, log_file)
            
            # Check for timeout
            if claude_result.get("timeout", False):
                if attempt < max_retries:
                    warning(f"Claude CLI timed out for {repo}, retrying...")
                    continue
                else:
                    return {
                        "success": False,
                        "repo": repo,
                        "details": f"Claude CLI timed out after {max_retries} attempts",
                        "prompt_file": prompt_file,
                        "summary_file": summary_file,
                        "log_file": log_file
                    }
            
            if not claude_result["success"]:
                if attempt < max_retries:
                    warning(f"Claude CLI failed: {claude_result['error']}, retrying...")
                    continue
                else:
                    return {
                        "success": False,
                        "repo": repo,
                        "details": f"Claude CLI failed after {max_retries} attempts: {claude_result['error']}",
                        "prompt_file": prompt_file,
                        "summary_file": summary_file,
                        "log_file": log_file
                    }
            
            # Claude should have written the file directly
            # Do NOT save stdout as it contains stream-json logs, not the actual summary
            
            # Verify the summary file was created and is valid
            if not summary_file.exists():
                if attempt < max_retries:
                    warning(f"No summary file created for {repo}, retrying...")
                    continue
                else:
                    return {
                        "success": False,
                        "repo": repo,
                        "details": f"No summary file created after {max_retries} attempts. Make sure the prompt instructs Claude to write to a file.",
                        "prompt_file": prompt_file,
                        "summary_file": summary_file,
                        "log_file": log_file
                    }
            
            # Validate the summary file
            if not validate_summary_file(summary_file):
                if attempt < max_retries:
                    warning(f"Invalid summary file generated for {repo}, retrying...")
                    summary_file.unlink()  # Remove invalid file
                    continue
                else:
                    return {
                        "success": False,
                        "repo": repo,
                        "details": f"Invalid summary file after {max_retries} attempts (contains stream logs or invalid JSON)",
                        "prompt_file": prompt_file,
                        "summary_file": summary_file,
                        "log_file": log_file
                    }
            
            # Success!
            file_size = summary_file.stat().st_size
            if attempt > 1:
                info(f"Successfully generated summary for {repo} on attempt {attempt}")
            
            return {
                "success": True,
                "repo": repo,
                "details": f"Summary generated ({file_size:,} bytes)",
                "prompt_file": prompt_file,
                "summary_file": summary_file,
                "log_file": log_file,
                "week_range": week_range_str
            }
            
        except Exception as e:
            if attempt < max_retries:
                warning(f"Error generating summary for {repo}: {e}, retrying...")
                continue
            else:
                error(f"Error generating summary for {repo} after {max_retries} attempts: {e}")
                return {
                    "success": False,
                    "repo": repo,
                    "details": f"Error after {max_retries} attempts: {str(e)}",
                    "prompt_file": prompt_file,
                    "summary_file": summary_file,
                    "log_file": log_file
                }


def summarize_main(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to generate summaries for"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI (space-separated)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without running Claude CLI"),
    prompt_only: bool = typer.Option(False, "--prompt-only", help="Only generate prompts without running Claude CLI"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show file paths that will be used"),
    parallel_workers: Optional[int] = typer.Option(None, "--parallel-workers", help="Number of parallel Claude instances (default from config)"),
    skip_existing: bool = typer.Option(True, "--skip-existing", help="Skip weeks that already have summaries"),
) -> None:
    """Generate summaries using Claude CLI."""
    
    try:
        config = load_config()
        
        # Parse Claude args if provided
        parsed_claude_args = None
        if claude_args:
            parsed_claude_args = claude_args.split()
        
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
        else:
            repositories_to_process = config.repositories
        
        if not repositories_to_process:
            error("No repositories specified. Use arguments or configure in .ruminant.toml")
            raise typer.Exit(1)
        
        print_repo_list(repositories_to_process)
        
        # Determine time range
        if year and week:
            target_year, target_week = year, week
        elif week and not year:
            # If only week is provided, use current year
            current_year, _ = get_last_complete_week()
            target_year, target_week = current_year, week
        else:
            target_year, target_week = get_last_complete_week()
        
        # Get list of weeks to process
        if weeks > 1:
            week_list = get_week_list(weeks, target_year, target_week)
        else:
            week_list = [(target_year, target_week)]
        
        all_results = []
        
        # Generate individual repo summaries
        # Original per-repository logic
        if not repositories_to_process:
            error("No repositories to process")
            raise typer.Exit(1)
        
        # Calculate total operations for progress tracking
        total_operations = len(repositories_to_process) * len(week_list)
        current_operation = 0
        
        # Show paths if requested
        if show_paths:
            step("File paths to be used:")
            for repo in repositories_to_process:
                for w_year, w_week in week_list:
                    prompt_file = get_prompt_file_path(repo, w_year, w_week)
                    summary_file = get_summary_file_path(repo, w_year, w_week)
                    print_file_paths(repo, w_year, w_week, prompt_file, summary_file)
            return
        
        # Configure Claude CLI
        claude_cmd = config.claude.command
        claude_cmd_args = parsed_claude_args if parsed_claude_args else config.claude.args
        
        step(f"Generating {total_operations} summaries for {len(week_list)} week(s)")
        
        if dry_run:
            info("DRY RUN MODE - No actual summaries will be generated")
        elif prompt_only:
            info("PROMPT ONLY MODE - Only prompts will be generated")
        
        info(f"Claude CLI: {claude_cmd} {' '.join(claude_cmd_args)}")
        
        # Get parallel workers setting
        workers = parallel_workers
        if workers is None:
            workers = config.claude.parallel_workers
        if workers is None or workers <= 0:
            workers = None  # Will process sequentially
        
        # Determine if we should use parallel processing
        use_parallel = (
            workers is not None and 
            workers > 1 and 
            total_operations > 1 and 
            not dry_run and 
            not prompt_only
        )
        
        if use_parallel:
            info(f"Using {workers} parallel workers for summary generation")
        else:
            info("Processing summaries sequentially")
        
        # Process based on mode
        if dry_run or prompt_only or not use_parallel:
            # Sequential processing for dry run, prompt-only, or when parallel is disabled
            for repo in repositories_to_process:
                for w_year, w_week in week_list:
                    current_operation += 1
                    
                    # Check if summary already exists
                    summary_file = get_summary_file_path(repo, w_year, w_week)
                    if skip_existing and summary_file.exists() and validate_summary_file(summary_file):
                        info(f"[{current_operation}/{total_operations}] Skipping: {repo} week {w_week}/{w_year} (already exists)")
                        all_results.append({
                            "success": True,
                            "repo": repo,
                            "details": "Summary already exists",
                            "prompt_file": get_prompt_file_path(repo, w_year, w_week),
                            "summary_file": summary_file,
                            "skipped": True
                        })
                        continue
                    
                    info(f"[{current_operation}/{total_operations}] Processing: {repo} week {w_week}/{w_year}")
                    
                    # Generate prompt first
                    prompt_result = generate_prompt(repo, w_year, w_week, config)
                    if not prompt_result["success"]:
                        error(f"Failed to generate prompt: {prompt_result['details']}")
                        all_results.append(prompt_result)
                        continue
                    
                    info(f"Generated prompt: {prompt_result['prompt_file']}")
                    
                    if prompt_only:
                        success(f"Prompt generated: {prompt_result['prompt_file']}")
                        all_results.append(prompt_result)
                        continue
                    
                    if dry_run:
                        prompt_file = get_prompt_file_path(repo, w_year, w_week)
                        summary_file = get_summary_file_path(repo, w_year, w_week)
                        log_file = get_session_log_file_path(repo, w_year, w_week)
                        
                        if prompt_file.exists():
                            result = {
                                "success": True,
                                "repo": repo,
                                "details": f"Would generate from {prompt_file} -> {summary_file}",
                                "prompt_file": prompt_file,
                                "summary_file": summary_file,
                                "log_file": log_file
                            }
                        else:
                            result = {
                                "success": False,
                                "repo": repo,
                                "details": f"Prompt file missing: {prompt_file}",
                                "prompt_file": prompt_file,
                                "summary_file": summary_file,
                                "log_file": log_file
                            }
                    else:
                        # Generate actual summary
                        result = generate_summary(repo, w_year, w_week, config, parsed_claude_args)
                    
                    all_results.append(result)
                    
                    if result["success"]:
                        success(f"Summary: {result['summary_file']}")
                    else:
                        error(f"Failed: {result['details']}")
        else:
            # Parallel processing for actual summary generation
            # Collect all tasks
            tasks = []
            for repo in repositories_to_process:
                for w_year, w_week in week_list:
                    # Check if summary already exists
                    summary_file = get_summary_file_path(repo, w_year, w_week)
                    if skip_existing and summary_file.exists() and validate_summary_file(summary_file):
                        info(f"Skipping: {repo} week {w_week}/{w_year} (already exists)")
                        all_results.append({
                            "success": True,
                            "repo": repo,
                            "details": "Summary already exists",
                            "prompt_file": get_prompt_file_path(repo, w_year, w_week),
                            "summary_file": summary_file,
                            "skipped": True
                        })
                    else:
                        tasks.append((repo, w_year, w_week))
            
            if not tasks:
                info("All summaries already exist, nothing to process")
            else:
                # First, generate all prompts sequentially (they're quick)
                step("Generating prompts for all tasks...")
                for repo, w_year, w_week in tasks:
                    prompt_result = generate_prompt(repo, w_year, w_week, config)
                    if not prompt_result["success"]:
                        error(f"Failed to generate prompt for {repo} week {w_week}/{w_year}: {prompt_result['details']}")
                        all_results.append(prompt_result)
                    else:
                        info(f"Generated prompt: {prompt_result['prompt_file']}")
            
                # Now generate summaries in parallel
                step(f"Generating summaries with {workers} parallel workers...")
                parallel_start_time = time.time()
                
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    # Submit all tasks
                    future_to_task = {}
                    submitted_count = 0
                    task_start_times = {}
                    
                    for repo, w_year, w_week in tasks:
                        # Only submit if prompt was successfully generated
                        prompt_file = get_prompt_file_path(repo, w_year, w_week)
                        if prompt_file.exists():
                            info(f"[Worker {(submitted_count % workers) + 1}] Submitting: {repo} week {w_week}/{w_year}")
                            future = executor.submit(generate_summary, repo, w_year, w_week, config, parsed_claude_args)
                            future_to_task[future] = (repo, w_year, w_week)
                            task_start_times[(repo, w_year, w_week)] = time.time()
                            submitted_count += 1
                        else:
                            warning(f"Skipping {repo} week {w_week}/{w_year} - prompt file missing")
                    
                    info(f"Submitted {submitted_count} tasks to {workers} workers")
                    info("Processing summaries as they complete...")
                    
                    # Process results as they complete
                    completed_count = 0
                    for future in as_completed(future_to_task):
                        repo, w_year, w_week = future_to_task[future]
                        current_operation += 1
                        completed_count += 1
                        
                        # Calculate task duration
                        task_key = (repo, w_year, w_week)
                        task_duration = time.time() - task_start_times.get(task_key, parallel_start_time)
                        
                        try:
                            info(f"[{completed_count}/{submitted_count}] Processing result for: {repo} week {w_week}/{w_year}")
                            result = future.result()
                            
                            if result["success"]:
                                success(f"[{completed_count}/{submitted_count}] ✓ Completed: {repo} week {w_week}/{w_year} (took {task_duration:.1f}s)")
                                info(f"  → Summary saved to: {result['summary_file']}")
                                if result.get('log_file'):
                                    info(f"  → Session log: {result['log_file']}")
                            else:
                                error(f"[{completed_count}/{submitted_count}] ✗ Failed: {repo} week {w_week}/{w_year} (after {task_duration:.1f}s)")
                                error(f"  → Error: {result['details']}")
                                if result.get('log_file'):
                                    warning(f"  → Check log: {result['log_file']}")
                        except Exception as e:
                            result = {
                                "success": False,
                                "repo": repo,
                                "details": f"Exception during parallel execution: {e}",
                                "prompt_file": get_prompt_file_path(repo, w_year, w_week),
                                "summary_file": get_summary_file_path(repo, w_year, w_week),
                                "log_file": get_session_log_file_path(repo, w_year, w_week)
                            }
                            error(f"[{completed_count}/{submitted_count}] ✗ Exception: {repo} week {w_week}/{w_year} (after {task_duration:.1f}s)")
                            error(f"  → Exception: {e}")
                        
                        all_results.append(result)
                        
                        # Show progress with time estimate
                        remaining = submitted_count - completed_count
                        if remaining > 0:
                            elapsed = time.time() - parallel_start_time
                            avg_time = elapsed / completed_count
                            estimated_remaining = avg_time * remaining
                            info(f"Progress: {completed_count}/{submitted_count} completed, {remaining} in progress...")
                            info(f"  → Elapsed: {elapsed:.1f}s, Est. remaining: {estimated_remaining:.1f}s")
                
                # Final timing
                total_parallel_time = time.time() - parallel_start_time
                info(f"Parallel processing completed in {total_parallel_time:.1f}s")
        
        # Print summary
        successful_results = [r for r in all_results if r["success"]]
        failed_results = [r for r in all_results if not r["success"]]
        
        if successful_results:
            action = "Would generate" if dry_run else "Generated"
            success(f"{action} {len(successful_results)}/{len(all_results)} summaries")
        
        if failed_results:
            warning(f"Failed to generate {len(failed_results)} summaries")
            summary_table("Failed Summaries", failed_results)
        
        operation_summary("Summary Generation", len(all_results), len(successful_results))
        
        # Show next steps
        if successful_results and not dry_run:
            info("Summaries generated successfully.")
        
    except KeyboardInterrupt:
        warning("Summary generation interrupted by user")
        raise typer.Exit(1)
    except typer.Exit:
        # Re-raise typer exits
        raise
    except Exception as e:
        error(f"Summary generation failed: {e}")
        raise typer.Exit(1)