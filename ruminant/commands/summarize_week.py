"""Generate comprehensive weekly summaries across all groups with release tracking."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import subprocess
import concurrent.futures
import typer

from ..config import load_config
from ..utils.dates import get_week_date_range, get_last_complete_week, get_week_list
from ..utils.paths import get_data_dir
from ..utils.logging import console, success, error, warning, info, step


def collect_releases_for_week(year: int, week: int) -> List[Dict]:
    """Collect all releases from all repositories for a specific week."""
    data_dir = get_data_dir()
    gh_dir = data_dir / "gh"
    all_releases = []
    
    if not gh_dir.exists():
        return []
    
    # Scan all repository directories
    for repo_dir in gh_dir.iterdir():
        if repo_dir.is_dir():
            for owner_dir in repo_dir.iterdir():
                if owner_dir.is_dir():
                    # Look for the week file
                    week_file = owner_dir / f"week-{week}-{year}.json"
                    if week_file.exists():
                        try:
                            with open(week_file, 'r') as f:
                                data = json.load(f)
                                releases = data.get('releases', [])
                                # Add repository context to each release
                                for release in releases:
                                    release['repository'] = f"{repo_dir.name}/{owner_dir.name}"
                                all_releases.extend(releases)
                        except Exception as e:
                            warning(f"Error reading {week_file}: {e}")
    
    # Sort releases by date
    all_releases.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    return all_releases


def collect_group_summaries_for_week(year: int, week: int) -> Dict[str, Dict]:
    """Collect all group summaries for a specific week."""
    data_dir = get_data_dir()
    groups_dir = data_dir / "groups"
    summaries = {}
    
    if not groups_dir.exists():
        return {}
    
    for group_dir in groups_dir.iterdir():
        if group_dir.is_dir():
            week_file = group_dir / f"week-{week}-{year}.json"
            if week_file.exists():
                try:
                    with open(week_file, 'r') as f:
                        summaries[group_dir.name] = json.load(f)
                except Exception as e:
                    warning(f"Error reading {week_file}: {e}")
    
    return summaries


def generate_week_summary_prompt(
    year: int,
    week: int,
    current_week_data: Dict,
    previous_weeks_data: List[Dict],
    config: Any
) -> str:
    """Generate a prompt for summarizing the entire week across all projects."""
    
    week_start, week_end = get_week_date_range(year, week)
    data_dir = get_data_dir()
    output_file = get_week_summary_path(year, week)
    
    prompt = f"""You are analyzing GitHub activity data for the week of {week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')} (Week {week}, {year}).

## OUTPUT LOCATION

Please write your weekly summary directly to this file as JSON:
**Output File**: `{output_file.relative_to(data_dir.parent)}`

This summary should provide a high-level overview of ALL activity across the entire ecosystem for this week.

## CURRENT WEEK DATA LOCATIONS

### Release Data
"""
    
    # Reference release data locations
    releases = current_week_data.get('releases', [])
    if releases:
        prompt += f"\n{len(releases)} releases were published this week. Release data can be found in:\n\n"
        
        # Group releases by repository
        releases_by_repo = {}
        for release in releases:
            repo = release.get('repository', 'unknown')
            if repo not in releases_by_repo:
                releases_by_repo[repo] = []
            releases_by_repo[repo].append(release)
        
        for repo, repo_releases in releases_by_repo.items():
            owner, name = repo.split('/') if '/' in repo else ('unknown', repo)
            cache_file = f"data/gh/{owner}/{name}/week-{week}-{year}.json"
            prompt += f"- **{repo}**: {len(repo_releases)} release(s)\n"
            prompt += f"  File: `{cache_file}`\n"
            prompt += f"  JSON key: `releases`\n"
            prompt += f"  Tags: {', '.join(r.get('tag_name', 'unknown') for r in repo_releases)}\n\n"
    else:
        prompt += "\nNo releases were published this week.\n\n"
    
    # Reference group summary locations
    prompt += "### Group Summary Locations\n\n"
    prompt += "Group summaries with detailed activity reports are available at:\n\n"
    
    for group_name in current_week_data.get('group_summaries', {}).keys():
        summary_file = f"data/groups/{group_name}/week-{week}-{year}.json"
        prompt += f"- **{group_name.upper()}**: `{summary_file}`\n"
        prompt += f"  Keys: `brief_summary`, `group_overview`, `key_projects`, `priority_items`, `notable_discussions`, `emerging_trends`\n\n"
    
    # Add context from previous weeks (display in chronological order, oldest first)
    if previous_weeks_data:
        prompt += "\n## PREVIOUS WEEKS DATA LOCATIONS\n\n"
        prompt += "For context and trend analysis, reference data from previous weeks (oldest to newest):\n\n"
        
        # Sort by week in ascending order (oldest first)
        sorted_prev_data = sorted(previous_weeks_data, key=lambda x: (x['year'], x['week']))
        
        for prev_data in sorted_prev_data:
            prev_year = prev_data['year']
            prev_week = prev_data['week']
            prev_releases = prev_data.get('releases', [])
            prev_week_summary = prev_data.get('week_summary')
            
            prompt += f"### Week {prev_week}, {prev_year}\n\n"
            
            # Reference previous week summary if it exists
            prev_summary_path = get_week_summary_path(prev_year, prev_week)
            if prev_summary_path.exists():
                prompt += f"- **Weekly Summary**: `{prev_summary_path.relative_to(data_dir.parent)}`\n"
            elif prev_week_summary:  # Backward compatibility with old location
                week_summary_file = f"data/week-summaries/week-{prev_week}-{prev_year}.json"
                prompt += f"- **Weekly Summary (legacy)**: `{week_summary_file}` (key: `summary`)\n"
            
            # Reference release data if any
            if prev_releases:
                prompt += f"- **Releases** ({len(prev_releases)} total):\n"
                
                # Group by repository for file references
                prev_releases_by_repo = {}
                for release in prev_releases:
                    repo = release.get('repository', 'unknown')
                    if repo not in prev_releases_by_repo:
                        prev_releases_by_repo[repo] = 0
                    prev_releases_by_repo[repo] += 1
                
                for repo, count in list(prev_releases_by_repo.items())[:3]:  # Show first 3
                    owner, name = repo.split('/') if '/' in repo else ('unknown', repo)
                    prompt += f"  - {repo} ({count}): `data/gh/{owner}/{name}/week-{prev_week}-{prev_year}.json`\n"
                
                if len(prev_releases_by_repo) > 3:
                    prompt += f"  - ... and {len(prev_releases_by_repo) - 3} more repositories\n"
            
            # Reference group summaries
            if prev_data.get('group_summaries'):
                prompt += f"- **Group Summaries**:\n"
                for group_name in prev_data['group_summaries'].keys():
                    prompt += f"  - {group_name}: `data/groups/{group_name}/week-{prev_week}-{prev_year}.json`\n"
            
            prompt += "\n"
    
    # Instructions for the summary
    prompt += """
## YOUR TASK

Please analyze the data files referenced above to generate a comprehensive weekly summary.

**IMPORTANT**: The file paths above point to JSON files containing the actual data. You should:
1. Look up and read the referenced JSON files to get the complete information
2. For releases, check the `releases` key in the gh/ repository cache files
3. For group summaries, read the full content from the groups/ weekly files
4. For previous week context, reference the weekly summary files where available

**CRITICAL: OUTPUT ONLY VALID JSON - NO OTHER TEXT**

You must output ONLY the JSON object below. Do not include any other text, explanations, or markdown formatting outside the JSON.

Generate a JSON file with the following structure (matching the group summary format):

```json
{
  "week": """ + str(week) + """,
  "year": """ + str(year) + """,
  "week_range": \"""" + f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}" + """\",
  "brief_summary": "A single sentence (max 150 chars) summarizing the most important activity this week",
  "group_overview": "Markdown text providing a high-level overview of all group activities with bullet points highlighting major themes and developments across core, tools, ecosystem, and oxcaml groups",
  "cross_repository_work": "Markdown text describing coordination and shared work across multiple repositories, highlighting cross-cutting themes and collaboration patterns",
  "key_projects": "Markdown text listing the most significant individual projects and initiatives with specific contributors, PR/issue numbers, and progress details",
  "priority_items": "Markdown text highlighting critical issues, urgent fixes, and high-priority items that require immediate attention or resolution",
  "notable_discussions": "Markdown text describing important technical discussions, design debates, or community conversations that shaped the week's direction",
  "emerging_trends": "Markdown text identifying patterns, themes, and trends that are emerging across the ecosystem, including technology adoption, architectural shifts, or community focus areas"
}
```

**IMPORTANT**: 
- Output ONLY the JSON object
- Do not include any other text before or after the JSON
- Do not include markdown code block markers (```)
- The JSON must be valid and parseable

NOTE: Build upon the context from previous weeks by reading the referenced files. Reference trends, 
continuing work, and completed items that were in progress in earlier weeks. This creates a 
narrative thread connecting the weekly summaries.

IMPORTANT FORMATTING REQUIREMENTS:
- Use the special syntax __RUMINANT:groupname__ to link to specific group weekly notes
  Example: "The core team made significant progress on multicore improvements __RUMINANT:core__"
- This allows readers to navigate directly to detailed group summaries
- Use these links whenever referencing specific group activities
- Keep the summary concise but comprehensive (aim for 500-800 words)
- Use bullet points for clarity on each of the items like cross repository work, key projects, priority items, notable discussions and emerging trends
- Highlight specific people's contributions where notable
- Include specific PR/issue numbers for major items

LINKING AND FORMATTING REQUIREMENTS:

1. USER MENTIONS:
   - When mentioning a GitHub user, check if their data exists in data/users/[username].json
   - If user data exists and contains a "name" field, format as: [Full Name](https://github.com/username)
   - If no name is available or file doesn't exist, format as: [@username](https://github.com/username)

2. ISSUE/PR REFERENCES:
   - Always use full format: owner/repo#number
   - Convert to: [owner/repo#number](https://github.com/owner/repo/issues/number)
   - Example: ocaml/ocaml#5678 becomes [ocaml/ocaml#5678](https://github.com/ocaml/ocaml/issues/5678)

3. CROSS-REPOSITORY CONNECTIONS:
   - Pay special attention to work that spans multiple repositories
   - Look for related PRs, shared dependencies, or coordinated releases
   - Highlight any blocking dependencies between repositories

CRITICAL: 
- EVERY bullet point in the markdown content must include clickable PR/issue links for reader follow-up
- Use full owner/repo#number format for all issue/PR references
- Format all GitHub references as proper markdown links

TONE AND LANGUAGE REQUIREMENTS:
- Use factual, objective language - avoid subjective or hyperbolic terms
- AVOID words like: dominating, strong, concentrated, exceptional, significant, massive, critical, urgent
- INSTEAD use specific metrics and neutral descriptions:
  * "37 PRs merged" instead of "strong activity"
  * "addressed 15 issues" instead of "dominated the week"
  * "3 maintainers collaborated on" instead of "concentrated effort"
- Focus on quantifiable data: number of PRs, issues, contributors, lines changed
- Let the links and specific references speak for themselves
- Describe what happened, not how impressive or important it was
- When describing priorities, reference the specific issues rather than characterizing urgency

The summary should be suitable for:
- Developers wanting a quick overview of ecosystem activity
- Project maintainers tracking cross-project developments  
- Community members interested in the project's direction
"""
    
    return prompt


def get_week_summary_path(year: int, week: int) -> Path:
    """Get the path where the week summary should be saved."""
    data_dir = get_data_dir()
    summaries_dir = data_dir / "summaries" / "weekly"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    return summaries_dir / f"week-{week}-{year}.json"


def save_week_summary_metadata(year: int, week: int) -> Path:
    """Save metadata about the week summary generation."""
    data_dir = get_data_dir()
    metadata_dir = data_dir / "summaries" / "weekly" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    week_start, week_end = get_week_date_range(year, week)
    
    metadata = {
        "year": year,
        "week": week,
        "week_range": f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}",
        "generated_at": datetime.now().isoformat(),
        "summary_file": str(get_week_summary_path(year, week))
    }
    
    output_file = metadata_dir / f"week-{week}-{year}.json"
    with open(output_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    return output_file


def summarize_week_main(
    year: Optional[int] = None,
    week: Optional[int] = None,
    claude_args: Optional[str] = None,
    dry_run: bool = False,
    prompt_only: bool = False,
    lookback_weeks: int = 3
) -> None:
    """Generate a comprehensive weekly summary across all groups."""
    
    try:
        config = load_config()
        
        # Determine target week
        if year and week:
            target_year, target_week = year, week
        else:
            target_year, target_week = get_last_complete_week()
        
        info(f"Generating weekly summary for Week {target_week}, {target_year}")
        
        # Collect current week data
        step("Collecting current week data...")
        current_releases = collect_releases_for_week(target_year, target_week)
        current_summaries = collect_group_summaries_for_week(target_year, target_week)
        
        if not current_summaries:
            error("No group summaries found for the current week. Run 'ruminant group' first.")
            raise typer.Exit(1)
        
        current_week_data = {
            'year': target_year,
            'week': target_week,
            'releases': current_releases,
            'group_summaries': current_summaries
        }
        
        info(f"Found {len(current_releases)} releases and {len(current_summaries)} group summaries")
        
        # Collect previous weeks data for context (in reverse chronological order for display)
        step(f"Collecting previous {lookback_weeks} weeks for context...")
        previous_weeks_data = []
        
        for i in range(1, lookback_weeks + 1):
            # Calculate previous week
            prev_date = datetime.strptime(f"{target_year}-W{target_week:02d}-1", "%Y-W%W-%w") - timedelta(weeks=i)
            prev_year = prev_date.year
            prev_week = prev_date.isocalendar()[1]
            
            prev_releases = collect_releases_for_week(prev_year, prev_week)
            prev_summaries = collect_group_summaries_for_week(prev_year, prev_week)
            
            # Check for existing week summaries to include in context
            week_summary = None
            
            # Check new location first
            new_summary_path = get_week_summary_path(prev_year, prev_week)
            if new_summary_path.exists():
                try:
                    with open(new_summary_path, 'r') as f:
                        week_summary = f.read()
                except:
                    pass
            else:
                # Check legacy location
                week_summary_file = get_data_dir() / "week-summaries" / f"week-{prev_week}-{prev_year}.json"
                if week_summary_file.exists():
                    try:
                        with open(week_summary_file, 'r') as f:
                            week_summary_data = json.load(f)
                            week_summary = week_summary_data.get('summary')
                    except:
                        pass
            
            if prev_summaries or week_summary:  # Include if we have any data
                previous_weeks_data.append({
                    'year': prev_year,
                    'week': prev_week,
                    'releases': prev_releases,
                    'group_summaries': prev_summaries,
                    'week_summary': week_summary
                })
        
        info(f"Collected data from {len(previous_weeks_data)} previous weeks")
        
        # Generate prompt
        step("Generating summary prompt...")
        prompt = generate_week_summary_prompt(
            target_year,
            target_week,
            current_week_data,
            previous_weeks_data,
            config
        )
        
        # Save prompt for inspection
        prompt_dir = get_data_dir() / "prompts" / "week-summaries"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = prompt_dir / f"week-{target_week}-{target_year}.md"
        
        with open(prompt_file, 'w') as f:
            f.write(prompt)
        
        info(f"Prompt saved to {prompt_file}")
        
        if prompt_only:
            success("Prompt generated successfully (--prompt-only mode)")
            console.print(f"\nPrompt saved to: {prompt_file}")
            return
        
        if dry_run:
            success("Dry run complete. Prompt generated but not sent to Claude.")
            console.print(f"\nPrompt saved to: {prompt_file}")
            return
        
        # Prepare output file and get date range
        output_file = get_week_summary_path(target_year, target_week)
        week_start, week_end = get_week_date_range(target_year, target_week)
        
        # Call Claude CLI
        step("Calling Claude CLI to generate summary...")
        step(f"Output will be written to: {output_file}")
        
        claude_command = config.claude.command
        claude_base_args = config.claude.args.copy() if config.claude.args else []
        
        # Add custom args if provided
        if claude_args:
            claude_base_args.extend(claude_args.split())
        
        # Build command
        cmd = [claude_command] + claude_base_args
        
        info(f"Running command: {' '.join(cmd)}")
        info(f"Prompt length: {len(prompt)} characters")
        
        try:
            # Run Claude CLI - it should write directly to the output file
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minute timeout
            )
            
            # Check if Claude created the output file successfully
            if not output_file.exists():
                error("Claude did not create the expected output file")
                error(f"Return code: {result.returncode}")
                error(f"Stderr: {result.stderr}")
                error(f"Stdout: {result.stdout}")
                raise typer.Exit(1)
            
            # Read and validate the generated file
            try:
                with open(output_file, 'r') as f:
                    file_content = f.read().strip()
                
                if not file_content:
                    error("Output file is empty")
                    raise typer.Exit(1)
                
                # Try to parse as JSON to validate structure
                try:
                    summary_data = json.loads(file_content)
                    
                    # Validate that it has the expected structure
                    expected_fields = ['brief_summary', 'group_overview', 'cross_repository_work', 
                                     'key_projects', 'priority_items', 'notable_discussions', 'emerging_trends']
                    missing_fields = [field for field in expected_fields if field not in summary_data]
                    
                    if missing_fields:
                        warning(f"JSON is missing expected fields: {missing_fields}")
                        # Continue anyway, but log the issue
                    
                    # Ensure required metadata fields are present
                    updated = False
                    if 'week' not in summary_data:
                        summary_data['week'] = target_week
                        updated = True
                    if 'year' not in summary_data:
                        summary_data['year'] = target_year
                        updated = True
                    if 'week_range' not in summary_data:
                        summary_data['week_range'] = f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"
                        updated = True
                    
                    # Always add generated_at timestamp
                    summary_data['generated_at'] = datetime.now().isoformat()
                    updated = True
                    
                    # Rewrite file if we added metadata
                    if updated:
                        with open(output_file, 'w') as f:
                            json.dump(summary_data, f, indent=2)
                        
                    success(f"Weekly summary generated and validated successfully")
                    
                except json.JSONDecodeError as e:
                    # If not valid JSON, preserve the original output and error out
                    error(f"Output file contains invalid JSON: {e}")
                    error(f"First 200 chars of output: {file_content[:200]}...")
                    
                    # Check if this looks like a conversational response
                    if (file_content.startswith('✅') or 
                        'Weekly summary' in file_content[:100] or 
                        'I have' in file_content[:50] or
                        'The summary' in file_content[:50]):
                        error("Claude returned a conversational response instead of JSON structure")
                    
                    error(f"Invalid JSON output preserved in: {output_file}")
                    error("Please review the file contents and regenerate if needed")
                    raise typer.Exit(1)
                    
            except Exception as e:
                error(f"Failed to read or process output file: {e}")
                raise typer.Exit(1)
            
            success(f"Weekly summary saved to {output_file}")
            
            # Save metadata
            metadata_file = save_week_summary_metadata(target_year, target_week)
            info(f"Metadata saved to {metadata_file}")
            
        except subprocess.CalledProcessError as e:
            error(f"Claude CLI failed: {e}")
            if e.stderr:
                error(f"Error output: {e.stderr}")
            raise typer.Exit(1)
        
    except KeyboardInterrupt:
        warning("Summary generation interrupted by user")
        raise typer.Exit(1)
    except Exception as e:
        error(f"Failed to generate weekly summary: {e}")
        raise typer.Exit(1)
