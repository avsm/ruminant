#!/usr/bin/env python3
# /// script
# dependencies = [
#     "pytz",
# ]
# ///
"""
Generate Claude prompts for weekly GitHub activity summaries.
This script reads cached GitHub data and generates prompts for summarization.
"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta
import pytz


# Cache and report directories
CACHE_DIR = ".cache"
CLAUDE_CACHE_DIR = ".claude-cache"
CLAUDE_REPORT_DIR = ".claude-report"


def get_cache_file_path(repo, year, week):
    """Get the cache file path for a specific repo and week."""
    owner, name = repo.split("/")
    cache_dir = os.path.join(CACHE_DIR, owner, name)
    return os.path.join(cache_dir, f"week-{week:02d}-{year}.json")


def get_week_date_range(year, week):
    """Get the start and end dates for a given year and week number (ISO 8601)."""
    # Get the first day of the year
    jan_4 = datetime(year, 1, 4, tzinfo=pytz.utc)
    # Find the start of week 1 (Monday)
    week_1_start = jan_4 - timedelta(days=jan_4.weekday())
    # Calculate the start of the requested week
    week_start = week_1_start + timedelta(weeks=week - 1)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return week_start, week_end


def get_last_complete_week():
    """Get the year and week number of the last complete week."""
    now = datetime.now()
    last_week = now - timedelta(days=7)
    return last_week.isocalendar()[0], last_week.isocalendar()[1]


def load_custom_prompt(repo):
    """Load custom prompt for a specific repository from prompts/<user>/<repo>.txt."""
    try:
        owner, name = repo.split("/")
        prompt_file = os.path.join("prompts", owner, f"{name}.txt")
        
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                custom_prompt = f.read().strip()
                if custom_prompt:
                    # Add cache directory information to custom prompt
                    cache_info = f"\n\nNOTE: Cached GitHub data files are stored in these subdirectories:\n"
                    cache_info += f"- Original cache: {CACHE_DIR}/{owner}/{name}/\n"
                    cache_info += f"- Claude-optimized cache: {CLAUDE_CACHE_DIR}/{owner}/{name}/"
                    custom_prompt += cache_info
                    print(f"✓ Loaded custom prompt for {repo} from {prompt_file}")
                    return custom_prompt
        
        return None
    except Exception as e:
        print(f"Warning: Error loading custom prompt for {repo}: {e}")
        return None


def truncate_text(text, max_length=250):
    """Truncate text to max_length characters, adding ellipsis if truncated."""
    if not text or len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."


def create_claude_optimized_json(original_json_path, repo, year, week):
    """Create a Claude-optimized version of the JSON with truncated comment bodies."""
    
    # Create claude cache directory structure
    owner, name = repo.split("/")
    claude_cache_dir = os.path.join(CLAUDE_CACHE_DIR, owner, name)
    os.makedirs(claude_cache_dir, exist_ok=True)
    
    claude_json_path = os.path.join(claude_cache_dir, f"week-{week:02d}-{year}.json")
    
    # Check if claude-optimized version already exists and is newer
    if (os.path.exists(claude_json_path) and 
        os.path.exists(original_json_path) and
        os.path.getmtime(claude_json_path) > os.path.getmtime(original_json_path)):
        print(f"✓ Using existing Claude-optimized JSON: {claude_json_path}")
        return claude_json_path
    
    # Load original JSON
    try:
        with open(original_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading original JSON {original_json_path}: {e}")
        return None
    
    print(f"Creating Claude-optimized JSON from {original_json_path}...")
    
    def truncate_comment_bodies(items):
        """Truncate comment bodies in a list of issues/PRs."""
        truncated_items = []
        for item in items:
            item_copy = item.copy()
            # Truncate main body
            if 'body' in item_copy:
                item_copy['body'] = truncate_text(item_copy['body'], 150)
            
            # Truncate comments (now just strings)
            if 'comments' in item_copy and isinstance(item_copy['comments'], list):
                truncated_comments = []
                for comment in item_copy['comments']:
                    if isinstance(comment, str):
                        # Comments are now in format "@author: body"
                        truncated_comments.append(truncate_text(comment, 200))
                item_copy['comments'] = truncated_comments
            
            truncated_items.append(item_copy)
        return truncated_items
    
    # Create optimized copy
    optimized_data = data.copy()
    
    # Truncate comment bodies in all sections
    optimized_data['issues'] = truncate_comment_bodies(optimized_data.get('issues', []))
    optimized_data['prs'] = truncate_comment_bodies(optimized_data.get('prs', []))
    optimized_data['good_first_issues'] = truncate_comment_bodies(optimized_data.get('good_first_issues', []))
    
    # Discussions usually have shorter bodies, but truncate anyway
    truncated_discussions = []
    for discussion in optimized_data.get('discussions', []):
        discussion_copy = discussion.copy()
        if 'body' in discussion_copy:
            discussion_copy['body'] = truncate_text(discussion_copy['body'], 150)
        truncated_discussions.append(discussion_copy)
    optimized_data['discussions'] = truncated_discussions
    
    # Save optimized version
    try:
        with open(claude_json_path, 'w', encoding='utf-8') as f:
            json.dump(optimized_data, f, ensure_ascii=False, indent=2)
        
        # Calculate size reduction
        orig_size = os.path.getsize(original_json_path)
        new_size = os.path.getsize(claude_json_path)
        reduction = ((orig_size - new_size) / orig_size) * 100
        
        print(f"✓ Created Claude-optimized JSON: {claude_json_path}")
        print(f"  Size reduction: {orig_size:,} → {new_size:,} bytes ({reduction:.1f}% smaller)")
        
        return claude_json_path
        
    except Exception as e:
        print(f"Error creating Claude-optimized JSON: {e}")
        return None


def generate_prompt(repo, year, week, output_file=None, json_path=None, save_prompt=True):
    """Generate a Claude prompt for summarizing repository activity."""
    
    # Get week date range
    week_start, week_end = get_week_date_range(year, week)
    week_start_str = week_start.strftime('%Y-%m-%d')
    week_end_str = week_end.strftime('%Y-%m-%d')
    
    # Check if cached data exists
    cache_file = get_cache_file_path(repo, year, week)
    if not os.path.exists(cache_file):
        print(f"Error: No cached data found for {repo} week {week} of {year}")
        print(f"Expected cache file: {cache_file}")
        print(f"Run 'python gh-fetch.py {repo} --year {year} --week {week}' to fetch the data first.")
        return None
    
    # Create Claude-optimized JSON
    claude_json_path = create_claude_optimized_json(cache_file, repo, year, week)
    if not claude_json_path:
        print(f"Error: Failed to create Claude-optimized JSON for {repo} week {week} of {year}")
        return None
    
    # Use the JSON path provided or the optimized one
    if json_path:
        json_to_use = json_path
        json_filename = os.path.basename(json_path)
    else:
        json_to_use = claude_json_path
        json_filename = os.path.basename(claude_json_path)
    
    # Default output filename if not specified
    if not output_file:
        # Create report directory structure mirroring cache structure
        owner, name = repo.split("/")
        report_dir = os.path.join(CLAUDE_REPORT_DIR, owner, name)
        os.makedirs(report_dir, exist_ok=True)
        
        # Use week number as filename (e.g., 35.md)
        output_file = os.path.join(report_dir, f"{week}.md")
    
    # Generate prompt filename in the report directory
    owner, name = repo.split("/")
    report_dir = os.path.join(CLAUDE_REPORT_DIR, owner, name)
    os.makedirs(report_dir, exist_ok=True)
    prompt_file = os.path.join(report_dir, f"{week}-prompt.txt")
    
    # Load custom prompt for this repository
    custom_prompt = load_custom_prompt(repo)
    
    # Build the detailed prompt
    owner, name = repo.split("/")
    claude_cache_location = os.path.join(CLAUDE_CACHE_DIR, owner, name)
    
    base_prompt = f"""
