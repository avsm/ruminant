"""Group command for generating consolidated summaries across multiple repositories."""

import json
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
import typer
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list, format_week_range
from ..utils.logging import (
    success, error, warning, info, step, print_repo_list,
    confirm_operation, operation_summary
)
from ..utils.claude import run_claude_cli, validate_summary_file


def ensure_group_dirs(group: str) -> None:
    """Ensure all necessary directories exist for a group."""
    Path(f"data/groups/{group}").mkdir(parents=True, exist_ok=True)
    Path(f"data/prompts/groups/{group}").mkdir(parents=True, exist_ok=True)
    Path(f"data/logs/groups/{group}").mkdir(parents=True, exist_ok=True)


def get_group_prompt_file_path(group: str, year: int, week: int) -> Path:
    """Get the path for a group prompt file."""
    return Path(f"data/prompts/groups/{group}/week-{week:02d}-{year}-prompt.txt")


def get_group_summary_file_path(group: str, year: int, week: int) -> Path:
    """Get the path for a group summary file."""
    return Path(f"data/groups/{group}/week-{week:02d}-{year}.json")


def get_group_log_file_path(group: str, year: int, week: int) -> Path:
    """Get the path for a group session log file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(f"data/logs/groups/{group}/week-{week:02d}-{year}-{timestamp}.json")


def generate_group_prompt(group: str, repositories: List[str], year: int, week: int) -> dict:
    """Generate a prompt for group summary."""
    ensure_group_dirs(group)
    
    prompt_file = get_group_prompt_file_path(group, year, week)
    week_range = format_week_range(year, week)
    
    # Check which repository summaries exist
    available_summaries = []
    missing_summaries = []
    
    for repo in repositories:
        summary_file = Path(f"data/summaries/{repo}/week-{week:02d}-{year}.json")
        if summary_file.exists():
            available_summaries.append(repo)
        else:
            missing_summaries.append(repo)
    
    if not available_summaries:
        return {
            "success": False,
            "group": group,
            "details": f"No repository summaries available for week {week}/{year}",
            "prompt_file": prompt_file,
            "missing": missing_summaries
        }
    
    # Count users available
    user_count = len(list(Path("data/users").glob("*.json"))) if Path("data/users").exists() else 0
    
    # Build the prompt
    prompt_lines = [
        f"You are a software development manager responsible for analyzing GitHub repository activity across the {group} group.",
        "",
        f"Please analyze the summary data for the {group} group covering the period {week_range} (week {week} of {year}).",
        "",
        "USER DATA AVAILABLE:",
        "The data/users/ directory contains JSON files with GitHub user information. Each file is named [username].json and contains:",
        "- Full name (if available)",
        "- Avatar URL",
        "- Bio",
        "- Company",
        "- Location",
        "- Blog/website",
        "- Other profile information",
        "",
        f"{user_count} user profiles are available in data/users/",
        "",
        "YOUR TASK:",
        f"1. Read and analyze the individual repository summaries from:",
    ]
    
    for repo in available_summaries:
        summary_file = Path(f"data/summaries/{repo}/week-{week:02d}-{year}.json")
        prompt_lines.append(f"   - {summary_file}")
    
    prompt_lines.extend([
        f"2. Generate a comprehensive group summary report",
        f"3. Write this report to: {get_group_summary_file_path(group, year, week)}",
        "",
        f"REPOSITORIES IN THIS GROUP: {', '.join(available_summaries)}",
        ""
    ])
    
    if missing_summaries:
        prompt_lines.extend([
            f"NOTE: The following repositories are configured but have no summaries available: {', '.join(missing_summaries)}",
            ""
        ])
    
    prompt_lines.extend([
        "The report should include the following sections:",
        "",
        "1. **Group Overview**: A concise summary of activity across all repositories (MUST use bullet points)",
        "2. **Cross-Repository Work**: Highlight any connected work, dependencies, or collaborations between repositories (MUST use bullet points)",
        "3. **Key Projects and Initiatives**: Major ongoing work across the group (MUST use bullet points)",
        "4. **Priority Items**: Issues and PRs that need immediate attention (MUST use bullet points)",
        "5. **Notable Discussions**: Important discussions from any repository (MUST use bullet points)",
        "6. **Emerging Trends**: Patterns observed across the group (MUST use bullet points)",
        "",
        "CRITICAL REQUIREMENTS:",
        "- ALL sections MUST use bullet point format (starting with \"-\" or \"*\") for consistency and readability",
        "- SKIP any section entirely if there is no meaningful content for it",
        "- DO NOT include placeholder text like \"No discussions were recorded\" or \"There are no XYZ to report\"",
        "- Only include sections that have actual, substantive content",
        "- Be as concise as possible while maintaining clarity",
        "",
        "TONE AND LANGUAGE REQUIREMENTS:",
        "- Use factual, objective language - avoid hyperbolic terms and emotive words like dominate or exceptional",
        "- Prefer specific, quantifiable descriptions",
        "- Focus on concrete changes and measurable impacts",
        "",
        "IMPORTANT: Since this is a multi-repository group summary:",
        "- Always use the full format for issues/PRs: owner/repo#number",
        "- Example: ocaml/ocaml#12345 instead of just #12345",
        "- This ensures clarity about which repository each item belongs to",
        "",
        "LINKING AND FORMATTING REQUIREMENTS:",
        "",
        "1. USER MENTIONS:",
        "   - When mentioning a GitHub user, check if their data exists in data/users/[username].json",
        "   - If user data exists and contains a \"name\" field, format as: [Full Name](https://github.com/username)",
        "   - If no name is available or file doesn't exist, format as: [@username](https://github.com/username)",
        "",
        "2. ISSUE/PR REFERENCES:",
        "   - Always use full format: owner/repo#number",
        "   - Convert to: [owner/repo#number](https://github.com/owner/repo/issues/number)",
        "   - Example: ocaml/ocaml#5678 becomes [ocaml/ocaml#5678](https://github.com/ocaml/ocaml/issues/5678)",
        "",
        "3. CROSS-REPOSITORY CONNECTIONS:",
        "   - Pay special attention to work that spans multiple repositories",
        "   - Look for related PRs, shared dependencies, or coordinated releases",
        "   - Highlight any blocking dependencies between repositories",
        "",
        "ACTION REQUIRED:",
        f"1. Use the Read tool to load and analyze the individual repository summaries from data/summaries/",
        f"2. Generate a JSON report with the following structure:",
        "",
        "{",
        f'  "week": {week},',
        f'  "year": {year},',
        f'  "group": "{group}",',
        f'  "repositories": {json.dumps(available_summaries)},',
        f'  "week_range": "{week_range}",',
        '  "brief_summary": "A single sentence (max 150 chars) summarizing the most important activity this week",',
        '  "group_overview": "Markdown content for group overview (MUST use bullet points)",',
        '  "cross_repository_work": "Markdown content for cross-repository work (MUST use bullet points)",',
        '  "key_projects": "Markdown content for key projects (MUST use bullet points)",',
        '  "priority_items": "Markdown content for priority items (MUST use bullet points)",',
        '  "notable_discussions": "Markdown content for notable discussions (MUST use bullet points)",',
        '  "emerging_trends": "Markdown content for emerging trends (MUST use bullet points)"',
        "}",
        "",
        "IMPORTANT JSON FORMATTING RULES:",
        "- brief_summary: A single, concise sentence (maximum 150 characters) that captures the most significant activity or theme of the week",
        "- Each section value should contain the markdown content that would have been in that section",
        "- ALL sections MUST use bullet points format (starting with \"-\" or \"*\")",
        "- If a section has no meaningful content, set its value to null (not an empty string)",
        "- Ensure proper JSON escaping for special characters in the markdown content",
        "- The JSON must be valid and properly formatted",
        "",
        f"3. Use the Write tool to save the complete JSON report to: {get_group_summary_file_path(group, year, week)}",
        "4. Return a confirmation message that the file was written successfully",
        "",
        "Remember:",
        "- Focus on the group-level view and cross-repository insights",
        "- Use full owner/repo#number format for all issue/PR references",
        "- Check data/users/[username].json files for user full names",
        "- Format all GitHub references as proper markdown links",
        "",
        "IMPORTANT: You must use the Read tool to load the individual repository summaries and the Write tool to save the output file.",
        "",
        "FINAL VERIFICATION STEP - ABSOLUTELY CRITICAL:",
        "",
        "Before writing your final JSON output to the file, you MUST perform this comprehensive link verification:",
        "",
        "1. **SCAN EVERY SECTION** of your generated content systematically:",
        "   - group_overview",
        "   - cross_repository_work",
        "   - key_projects",
        "   - priority_items",
        "   - notable_discussions",
        "   - emerging_trends",
        "",
        "2. **VERIFY COMPREHENSIVE LINKING** for each section:",
        "   - ✓ Every PR/issue number → [owner/repo#number](https://github.com/owner/repo/issues/number)",
        "   - ✓ Every contributor name → Check data/users/[username].json for full name",
        "   - ✓ Every repository mention → Properly formatted with owner/repo",
        "   - ✓ EVERY BULLET POINT should include at least one clickable issue/PR link where possible",
        "",
        "3. **COMMON PATTERNS TO FIX**:",
        "   - \"PR #123\" or \"issue #456\" → MUST be [owner/repo#123](...)",
        "   - \"merged 5 PRs\" → List specific PR numbers with links if known",
        "   - \"@username\" → Check user data and format as [Full Name](https://github.com/username)",
        "   - \"ocaml/dune repository\" → Include link to https://github.com/ocaml/dune",
        "   - \"cross-repository work\" → Specify which repositories with links",
        "   - Generic statements → Find and include specific issue/PR references",
        "",
        "4. **ISSUE INCLUSION REQUIREMENT**:",
        "   - EVERY bullet point should strive to include at least one relevant issue or PR link",
        "   - If discussing a feature → Link to the tracking issue or implementation PR",
        "   - If mentioning a bug fix → Link to the bug report and fix PR",
        "   - If referencing discussions → Link to the discussion issue or PR comments",
        "   - Only omit links if truly no relevant issue/PR exists (rare)",
        "",
        "5. **DOUBLE-CHECK THESE AREAS** (often missed):",
        "   - Contributors mentioned in passing (not just main authors)",
        "   - Issue numbers in priority_items section",
        "   - Repository references in cross_repository_work",
        "   - PR numbers mentioned in emerging_trends",
        "   - All usernames in notable_discussions",
        "   - Background context that references past work",
        "",
        "6. **IF YOU FIND MISSING LINKS**:",
        "   - STOP immediately",
        "   - Add the proper link formatting",
        "   - Re-scan that entire section for other missed links",
        "   - Do NOT proceed until ALL links are added",
        "",
        "7. **QUALITY METRICS** - Your summary should have:",
        "   - 100% of PR/issue numbers converted to clickable links",
        "   - 100% of contributor names checked against user data",
        "   - 100% of repository references properly formatted",
        "   - 90%+ of bullet points containing at least one issue/PR link",
        "   - Zero generic statements without supporting issue/PR references",
        "",
        "This verification is MANDATORY. A summary without comprehensive linking fails to serve its purpose",
        "of helping readers navigate to the actual work being discussed. Every bullet point should provide",
        "a direct path to the underlying issues and PRs. Take the time to get this right."
    ])
    
    # Write the prompt file
    try:
        prompt_file.write_text("\n".join(prompt_lines))
        return {
            "success": True,
            "group": group,
            "prompt_file": prompt_file,
            "available": available_summaries,
            "missing": missing_summaries
        }
    except Exception as e:
        return {
            "success": False,
            "group": group,
            "details": str(e),
            "prompt_file": prompt_file
        }


def generate_group_summary(group: str, year: int, week: int, config, claude_args: Optional[List[str]] = None) -> dict:
    """Generate a group summary using Claude CLI."""
    
    ensure_group_dirs(group)
    
    prompt_file = get_group_prompt_file_path(group, year, week)
    summary_file = get_group_summary_file_path(group, year, week)
    log_file = get_group_log_file_path(group, year, week)
    
    # Check if prompt file exists
    if not prompt_file.exists():
        return {
            "success": False,
            "group": group,
            "details": f"Prompt file not found: {prompt_file}",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }
    
    # Use custom Claude args if provided, otherwise use config
    cmd_args = claude_args if claude_args else config.claude.args
    
    # Run Claude CLI
    claude_result = run_claude_cli(prompt_file, config.claude.command, cmd_args, log_file)
    
    if not claude_result["success"]:
        if claude_result.get("timeout"):
            details = "Claude CLI timed out"
        else:
            details = claude_result.get("error", "Unknown error")
        
        return {
            "success": False,
            "group": group,
            "details": details,
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }
    
    # Check if summary file was created
    if not summary_file.exists():
        return {
            "success": False,
            "group": group,
            "details": "Summary file was not created by Claude",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }
    
    # Validate the summary file using common validation
    if not validate_summary_file(summary_file):
        return {
            "success": False,
            "group": group,
            "details": "Invalid summary file (contains stream logs or invalid JSON)",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "log_file": log_file
        }
    
    return {
        "success": True,
        "group": group,
        "prompt_file": prompt_file,
        "summary_file": summary_file,
        "log_file": log_file
    }


def process_group_week(group_name: str, repositories: List[str], year: int, week: int, 
                       config, claude_args: Optional[List[str]], 
                       prompt_only: bool, dry_run: bool, skip_existing: bool) -> Dict[str, Any]:
    """Process a single group for a single week. Used for both sequential and parallel processing."""
    
    # Check if summary already exists and is valid
    summary_file = get_group_summary_file_path(group_name, year, week)
    if skip_existing and summary_file.exists() and validate_summary_file(summary_file):
        return {
            "success": True,
            "group": group_name,
            "summary_file": summary_file,
            "skipped": True,
            "details": "Valid summary already exists"
        }
    
    # Generate prompt
    prompt_result = generate_group_prompt(group_name, repositories, year, week)
    
    if not prompt_result["success"]:
        return prompt_result
    
    if prompt_result.get("missing"):
        # Add missing info to result but don't print here (will be handled by caller)
        prompt_result["has_missing"] = True
    
    if prompt_only:
        return prompt_result
    
    if dry_run:
        summary_file = get_group_summary_file_path(group_name, year, week)
        return {
            "success": True,
            "group": group_name,
            "prompt_file": prompt_result['prompt_file'],
            "summary_file": summary_file,
            "dry_run": True
        }
    
    # Generate summary
    return generate_group_summary(group_name, year, week, config, claude_args)


def group_main(
    group: Optional[str] = typer.Argument(None, help="Group name to generate summary for"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to process"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    all_groups: bool = typer.Option(False, "--all", help="Generate summaries for all configured groups"),
    prompt_only: bool = typer.Option(False, "--prompt-only", help="Only generate prompts without running Claude"),
    claude_args: Optional[str] = typer.Option(None, "--claude-args", help="Additional arguments for Claude CLI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
    skip_existing: bool = typer.Option(True, "--skip-existing", help="Skip groups that already have summaries"),
) -> None:
    """Generate consolidated summaries for repository groups."""
    
    try:
        config = load_config()
        
        # Determine which groups to process
        if all_groups:
            if not config.groups:
                error("No groups configured in .ruminant.toml")
                raise typer.Exit(1)
            groups_to_process = list(config.groups.keys())
        elif group:
            if group not in config.groups:
                error(f"Group '{group}' not found in configuration")
                available = list(config.groups.keys()) if config.groups else []
                if available:
                    info(f"Available groups: {', '.join(available)}")
                raise typer.Exit(1)
            groups_to_process = [group]
        else:
            error("Specify a group name or use --all for all groups")
            if config.groups:
                info(f"Available groups: {', '.join(config.groups.keys())}")
            raise typer.Exit(1)
        
        # Determine time range
        if year and week:
            target_year, target_week = year, week
        else:
            target_year, target_week = get_last_complete_week()
        
        # Get list of weeks to process
        if weeks > 1:
            week_list = get_week_list(weeks, target_year, target_week)
        else:
            week_list = [(target_year, target_week)]
        
        # Parse Claude args if provided
        parsed_claude_args = None
        if claude_args:
            parsed_claude_args = claude_args.split()
        
        # Calculate total operations
        total_operations = len(groups_to_process) * len(week_list)
        
        # Show what we'll be processing
        info(f"Processing {len(groups_to_process)} group(s) for {len(week_list)} week(s)")
        for group_name in groups_to_process:
            repos = config.get_repositories_for_group(group_name)
            info(f"  {group_name}: {len(repos)} repositories")
        
        if dry_run:
            info("DRY RUN MODE - No actual work will be performed")
        elif prompt_only:
            info("PROMPT ONLY MODE - Only prompts will be generated")
        
        # Determine whether to use parallel processing
        workers = config.claude.parallel_workers if hasattr(config.claude, 'parallel_workers') else None
        use_parallel = (
            workers is not None and 
            workers > 1 and 
            total_operations > 1 and 
            not dry_run and 
            not prompt_only
        )
        
        all_results = []
        current_operation = 0
        
        if use_parallel:
            # Parallel processing
            info(f"Using {workers} parallel workers for group summary generation")
            
            # Collect all tasks
            tasks = []
            for group_name in groups_to_process:
                repositories = config.get_repositories_for_group(group_name)
                for w_year, w_week in week_list:
                    tasks.append((group_name, repositories, w_year, w_week))
            
            # First, generate all prompts sequentially (they're quick)
            step("Generating prompts for all group summaries...")
            prompt_results = []
            skipped_count = 0
            for group_name, repositories, w_year, w_week in tasks:
                # Check if summary already exists and skip if requested
                summary_file = get_group_summary_file_path(group_name, w_year, w_week)
                if skip_existing and summary_file.exists() and validate_summary_file(summary_file):
                    info(f"Skipping group '{group_name}' week {w_week}/{w_year} - valid summary exists")
                    all_results.append({
                        "success": True,
                        "group": group_name,
                        "summary_file": summary_file,
                        "skipped": True,
                        "details": "Valid summary already exists"
                    })
                    skipped_count += 1
                    continue
                
                info(f"Generating prompt for group '{group_name}' week {w_week}/{w_year}")
                prompt_result = generate_group_prompt(group_name, repositories, w_year, w_week)
                
                if not prompt_result["success"]:
                    error(f"Failed to generate prompt: {prompt_result.get('details', 'Unknown error')}")
                    all_results.append(prompt_result)
                else:
                    success(f"Generated prompt: {prompt_result['prompt_file']}")
                    if prompt_result.get("missing"):
                        warning(f"Missing summaries for: {', '.join(prompt_result['missing'])}")
                    prompt_results.append((group_name, repositories, w_year, w_week))
            
            if skipped_count > 0:
                info(f"Skipped {skipped_count} existing summaries")
            
            if prompt_only:
                info("Prompt-only mode - skipping summary generation")
                for result in prompt_results:
                    all_results.append({"success": True, "group": result[0], "prompt_only": True})
            else:
                # Now generate summaries in parallel
                step(f"Generating summaries with {workers} parallel workers...")
                parallel_start_time = time.time()
                
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    # Submit all tasks
                    future_to_task = {}
                    submitted_count = 0
                    task_start_times = {}
                    
                    for group_name, repositories, w_year, w_week in prompt_results:
                        # Only submit if prompt was successfully generated
                        prompt_file = get_group_prompt_file_path(group_name, w_year, w_week)
                        if prompt_file.exists():
                            info(f"[Worker {(submitted_count % workers) + 1}] Submitting: {group_name} week {w_week}/{w_year}")
                            info(f"  → Processing {len(repositories)} repositories")
                            future = executor.submit(
                                generate_group_summary, 
                                group_name, w_year, w_week, config, parsed_claude_args
                            )
                            future_to_task[future] = (group_name, w_year, w_week, repositories)
                            task_start_times[(group_name, w_year, w_week)] = time.time()
                            submitted_count += 1
                        else:
                            warning(f"Skipping {group_name} week {w_week}/{w_year} - prompt file missing")
                    
                    info(f"Submitted {submitted_count} group summary tasks to {workers} workers")
                    info("Processing group summaries as they complete...")
                    
                    # Process results as they complete
                    completed_count = 0
                    for future in as_completed(future_to_task):
                        group_name, w_year, w_week, repositories = future_to_task[future]
                        current_operation += 1
                        completed_count += 1
                        
                        # Calculate task duration
                        task_key = (group_name, w_year, w_week)
                        task_duration = time.time() - task_start_times.get(task_key, parallel_start_time)
                        
                        try:
                            info(f"[{completed_count}/{submitted_count}] Processing result for: {group_name} week {w_week}/{w_year}")
                            result = future.result()
                            
                            if result["success"]:
                                success(f"[{completed_count}/{submitted_count}] ✓ Completed: {group_name} week {w_week}/{w_year} (took {task_duration:.1f}s)")
                                info(f"  → Group summary saved to: {result['summary_file']}")
                                info(f"  → Consolidated {len(repositories)} repositories")
                                if result.get('log_file'):
                                    info(f"  → Session log: {result['log_file']}")
                            else:
                                error(f"[{completed_count}/{submitted_count}] ✗ Failed: {group_name} week {w_week}/{w_year} (after {task_duration:.1f}s)")
                                error(f"  → Error: {result.get('details', 'Unknown error')}")
                                if result.get('log_file'):
                                    warning(f"  → Check log: {result['log_file']}")
                        except Exception as e:
                            result = {
                                "success": False,
                                "group": group_name,
                                "details": f"Exception during parallel execution: {e}",
                                "prompt_file": get_group_prompt_file_path(group_name, w_year, w_week),
                                "summary_file": get_group_summary_file_path(group_name, w_year, w_week),
                                "log_file": get_group_log_file_path(group_name, w_year, w_week)
                            }
                            error(f"[{completed_count}/{submitted_count}] ✗ Exception: {group_name} week {w_week}/{w_year} (after {task_duration:.1f}s)")
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
                info(f"Parallel processing completed in {total_parallel_time:.1f}s ({submitted_count} group summaries)")
        else:
            # Sequential processing
            info("Processing group summaries sequentially")
            
            for group_name in groups_to_process:
                repositories = config.get_repositories_for_group(group_name)
                
                for w_year, w_week in week_list:
                    current_operation += 1
                    step(f"[{current_operation}/{total_operations}] Processing group '{group_name}' for week {w_week}/{w_year}")
                    
                    result = process_group_week(
                        group_name, repositories, w_year, w_week,
                        config, parsed_claude_args, prompt_only, dry_run, skip_existing
                    )
                    
                    if result["success"]:
                        if result.get("skipped"):
                            info(f"Skipped - valid summary already exists: {result['summary_file']}")
                        elif prompt_only:
                            success(f"Generated prompt: {result['prompt_file']}")
                        elif dry_run:
                            info(f"Would generate summary from {result['prompt_file']}")
                            info(f"Would write to {result['summary_file']}")
                        else:
                            success(f"Generated summary: {result['summary_file']}")
                        
                        if result.get("missing") or result.get("has_missing"):
                            warning(f"Missing summaries for: {', '.join(result.get('missing', []))}")
                    else:
                        error(f"Failed: {result.get('details', 'Unknown error')}")
                    
                    all_results.append(result)
        
        # Print summary
        successful = [r for r in all_results if r["success"]]
        failed = [r for r in all_results if not r["success"]]
        skipped = [r for r in successful if r.get("skipped")]
        
        operation_summary("Group Summary Generation", len(all_results), len(successful))
        
        if skipped:
            info(f"Skipped {len(skipped)} existing summaries")
        
        if failed:
            warning(f"Failed to generate {len(failed)} group summaries")
            for result in failed:
                error(f"  {result.get('group', 'Unknown')}: {result.get('details', 'Unknown error')}")
        
        if not successful:
            raise typer.Exit(1)
            
    except KeyboardInterrupt:
        warning("Group summary generation interrupted by user")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        error(f"Group summary generation failed: {e}")
        raise typer.Exit(1)
