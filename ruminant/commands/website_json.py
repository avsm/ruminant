"""Website JSON export command for JavaScript frontend consumption."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import subprocess

import typer

from ..config import load_config
from ..utils.dates import format_week_range
from ..utils.paths import get_data_dir
from ..utils.logging import success, error, info, step
from ..utils.github import extract_users_from_data, fetch_user_info
import re


@dataclass
class WeekSummary:
    """Summary of a week for index."""
    year: int
    week: int
    week_range: str
    repos_count: int
    groups: List[str]
    has_new_features: bool
    summary: Optional[str]


def parse_report_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a single annotated report JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        error(f"Failed to parse {file_path}: {e}")
        return None


def parse_group_summary_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a group summary JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        error(f"Failed to parse {file_path}: {e}")
        return None


def collect_all_data(data_dir: Path) -> tuple[Dict[str, List[Dict]], Dict[str, List[Dict]], Dict[str, Dict], Dict[str, List[Dict]]]:
    """Collect all reports, group summaries, and weekly summaries organized by week."""
    
    weeks_data = {}  # key: "year-week", value: list of individual summaries
    group_summaries = {}  # key: "year-week", value: list of group summaries
    weekly_summaries = {}  # key: "year-week", value: weekly summary dict
    repo_data = {}  # key: "org/repo", value: list of weekly summaries for that repo
    
    # Collect individual repository summaries from data/summaries/<org>/<repo>/
    summaries_dir = data_dir / "summaries"
    if summaries_dir.exists():
        for org_dir in summaries_dir.iterdir():
            if org_dir.is_dir():
                for repo_dir in org_dir.iterdir():
                    if repo_dir.is_dir():
                        for summary_file in repo_dir.glob("week-*.json"):
                            summary = parse_report_json(summary_file)
                            if summary:
                                week_key = f"{summary['year']}-{summary['week']:02d}"
                                if week_key not in weeks_data:
                                    weeks_data[week_key] = []
                                
                                # Add org/repo info
                                summary['org'] = org_dir.name
                                summary['repo_name'] = repo_dir.name
                                summary['repo_full'] = f"{org_dir.name}/{repo_dir.name}"
                                
                                weeks_data[week_key].append(summary)
                                
                                # Also collect by repository
                                repo_key = f"{org_dir.name}/{repo_dir.name}"
                                if repo_key not in repo_data:
                                    repo_data[repo_key] = []
                                repo_data[repo_key].append(summary)
    
    # Collect group summaries from data/groups/<group>/
    groups_dir = data_dir / "groups"
    if groups_dir.exists():
        for group_dir in groups_dir.iterdir():
            if group_dir.is_dir():
                for summary_file in group_dir.glob("week-*.json"):
                    summary = parse_group_summary_json(summary_file)
                    if summary:
                        # Extract week info from filename (week-NN-YYYY.json)
                        parts = summary_file.stem.split('-')
                        if len(parts) >= 3:
                            week = int(parts[1])
                            year = int(parts[2])
                            week_key = f"{year}-{week:02d}"
                            
                            if week_key not in group_summaries:
                                group_summaries[week_key] = []
                            
                            # Ensure group name is in summary
                            if 'group' not in summary:
                                summary['group'] = group_dir.name
                            if 'year' not in summary:
                                summary['year'] = year
                            if 'week' not in summary:
                                summary['week'] = week
                            
                            group_summaries[week_key].append(summary)
    
    # Collect weekly summaries from data/summaries/weekly/
    weekly_summaries_dir = data_dir / "summaries" / "weekly"
    if weekly_summaries_dir.exists():
        for summary_file in weekly_summaries_dir.glob("week-*.json"):
            summary = parse_group_summary_json(summary_file)
            if summary:
                # Extract week info from filename (week-NN-YYYY.json)
                parts = summary_file.stem.split('-')
                if len(parts) >= 3:
                    week = int(parts[1])
                    year = int(parts[2])
                    week_key = f"{year}-{week:02d}"
                    
                    # Ensure metadata is in summary
                    if 'year' not in summary:
                        summary['year'] = year
                    if 'week' not in summary:
                        summary['week'] = week
                    
                    weekly_summaries[week_key] = summary
    
    return weeks_data, group_summaries, weekly_summaries, repo_data


def generate_week_index(weeks_data: Dict[str, List[Dict]], group_summaries: Dict[str, List[Dict]], weekly_summaries: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """Generate index of all weeks with summary information."""
    
    index = []
    all_weeks = set(weeks_data.keys()) | set(group_summaries.keys()) | set(weekly_summaries.keys())
    
    for week_key in sorted(all_weeks, reverse=True):
        parts = week_key.split('-')
        year = int(parts[0])
        week = int(parts[1])
        
        # Get reports for this week
        week_reports = weeks_data.get(week_key, [])
        week_groups = group_summaries.get(week_key, [])
        week_summary = weekly_summaries.get(week_key)
        
        # Calculate detailed statistics
        total_commits = 0
        total_prs = 0
        total_issues = 0
        active_contributors = set()
        repos_with_commits = 0
        
        # Get data directory for git repos
        data_dir = get_data_dir()
        git_dir = data_dir / "git"
        
        for report in week_reports:
            # Count repositories with actual commits
            if report.get('start_commit') and report.get('end_commit'):
                repos_with_commits += 1
                
                # Try to count actual commits from git repo
                repo_name = report.get('repo', '')
                if repo_name:
                    # Try to find the git repo path
                    # Repos are organized like data/git/ocaml/dune, data/git/ocaml-multicore/eio, etc.
                    possible_paths = [
                        git_dir / "ocaml" / repo_name,
                        git_dir / "ocaml-multicore" / repo_name,
                        git_dir / "oxcaml" / repo_name,
                        git_dir / "ocsigen" / repo_name,
                        git_dir / "janestreet" / repo_name,
                        git_dir / "ocaml-dune" / repo_name,
                    ]
                    
                    for repo_path in possible_paths:
                        if repo_path.exists():
                            commit_count = count_git_commits(
                                repo_path,
                                report['start_commit'],
                                report['end_commit']
                            )
                            if commit_count > 0:
                                total_commits += commit_count
                                break
                    else:
                        # Fallback to estimate if we can't find the repo
                        total_commits += 10
                else:
                    # Fallback estimate
                    total_commits += 10
            
            # Count PRs and issues from activity
            if report.get('activity'):
                # Count PRs and issues mentioned in activity
                activity_text = report['activity'].lower()
                total_prs += activity_text.count('pr #') + activity_text.count('pull request')
                total_issues += activity_text.count('issue #') + activity_text.count('fixes #')
            
            # Collect unique contributors
            if report.get('notable_contributors'):
                for contrib in report['notable_contributors']:
                    if isinstance(contrib, dict) and contrib.get('login'):
                        active_contributors.add(contrib['login'])
        
        # Extract brief summary - prefer weekly summary, then group, then individual
        summary_text = None
        if week_summary and week_summary.get('brief_summary'):
            summary_text = week_summary['brief_summary']
        elif week_groups:
            for group in week_groups:
                # Use the explicit brief_summary field if available
                if group.get('brief_summary'):
                    summary_text = group['brief_summary']
                    break
        # Fallback to individual repository summaries if no group summary
        elif week_reports:
            for report in week_reports:
                if report.get('brief_summary'):
                    summary_text = report['brief_summary']
                    break
        
        # Check for new features in weekly, group, and individual summaries
        has_new_features = (
            (week_summary and bool(week_summary.get('new_features'))) or
            any(bool(report.get('new_features')) for report in week_reports) or
            any(bool(group.get('new_features')) for group in week_groups)
        )
        
        # Get week range - prefer weekly summary, then reports, then groups
        week_range = None
        if week_summary and week_summary.get('week_range'):
            week_range = week_summary['week_range']
        elif week_reports:
            week_range = week_reports[0].get('week_range')
        elif week_groups:
            week_range = week_groups[0].get('week_range')
        if not week_range:
            week_range = format_week_range(year, week)
        
        week_summary = {
            'year': year,
            'week': week,
            'week_key': week_key,
            'week_range': week_range,
            'repos_count': len(week_reports),
            'repos_with_commits': repos_with_commits,
            'groups': [g['group'] for g in week_groups],
            'has_new_features': has_new_features,
            'summary': summary_text,
            'activity_level': calculate_activity_level(week_reports, week_groups, week_summary),
            'has_weekly_summary': week_summary is not None,
            'stats': {
                'total_commits': total_commits,
                'total_prs': total_prs,
                'total_issues': total_issues,
                'contributor_count': len(active_contributors),
                'active_repos': repos_with_commits
            }
        }
        
        index.append(week_summary)
    
    return index


def count_git_commits(repo_path: Path, start_commit: str, end_commit: str) -> int:
    """Count commits between two SHAs in a git repository."""
    try:
        # Get commit count using git rev-list
        result = subprocess.run(
            ['git', 'rev-list', '--count', f'{start_commit}..{end_commit}'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError):
        pass
    return 0


def calculate_activity_level(reports: List[Dict], groups: List[Dict], weekly_summary: Optional[Dict] = None) -> int:
    """Calculate activity level for a week."""
    level = 0

    # Count individual summary content
    for report in reports:
        if report.get('new_features'):
            level += 4  # High value for new features
        if report.get('activity'):
            level += 3
        if report.get('new_features'):
            level += 2
        if report.get('notable_contributors'):
            level += 1
        if report.get('emerging_trends'):
            level += 2
    
    # Count group summary content
    for group in groups:
        if group.get('group_overview'):
            level += 2
        if group.get('cross_repository_work'):
            level += 3
        if group.get('key_projects'):
            level += 3
        if group.get('new_features'):
            level += 2
        if group.get('notable_discussions'):
            level += 1
        if group.get('emerging_trends'):
            level += 2
    
    # Count weekly summary content (highest weight since it's ecosystem-wide)
    if weekly_summary:
        if weekly_summary.get('group_overview'):
            level += 5
        if weekly_summary.get('cross_repository_work'):
            level += 4
        if weekly_summary.get('key_projects'):
            level += 4
        if weekly_summary.get('new_features'):
            level += 3
        if weekly_summary.get('notable_discussions'):
            level += 2
        if weekly_summary.get('emerging_trends'):
            level += 3
    
    return level


def generate_week_detail(week_key: str, reports: List[Dict], groups: List[Dict], weekly_summary: Optional[Dict] = None) -> Dict[str, Any]:
    """Generate detailed week data for a specific week."""
    
    parts = week_key.split('-')
    year = int(parts[0])
    week = int(parts[1])
    
    # Get week range - prefer weekly summary
    week_range = None
    if weekly_summary and weekly_summary.get('week_range'):
        week_range = weekly_summary['week_range']
    elif reports:
        week_range = reports[0].get('week_range')
    elif groups:
        week_range = groups[0].get('week_range')
    if not week_range:
        week_range = format_week_range(year, week)
    
    return {
        'year': year,
        'week': week,
        'week_key': week_key,
        'week_range': week_range,
        'repositories': reports,
        'group_summaries': groups,
        'weekly_summary': weekly_summary,
        'activity_level': calculate_activity_level(reports, groups, weekly_summary),
        'stats': {
            'total_repos': len(reports),
            'total_groups': len(groups),
            'has_weekly_summary': weekly_summary is not None,
            'has_new_features': any(r.get('new_features') for r in reports),
            'has_new_features': any(r.get('new_features') for r in reports) or any(g.get('new_features') for g in groups) or (weekly_summary and weekly_summary.get('new_features')),
            'has_emerging_trends': any(r.get('emerging_trends') for r in reports) or any(g.get('emerging_trends') for g in groups) or (weekly_summary and weekly_summary.get('emerging_trends')),
            'repos_with_commits': sum(1 for r in reports if r.get('start_commit') and r.get('end_commit'))
        }
    }


def generate_repositories_index(repo_data: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Generate index of all repositories with their activity history."""
    
    repositories = {}
    
    for repo_key, summaries in repo_data.items():
        org, repo_name = repo_key.split('/')
        
        # Sort summaries by week (newest first)
        sorted_summaries = sorted(summaries, key=lambda x: f"{x['year']}-{x['week']:02d}", reverse=True)
        
        repositories[repo_key] = {
            'org': org,
            'repo_name': repo_name,
            'repo_full': repo_key,
            'total_weeks': len(summaries),
            'latest_week': sorted_summaries[0] if sorted_summaries else None,
            'oldest_week': sorted_summaries[-1] if sorted_summaries else None,
            'weeks': [{
                'year': s['year'],
                'week': s['week'],
                'week_key': f"{s['year']}-{s['week']:02d}",
                'week_range': s.get('week_range'),
                'has_new_features': bool(s.get('new_features')),
                'has_activity': bool(s.get('activity')),
                'start_commit': s.get('start_commit'),
                'end_commit': s.get('end_commit')
            } for s in sorted_summaries]
        }
    
    return repositories


