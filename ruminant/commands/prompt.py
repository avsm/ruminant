"""Prompt generation command adapted from claude-summary-prompt.py."""

import json
import typer
from typing import Optional, List

from ..config import load_config
from ..utils.dates import get_last_complete_week, get_week_list, get_week_date_range, format_week_range
from ..utils.paths import (
    get_cache_file_path, get_prompt_file_path, get_summary_file_path,
    ensure_repo_dirs, parse_repo, get_group_prompt_file_path,
    get_group_summary_file_path, ensure_group_dirs
)
from ..utils.logging import (
    success, error, warning, info, step, summary_table, operation_summary,
    print_repo_list, print_file_paths
)

def generate_prompt(repo: str, year: int, week: int, config) -> dict:
    """Generate a Claude prompt for summarizing repository activity."""
    from pathlib import Path
    import glob
    
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
        
        # Get list of available user data files
        user_data_dir = Path("data/users")
        user_files = []
        if user_data_dir.exists():
            user_files = sorted([f.stem for f in user_data_dir.glob("*.json")])
        
        # Build the detailed prompt
        base_prompt = f"""You are a software development manager responsible for analyzing GitHub repository activity.

Please analyze GitHub repository data for {repo} covering the period {week_range_str} (week {week} of {year}).

USER DATA AVAILABLE:
The data/users/ directory contains JSON files with GitHub user information. Each file is named [username].json and contains:
- Full name (if available)
- Avatar URL
- Bio
- Company
- Location
- Blog/website
- Other profile information

{len(user_files)} user profiles are available in data/users/

NOTE: If you need additional information about any PR or issue beyond what's in the JSON data, you can use the GitHub MCP server tools
(e.g., mcp__github__get_pull_request, mcp__github__get_issue) to fetch more details about specific items.

YOUR TASK:
1. Read and analyze the GitHub data from: {cache_file}
2. Generate a comprehensive markdown summary report  
3. Write this report to the file: {summary_file}

DATA SUMMARY: The JSON file contains {issues_count} issues, {prs_count} PRs, {discussions_count} discussions, and {gfi_count} good first issues.

The report should include the following sections:

1. A concise summary of the overall activity and key themes (MUST use bullet points)
2. The most important ongoing projects or initiatives based on the data (MUST use bullet points)
3. Prioritized issues and PRs that need immediate attention (MUST use bullet points)
4. Notable discussions that should be highlighted (MUST use bullet points)
5. Identify any emerging trends or patterns in development (MUST use bullet points)
6. Good first issues for new contributors (MUST use bullet points)

CRITICAL REQUIREMENTS:
- ALL sections MUST use bullet point format (starting with "-" or "*") for consistency and readability
- SKIP any section entirely if there is no meaningful content for it
- DO NOT include placeholder text like "No discussions were recorded" or "There are no XYZ to report"
- Only include sections that have actual, substantive content
- Be as concise as possible while maintaining clarity

TONE AND LANGUAGE REQUIREMENTS:
- Use factual, objective language - avoid hyperbolic terms like "major", "massive", "critical", "significant", "groundbreaking"
- Prefer specific, quantifiable descriptions: "15 PRs merged", "3 bug fixes", "2 new features", "affects 5 modules"  
- Instead of "major refactoring" → "refactoring affecting 12 files"
- Instead of "critical bug fix" → "bug fix for memory leak affecting startup"
- Instead of "massive performance improvement" → "30% performance improvement in query processing"
- Focus on concrete changes and measurable impacts

IMPORTANT: For each PR or issue you mention, ALWAYS include the contributor's GitHub username properly formatted. This is critical for recognizing contributors' work.

LINKING AND FORMATTING REQUIREMENTS:

1. USER MENTIONS:
   - When mentioning a GitHub user, check if their data exists in data/users/[username].json
   - If user data exists and contains a "name" field, format as: [Full Name](https://github.com/username)
   - If no name is available or file doesn't exist, format as: [@username](https://github.com/username)
   - Example: [Gabriel Scherer](https://github.com/gasche) or [@gasche](https://github.com/gasche)

2. ISSUE/PR REFERENCES:
   - For issues/PRs in the current repository, convert #1234 to [#1234](https://github.com/{repo}/issues/1234)
   - For cross-repository references, convert owner/repo#1234 to [owner/repo#1234](https://github.com/owner/repo/issues/1234)
   - Note: GitHub treats PRs and issues in the same namespace, so /issues/ works for both
   - Examples:
     - #5678 becomes [#5678](https://github.com/{repo}/issues/5678)
     - ocaml/dune#1234 becomes [ocaml/dune#1234](https://github.com/ocaml/dune/issues/1234)

3. GENERAL LINKING:
   - EVERY bullet point MUST include relevant PR/issue numbers as clickable links
   - For "Key Ongoing Projects", always include specific issue/PR references
   - For groups of related work, list ALL relevant PR/issue numbers, not just examples
   - Even general observations should reference specific PRs/issues that support them

FORMATTING INSTRUCTIONS:
- ALL content MUST be organized using bullet points (starting with "-" or "*")
- AVOID listing large numbers of PRs in sequence - instead, summarize them by theme with all relevant numbers
- For groups of related PRs, summarize the theme and list ALL relevant PR/issue numbers in parentheses
- Use bullet points effectively to organize information - this is MANDATORY for all sections
- EVERY bullet point must have associated PR/issue numbers for reader follow-up

Example of correct format:

- **Authentication Framework** ([#1234](https://github.com/{repo}/issues/1234), [#5678](https://github.com/{repo}/issues/5678), [#5681](https://github.com/{repo}/issues/5681)): Core authentication implementation by [John Doe](https://github.com/username) with related security improvements
- **Performance Optimization** ([#5679](https://github.com/{repo}/issues/5679), [#5680](https://github.com/{repo}/issues/5680)): Backend optimizations by [@anotheruser](https://github.com/anotheruser) including database and caching improvements
- **Bug Fixes**: Memory leak fix by [Jane Smith](https://github.com/developer) ([#5684](https://github.com/{repo}/issues/5684)), UI rendering issues resolved ([#5685](https://github.com/{repo}/issues/5685), [#5686](https://github.com/{repo}/issues/5686))
- **Documentation Updates** ([#5687](https://github.com/{repo}/issues/5687), [#5688](https://github.com/{repo}/issues/5688)): API documentation improvements and new contributor guide by [@writer](https://github.com/writer)

NOTE: Every substantive point MUST include properly formatted, clickable PR/issue links to allow readers to investigate further

REMEMBER TO:
1. Check data/users/[username].json for each mentioned user to get their full name
2. Format all issue/PR references as clickable markdown links
3. Use the correct GitHub URLs for all references"""

        # Add custom prompt if provided
        if custom_prompt:
            base_prompt += f"\n\nCUSTOM REPOSITORY-SPECIFIC INSTRUCTIONS:\n{custom_prompt}\n"

        prompt = base_prompt + f"""

ACTION REQUIRED:
1. Read the GitHub activity data from the JSON file: {cache_file}
2. Generate a JSON report with the following structure:

{{
  "week": {week},
  "year": {year},
  "repo": "{repo}",
  "week_range": "{week_range_str}",
  "brief_summary": "A single sentence (max 150 chars) summarizing the most important activity this week",
  "overall_activity": "Markdown content for overall activity summary (always include if there's any activity - MUST use bullet points - include key PR/issue numbers)",
  "ongoing_projects": "Markdown content for key ongoing projects (only include if there are identifiable projects - MUST use bullet points - MUST include all relevant issue/PR references)",
  "priority_items": "Markdown content for priority items (only include if there are items needing immediate attention - MUST use bullet points - include specific PR/issue numbers)",
  "notable_discussions": "Markdown content for notable discussions (only include if there are actual significant discussions - MUST use bullet points - include discussion numbers if available)",
  "emerging_trends": "Markdown content for emerging trends (only include if clear patterns are identifiable - MUST use bullet points - support with specific PR/issue examples)",
  "good_first_issues": "Markdown content for good first issues (only include if there are actual good first issues available - MUST use bullet points - list all issue numbers)",
  "contributors": "Markdown content for contributors (always include if there are any contributors - reference their specific contributions by PR/issue number)"
}}

IMPORTANT JSON FORMATTING RULES:
- brief_summary: A single, concise sentence (maximum 150 characters) that captures the most significant activity or theme of the week
- Each section value should contain the markdown content that would have been in that section
- ALL sections MUST use bullet points format (starting with "-" or "*") for better readability
- If a section has no meaningful content, set its value to null (not an empty string)
- The markdown content within each section should follow the same formatting rules:
  - Bullet points for organization
  - Clickable links for all PR/issue references (e.g., [#1234](https://github.com/{repo}/issues/1234))
  - Properly formatted user mentions with links (e.g., [Full Name](https://github.com/username) or [@username](https://github.com/username))
- Ensure proper JSON escaping for special characters in the markdown content
- The JSON must be valid and properly formatted

3. Write the complete JSON report to: {summary_file}
4. Return a confirmation message that the file was written successfully

Remember: 
- ALL sections MUST use bullet point format - this is mandatory for consistency
- Set section values to null if they would be empty or contain only filler text
- EVERY bullet point in the markdown content must include clickable PR/issue links for reader follow-up
- Check data/users/[username].json files to get full names for user mentions
- Format all GitHub references as proper markdown links
- Use GitHub MCP server tools if you need additional information about specific PRs/issues
- The output file MUST be written with the complete JSON summary

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


def generate_group_prompt(group_name: str, repositories: List[str], year: int, week: int, config) -> dict:
    """Generate a group-specific Claude prompt for summarizing activity across repositories in a group."""
    
    # Get week date range
    week_start, week_end = get_week_date_range(year, week)
    week_range_str = format_week_range(year, week)
    
    # Check which repositories have summaries available
    available_repos = []
    missing_repos = []
    for repo in repositories:
        summary_file = get_summary_file_path(repo, year, week)
        if summary_file.exists():
            available_repos.append(repo)
        else:
            missing_repos.append(repo)
    
    if not available_repos:
        return {
            "success": False,
            "details": f"No repository summaries found for week {week}/{year}",
            "prompt_file": None,
            "summary_file": None
        }
    
    try:
        # Get file paths
        ensure_group_dirs(group_name)
        prompt_file = get_group_prompt_file_path(group_name, year, week)
        summary_file = get_group_summary_file_path(group_name, year, week)
        
        # Get group configuration
        group_config = config.groups.get(group_name)
        if not group_config:
            return {
                "success": False,
                "details": f"Group '{group_name}' not found in configuration",
                "prompt_file": None,
                "summary_file": None
            }
        
        # Build the list of summary files
        summary_files_list = "\n".join([
            f"- {get_summary_file_path(repo, year, week)}" 
            for repo in available_repos
        ])
        
        # Build the group-specific prompt
        prompt = f"""You are a software development manager responsible for creating a high-level weekly summary for the {group_config.name} group.

