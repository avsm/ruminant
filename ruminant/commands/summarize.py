"""Summarize command for generating reports using Claude CLI."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import typer
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list, format_week_range
from ..utils.paths import (
    get_prompt_file_path, get_summary_file_path, get_session_log_file_path,
    ensure_repo_dirs, parse_repo, get_aggregate_prompt_file_path,
    get_aggregate_summary_file_path, get_aggregate_session_log_file_path,
    ensure_aggregate_dirs
)
from ..utils.logging import (
    success, error, warning, info, step, summary_table, operation_summary,
    print_repo_list
)

def run_claude_cli(prompt_file: Path, claude_command: str, claude_args: List[str], log_file: Path) -> dict:
    """Run Claude CLI with the given prompt file and save verbose logs."""
    try:
        # Build the command with verbose and stream-json flags
        cmd = [claude_command] + claude_args + ["--verbose", "--output-format", "stream-json"]
        
        # Read the prompt file
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()
        
        info(f"Running Claude CLI: {' '.join(cmd)}")
        
        # Run Claude CLI with prompt as input
        result = subprocess.run(
            cmd,
            input=prompt_content,
            text=True,
            capture_output=True,
            timeout=300  # 5 minute timeout
        )
        
        # Always save session log
        try:
            # Ensure log directory exists
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Parse and save the stream-json output from stdout
            log_entries = []
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        try:
                            # Each line should be a JSON object
                            log_entry = json.loads(line)
                            log_entries.append(log_entry)
                        except json.JSONDecodeError:
                            # If not JSON, save as plain text entry
                            log_entries.append({"type": "text", "content": line})
            
            # Save the complete session log (even if empty)
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "command": ' '.join(cmd),
                    "timestamp": datetime.now().isoformat(),
                    "returncode": result.returncode,
                    "stdout_size": len(result.stdout) if result.stdout else 0,
                    "stderr_size": len(result.stderr) if result.stderr else 0,
                    "entries": log_entries
                }, f, indent=2)
            
            info(f"Session log saved: {log_file}")
            
        except Exception as e:
            warning(f"Failed to save session log: {e}")
        
        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout,
                "error": result.stderr,
                "log_file": log_file
            }
        else:
            return {
                "success": False,
                "output": result.stdout,
                "error": result.stderr,
                "returncode": result.returncode,
                "log_file": log_file
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Claude CLI timed out after 5 minutes",
            "output": "",
            "log_file": log_file
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"Claude CLI command '{claude_command}' not found. Make sure it's installed and in your PATH.",
            "output": "",
            "log_file": log_file
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error running Claude CLI: {e}",
            "output": "",
            "log_file": log_file
        }


def generate_summary(repo: str, year: int, week: int, config, claude_args: Optional[List[str]] = None) -> dict:
    """Generate a summary using Claude CLI for a specific repo and week."""
    
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
    
    try:
        # Use custom Claude args if provided, otherwise use config
        cmd_args = claude_args if claude_args else config.claude.args
        
        # Run Claude CLI with logging
        claude_result = run_claude_cli(prompt_file, config.claude.command, cmd_args, log_file)
        
        if not claude_result["success"]:
            return {
                "success": False,
                "repo": repo,
                "details": f"Claude CLI failed: {claude_result['error']}",
                "prompt_file": prompt_file,
                "summary_file": summary_file,
                "log_file": log_file
            }
        
        # Claude should have written the file directly, but let's check if we have output
        if claude_result["output"].strip():
            # If Claude returned output instead of writing file, save it
            if not summary_file.exists():
                with open(summary_file, 'w', encoding='utf-8') as f:
                    f.write(claude_result["output"])
        
        # Verify the summary file was created
        if not summary_file.exists():
            return {
                "success": False,
                "repo": repo,
                "details": "Claude CLI completed but no summary file was created",
                "prompt_file": prompt_file,
                "summary_file": summary_file,
                "log_file": log_file
            }
        
        # Get file size for reporting
        file_size = summary_file.stat().st_size
        
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
        error(f"Error generating summary for {repo}: {e}")
        return {
            "success": False,
            "repo": repo,
            "details": str(e),
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }


def generate_aggregate_summary(year: int, week: int, config, claude_args: Optional[List[str]] = None) -> dict:
    """Generate an aggregate summary using Claude CLI for a specific week."""
    
    # Get file paths
    ensure_aggregate_dirs()
    prompt_file = get_aggregate_prompt_file_path(year, week)
    summary_file = get_aggregate_summary_file_path(year, week)
    log_file = get_aggregate_session_log_file_path(year, week)
    week_range_str = format_week_range(year, week)
    
    # Check if prompt file exists
    if not prompt_file.exists():
        return {
            "success": False,
            "details": f"Aggregate prompt file not found: {prompt_file}",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }
    
    try:
        # Use custom Claude args if provided, otherwise use config
        cmd_args = claude_args if claude_args else config.claude.args
        
        # Run Claude CLI with logging
        claude_result = run_claude_cli(prompt_file, config.claude.command, cmd_args, log_file)
        
        if not claude_result["success"]:
            return {
                "success": False,
                "details": f"Claude CLI failed: {claude_result['error']}",
                "prompt_file": prompt_file,
                "summary_file": summary_file,
                "log_file": log_file
            }
        
        # Claude should have written the file directly, but let's check if we have output
        if claude_result["output"].strip():
            # If Claude returned output instead of writing file, save it
            if not summary_file.exists():
                with open(summary_file, 'w', encoding='utf-8') as f:
                    f.write(claude_result["output"])
        
        # Verify the summary file was created
        if not summary_file.exists():
            return {
                "success": False,
                "details": "Claude CLI completed but no aggregate summary file was created",
                "prompt_file": prompt_file,
                "summary_file": summary_file,
                "log_file": log_file
            }
        
        # Get file size for reporting
        file_size = summary_file.stat().st_size
        
        return {
            "success": True,
            "details": f"Aggregate summary generated ({file_size:,} bytes)",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file,
            "week_range": week_range_str
        }
        
    except Exception as e:
        error(f"Error generating aggregate summary: {e}")
        return {
            "success": False,
            "details": str(e),
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
    parallel_workers: Optional[int] = typer.Option(None, "--parallel-workers", help="Number of parallel Claude instances (default from config)"),
    aggregate: bool = typer.Option(False, "--aggregate", help="Generate aggregate weekly summary across all repositories"),
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
        else:
            target_year, target_week = get_last_complete_week()
        
        # Handle aggregate mode
        if aggregate:
            # Get list of weeks to process
            if weeks > 1:
                week_list = get_week_list(weeks, target_year, target_week)
                step(f"Generating aggregate summaries for {weeks} weeks")
            else:
                week_list = [(target_year, target_week)]
                step(f"Generating aggregate summary for week {target_week} of {target_year}")
            
            if dry_run:
                info("DRY RUN MODE - No actual summaries will be generated")
            
            # Show Claude CLI configuration
            claude_cmd = config.claude.command
            claude_cmd_args = parsed_claude_args if parsed_claude_args else config.claude.args
            info(f"Claude CLI: {claude_cmd} {' '.join(claude_cmd_args)}")
            
            # Generate aggregate summaries for each week
            all_results = []
            total_operations = len(week_list)
            current_operation = 0
            
            for w_year, w_week in week_list:
                current_operation += 1
                info(f"[{current_operation}/{total_operations}] Generating aggregate summary for week {w_week}/{w_year}")
                
                if dry_run:
                    # Just check if prompt file exists
                    prompt_file = get_aggregate_prompt_file_path(w_year, w_week)
                    summary_file = get_aggregate_summary_file_path(w_year, w_week)
                    log_file = get_aggregate_session_log_file_path(w_year, w_week)
                    
                    if prompt_file.exists():
                        result = {
                            "success": True,
                            "details": f"Would generate from {prompt_file} -> {summary_file}",
                            "prompt_file": prompt_file,
                            "summary_file": summary_file,
                            "log_file": log_file
                        }
                    else:
                        result = {
                            "success": False,
                            "details": f"Aggregate prompt file missing: {prompt_file}",
                            "prompt_file": prompt_file,
                            "summary_file": summary_file,
                            "log_file": log_file
                        }
                else:
                    result = generate_aggregate_summary(w_year, w_week, config, parsed_claude_args)
                
                all_results.append(result)
                
                if result["success"]:
                    success(f"Aggregate summary: {result['summary_file']}")
                else:
                    error(f"Failed: {result['details']}")
        else:
            # Original per-repository logic
            # Get list of weeks to process
            if weeks > 1:
                week_list = get_week_list(weeks, target_year, target_week)
                step(f"Generating summaries for {len(repositories_to_process)} repositories for {weeks} weeks")
            else:
                week_list = [(target_year, target_week)]
                step(f"Generating summaries for {len(repositories_to_process)} repositories for week {target_week} of {target_year}")
            
            if dry_run:
                info("DRY RUN MODE - No actual summaries will be generated")
            
            # Calculate total operations
            total_operations = len(repositories_to_process) * len(week_list)
            
            # Show Claude CLI configuration
            claude_cmd = config.claude.command
            claude_cmd_args = parsed_claude_args if parsed_claude_args else config.claude.args
            workers = parallel_workers if parallel_workers is not None else config.claude.parallel_workers
            info(f"Claude CLI: {claude_cmd} {' '.join(claude_cmd_args)}")
            if not dry_run and total_operations > 1:
                info(f"Using {workers} parallel workers")
            
            # Generate summaries for all repos and weeks
            all_results = []
            current_operation = 0
            
            if dry_run or total_operations == 1:
                # Sequential processing for dry run or single operation
                for repo in repositories_to_process:
                    for w_year, w_week in week_list:
                        current_operation += 1
                        info(f"[{current_operation}/{total_operations}] Generating summary for {repo} week {w_week}/{w_year}")
                        
                        if dry_run:
                            # Just check if prompt file exists
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
                            result = generate_summary(repo, w_year, w_week, config, parsed_claude_args)
                        
                        all_results.append(result)
                        
                        if result["success"]:
                            success(f"Summary: {result['summary_file']}")
                        else:
                            error(f"Failed: {result['details']}")
            else:
                # Parallel processing for multiple operations
                tasks = []
                for repo in repositories_to_process:
                    for w_year, w_week in week_list:
                        tasks.append((repo, w_year, w_week))
                
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    # Submit all tasks
                    future_to_task = {}
                    for repo, w_year, w_week in tasks:
                        future = executor.submit(generate_summary, repo, w_year, w_week, config, parsed_claude_args)
                        future_to_task[future] = (repo, w_year, w_week)
                    
                    # Process results as they complete
                    for future in as_completed(future_to_task):
                        repo, w_year, w_week = future_to_task[future]
                        current_operation += 1
                        
                        try:
                            result = future.result()
                            info(f"[{current_operation}/{total_operations}] Completed: {repo} week {w_week}/{w_year}")
                            
                            if result["success"]:
                                success(f"Summary: {result['summary_file']}")
                            else:
                                error(f"Failed: {result['details']}")
                        except Exception as e:
                            result = {
                                "success": False,
                                "repo": repo,
                                "details": f"Exception during parallel execution: {e}",
                                "prompt_file": get_prompt_file_path(repo, w_year, w_week),
                                "summary_file": get_summary_file_path(repo, w_year, w_week),
                                "log_file": get_session_log_file_path(repo, w_year, w_week)
                            }
                            error(f"[{current_operation}/{total_operations}] Failed: {repo} week {w_week}/{w_year} - {e}")
                        
                        all_results.append(result)
        
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
            if aggregate:
                info("Aggregate summaries generated successfully.")
            elif config.reporting.auto_annotate:
                info("To annotate reports with GitHub links:")
                info("  ruminant annotate")
            else:
                info("Summaries generated. Run 'ruminant annotate' to add GitHub links.")
        
        # Exit with error if any operations failed
        if failed_results:
            raise typer.Exit(1)
            
    except KeyboardInterrupt:
        warning("Summary generation interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Summary generation failed: {e}")
        raise typer.Exit(1)


