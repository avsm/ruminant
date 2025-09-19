#!/usr/bin/env python3

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import asyncio
import typer

from rich.console import Console
from rich import print as rprint
from anthropic import AsyncAnthropic

from ..config import load_config
from ..claude import create_client, get_context_params

console = Console()


def get_current_week_info():
    """Get the current week number and year."""
    today = datetime.now()
    year = today.year
    week = today.isocalendar()[1]
    return year, week


def get_week_date_range(year: int, week: int):
    """Get the date range for a given week."""
    # Get the first day of the week (Monday)
    jan1 = datetime(year, 1, 1)
    days_to_monday = (7 - jan1.weekday()) % 7
    first_monday = jan1 + timedelta(days=days_to_monday)

    if jan1.weekday() <= 3:  # Thursday or earlier
        first_monday -= timedelta(days=7)

    week_start = first_monday + timedelta(weeks=week-1)
    week_end = week_start + timedelta(days=6)

    return week_start, week_end


def get_day_name_and_date(date: datetime) -> str:
    """Get formatted day name and date."""
    return date.strftime("%A, %B %d, %Y")


def filter_activity_by_date(data: Dict, target_date: datetime) -> Dict:
    """Filter repository/group activities for a specific date."""
    date_str = target_date.strftime("%Y-%m-%d")

    filtered = {
        'commits': [],
        'pull_requests': [],
        'issues': [],
        'discussions': []
    }

    # Helper function to check if a date string matches our target date
    def is_same_date(iso_date_str: str) -> bool:
        if not iso_date_str:
            return False
        try:
            activity_date = datetime.fromisoformat(iso_date_str.replace('Z', '+00:00'))
            return activity_date.date() == target_date.date()
        except:
            return False

    # Filter commits by author date
    if 'commits' in data:
        for commit in data['commits']:
            if is_same_date(commit.get('commit', {}).get('author', {}).get('date', '')):
                filtered['commits'].append(commit)

    # Filter pull requests by created or updated date
    if 'pull_requests' in data:
        for pr in data['pull_requests']:
            # Include if created, updated, merged, or closed on this date
            if (is_same_date(pr.get('created_at', '')) or
                is_same_date(pr.get('updated_at', '')) or
                is_same_date(pr.get('merged_at', '')) or
                is_same_date(pr.get('closed_at', ''))):
                filtered['pull_requests'].append(pr)

    # Filter issues by created or updated date
    if 'issues' in data:
        for issue in data['issues']:
            if (is_same_date(issue.get('created_at', '')) or
                is_same_date(issue.get('updated_at', '')) or
                is_same_date(issue.get('closed_at', ''))):
                filtered['issues'].append(issue)

    # Filter discussions
    if 'discussions' in data:
        for discussion in data['discussions']:
            if (is_same_date(discussion.get('createdAt', '')) or
                is_same_date(discussion.get('updatedAt', ''))):
                filtered['discussions'].append(discussion)

    return filtered