GROUP CONTEXT:
- Group: {group_config.name}
- Description: {group_config.description}

Please analyze the weekly summaries for the following repositories in this group covering the period {week_range_str} (week {week} of {year}):

REPOSITORIES TO ANALYZE:
{summary_files_list}

{group_config.prompt if group_config.prompt else ""}

YOUR TASK:
1. Read and analyze ALL the repository summaries listed above using the Read tool
2. Generate a comprehensive group summary JSON that captures the week's activity across all repositories in the {group_config.name} group
3. Write this summary to the file: {summary_file}

The aggregate summary should synthesize information across all repositories to provide:
- A unified view of development activity
- Cross-repository patterns and themes
- Overall project health and progress
- Key achievements and challenges across the ecosystem

CRITICAL REQUIREMENTS:
- ALWAYS format issues/PRs as clickable links: [owner/repo#number](https://github.com/owner/repo/issues/number)
- Never use just #number alone - it's ambiguous across multiple repositories
- Repository references use [@owner/repo](https://github.com/owner/repo) format when referring to the repo itself
- ALL sections MUST use bullet point format for consistency
- Synthesize information - don't just concatenate individual summaries
- Identify cross-repository dependencies and interactions where applicable
- Check data/users/ directory for user information to create proper user links

Generate a JSON report with the following structure:

{{
  "week": {week},
  "year": {year},
  "week_range": "{week_range_str}",
  "repositories_included": {json.dumps(available_repos)},
  "short_summary": "A 1-2 sentence SPECIFIC summary mentioning actual features/fixes/changes suitable for calendar previews (max 200 chars)",
  "overall_activity": "Comprehensive markdown summary of activity across all repos (MUST use bullet points with specific PR/issue references)",
  "key_achievements": "Major accomplishments and milestones across repos (MUST use bullet points with specific PR/issue references)",
  "ongoing_initiatives": "Cross-repository projects and coordinated efforts (MUST use bullet points with specific PR/issue references)",
  "priority_items": "Critical issues and PRs needing attention across repos (MUST use bullet points with specific PR/issue references)",
  "notable_discussions": "Important discussions that affect multiple repos or the ecosystem (MUST use bullet points with discussion/issue references)",
  "emerging_patterns": "Trends and patterns observed across repositories (MUST use bullet points with example PR/issue references)",
  "ecosystem_health": "Overall assessment of the ecosystem's development health (MUST use bullet points with supporting PR/issue references)",
  "contributors_spotlight": "Notable contributors and their cross-repository contributions"
}}

FORMATTING REQUIREMENTS:
- short_summary: MUST be specific (e.g., "DWARF debugging in oxcaml, dune pkg parallelism fixes, LLVM backend progress" NOT "Active development across ecosystem")
- short_summary: Avoid hyperbolic terms like "major", "significant", "massive", "critical", "groundbreaking" - use specific feature/fix names
- short_summary: Keep under 200 characters, no markdown, suitable for calendar previews

TONE AND LANGUAGE REQUIREMENTS:
- Use factual, objective language throughout all sections
- Prefer quantifiable descriptions: "15 PRs merged", "3 repositories", "5 bug fixes", "affects 12 modules"
- Instead of "major development" → "15 commits across 5 files"
- Instead of "significant milestone" → "feature completion for 3 modules"
- Instead of "critical infrastructure work" → "infrastructure updates affecting 4 repositories"
- Focus on concrete changes, specific numbers, and measurable impacts
- Each other section should contain markdown with bullet points
- EVERY bullet point should include relevant PR/issue references where possible to help readers navigate to specifics
- Every repository reference must use [@owner/repo](https://github.com/owner/repo) format when referring to the repo itself
- Every PR/issue reference MUST be a clickable link: [owner/repo#number](https://github.com/owner/repo/issues/number)
- Include multiple PR/issue references per bullet point when describing related work
- User mentions should be formatted as [Full Name](https://github.com/username) when name is available in data/users/
- If a section has no meaningful content, set its value to null
- Ensure proper JSON escaping for special characters

SYNTHESIS GUIDELINES:
- Look for common themes across repositories (e.g., "security improvements in [@ocaml/dune](https://github.com/ocaml/dune) and [@ocaml/opam](https://github.com/ocaml/opam)")
- Identify dependencies (e.g., "[ocaml/dune#123](https://github.com/ocaml/dune/issues/123) blocked by [ocaml/ocaml#456](https://github.com/ocaml/ocaml/issues/456)")
- Highlight coordinated efforts (e.g., "LLVM backend work spans [@oxcaml/oxcaml](https://github.com/oxcaml/oxcaml) and [@ocaml/ocaml](https://github.com/ocaml/ocaml)")
- Note ecosystem-wide impacts (e.g., "Breaking changes in [@ocaml/ocaml](https://github.com/ocaml/ocaml) affecting [@ocaml/dune](https://github.com/ocaml/dune) and [@ocaml/merlin](https://github.com/ocaml/merlin)")
- When referring to issues/PRs, ALWAYS format as clickable markdown links

Remember:
- You MUST read ALL the listed summary files before generating the aggregate
- Focus on synthesis and patterns, not just listing individual repo activities
- The short_summary is essential for calendar views - be SPECIFIC about actual changes/features
- Good short_summary: "DWARF debug shapes, dune pkg Docker support, JSIR multi-file compilation, ARM64 assembler fix"
- Bad short_summary: "Active development with improvements across the OCaml ecosystem"
- All sections except short_summary MUST use bullet points
- ALL issue/PR references must be formatted as clickable markdown links
- Check data/users/ for user information to properly format contributor mentions
- Write the complete JSON summary to: {summary_file}

ACTION REQUIRED:
1. Use the Read tool to load each repository summary file
2. Analyze and synthesize the information across all repositories
3. Generate the aggregate JSON summary following the structure above
4. Write the JSON to the output file
5. Return a confirmation message"""
        
        # Add note about missing repos if any
        if missing_repos:
            prompt += f"\n\nNOTE: The following repositories do not have summaries for this week and will not be included: {', '.join(missing_repos)}"
        
        # Save prompt to file
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        return {
            "success": True,
            "details": f"Aggregate prompt generated for {len(available_repos)} repositories",
            "prompt_file": prompt_file,
            "summary_file": summary_file,
            "week_range": week_range_str,
            "repositories": available_repos,
            "missing": missing_repos
        }
        
    except Exception as e:
        error(f"Error generating aggregate prompt: {e}")
        return {
            "success": False,
            "details": str(e),
            "prompt_file": None,
            "summary_file": None
        }


def prompt_main(
    repos: Optional[List[str]] = typer.Argument(None, help="Repository names (owner/repo format)"),
    weeks: int = typer.Option(1, "--weeks", help="Number of weeks to generate prompts for"),
    year: Optional[int] = typer.Option(None, "--year", help="Year for the week"),
    week: Optional[int] = typer.Option(None, "--week", help="Week number (1-53)"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show file paths that will be used"),
    group: Optional[str] = typer.Option(None, "--group", help="Generate prompt for a specific group"),
    all_groups: bool = typer.Option(False, "--all-groups", help="Generate prompts for all configured groups"),
    skip_groups: bool = typer.Option(False, "--skip-groups", help="Skip group prompt generation"),
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
        else:
            week_list = [(target_year, target_week)]
        
        all_results = []
        
        # Handle specific group generation
        if group:
            if group not in config.groups:
                error(f"Group '{group}' not found in configuration")
                raise typer.Exit(1)
            
            group_repos = config.get_repositories_for_group(group)
            step(f"Generating prompts for group '{group}' with {len(group_repos)} repositories for {len(week_list)} week(s)")
            
            for w_year, w_week in week_list:
                info(f"Generating group prompt for '{group}' week {w_week}/{w_year}")
                result = generate_group_prompt(group, group_repos, w_year, w_week, config)
                all_results.append(result)
                
                if result["success"]:
                    success(f"Generated group prompt: {result['prompt_file']}")
                    if result.get("missing"):
                        warning(f"Missing summaries for: {', '.join(result['missing'])}")
                else:
                    error(f"Failed: {result['details']}")
        
        # Handle all groups generation
        elif all_groups:
            if not config.groups:
                error("No groups configured")
                raise typer.Exit(1)
            
            step(f"Generating prompts for {len(config.groups)} groups for {len(week_list)} week(s)")
            
            for group_name in config.groups:
                group_repos = config.get_repositories_for_group(group_name)
                for w_year, w_week in week_list:
                    info(f"Generating group prompt for '{group_name}' week {w_week}/{w_year}")
                    result = generate_group_prompt(group_name, group_repos, w_year, w_week, config)
                    all_results.append(result)
                    
                    if result["success"]:
                        success(f"Generated group prompt: {result['prompt_file']}")
                        if result.get("missing"):
                            warning(f"Missing summaries for: {', '.join(result['missing'])}")
                    else:
                        error(f"Failed: {result['details']}")
        
        # Default: generate individual repo prompts, then group prompts
        else:
            # First, generate individual repository prompts
            step(f"Generating prompts for {len(repositories_to_process)} repositories for {len(week_list)} week(s)")
            
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
                    else:
                        error(f"Failed: {result['details']}")
            
            # Then, generate group prompts (unless skipped)
            if not skip_groups and config.groups:
                step(f"Generating prompts for {len(config.groups)} groups")
                
                for group_name in config.groups:
                    group_repos = config.get_repositories_for_group(group_name)
                    for w_year, w_week in week_list:
                        info(f"Generating group prompt for '{group_name}' week {w_week}/{w_year}")
                        result = generate_group_prompt(group_name, group_repos, w_year, w_week, config)
                        all_results.append(result)
                        
                        if result["success"]:
                            success(f"Generated group prompt: {result['prompt_file']}")
                            if result.get("missing"):
                                warning(f"Missing summaries for: {', '.join(result['missing'])}")
                        else:
                            error(f"Failed: {result['details']}")
        
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


