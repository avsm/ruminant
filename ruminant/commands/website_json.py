"""Website JSON export command for JavaScript frontend consumption."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

import typer

from ..config import load_config
from ..utils.dates import format_week_range
from ..utils.paths import get_data_dir
from ..utils.logging import success, error, info, step


@dataclass
class WeekSummary:
    """Summary of a week for index."""
    year: int
    week: int
    week_range: str
    repos_count: int
    groups: List[str]
    has_priority_items: bool
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


def collect_all_data(data_dir: Path) -> tuple[Dict[str, List[Dict]], Dict[str, List[Dict]]]:
    """Collect all reports and group summaries organized by week."""
    
    weeks_data = {}  # key: "year-week", value: list of reports
    group_summaries = {}  # key: "year-week", value: list of group summaries
    
    # Collect annotated reports
    reports_dir = data_dir / "reports"
    if reports_dir.exists():
        for org_dir in reports_dir.iterdir():
            if org_dir.is_dir() and org_dir.name != "groups":
                for repo_dir in org_dir.iterdir():
                    if repo_dir.is_dir():
                        for report_file in repo_dir.glob("week-*.json"):
                            report = parse_report_json(report_file)
                            if report:
                                week_key = f"{report['year']}-{report['week']:02d}"
                                if week_key not in weeks_data:
                                    weeks_data[week_key] = []
                                
                                # Add org/repo info
                                report['org'] = org_dir.name
                                report['repo_name'] = repo_dir.name
                                report['repo_full'] = f"{org_dir.name}/{repo_dir.name}"
                                
                                weeks_data[week_key].append(report)
    
    # Collect group summaries from reports/groups (annotated)
    groups_dir = data_dir / "reports" / "groups"
    if groups_dir.exists():
        for group_dir in groups_dir.iterdir():
            if group_dir.is_dir():
                for summary_file in group_dir.glob("week-*.json"):
                    summary = parse_group_summary_json(summary_file)
                    if summary:
                        # Extract week info from filename
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
    
    # Fallback to non-annotated summaries if no annotated ones exist
    if not group_summaries:
        summaries_dir = data_dir / "summaries" / "groups"
        if summaries_dir.exists():
            for group_dir in summaries_dir.iterdir():
                if group_dir.is_dir():
                    for summary_file in group_dir.glob("week-*.json"):
                        summary = parse_group_summary_json(summary_file)
                        if summary:
                            # Extract week info from filename
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
    
    return weeks_data, group_summaries


def generate_week_index(weeks_data: Dict[str, List[Dict]], group_summaries: Dict[str, List[Dict]]) -> List[Dict[str, Any]]:
    """Generate index of all weeks with summary information."""
    
    index = []
    all_weeks = set(weeks_data.keys()) | set(group_summaries.keys())
    
    for week_key in sorted(all_weeks, reverse=True):
        parts = week_key.split('-')
        year = int(parts[0])
        week = int(parts[1])
        
        # Get reports for this week
        week_reports = weeks_data.get(week_key, [])
        week_groups = group_summaries.get(week_key, [])
        
        # Extract summary from first group summary if available
        summary_text = None
        if week_groups:
            for group in week_groups:
                if group.get('short_summary'):
                    summary_text = group['short_summary']
                    break
        
        # Check for priority items
        has_priority = any(
            bool(report.get('priority_items')) 
            for report in week_reports
        )
        
        # Get week range
        week_range = None
        if week_reports:
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
            'groups': [g['group'] for g in week_groups],
            'has_priority_items': has_priority,
            'summary': summary_text,
            'activity_level': calculate_activity_level(week_reports, week_groups)
        }
        
        index.append(week_summary)
    
    return index


def calculate_activity_level(reports: List[Dict], groups: List[Dict]) -> int:
    """Calculate activity level for a week."""
    level = 0
    
    # Count report content
    for report in reports:
        if report.get('overall_activity'):
            level += 2
        if report.get('ongoing_projects'):
            level += 3
        if report.get('priority_items'):
            level += 3
        if report.get('contributors'):
            level += 1
        if report.get('emerging_trends'):
            level += 2
    
    # Count group content
    for group in groups:
        if any([
            group.get('overall_activity'),
            group.get('key_achievements'),
            group.get('ongoing_initiatives'),
            group.get('priority_items')
        ]):
            level += 3
    
    return level


def generate_week_detail(week_key: str, reports: List[Dict], groups: List[Dict]) -> Dict[str, Any]:
    """Generate detailed week data for a specific week."""
    
    parts = week_key.split('-')
    year = int(parts[0])
    week = int(parts[1])
    
    # Get week range
    week_range = None
    if reports:
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
        'activity_level': calculate_activity_level(reports, groups),
        'stats': {
            'total_repos': len(reports),
            'total_groups': len(groups),
            'has_priority_items': any(r.get('priority_items') for r in reports),
            'has_emerging_trends': any(r.get('emerging_trends') for r in reports)
        }
    }


def generate_groups_index(all_groups: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Generate index of all groups with their history."""
    
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
                'has_content': bool(group.get('overall_activity') or group.get('key_achievements'))
            })
            
            # Collect repositories
            if group.get('repositories_included'):
                groups_data[group_name]['repositories'].update(group['repositories_included'])
    
    # Convert sets to lists and count
    for group_name in groups_data:
        groups_data[group_name]['repositories'] = list(groups_data[group_name]['repositories'])
        groups_data[group_name]['total_weeks'] = len(groups_data[group_name]['weeks'])
        # Sort weeks
        groups_data[group_name]['weeks'].sort(key=lambda x: x['week_key'], reverse=True)
    
    return groups_data


