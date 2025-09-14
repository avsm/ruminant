"""Prompt generation command adapted from claude-summary-prompt.py."""

import json
import typer
from typing import Optional, List, Dict, Any
from datetime import datetime

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


def calculate_weekly_stats(data: Dict[str, Any], week_start: datetime, week_end: datetime) -> Dict[str, Any]:
    """Calculate factual statistics from GitHub data for the specified week."""
    from dateutil.parser import parse
    
    stats = {
        'prs_merged': 0,
        'prs_opened': 0,
        'prs_closed': 0,
        'issues_opened': 0,
        'issues_closed': 0,
        'releases': 0,
        'contributors': set(),
        'new_contributors': set(),
        'tags_created': [],
        'release_names': []
    }
    
    # Analyze PRs
    for pr in data.get('prs', []):
        if pr.get('merged_at'):
            merged_date = parse(pr['merged_at'])
            if week_start <= merged_date <= week_end:
                stats['prs_merged'] += 1
                # The user field is already a string (username), not a dict
                username = pr.get('user')
                if username:
                    stats['contributors'].add(username)
        
        if pr.get('created_at'):
            created_date = parse(pr['created_at'])
            if week_start <= created_date <= week_end:
                stats['prs_opened'] += 1
                username = pr.get('user')
                if username:
                    stats['contributors'].add(username)
        
        if pr.get('closed_at') and not pr.get('merged_at'):
            closed_date = parse(pr['closed_at'])
            if week_start <= closed_date <= week_end:
                stats['prs_closed'] += 1
    
    # Analyze issues
    for issue in data.get('issues', []):
        if issue.get('created_at'):
            created_date = parse(issue['created_at'])
            if week_start <= created_date <= week_end:
                stats['issues_opened'] += 1
        
        if issue.get('closed_at'):
            closed_date = parse(issue['closed_at'])
            if week_start <= closed_date <= week_end:
                stats['issues_closed'] += 1
    
    # Look for releases in PR titles/descriptions or issues
    for pr in data.get('prs', []):
        title = pr.get('title', '').lower()
        if any(keyword in title for keyword in ['release', 'version', 'v1.', 'v2.', 'v3.', 'v4.', 'v5.']):
            if pr.get('merged_at'):
                merged_date = parse(pr['merged_at'])
                if week_start <= merged_date <= week_end:
                    stats['releases'] += 1
                    stats['release_names'].append(pr.get('title', ''))
    
    # Convert sets to counts
    stats['unique_contributors'] = len(stats['contributors'])
    stats['contributors'] = list(stats['contributors'])
    stats['new_contributors'] = list(stats['new_contributors'])
    
    return stats


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
        
        # Calculate weekly statistics for context
        week_stats = calculate_weekly_stats(original_data, week_start, week_end)
        
        # Check if git repository is available (always check now)
        owner, name = parse_repo(repo)
        git_repo_path = Path("data/git") / owner / name
        git_mirror_path = git_repo_path / ".git"
        git_available = None

        # Always check for git repo (removed skip logic)
        # Check for mirror clone first (preferred for analysis)
        if git_mirror_path.exists() and not (git_mirror_path / ".git").exists():
            git_available = (git_mirror_path, "mirror")
        elif git_repo_path.exists() and (git_repo_path / ".git").exists():
            git_available = (git_repo_path, "regular")
        
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
        
        # Build git repository section if available
        git_section = ""
        if git_available:
            git_path, git_type = git_available
            git_section = f"""
GIT REPOSITORY AVAILABLE:
A {'bare mirrored' if git_type == 'mirror' else 'regular'} git repository is available at: {git_path}
NOTE: This is a bare mirrored checkout - it contains only git metadata, not working files.

NEW FEATURES ANALYSIS:
You MUST analyze the git repository to identify new user-facing features introduced this week.

1. First, identify the default branch (usually 'main' or 'master' or 'trunk/):
   ```bash
   # Check for main or master branches:
   {'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} show-ref | grep -E "/(main|master|trunk)$" | head -1
   ```

2. Get commits for the week and find boundary commits:
   ```bash
   # Get all commits in the week range on the main branch
   {'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} log main --since="{week_start.strftime('%Y-%m-%d')}" --until="{week_end.strftime('%Y-%m-%d')} 23:59:59" --format="%H %ai %s"

   # Get the first commit of the week (oldest) - CAPTURE THIS AS start_commit
   FIRST=`{'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} rev-list --since="{week_start.strftime('%Y-%m-%d')}" --until="{week_end.strftime('%Y-%m-%d')} 23:59:59" HEAD | tail -1`

   # Get the last commit of the week (newest) - CAPTURE THIS AS end_commit
   LAST=`{'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} rev-list --since="{week_start.strftime('%Y-%m-%d')}" --until="{week_end.strftime('%Y-%m-%d')} 23:59:59" HEAD | head -1`

   # IMPORTANT: Save $FIRST and $LAST as start_commit and end_commit in your JSON output
   ```

3. Generate a comprehensive diff for the week:
   ```bash
   # Use the commit hashes to generate diff (more reliable than date references)
   # Note: Use $FIRST^ to include changes from the first commit itself
   {'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} diff --stat $FIRST^..$LAST

   # For detailed file changes
   {'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} diff $FIRST^..$LAST -- '*.md' '**/docs/*' CHANGES* README* changelog* CHANGELOG*
   ```

4. Analyze API and code changes:
   ```bash
   # Look for API changes in interface files (language-specific)
   {'git --git-dir=' + str(git_path) if git_type == 'mirror' else 'cd ' + str(git_path) + ' && git'} diff $FIRST^..$LAST -- *.mli *.ml'
   ```

5. For each significant change identified:
   - Determine if it's user-facing (affects APIs, CLIs, documentation, examples)
   - Cross-reference with the PR/issue data to find the associated PR number
   - If no PR is found, use the commit hash for direct linking
   - Pay special attention to:
     * New command-line flags or options
     * New API functions or modules
     * Breaking changes mentioned in documentation
     * New examples or tutorials added
     * Configuration changes
     * Performance improvements mentioned in commit messages

TROUBLESHOOTING GIT ANALYSIS:
- For bare repos, use --git-dir=path/.git instead of cd path
- The working directory may be the repo itself - check with pwd first
- Use HEAD instead of main/master/trunk if branch detection fails
- Include 23:59:59 in --until dates to capture full day

CRITICAL: Do NOT analyze commits from other branches, forks, or unrelated repositories. Only look at the main/master branch of this specific repository.
"""
        
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
{git_section}
NOTE: If you need additional information about any PR or issue beyond what's in the JSON data, you can use the GitHub MCP server tools
(e.g., mcp__github__get_pull_request, mcp__github__get_issue) to fetch more details about specific items.