You are a software development manager responsible for analyzing GitHub repository activity.

I will provide you with JSON data from the file '{json_filename}' containing pull requests, issues, and discussions from
the repository {repo} for the period {week_start_str} to {week_end_str} (week {week} of {year}).

NOTE: If you need additional information about any PR or issue beyond what's in the JSON file, you can use the GitHub MCP server tools
(e.g., mcp__github__get_pull_request, mcp__github__get_issue) to fetch more details about specific items.

YOUR TASK:
1. Read and analyze the JSON file '{json_filename}' in the subdirectory: {claude_cache_location}/
2. Generate a comprehensive markdown summary report
3. Write this report to the file: {output_file}

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

NOTE: Every substantive point MUST include PR/issue numbers to allow readers to investigate further
"""

    # Add custom prompt if provided
    if custom_prompt:
        base_prompt += f"\n\nCUSTOM REPOSITORY-SPECIFIC INSTRUCTIONS:\n{custom_prompt}\n"

    prompt = base_prompt + f"""

ACTION REQUIRED:
1. Read the JSON file '{json_filename}' from the subdirectory: {claude_cache_location}/
2. Analyze the repository activity data
3. Generate a markdown report with the following structure:

# {week_start_str} to {week_end_str} - {repo} Activity Summary

Then include only the sections that have meaningful content, with PR/issue numbers for every bullet point:
- ## Overall Activity Summary (always include if there's any activity - include key PR/issue numbers)
- ## Key Ongoing Projects (only if there are identifiable projects - MUST include all relevant issue/PR references)
- ## Priority Items (only if there are items needing immediate attention - include specific PR/issue numbers)
- ## Notable Discussions (only if there are actual significant discussions - include discussion numbers if available)
- ## Emerging Trends (only if clear patterns are identifiable - support with specific PR/issue examples)
- ## Good First Issues (only if there are actual good first issues available - list all issue numbers)
- ## Contributors (always include if there are any contributors - reference their specific contributions by PR/issue number)

4. Write the complete markdown report to: {output_file}
5. Return a confirmation message that the file was written successfully