def generate_groups_index(all_groups: Dict[str, List[Dict]], config) -> Dict[str, Any]:
    """Generate index of all groups with their history, preserving config order."""
    
    groups_data = {}
    
    for week_key, week_groups in all_groups.items():
        for group in week_groups:
            group_name = group.get('group', 'unknown')
            
            if group_name not in groups_data:
                groups_data[group_name] = {
                    'name': group_name,
                    'weeks': [],
                    'total_weeks': 0,
                    'repositories': set()
                }
            
            # Add week info
            groups_data[group_name]['weeks'].append({
                'week_key': week_key,
                'year': group.get('year'),
                'week': group.get('week'),
                'week_range': group.get('week_range'),
                'has_content': bool(
                    group.get('group_overview') or 
                    group.get('cross_repository_work') or 
                    group.get('key_projects')
                )
            })
            
            # Collect repositories from the new 'repositories' field
            if group.get('repositories'):
                groups_data[group_name]['repositories'].update(group['repositories'])
    
    # Convert sets to lists and count
    for group_name in groups_data:
        groups_data[group_name]['repositories'] = list(groups_data[group_name]['repositories'])
        groups_data[group_name]['total_weeks'] = len(groups_data[group_name]['weeks'])
        # Sort weeks
        groups_data[group_name]['weeks'].sort(key=lambda x: x['week_key'], reverse=True)
    
    # Create ordered dict based on config file order
    ordered_groups = {}
    if hasattr(config, 'groups'):
        # First add groups in config order
        for group_name in config.groups.keys():
            if group_name in groups_data:
                ordered_groups[group_name] = groups_data[group_name]
        # Then add any remaining groups not in config
        for group_name in groups_data:
            if group_name not in ordered_groups:
                ordered_groups[group_name] = groups_data[group_name]
    else:
        ordered_groups = groups_data
    
    return ordered_groups