async def generate_daily_summary(
    client: AsyncAnthropic,
    repos_data: List[Dict],
    groups_data: Dict,
    date: datetime,
    claude_args: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a summary for a single day's activity."""

    day_name = get_day_name_and_date(date)
    date_str = date.strftime("%Y-%m-%d")

    # Create the daily summary prompt
    prompt = f"""You are analyzing OCaml ecosystem activity for {day_name}.

Please create a concise daily summary of the most important developments and activities from today.

## Repository Activity for {date_str}

{json.dumps(repos_data, indent=2)}

## Group Context

{json.dumps(groups_data, indent=2)}

Generate a structured daily summary with the following format:

1. **Key Highlights** - 2-3 most important developments of the day
2. **Notable Commits** - Significant code changes or features merged
3. **Active Discussions** - Important issues or PRs with active discussion
4. **Community Activity** - Notable contributor activities or milestones

Keep the summary brief and focused on what happened specifically today.
Format the response as valid JSON with these fields:
- date: "{date_str}"
- day_name: "{date.strftime('%A')}"
- highlights: list of 2-3 key highlights
- commits: list of notable commits with repo and description
- discussions: list of active discussions with links
- community: brief description of community activity
- summary: 1-2 sentence overall summary of the day
"""

    messages = [{"role": "user", "content": prompt}]

    response = await client.messages.create(
        messages=messages,
        **get_context_params(claude_args),
        max_tokens=2000
    )

    # Parse the response as JSON
    try:
        summary = json.loads(response.content[0].text)
        summary['generated_at'] = datetime.now().isoformat()
        return summary
    except json.JSONDecodeError:
        # Fallback to text if not valid JSON
        return {
            'date': date_str,
            'day_name': date.strftime('%A'),
            'summary': response.content[0].text,
            'generated_at': datetime.now().isoformat()
        }


async def summarize_daily_main(
    year: Optional[int] = None,
    week: Optional[int] = None,
    date: Optional[str] = None,  # Specific date in YYYY-MM-DD format
    claude_args: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False
):
    """
    Generate daily summaries for the current week or a specific date.

    This command is designed to be run daily to incrementally build
    up summaries throughout the week.
    """
    config = load_config()

    # Determine the target date
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d")
        year = target_date.year
        week = target_date.isocalendar()[1]
    else:
        # Default to today
        target_date = datetime.now()
        if not year:
            year = target_date.year
        if not week:
            week = target_date.isocalendar()[1]

    console.print(f"[green]📅 Generating daily summary for {get_day_name_and_date(target_date)}[/green]")

    # Load repository data from gh directory
    week_key = f"week-{week:02d}-{year}"
    daily_activities = []

    # Collect data from all repositories for this week
    gh_dir = Path("data/gh")
    if not gh_dir.exists():
        console.print(f"[red]Error: No data found in {gh_dir}[/red]")
        console.print("[yellow]Run 'ruminant sync --current --force' first to fetch the current week's data[/yellow]")
        raise typer.Exit(1)

    # Iterate through organizations and repositories
    for org_dir in gh_dir.iterdir():
        if not org_dir.is_dir():
            continue

        for repo_dir in org_dir.iterdir():
            if not repo_dir.is_dir():
                continue

            week_file = repo_dir / f"{week_key}.json"
            if week_file.exists():
                with open(week_file) as f:
                    repo_data = json.load(f)

                    # Filter this repo's activity for the target date
                    filtered = filter_activity_by_date(repo_data, target_date)

                    # Only include repos with activity on this date
                    if any(filtered[key] for key in filtered):
                        daily_activities.append({
                            'org': org_dir.name,
                            'repo': repo_dir.name,
                            'activity': filtered
                        })

    if not daily_activities:
        console.print(f"[yellow]No activity found for {target_date.strftime('%Y-%m-%d')}[/yellow]")
        if not force:
            return

    # Check if daily summary already exists
    daily_dir = Path(f"data/daily/{year}")
    daily_dir.mkdir(parents=True, exist_ok=True)

    date_str = target_date.strftime("%Y-%m-%d")
    daily_file = daily_dir / f"{date_str}.json"

    if daily_file.exists() and not force:
        console.print(f"[yellow]Daily summary for {date_str} already exists. Use --force to regenerate.[/yellow]")
        return

    if dry_run:
        console.print("[cyan]DRY RUN: Would generate daily summary[/cyan]")
        console.print(f"  Target date: {date_str}")
        console.print(f"  Week: {week} of {year}")
        console.print(f"  Repositories with activity: {len(daily_activities)}")
        console.print(f"  Output: {daily_file}")
        return

    # Generate the daily summary
    client = create_client()

    # Load groups data if available
    groups_data = {}
    groups_week_file = Path(f"data/groups/{year}/{week:02d}/summary.json")
    if groups_week_file.exists():
        with open(groups_week_file) as f:
            groups_data = json.load(f)

    summary = await generate_daily_summary(
        client,
        daily_activities,
        groups_data,
        target_date,
        claude_args
    )

    # Save the daily summary
    with open(daily_file, 'w') as f:
        json.dump(summary, f, indent=2)

    console.print(f"[green]✅ Daily summary saved to {daily_file}[/green]")

    # Also save to a week-aggregated file
    week_daily_dir = Path(f"data/weekly_daily/{year}")
    week_daily_dir.mkdir(parents=True, exist_ok=True)
    week_daily_file = week_daily_dir / f"week-{week:02d}-daily.json"

    daily_summaries = {}
    if week_daily_file.exists():
        with open(week_daily_file) as f:
            daily_summaries = json.load(f)

    # Add or update today's summary
    daily_summaries[date_str] = summary

    # Sort by date
    daily_summaries = dict(sorted(daily_summaries.items()))

    with open(week_daily_file, 'w') as f:
        json.dump(daily_summaries, f, indent=2)

    console.print(f"[green]✅ Updated week's daily summaries at {week_daily_file}[/green]")


def summarize_daily(
    year: Optional[int] = None,
    week: Optional[int] = None,
    date: Optional[str] = None,
    claude_args: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False
):
    """Wrapper to run async function."""
    asyncio.run(summarize_daily_main(year, week, date, claude_args, dry_run, force))