Remember: 
- Skip sections entirely if they would be empty or contain only filler text
- EVERY bullet point must include relevant PR/issue numbers for reader follow-up
- Use GitHub MCP server tools if you need additional information about specific PRs/issues
The output file MUST be written with the complete markdown summary.

IMPORTANT FILE LOCATIONS:
- JSON file full path: {json_to_use}
- Output file path: {output_file}
- Cache directory: {claude_cache_location}/
"""

    # Save prompt to file if requested
    if save_prompt:
        try:
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"✓ Prompt saved to: {prompt_file}")
        except Exception as e:
            print(f"Warning: Error saving prompt to file {prompt_file}: {e}")
            prompt_file = None

    return {
        'prompt': prompt,
        'prompt_file': prompt_file,
        'json_path': json_to_use,
        'output_file': output_file,
        'repo': repo,
        'year': year,
        'week': week,
        'week_start': week_start_str,
        'week_end': week_end_str
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate Claude prompts for weekly GitHub activity summaries.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate prompt and save to file (default behavior)
  python claude-summary-prompt.py owner/repo
  # Creates: owner-repo-week-XX-YYYY-prompt.txt
  
  # Specific week
  python claude-summary-prompt.py owner/repo --year 2025 --week 30
  
  # Custom output and prompt files
  python claude-summary-prompt.py owner/repo --output my-summary.md --prompt-file my-prompt.txt
  
  # Print prompt to stdout instead of saving
  python claude-summary-prompt.py owner/repo --no-save-prompt
  
  # Quiet mode (minimal output)
  python claude-summary-prompt.py owner/repo --quiet
  
  # Use with Claude CLI
  cat owner-repo-week-45-2024-prompt.txt | claude
  
Note: This script requires that the data has already been fetched using gh-fetch.py or weekly.py
        """
    )
    parser.add_argument(
        "repo", 
        help="GitHub repository in format owner/repo"
    )
    
    # Week-based arguments
    parser.add_argument(
        "--year", type=int, help="Year for the week (defaults to current year for last complete week)"
    )
    parser.add_argument(
        "--week", type=int, help="Week number (1-53, defaults to last complete week)"
    )
    
    # Output options
    parser.add_argument(
        "--output", help="Output file path for the summary (default: repo-week-XX-YYYY.md)"
    )
    parser.add_argument(
        "--prompt-file", help="Custom filename for the prompt (default: repo-week-XX-YYYY-prompt.txt)"
    )
    parser.add_argument(
        "--no-save-prompt", action="store_true", help="Don't save the prompt to a file (just print to stdout)"
    )
    parser.add_argument(
        "--json-path", help="Path to specific JSON file to use (default: uses cached data)"
    )
    parser.add_argument(
        "--show-paths", action="store_true", help="Show the paths that will be used"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Minimal output - only show essential information"
    )

    args = parser.parse_args()

    # Determine time range
    if args.year and args.week:
        year, week = args.year, args.week
    else:
        # Use last complete week as default
        year, week = get_last_complete_week()

    # Generate the prompt
    save_prompt = not args.no_save_prompt
    result = generate_prompt(args.repo, year, week, args.output, args.json_path, save_prompt)
    
    if not result:
        sys.exit(1)
    
    # Override prompt file name if specified
    if args.prompt_file and save_prompt:
        # Re-save with custom filename
        try:
            with open(args.prompt_file, 'w', encoding='utf-8') as f:
                f.write(result['prompt'])
            print(f"✓ Prompt saved to: {args.prompt_file}")
            result['prompt_file'] = args.prompt_file
        except Exception as e:
            print(f"Error saving prompt to custom file {args.prompt_file}: {e}")
    
    # Show paths if requested
    if args.show_paths:
        print(f"\n=== Paths ===")
        print(f"Repository: {result['repo']}")
        print(f"Week: {result['week']} of {result['year']} ({result['week_start']} to {result['week_end']})")
        print(f"JSON file: {result['json_path']}")
        print(f"Output file: {result['output_file']}")
        if result.get('prompt_file'):
            print(f"Prompt file: {result['prompt_file']}")
        print()
    
    # Print the prompt to stdout only if not saving to file or explicitly requested
    if args.no_save_prompt and not args.quiet:
        print(result['prompt'])
    
    if not args.quiet:
        print(f"\n=== Summary ===")
        print(f"Repository: {result['repo']}")
        print(f"Week: {result['week']} of {result['year']} ({result['week_start']} to {result['week_end']})")
        print(f"JSON data: {result['json_path']}")
        print(f"Output will be written to: {result['output_file']}")
        if result.get('prompt_file'):
            print(f"Prompt saved to: {result['prompt_file']}")
            print(f"\nTo use this prompt with Claude CLI:")
            print(f"  cat {result['prompt_file']} | claude")
        else:
            print(f"\nTo use this prompt with Claude CLI:")
            print(f"  python claude-summary-prompt.py {args.repo} --year {year} --week {week} --no-save-prompt | claude")


if __name__ == "__main__":
    main()