YOUR TASK:
1. Read and analyze the GitHub data from: {cache_file}
2. If a git repository is available, analyze commits to find activity not covered by PRs
3. Generate a comprehensive markdown summary report  
4. Write this report to the file: {summary_file}

DATA SUMMARY: The JSON file contains {issues_count} issues, {prs_count} PRs, {discussions_count} discussions, and {gfi_count} good first issues.

WEEKLY ACTIVITY STATISTICS (for your context only - DO NOT include these numbers in your summary):
- PRs merged: {week_stats['prs_merged']}
- PRs opened: {week_stats['prs_opened']} 
- PRs closed (not merged): {week_stats['prs_closed']}
- Issues opened: {week_stats['issues_opened']}
- Issues closed: {week_stats['issues_closed']}
- Unique contributors: {week_stats['unique_contributors']}
- Potential releases: {week_stats['releases']}

IMPORTANT: These statistics are provided for your understanding of the week's scope. The UI will display aggregate statistics separately, so your summary should focus on SPECIFIC, INTERESTING activities rather than repeating these numbers.

The report should include the following sections:

1. NEW FEATURES - User-facing changes introduced this week (MUST use bullet points, analyze git diff, prioritize code features over documentation)
2. ACTIVITY - Combined summary of overall themes, completed work, and ongoing initiatives (MUST use bullet points, focus on what's different and incomplete beyond the new features to minimize repetition)
3. Notable discussions that should be highlighted (MUST use bullet points)
4. Identify any emerging trends or patterns in development (MUST use bullet points)
5. Good first issues for new contributors (MUST use bullet points)
6. Contributors - Factual description of who did what (code, reviews, comments, discussions) without competition or rankings

CRITICAL REQUIREMENTS:
- NEW FEATURES section is now FIRST and REQUIRED when git repository is available
- NEW FEATURES must be derived from git diff analysis, focusing on user-facing changes
- Each new feature MUST link to its PR (if found) or commit hash (format: [commit_hash](https://github.com/{repo}/commit/hash))
- Focus particularly on documentation changes, API additions, CLI changes, and example code
- ALL sections MUST use bullet point format (starting with "-" or "*") for consistency and readability
- SKIP any section entirely if there is no meaningful content for it
- DO NOT include aggregate statistics (number of PRs merged, issues opened, etc.) - the UI provides these separately
- Focus on SPECIFIC, INTERESTING activities and developments rather than summary statistics
- ABSOLUTELY DO NOT include ANY of these phrases or similar:
  * "No activity recorded"
  * "No activity"
  * "No changes"
  * "Quiet week"
  * "No updates"
  * "No discussions were recorded"
  * "There are no XYZ to report"
  * "Nothing to report"
  * "[repo name] repository during this week"
- If a section has no real activity, set its value to null in the JSON
- Only include sections that have actual, substantive content
- Be as concise as possible while maintaining clarity

TONE AND LANGUAGE REQUIREMENTS:
- Use factual, objective language - avoid hyperbolic terms like "major", "massive", "critical", "significant", "groundbreaking"
- Prefer specific, concrete descriptions over vague generalizations
- Instead of "major refactoring" → "refactoring affecting authentication and database modules"
- Instead of "critical bug fix" → "bug fix for memory leak affecting startup"
- Instead of "massive performance improvement" → "performance improvement in query processing"
- Focus on concrete changes and their specific impacts rather than aggregate counts

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

BULLET POINT STYLE REQUIREMENTS:
- DO NOT use the pattern "**Category:** description" at the start of bullet points
- Instead, integrate **bold emphasis** naturally within the text to highlight key concepts
- The bold emphasis should highlight the most important words that make the point
- Write complete, flowing sentences that incorporate bold emphasis for key terms
- Avoid formulaic structures - each bullet should read naturally

Example of correct format:

- Core **authentication framework** implementation by [John Doe](https://github.com/username) with related **security improvements** across multiple modules ([#1234](https://github.com/{repo}/issues/1234), [#5678](https://github.com/{repo}/issues/5678), [#5681](https://github.com/{repo}/issues/5681))
- Backend **performance optimizations** by [@anotheruser](https://github.com/anotheruser) including **database query caching** and connection pooling improvements ([#5679](https://github.com/{repo}/issues/5679), [#5680](https://github.com/{repo}/issues/5680))
- Fixed **memory leak** in request handler by [Jane Smith](https://github.com/developer) ([#5684](https://github.com/{repo}/issues/5684)), resolved **UI rendering issues** affecting mobile devices ([#5685](https://github.com/{repo}/issues/5685), [#5686](https://github.com/{repo}/issues/5686))
- Improved **API documentation** with usage examples and added comprehensive **contributor guide** by [@writer](https://github.com/writer) ([#5687](https://github.com/{repo}/issues/5687), [#5688](https://github.com/{repo}/issues/5688))

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
2. If a git repository is available, analyze the git diff for the week to identify new features
3. Generate a JSON report with the following structure:

{{
  "week": {week},
  "year": {year},
  "repo": "{repo}",
  "week_range": "{week_range_str}",
  "start_commit": "The SHA of the first commit in this week's range (from git analysis) - set to null if no git repo available",
  "end_commit": "The SHA of the last commit in this week's range (from git analysis) - set to null if no git repo available",
  "brief_summary": "A single sentence (max 150 chars) summarizing the most important activity this week - set to null if NO activity",
  "new_features_summary": "One sentence (max 150 chars) listing key new user-facing features - set to null if no new features",
  "new_features": "Markdown content listing new user-facing features from git diff analysis - MUST link to PR or commit - set to null if none",
  "activity_summary": "One sentence (max 150 chars) summarizing activity beyond new features - set to null if no activity exists",
  "activity": "Markdown content combining overall themes, completed work, and ongoing initiatives - focus on what's different and incomplete beyond new features - set to null if no activity exists",
  "discussions_summary": "One sentence (max 150 chars) about discussions - set to null if no notable discussions exist",
  "notable_discussions": "Markdown content for notable discussions - set to null if no discussions exist",
  "trends_summary": "One sentence (max 150 chars) describing trends - set to null if no trends are identifiable",
  "emerging_trends": "Markdown content for emerging trends - set to null if no clear trends exist",
  "issues_summary": "One sentence (max 150 chars) about good first issues - set to null if none available",
  "good_first_issues": "Markdown content for good first issues - set to null if no good first issues exist",
  "contributors_summary": "One sentence (max 150 chars) factually describing contributor activity - set to null if no contributors",
  "contributors": "Markdown content detailing who contributed what (code, reviews, comments, discussions) - NO competition/rankings - set to null if no contributors this week"
}}

IMPORTANT JSON FORMATTING RULES:
- ALL fields MUST be set to null if they have no content (not empty strings, not placeholder text)
- Summary fields (*_summary): Set to null if that section has no activity
- Content fields: Set to null if no meaningful content exists for that section
- brief_summary: Set to null if the repository had NO activity at all this week
- For each section: If no real activity exists, BOTH the summary AND content fields must be null
- ALL sections with content MUST use bullet points format (starting with "-" or "*")
- NEVER include text like "No activity recorded" or similar phrases - use null instead
- The markdown content within each section should follow the same formatting rules:
  - Bullet points for organization
  - Clickable links for all PR/issue references (e.g., [#1234](https://github.com/{repo}/issues/1234))
  - Properly formatted user mentions with links (e.g., [Full Name](https://github.com/username) or [@username](https://github.com/username))

CRITICAL JSON ESCAPING REQUIREMENTS:
- ALL Markdown text content MUST be properly escaped for valid JSON
- Do not escape backticks for pre or code content, e.g. "\\`-gdwarf-pedantic\\`" should just be "`-gdwarf-pedantic`"
- The JSON MUST be valid and parseable by standard JSON parsers like jq

NO SIZE LIMIT FOR SUMMARIES:
- There is NO character or size limit for the summary content
- Include as many bullet points as necessary to capture ALL significant activity for the week
- Do not truncate or abbreviate the summary to save space
- Every meaningful PR, issue, discussion, and contribution should be included
- The goal is comprehensive coverage of the week's activity, not brevity

4. Write the complete JSON report to: {summary_file}
5. Return a confirmation message that the file was written successfully

NEW FEATURES SECTION GUIDELINES:
- MUST analyze git diff to find user-facing changes
- PRIORITIZE features in this order:
  1. New code features, APIs, and functionality
  2. Bug fixes that affect user experience
  3. Performance improvements
  4. Documentation updates and manual improvements (list these AFTER code features)
- Each feature bullet point should follow this format:
  * Brief description of the feature [#PR](link) or [commit](link)
  * Focus on: new CLI commands/flags, new APIs, bug fixes, performance improvements
  * Example: "- New `--parallel` flag for build command improves compilation speed [#1234](https://github.com/{repo}/issues/1234)"
  * Example: "- Fixed memory leak in request handler affecting long-running processes [8a1b2c3](https://github.com/{repo}/commit/8a1b2c3)"
  * Documentation example (comes AFTER code features): "- Updated installation guide with troubleshooting section [9b2c3d4](https://github.com/{repo}/commit/9b2c3d4)"
- If analyzing from git diff without a PR, use commit hash for linking
- Group similar features together (all code features first, then documentation)

CONTRIBUTORS SECTION GUIDELINES:
- Be FACTUAL and COMPREHENSIVE - describe what each person actually did
- NEVER make it a competition or ranking (avoid "top contributor", "most active", counting PRs)
- Include ALL forms of contribution:
  * Code contributions (PRs merged, commits)
  * Code reviews and review comments
  * Issue creation and triage
  * Discussion participation
  * Documentation improvements
  * Testing and bug reports
- Format example:
  * "- [Jane Doe](https://github.com/janedoe) implemented the new authentication system ([#123](link)), reviewed database optimizations ([#124](link)), and participated in API design discussions ([#125](link))"
  * "- [@johndoe](https://github.com/johndoe) fixed critical bugs in the parser ([#126](link), [#127](link)) and provided extensive review feedback on the LLVM backend changes"
- Group by person, not by contribution type
- Focus on the substance of contributions, not metrics

Remember:
- ALL sections MUST use bullet point format - this is mandatory for consistency
- Set BOTH summary AND content fields to null for sections with no activity
- ABSOLUTELY NEVER write phrases like "No activity recorded" - use null instead
- If the entire repository had zero activity, set ALL fields to null (every single field)
- Each section is independent - if activity has no content, set both activity_summary AND activity to null
- Summary fields should be concise sentences (max 150 chars) that capture the essence of that section
- Content fields have NO size limit - include ALL relevant activity with as many bullet points as needed
- EVERY bullet point in the markdown content must include clickable PR/issue links for reader follow-up
- Check data/users/[username].json files to get full names for user mentions
- Format all GitHub references as proper markdown links
- Use GitHub MCP server tools if you need additional information about specific PRs/issues
- The output file MUST be written with the complete JSON summary

IMPORTANT: You must use the Read tool to load and analyze the data from {cache_file}

FINAL VERIFICATION STEP - ABSOLUTELY CRITICAL:

Before writing your final JSON output to the file, you MUST perform this comprehensive link verification:

1. **SCAN EVERY SECTION** of your generated content systematically:
   - new_features (PRIORITY - must link to PRs or commits)
   - activity
   - notable_discussions
   - emerging_trends
   - good_first_issues
   - contributors

2. **VERIFY COMPREHENSIVE LINKING** for each section:
   - ✓ Every PR/issue number → [#number](https://github.com/{repo}/issues/number) or [owner/repo#number](https://github.com/owner/repo/issues/number)
   - ✓ Every contributor name → Check data/users/[username].json for full name
   - ✓ Every repository mention → Properly formatted with owner/repo
   - ✓ EVERY BULLET POINT should include at least one clickable issue/PR link where possible

3. **COMMON PATTERNS TO FIX**:
   - "PR #123" or "issue #456" → MUST be [#123](https://github.com/{repo}/issues/123)
   - "merged 5 PRs" → List specific PR numbers with links if known
   - "@username" → Check user data and format as [Full Name](https://github.com/username)
   - "ocaml/dune repository" → Include link to [ocaml/dune](https://github.com/ocaml/dune)
   - "cross-repository work" → Specify which repositories with links
   - Generic statements → Find and include specific issue/PR references

4. **DOUBLE-CHECK THESE AREAS** (often missed):
   - Contributors mentioned in passing (not just main authors)
   - Repository references in cross-repository mentions
   - PR numbers mentioned in emerging_trends
   - All usernames in notable_discussions
   - Background context that references past work

5. **IF YOU FIND MISSING LINKS**:
   - STOP immediately
   - Add the proper link formatting
   - Re-scan that entire section for other missed links
   - Do NOT proceed until ALL links are added

6. **QUALITY METRICS** - Your summary should have:
   - 100% of PR/issue numbers converted to clickable links
   - 100% of contributor names checked against user data
   - 100% of repository references properly formatted
   - 90%+ of bullet points containing at least one issue/PR link
   - Zero generic statements without supporting issue/PR references

7. **ISSUE INCLUSION REQUIREMENT**:
   - EVERY bullet point should strive to include at least one relevant issue or PR link
   - If discussing a feature → Link to the tracking issue or implementation PR
   - If mentioning a bug fix → Link to the bug report and fix PR
   - If referencing discussions → Link to the discussion issue or PR comments
   - Only omit links if truly no relevant issue/PR exists (rare)

This verification is MANDATORY. A summary without comprehensive linking fails to serve its purpose
of helping readers navigate to the actual work being discussed. Every bullet point should provide
a direct path to the underlying issues and PRs. Take the time to get this right."""
        
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
    from pathlib import Path
    
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
        
        # Build git repository information if available
        git_repos_section = ""
        
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
  "new_features_summary": "One sentence (max 150 chars) listing key new user-facing features across all repos - set to null if no new features",
  "new_features": "Markdown content listing new user-facing features from all repos - prioritize code features over docs - MUST link to PR or commit - set to null if none",
  "activity_summary": "One sentence (max 150 chars) summarizing activity beyond new features - set to null if no activity exists",
  "activity": "Comprehensive markdown summary of activity combining completed work and ongoing initiatives across all repos (MUST use bullet points with specific PR/issue references)",
  "notable_discussions": "Important discussions that affect multiple repos or the ecosystem (MUST use bullet points with discussion/issue references)",
  "emerging_patterns": "Trends and patterns observed across repositories (MUST use bullet points with example PR/issue references)",
  "ecosystem_health": "Overall assessment of the ecosystem's development health (MUST use bullet points with supporting PR/issue references)",
  "contributors_spotlight": "Factual description of contributors and their activities across repositories (code, reviews, discussions) - NO competition/rankings"
}}

FORMATTING REQUIREMENTS:
- short_summary: MUST be specific (e.g., "DWARF debugging in oxcaml, dune pkg parallelism fixes, LLVM backend progress" NOT "Active development across ecosystem")
- short_summary: Avoid hyperbolic terms like "major", "significant", "massive", "critical", "groundbreaking" - use specific feature/fix names
- short_summary: Keep under 200 characters, no markdown, suitable for calendar previews
- Content fields have NO size limit - include ALL relevant activity with as many bullet points as needed
- Do not truncate or abbreviate - comprehensive coverage is the goal
- There is NO word limit for the summaries - we want to capture as much activity as we can succinctly

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

CRITICAL JSON ESCAPING REQUIREMENTS:
- ALL Markdown text content MUST be properly escaped for valid JSON
- Do not escape backticks for pre or code content, e.g. "\\`-gdwarf-pedantic\\`" should just be "`-gdwarf-pedantic`"
- The JSON MUST be valid and parseable by standard JSON parsers like jq

NEW FEATURES SECTION GUIDELINES:
- Extract new_features from each repository's summary
- PRIORITIZE features in this order:
  1. New code features, APIs, and functionality
  2. Bug fixes that affect user experience
  3. Performance improvements
  4. Documentation updates and manual improvements (list these AFTER code features)
- Format as: "- [Repository] Feature description [#PR](link) or [commit](link)"
- Example: "- [@ocaml/dune](https://github.com/ocaml/dune) Added `--parallel` flag for build command [#1234](https://github.com/ocaml/dune/issues/1234)"
- Group similar features together (all code features first, then documentation)
- Include repository name prefix for clarity

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
- ALL issue/PR references must be formatted as clickable markdown links - Check data/users/ for user information to properly format contributor mentions
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