def collect_all_users(data_dir: Path) -> Dict[str, Any]:
    """Load all user data from data/users directory."""
    users_data = {}
    users_dir = data_dir / "users"
    
    if users_dir.exists():
        info(f"Loading user data from {users_dir}")
        for user_file in users_dir.glob("*.json"):
            try:
                with open(user_file, 'r', encoding='utf-8') as f:
                    user_info = json.load(f)
                    username = user_file.stem  # Get username from filename
                    users_data[username] = user_info
            except Exception as e:
                error(f"Failed to load user file {user_file}: {e}")
    else:
        warning("No users directory found, user data will be empty")
    
    return users_data


def generate_users_data(all_users: Dict[str, Any]) -> Dict[str, Any]:
    """Format already-loaded user data for JSON output."""
    users_data = {}
    
    info(f"Processing user data for {len(all_users)} users...")
    
    for username, user_info in all_users.items():
        users_data[username] = {
            'login': user_info.get('login', username),
            'name': user_info.get('name', ''),
            'avatar_url': user_info.get('avatar_url', ''),
            'html_url': user_info.get('html_url', f'https://github.com/{username}'),
            'bio': user_info.get('bio', ''),
            'company': user_info.get('company', ''),
            'location': user_info.get('location', ''),
            'public_repos': user_info.get('public_repos', 0),
            'followers': user_info.get('followers', 0),
            'created_at': user_info.get('created_at', ''),
        }
    
    return users_data


