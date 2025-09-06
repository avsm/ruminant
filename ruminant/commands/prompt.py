"""Prompt generation command adapted from claude-summary-prompt.py."""

import json
import typer
from typing import Optional, List

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list, get_week_date_range, format_week_range
from ..utils.paths import (
    get_cache_file_path, get_prompt_file_path, get_summary_file_path,
    ensure_repo_dirs, parse_repo
)
from ..utils.logging import (
    success, error, warning, info, step, summary_table, operation_summary,
    print_repo_list, print_file_paths
)

def generate_prompt(repo: str, year: int, week: int, config) -> dict:
    """Generate a Claude prompt for summarizing repository activity."""
    
    # Get week date range
    week_start, week_end = get_week_date_range(year, week)
    week_range_str = format_week_range(year, week)
    
    # Check if cached data exists
    cache_file = get_cache_file_path(repo, year, week)
    if not cache_file.exists():
        return {
            "success": False,
            "repo": repo,
            "details": f"No cached data found: {cache_file}",
            "cache_file": cache_file,
            "prompt_file": None,
            "summary_file": None
        }
    
    try:
        # Just check that the cache file exists and has data
        with open(cache_file, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
        
        # Count items for reporting
        issues_count = len(original_data.get('issues', []))
        prs_count = len(original_data.get('prs', []))
        discussions_count = len(original_data.get('discussions', []))
        gfi_count = len(original_data.get('good_first_issues', []))
        
        # Get file paths
        ensure_repo_dirs(repo)
        prompt_file = get_prompt_file_path(repo, year, week)
        summary_file = get_summary_file_path(repo, year, week)
        
        # Load custom prompt for this repository
        custom_prompt = config.custom_prompts.get(repo, "")
        
        # Build the detailed prompt
        base_prompt = f"""You are a software development manager responsible for analyzing GitHub repository activity.

Please analyze GitHub repository data for {repo} covering the period {week_range_str} (week {week} of {year}).

NOTE: If you need additional information about any PR or issue beyond what's in the JSON data, you can use the GitHub MCP server tools
(e.g., mcp__github__get_pull_request, mcp__github__get_issue) to fetch more details about specific items.

YOUR TASK:
1. Read and analyze the GitHub data from: {cache_file}
2. Generate a comprehensive markdown summary report  
3. Write this report to the file: {summary_file}

DATA SUMMARY: The JSON file contains {issues_count} issues, {prs_count} PRs, {discussions_count} discussions, and {gfi_count} good first issues.

The report should include the following sections:

1. A concise summary of the overall activity and key themes
2. The most important ongoing projects or initiatives based on the data
3. Prioritized issues and PRs that need immediate attention
4. Major discussions that should be highlighted
5. Identify any emerging trends or patterns in development
6. Good first issues for new contributors

CRITICAL REQUIREMENTS:
- SKIP any section entirely if there is no meaningful content for it
- DO NOT include placeholder text like "No discussions were recorded" or "There are no XYZ to report"
- Only include sections that have actual, substantive content
- Be as concise as possible while maintaining clarity

IMPORTANT: For each PR or issue you mention, ALWAYS include the contributor's GitHub username with @ symbol (e.g., @username) to properly credit their contributions. This is critical for recognizing contributors' work.

LINKING REQUIREMENTS:
- EVERY bullet point MUST include relevant PR/issue numbers in parentheses or inline
- For "Key Ongoing Projects", always include specific issue/PR references (#XXXX) where possible
- When referring to PRs, issues, or discussions, use ONLY the GitHub reference format: #XXXX (number with # prefix)
- DO NOT include the title after the reference number
- For groups of related work, list ALL relevant PR/issue numbers, not just examples
- Even general observations should reference specific PRs/issues that support them

FORMATTING INSTRUCTIONS:
- AVOID listing large numbers of PRs in sequence - instead, summarize them by theme with all relevant numbers
- For groups of related PRs, summarize the theme and list ALL relevant PR/issue numbers in parentheses
- Use bullet points effectively to organize information
- EVERY bullet point must have associated PR/issue numbers for reader follow-up

Example of correct format:

- **Authentication Framework** (#1234, #5678, #5681): Core authentication by @username with related security improvements
- **Performance Optimization** (#5679, #5680, #5682, #5683): Multiple backend optimizations by @anotheruser including database and caching improvements
- **Bug Fixes**: Critical memory leak fixed by @developer (#5684), UI rendering issues resolved (#5685, #5686)
- **Documentation Updates** (#5687, #5688): API documentation improvements and new contributor guide by @writer

NOTE: Every substantive point MUST include PR/issue numbers to allow readers to investigate further"""

        # Add custom prompt if provided
        if custom_prompt:
            base_prompt += f"\n\nCUSTOM REPOSITORY-SPECIFIC INSTRUCTIONS:\n{custom_prompt}\n"

        prompt = base_prompt + f"""

ACTION REQUIRED:
1. Read the GitHub activity data from the JSON file: {cache_file}
2. Generate a markdown report with the following structure:

# {week_range_str} - {repo} Activity Summary

Then include only the sections that have meaningful content, with PR/issue numbers for every bullet point:
- ## Overall Activity Summary (always include if there's any activity - include key PR/issue numbers)
- ## Key Ongoing Projects (only if there are identifiable projects - MUST include all relevant issue/PR references)
- ## Priority Items (only if there are items needing immediate attention - include specific PR/issue numbers)
- ## Notable Discussions (only if there are actual significant discussions - include discussion numbers if available)
- ## Emerging Trends (only if clear patterns are identifiable - support with specific PR/issue examples)
- ## Good First Issues (only if there are actual good first issues available - list all issue numbers)
- ## Contributors (always include if there are any contributors - reference their specific contributions by PR/issue number)

3. Write the complete markdown report to: {summary_file}
4. Return a confirmation message that the file was written successfully

Remember: 
- Skip sections entirely if they would be empty or contain only filler text
- EVERY bullet point must include relevant PR/issue numbers for reader follow-up
- Use GitHub MCP server tools if you need additional information about specific PRs/issues
- The output file MUST be written with the complete markdown summary

IMPORTANT: You must use the Read tool to load and analyze the data from {cache_file}"""
        
        # Save prompt to file
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        return {
            "success": True,
            "repo": repo,
            "details": f"Prompt generated ({len(prompt)} chars, {issues_count+prs_count+discussions_count} items)",
            "cache_file": cache_file,
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "week_range": week_range_str
        }
        
    except Exception as e:
        error(f"Error generating prompt for {repo}: {e}")
        return {
            "success": False,
            "repo": repo,
            "details": str(e),
            "cache_file": cache_file,
            "prompt_file": None,
            "summary_file": None
        }


def prompt_main(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to generate prompts for"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show file paths that will be used"),
) -> None:
    """Generate Claude prompts for weekly GitHub activity summaries."""
    
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
        
        # Get list of weeks to process
        if weeks > 1:
            week_list = get_week_list(weeks, target_year, target_week)
            step(f"Generating prompts for {len(repositories_to_process)} repositories for {weeks} weeks")
        else:
            week_list = [(target_year, target_week)]
            step(f"Generating prompts for {len(repositories_to_process)} repositories for week {target_week} of {target_year}")
        
        # Generate prompts for all repos and weeks
        all_results = []
        total_operations = len(repositories_to_process) * len(week_list)
        current_operation = 0
        
        for repo in repositories_to_process:
            for w_year, w_week in week_list:
                current_operation += 1
                info(f"[{current_operation}/{total_operations}] Generating prompt for {repo} week {w_week}/{w_year}")
                
                result = generate_prompt(repo, w_year, w_week, config)
                all_results.append(result)
                
                if result["success"]:
                    success(f"Generated prompt: {result['prompt_file']}")
                    if show_paths:
                        paths = {
                            "Cache file": result["cache_file"],
                            "Prompt file": result["prompt_file"],
                            "Summary file": result["summary_file"]
                        }
                        print_file_paths(f"{repo} Week {w_week}/{w_year} Paths", paths)
        
        # Print summary
        successful_results = [r for r in all_results if r["success"]]
        failed_results = [r for r in all_results if not r["success"]]
        
        if successful_results:
            success(f"Generated {len(successful_results)}/{len(all_results)} prompts")
        
        if failed_results:
            warning(f"Failed to generate {len(failed_results)} prompts")
            summary_table("Failed Prompts", failed_results)
        
        operation_summary("Prompt Generation", len(all_results), len(successful_results))
        
        # Show usage instructions
        if successful_results:
            info("To generate summaries with Claude CLI:")
            for result in successful_results[:3]:  # Show first 3 examples
                if result["success"]:
                    info(f"  cat {result['prompt_file']} | claude")
            if len(successful_results) > 3:
                info(f"  ... and {len(successful_results) - 3} more")
        
        # Exit with error if any operations failed
        if failed_results:
            raise typer.Exit(1)
            
    except KeyboardInterrupt:
        warning("Prompt generation interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Prompt generation failed: {e}")
        raise typer.Exit(1)