def website_json_main(
    output_dir: Optional[str] = typer.Option("website-json", "--output", "-o", help="Output directory for JSON files"),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print JSON output"),
) -> None:
    """Generate JSON files for JavaScript frontend consumption."""
    
    try:
        config = load_config()
        data_dir = get_data_dir()
        output_path = Path(output_dir)
        
        step("Collecting all report and summary data...")
        weeks_data, group_summaries = collect_all_data(data_dir)
        
        if not weeks_data and not group_summaries:
            error("No annotated reports or group summaries found. Run 'ruminant annotate' first.")
            raise typer.Exit(1)
        
        total_weeks = len(set(weeks_data.keys()) | set(group_summaries.keys()))
        info(f"Found data for {total_weeks} weeks")
        
        # Create output directory structure
        step("Creating output directory structure...")
        output_path.mkdir(exist_ok=True)
        weeks_dir = output_path / "weeks"
        weeks_dir.mkdir(exist_ok=True)
        
        # Generate and save week index
        step("Generating week index...")
        week_index = generate_week_index(weeks_data, group_summaries)
        
        index_data = {
            'project': config.project_name,
            'generated_at': datetime.now().isoformat(),
            'total_weeks': len(week_index),
            'weeks': week_index
        }
        
        indent = 2 if pretty else None
        with open(output_path / "index.json", 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=indent, ensure_ascii=False)
        
        # Generate and save individual week files
        step("Generating individual week files...")
        all_weeks = set(weeks_data.keys()) | set(group_summaries.keys())
        
        for week_key in all_weeks:
            week_reports = weeks_data.get(week_key, [])
            week_groups = group_summaries.get(week_key, [])
            
            week_detail = generate_week_detail(week_key, week_reports, week_groups)
            
            with open(weeks_dir / f"{week_key}.json", 'w', encoding='utf-8') as f:
                json.dump(week_detail, f, indent=indent, ensure_ascii=False)
        
        info(f"Generated {len(all_weeks)} week files")
        
        # Generate groups index
        step("Generating groups index...")
        groups_index = generate_groups_index(group_summaries)
        
        with open(output_path / "groups.json", 'w', encoding='utf-8') as f:
            json.dump(groups_index, f, indent=indent, ensure_ascii=False)
        
        # Generate metadata file
        step("Generating metadata...")
        metadata = {
            'project': config.project_name,
            'generated_at': datetime.now().isoformat(),
            'version': '1.0',
            'total_weeks': len(week_index),
            'total_groups': len(groups_index),
            'latest_week': week_index[0] if week_index else None,
            'oldest_week': week_index[-1] if week_index else None
        }
        
        with open(output_path / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=indent, ensure_ascii=False)
        
        success(f"JSON export completed successfully in {output_path}")
        success(f"Generated: index.json, groups.json, metadata.json, and {len(all_weeks)} week files")
        info("These files can be served statically and consumed by a JavaScript frontend")
        
    except Exception as e:
        error(f"JSON export failed: {e}")
        raise typer.Exit(1)