def post_process_markdown_with_user_links(text: str, users_data: Dict[str, Any]) -> str:
    """Replace GitHub user links with full names if available."""
    if not text:
        return text
    
    # Pattern to match [text](https://github.com/username) 
    github_user_pattern = re.compile(r'\[([^\]]+)\]\(https://github\.com/([^)]+)\)')
    
    def replace_user_link(match):
        link_text = match.group(1)
        username = match.group(2)
        
        # Check if the link text is just the username (e.g., [@username])
        if link_text == f'@{username}' or link_text == username:
            # Replace with full name if available
            user_info = users_data.get(username, {})
            if user_info.get('name'):
                return f'[{user_info["name"]}](https://github.com/{username})'
        
        # Keep original link if link text is already customized or no full name available
        return match.group(0)
    
    return github_user_pattern.sub(replace_user_link, text)


def group_bullet_points_by_internal_links(content: str, group_order: List[str]) -> Dict[str, List[str]]:
    """Group bullet points by their internal group links and order by config."""
    if not content:
        return {}
    
    # Split content into bullet points (lines starting with -)
    lines = content.split('\n')
    bullet_points = []
    current_bullet = ""
    
    for line in lines:
        line = line.strip()
        if line.startswith('- '):
            if current_bullet:
                bullet_points.append(current_bullet)
            current_bullet = line
        elif current_bullet and line:
            current_bullet += '\n' + line
    
    if current_bullet:
        bullet_points.append(current_bullet)
    
    # Group bullets by their first __RUMINANT:group__ tag
    groups = {}
    ungrouped = []
    
    for bullet in bullet_points:
        # Find the first __RUMINANT:group__ pattern
        import re
        pattern = r'__RUMINANT:(\w+)__'
        match = re.search(pattern, bullet)
        
        if match:
            group_name = match.group(1)
            # Only remove the __RUMINANT:group__ tag if it's at the beginning of the bullet
            # (after the "- " marker)
            clean_bullet = bullet
            if bullet.strip().startswith('- __RUMINANT:'):
                # Remove only the first occurrence at the beginning
                clean_bullet = re.sub(r'^(\s*-\s*)__RUMINANT:\w+__\s*', r'\1', bullet)
            elif bullet.strip().startswith('__RUMINANT:'):
                # Handle case without the dash
                clean_bullet = re.sub(r'^__RUMINANT:\w+__\s*', '', bullet.strip())
                if clean_bullet and not clean_bullet.startswith('-'):
                    clean_bullet = '- ' + clean_bullet
            
            # Clean up any double spaces at the beginning
            clean_bullet = re.sub(r'^(\s*-\s*)\s+', r'\1', clean_bullet)
            
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(clean_bullet)
        else:
            ungrouped.append(bullet)
    
    # Order groups according to config order
    ordered_groups = {}
    for group in group_order:
        if group in groups:
            ordered_groups[group] = groups[group]
    
    # Add any ungrouped items at the end
    if ungrouped:
        ordered_groups['other'] = ungrouped
    
    return ordered_groups


def post_process_data_with_user_links(data: Any, users_data: Dict[str, Any], config: Optional[Dict] = None) -> Any:
    """Recursively process all data to replace user links with full names and group bullet points."""
    if isinstance(data, dict):
        processed = {}
        for key, value in data.items():
            if isinstance(value, str):
                # Check for __RUMINANT: tags in the ORIGINAL text before processing
                has_group_tags = value and '__RUMINANT:' in value
                
                # Process markdown for all string fields that look like content
                if any(field in key.lower() for field in ['summary', 'overview', 'body', 'description', 'content', 'features', 'activity', 'discussion', 'trend', 'project', 'work']):
                    processed_text = post_process_markdown_with_user_links(value, users_data)
                else:
                    processed_text = value
                
                # For weekly summary sections with bullet points, also create grouped version
                # Check for specific field names (regardless of where they appear)
                if (key in ['new_features', 'group_overview', 'cross_repository_work', 'activity', 'notable_discussions', 'emerging_trends'] 
                    and config and hasattr(config, 'groups') 
                    and has_group_tags):
                    
                    group_order = list(config.groups.keys())
                    # Pass the original value with __RUMINANT: tags intact
                    grouped_bullets = group_bullet_points_by_internal_links(value, group_order)
                    processed[key] = processed_text  # Keep original (with processed user links)
                    processed[key + '_grouped'] = grouped_bullets  # Add grouped version
                else:
                    processed[key] = processed_text
            else:
                processed[key] = post_process_data_with_user_links(value, users_data, config)
        return processed
    elif isinstance(data, list):
        return [post_process_data_with_user_links(item, users_data, config) for item in data]
    else:
        return data


def generate_activity_statistics(week_index: List[Dict[str, Any]], group_summaries: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Generate comprehensive activity statistics for visualization."""
    
    if not week_index:
        return {}
    
    # Extract activity levels
    activity_levels = [week['activity_level'] for week in week_index]
    
    # Basic statistics
    total_activity = sum(activity_levels)
    avg_activity = total_activity / len(activity_levels) if activity_levels else 0
    max_activity = max(activity_levels) if activity_levels else 0
    min_activity = min(activity_levels) if activity_levels else 0
    
    # Find peaks and valleys
    sorted_weeks = sorted(week_index, key=lambda w: w['activity_level'], reverse=True)
    top_weeks = sorted_weeks[:5]
    low_weeks = sorted_weeks[-5:]
    
    # Group activity analysis
    group_activity = {}
    for week_key, week_groups in group_summaries.items():
        for group in week_groups:
            group_name = group.get('group', 'unknown')
            if group_name not in group_activity:
                group_activity[group_name] = {'weeks': 0, 'total_activity': 0}
            group_activity[group_name]['weeks'] += 1
            
            # Find corresponding week in index to get activity level
            week_info = next((w for w in week_index if w['week_key'] == week_key), None)
            if week_info:
                group_activity[group_name]['total_activity'] += week_info['activity_level']
    
    # Calculate group averages
    for group in group_activity:
        group_activity[group]['avg_activity'] = (
            group_activity[group]['total_activity'] / group_activity[group]['weeks']
            if group_activity[group]['weeks'] > 0 else 0
        )
    
    # Normalize activity levels for visualization (0-100)
    normalized_activities = []
    if max_activity > 0:
        normalized_activities = [
            int((level / max_activity) * 100) for level in activity_levels
        ]
    
    # Create time series data for sparklines
    sparkline_data = []
    for week in reversed(week_index):  # Chronological order for sparklines
        sparkline_data.append({
            'week_key': week['week_key'],
            'activity_level': week['activity_level'],
            'normalized': int((week['activity_level'] / max_activity) * 100) if max_activity > 0 else 0,
            'has_features': week.get('has_new_features', False),
            'groups': week.get('groups', [])
        })
    
    return {
        'total_weeks': len(week_index),
        'total_activity': total_activity,
        'avg_activity': round(avg_activity, 1),
        'max_activity': max_activity,
        'min_activity': min_activity,
        'activity_levels': activity_levels,
        'normalized_activities': normalized_activities,
        'sparkline_data': sparkline_data,
        'top_weeks': [
            {
                'week_key': w['week_key'],
                'week_range': w['week_range'], 
                'activity_level': w['activity_level'],
                'summary': w['summary'][:100] + '...' if w.get('summary') and len(w['summary']) > 100 else w.get('summary', '')
            }
            for w in top_weeks
        ],
        'low_weeks': [
            {
                'week_key': w['week_key'],
                'week_range': w['week_range'],
                'activity_level': w['activity_level'],
                'summary': w['summary'][:100] + '...' if w.get('summary') and len(w['summary']) > 100 else w.get('summary', '')
            }
            for w in low_weeks
        ],
        'group_activity': group_activity,
        'weeks_with_summaries': len([w for w in week_index if w.get('has_weekly_summary', False)]),
        'weeks_with_features': len([w for w in week_index if w.get('has_new_features', False)]),
        'activity_distribution': {
            'high': len([a for a in activity_levels if a > avg_activity * 1.5]),
            'medium': len([a for a in activity_levels if avg_activity * 0.5 <= a <= avg_activity * 1.5]),
            'low': len([a for a in activity_levels if a < avg_activity * 0.5])
        }
    }


def website_json_main(
    output_dir: Optional[str] = typer.Option("website-json", "--output", "-o", help="Output directory for JSON files"),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print JSON output"),
) -> None:
    """Generate JSON files for JavaScript frontend consumption."""
    
    try:
        config = load_config()
        data_dir = get_data_dir()
        output_path = Path(output_dir)
        
        step("Collecting all summary data...")
        weeks_data, group_summaries, weekly_summaries, repo_data = collect_all_data(data_dir)
        
        if not weeks_data and not group_summaries and not weekly_summaries:
            error("No summaries found. Run 'ruminant summarize', 'ruminant group', and 'ruminant summarize-week' first.")
            raise typer.Exit(1)
        
        total_weeks = len(set(weeks_data.keys()) | set(group_summaries.keys()) | set(weekly_summaries.keys()))
        total_repos = sum(len(repos) for repos in weeks_data.values())
        total_groups = sum(len(groups) for groups in group_summaries.values())
        total_weeklies = len(weekly_summaries)
        
        info(f"Found data for {total_weeks} weeks")
        if total_repos > 0:
            info(f"  → {total_repos} individual repository summaries")
        if total_groups > 0:
            info(f"  → {total_groups} group summaries")
        if total_weeklies > 0:
            info(f"  → {total_weeklies} weekly summaries")
        
        # Create output directory structure
        step("Creating output directory structure...")
        output_path.mkdir(exist_ok=True)
        weeks_dir = output_path / "weeks"
        weeks_dir.mkdir(exist_ok=True)
        repos_dir = output_path / "repositories"
        repos_dir.mkdir(exist_ok=True)
        
        # Collect and generate users data
        step("Collecting user data...")
        all_users = collect_all_users(data_dir)
        users_data = generate_users_data(all_users)
        info(f"Generated user data for {len(users_data)} users")
        
        # Post-process all data to replace user links with full names and group bullet points
        step("Post-processing data to replace user links with full names and group bullet points...")
        weeks_data = post_process_data_with_user_links(weeks_data, users_data, config)
        group_summaries = post_process_data_with_user_links(group_summaries, users_data, config)
        weekly_summaries = post_process_data_with_user_links(weekly_summaries, users_data, config)
        repo_data = post_process_data_with_user_links(repo_data, users_data, config)
        
        # Generate and save week index
        step("Generating week index...")
        week_index = generate_week_index(weeks_data, group_summaries, weekly_summaries)
        
        index_data = {
            'project': config.project_name,
            'generated_at': datetime.now().isoformat(),
            'total_weeks': len(week_index),
            'total_weekly_summaries': total_weeklies,
            'total_repositories': len(repo_data),
            'weeks': week_index
        }
        
        indent = 2 if pretty else None
        with open(output_path / "index.json", 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=indent, ensure_ascii=False)
        
        # Generate and save individual week files
        step("Generating individual week files...")
        all_weeks = set(weeks_data.keys()) | set(group_summaries.keys()) | set(weekly_summaries.keys())
        
        for week_key in all_weeks:
            week_reports = weeks_data.get(week_key, [])
            week_groups = group_summaries.get(week_key, [])
            week_summary = weekly_summaries.get(week_key)
            
            week_detail = generate_week_detail(week_key, week_reports, week_groups, week_summary)
            
            with open(weeks_dir / f"{week_key}.json", 'w', encoding='utf-8') as f:
                json.dump(week_detail, f, indent=indent, ensure_ascii=False)
        
        info(f"Generated {len(all_weeks)} week files")
        
        # Generate groups index
        step("Generating groups index...")
        groups_index = generate_groups_index(group_summaries, config)
        
        with open(output_path / "groups.json", 'w', encoding='utf-8') as f:
            json.dump(groups_index, f, indent=indent, ensure_ascii=False)
        
        # Generate repositories index
        step("Generating repositories index...")
        repositories_index = generate_repositories_index(repo_data)
        
        with open(output_path / "repositories.json", 'w', encoding='utf-8') as f:
            json.dump(repositories_index, f, indent=indent, ensure_ascii=False)
        
        # Generate individual repository files
        step("Generating individual repository files...")
        for repo_key, summaries in repo_data.items():
            # Create safe filename from repo key
            safe_filename = repo_key.replace('/', '_')
            
            # Sort summaries by week (newest first)
            sorted_summaries = sorted(summaries, key=lambda x: f"{x['year']}-{x['week']:02d}", reverse=True)
            
            repo_detail = {
                'repo_full': repo_key,
                'org': repo_key.split('/')[0],
                'repo_name': repo_key.split('/')[1],
                'total_weeks': len(summaries),
                'summaries': sorted_summaries
            }
            
            with open(repos_dir / f"{safe_filename}.json", 'w', encoding='utf-8') as f:
                json.dump(repo_detail, f, indent=indent, ensure_ascii=False)
        
        info(f"Generated {len(repo_data)} repository files")
        
        # Save users data
        step("Saving users data...")
        with open(output_path / "users.json", 'w', encoding='utf-8') as f:
            json.dump(users_data, f, indent=indent, ensure_ascii=False)
        
        # Generate activity statistics
        step("Generating activity statistics...")
        activity_stats = generate_activity_statistics(week_index, group_summaries)
        
        with open(output_path / "activity_stats.json", 'w', encoding='utf-8') as f:
            json.dump(activity_stats, f, indent=indent, ensure_ascii=False)
        
        # Generate metadata file
        step("Generating metadata...")
        metadata = {
            'project': config.project_name,
            'generated_at': datetime.now().isoformat(),
            'version': '1.0',
            'total_weeks': len(week_index),
            'total_groups': len(groups_index),
            'total_repositories': len(repo_data),
            'total_weekly_summaries': total_weeklies,
            'latest_week': week_index[0] if week_index else None,
            'oldest_week': week_index[-1] if week_index else None,
            'activity_stats': activity_stats  # Include stats in metadata for quick access
        }
        
        with open(output_path / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=indent, ensure_ascii=False)
        
        success(f"JSON export completed successfully in {output_path}")
        success(f"Generated: index.json, groups.json, repositories.json, users.json, activity_stats.json, metadata.json")
        success(f"Also generated: {len(all_weeks)} week files and {len(repo_data)} repository files")
        info("These files can be served statically and consumed by a JavaScript frontend")
        
    except Exception as e:
        error(f"JSON export failed: {e}")
        raise typer.Exit(1)