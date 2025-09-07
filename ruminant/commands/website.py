"""Website command for generating static HTML from JSON reports."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

import typer
import markdown2

from ..config import load_config
from ..utils.dates import format_week_range
from ..utils.paths import get_data_dir
from ..utils.logging import success, error, info, step


@dataclass
class ReportData:
    """Structured data from a JSON report file."""
    org: str
    repo: str
    year: int
    week: int
    week_range: str
    overall_activity: Optional[str]
    ongoing_projects: Optional[str]
    priority_items: Optional[str]
    notable_discussions: Optional[str]
    emerging_trends: Optional[str]
    good_first_issues: Optional[str]
    contributors: Optional[str]
    file_path: Path
    
    @property
    def summary_text(self) -> str:
        """Get a brief summary for calendar view."""
        if self.overall_activity:
            # Extract first sentence or truncate at 150 chars
            text = self.overall_activity.strip()
            # Remove markdown links for cleaner display
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            if len(text) > 150:
                text = text[:147] + "..."
            return text
        return "Activity summary available"
    
    @property
    def has_content(self) -> bool:
        """Check if report has meaningful content."""
        return any([
            self.overall_activity,
            self.ongoing_projects,
            self.priority_items,
            self.notable_discussions,
            self.emerging_trends,
            self.good_first_issues,
            self.contributors
        ])


@dataclass
class GroupSummaryData:
    """Structured data from a group summary JSON."""
    group: str
    year: int
    week: int
    week_range: str
    repositories_included: List[str]
    short_summary: Optional[str]
    overall_activity: Optional[str]
    key_achievements: Optional[str]
    ongoing_initiatives: Optional[str]
    priority_items: Optional[str]
    notable_discussions: Optional[str]
    emerging_patterns: Optional[str]
    ecosystem_health: Optional[str]
    contributors_spotlight: Optional[str]
    file_path: Path
    
    @property
    def has_content(self) -> bool:
        """Check if summary has meaningful content."""
        return any([
            self.overall_activity,
            self.key_achievements,
            self.ongoing_initiatives,
            self.priority_items,
            self.notable_discussions,
            self.emerging_patterns,
            self.ecosystem_health,
            self.contributors_spotlight
        ])


@dataclass
class WeekData:
    """All activity for a specific week."""
    year: int
    week: int
    week_range: str
    repos: Dict[str, ReportData]  # repo_key -> ReportData
    group_summaries: Dict[str, GroupSummaryData] = None  # group_name -> GroupSummaryData
    
    def __post_init__(self):
        if self.group_summaries is None:
            self.group_summaries = {}
    
    @property
    def activity_level(self) -> int:
        """Calculate activity level based on content."""
        level = 0
        for repo in self.repos.values():
            # Count non-empty sections
            if repo.overall_activity:
                level += 2
            if repo.ongoing_projects:
                level += 3
            if repo.priority_items:
                level += 3
            if repo.contributors:
                level += 1
            if repo.emerging_trends:
                level += 2
        
        # Add bonus for group summaries
        if self.group_summaries:
            for summary in self.group_summaries.values():
                if summary.has_content:
                    level += 3
        
        return level


def parse_group_summary(file_path: Path, group_name: str) -> Optional[GroupSummaryData]:
    """Parse a group summary JSON file."""
    try:
        # Extract year, week from filename
        # Expected: data/summaries/groups/{group}/week-{week}-{year}.json or
        #           data/reports/groups/{group}/week-{week}-{year}.json
        filename = file_path.stem  # removes .json
        if not filename.startswith('week-'):
            return None
        
        # Parse week-NN-YYYY format
        parts = filename.split('-')
        if len(parts) != 3:
            return None
            
        week = int(parts[1])
        year = int(parts[2])
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        week_range = data.get('week_range', format_week_range(year, week))
        
        return GroupSummaryData(
            group=group_name,
            year=year,
            week=week,
            week_range=week_range,
            repositories_included=data.get('repositories_included', []),
            short_summary=data.get('short_summary'),
            overall_activity=data.get('overall_activity'),
            key_achievements=data.get('key_achievements'),
            ongoing_initiatives=data.get('ongoing_initiatives'),
            priority_items=data.get('priority_items'),
            notable_discussions=data.get('notable_discussions'),
            emerging_patterns=data.get('emerging_patterns'),
            ecosystem_health=data.get('ecosystem_health'),
            contributors_spotlight=data.get('contributors_spotlight'),
            file_path=file_path
        )
        
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        error(f"Error parsing group summary {file_path}: {e}")
        return None


def parse_json_report(file_path: Path) -> Optional[ReportData]:
    """Parse a single JSON report file."""
    try:
        # Extract org, repo from path
        # Expected: data/reports/{org}/{repo}/week-{week}-{year}.json
        parts = file_path.parts
        if len(parts) < 4 or not file_path.name.startswith('week-'):
            return None
            
        org = parts[-3]
        repo_name = parts[-2]
        
        # Read JSON content
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return ReportData(
            org=org,
            repo=repo_name,
            year=data.get('year', 0),
            week=data.get('week', 0),
            week_range=data.get('week_range', ''),
            overall_activity=data.get('overall_activity'),
            ongoing_projects=data.get('ongoing_projects'),
            priority_items=data.get('priority_items'),
            notable_discussions=data.get('notable_discussions'),
            emerging_trends=data.get('emerging_trends'),
            good_first_issues=data.get('good_first_issues'),
            contributors=data.get('contributors'),
            file_path=file_path
        )
        
    except Exception as e:
        error(f"Failed to parse {file_path}: {e}")
        return None


def collect_all_reports(data_dir: Path) -> Tuple[List[ReportData], Dict[str, List[GroupSummaryData]]]:
    """Collect and parse all JSON report files and group summaries."""
    reports = []
    reports_dir = data_dir / "reports"
    
    if reports_dir.exists():
        # Find all .json files in reports directory (excluding groups)
        for report_file in reports_dir.rglob("*.json"):
            # Skip files in groups directory
            if "groups" not in report_file.parts:
                report_data = parse_json_report(report_file)
                if report_data and report_data.has_content:
                    reports.append(report_data)
    
    # Collect group summaries
    group_summaries = {}
    
    # First try to load from reports/groups (annotated)
    reports_groups_dir = data_dir / "reports" / "groups"
    if reports_groups_dir.exists():
        for group_dir in reports_groups_dir.iterdir():
            if group_dir.is_dir():
                group_name = group_dir.name
                group_summaries[group_name] = []
                for summary_file in group_dir.glob("*.json"):
                    summary_data = parse_group_summary(summary_file, group_name)
                    if summary_data and summary_data.has_content:
                        group_summaries[group_name].append(summary_data)
    
    # Fallback to original summaries if no annotated ones exist
    if not group_summaries:
        summaries_groups_dir = data_dir / "summaries" / "groups"
        if summaries_groups_dir.exists():
            for group_dir in summaries_groups_dir.iterdir():
                if group_dir.is_dir():
                    group_name = group_dir.name
                    group_summaries[group_name] = []
                    for summary_file in group_dir.glob("*.json"):
                        summary_data = parse_group_summary(summary_file, group_name)
                        if summary_data and summary_data.has_content:
                            group_summaries[group_name].append(summary_data)
    
    # Sort reports by year, week, org, repo
    reports.sort(key=lambda x: (x.year, x.week, x.org, x.repo))
    
    # Sort group summaries by year and week
    for group_name in group_summaries:
        group_summaries[group_name].sort(key=lambda x: (x.year, x.week))
    
    return reports, group_summaries


def organize_by_weeks(reports: List[ReportData], group_summaries: Dict[str, List[GroupSummaryData]]) -> Dict[Tuple[int, int], WeekData]:
    """Organize reports and group summaries by (year, week)."""
    weeks = {}
    
    for report in reports:
        week_key = (report.year, report.week)
        repo_key = f"{report.org}/{report.repo}"
        
        if week_key not in weeks:
            weeks[week_key] = WeekData(
                year=report.year,
                week=report.week,
                week_range=report.week_range,
                repos={},
                group_summaries={}
            )
        
        weeks[week_key].repos[repo_key] = report
    
    # Add group summaries
    for group_name, summaries in group_summaries.items():
        for summary in summaries:
            week_key = (summary.year, summary.week)
            
            if week_key not in weeks:
                weeks[week_key] = WeekData(
                    year=summary.year,
                    week=summary.week,
                    week_range=summary.week_range,
                    repos={},
                    group_summaries={}
                )
            
            weeks[week_key].group_summaries[group_name] = summary
    
    return weeks


def get_all_repos(reports: List[ReportData]) -> Set[str]:
    """Get all unique repository names."""
    return set(f"{r.org}/{r.repo}" for r in reports)


def generate_calendar_html(weeks_data: Dict[Tuple[int, int], WeekData], all_repos: Set[str]) -> str:
    """Generate the main calendar HTML with improved layout."""
    # Sort weeks chronologically
    sorted_weeks = sorted(weeks_data.items(), reverse=True)  # Most recent first
    
    if not sorted_weeks:
        return "<p>No reports found</p>"
    
    # Group weeks by year for better organization
    years = defaultdict(list)
    for (year, week), week_data in sorted_weeks:
        years[year].append((week, week_data))
    
    html_parts = []
    
    # Generate calendar for each year
    for year in sorted(years.keys(), reverse=True):
        year_weeks = sorted(years[year], reverse=True)
        
        html_parts.append('<div class="year-section">')
        html_parts.append(f'<h2 class="year-header">{year}</h2>')
        html_parts.append('<div class="calendar-grid">')
        
        for week_num, week_data in year_weeks:
            # Determine activity intensity class
            activity_class = get_activity_class(week_data.activity_level)
            
            # Create navigation links
            prev_week, next_week = get_adjacent_weeks(sorted_weeks, (year, week_num))
            
            # Create summary content - prioritize group summaries if available
            summary_content = ''
            if week_data.group_summaries:
                # Use group summaries
                group_items = []
                for group_name in sorted(week_data.group_summaries.keys())[:2]:
                    summary = week_data.group_summaries[group_name]
                    if summary.short_summary:
                        text = summary.short_summary
                        if len(text) > 80:
                            text = text[:77] + "..."
                        group_items.append(f'{group_name}: {text}')
                
                if len(week_data.group_summaries) > 2:
                    group_items.append(f'+{len(week_data.group_summaries) - 2} more groups')
                
                summary_content = ' • '.join(group_items)
            else:
                # Fall back to individual repo summaries
                repo_items = []
                for repo in sorted(week_data.repos.keys())[:3]:
                    report = week_data.repos[repo]
                    summary = report.summary_text
                    if len(summary) > 60:
                        summary = summary[:57] + "..."
                    repo_items.append(f'{repo}: {summary}')
                
                if len(week_data.repos) > 3:
                    repo_items.append(f'+{len(week_data.repos) - 3} more repos')
                
                summary_content = ' • '.join(repo_items)
            
            # Repo count indicator
            repo_count_html = f'<span class="repo-count">{len(week_data.repos)} repos'
            if week_data.group_summaries:
                repo_count_html += f' • 📊 {len(week_data.group_summaries)} groups'
            repo_count_html += '</span>'
            
            # Create week card
            html_parts.append(f'''
            <div class="week-card {activity_class}" data-week="{year}-{week_num:02d}" data-repos="{' '.join(week_data.repos.keys())}">
                <a href="weeks/{year}-{week_num:02d}.html" class="week-link">
                    <div class="week-header">
                        <div class="week-number">Week {week_num}</div>
                        <div class="week-dates">{week_data.week_range}</div>
                    </div>
                    <div class="week-content">
                        {repo_count_html}
                        <div class="week-summary">{summary_content}</div>
                    </div>
                </a>
            </div>
            ''')
        
        html_parts.append('</div>')  # calendar-grid
        html_parts.append('</div>')  # year-section
    
    return '\n'.join(html_parts)


def get_activity_class(activity_level: int) -> str:
    """Get CSS class based on activity level."""
    if activity_level == 0:
        return "activity-none"
    elif activity_level < 5:
        return "activity-low"
    elif activity_level < 10:
        return "activity-medium"
    elif activity_level < 20:
        return "activity-high"
    else:
        return "activity-very-high"


def get_adjacent_weeks(sorted_weeks: List[Tuple[Tuple[int, int], WeekData]], current_week: Tuple[int, int]) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Get the previous and next week keys."""
    week_keys = [week_key for week_key, _ in sorted_weeks]
    
    try:
        current_idx = week_keys.index(current_week)
        # Note: list is reverse sorted, so prev is actually next in list
        prev_week = week_keys[current_idx + 1] if current_idx < len(week_keys) - 1 else None
        next_week = week_keys[current_idx - 1] if current_idx > 0 else None
        return prev_week, next_week
    except ValueError:
        return None, None


def format_markdown_section(content: Optional[str]) -> str:
    """Convert markdown content to HTML using markdown2."""
    if not content:
        return ""
    
    # Configure markdown2 with useful extras
    # - fenced-code-blocks: Support for ```code``` blocks
    # - tables: Support for tables
    # - strike: Support for ~~strikethrough~~
    # - target-blank-links: Add target="_blank" to links automatically
    # - nofollow: Add rel="noopener" for security
    extras = [
        "fenced-code-blocks",
        "tables", 
        "strike",
        "target-blank-links",
        "nofollow",
        "code-friendly",
        "cuddled-lists"
    ]
    
    # Convert markdown to HTML
    html = markdown2.markdown(content, extras=extras)
    
    # Post-process to ensure all external links open in new tab with security
    # (markdown2's target-blank-links should handle this, but let's be sure)
    html = re.sub(
        r'<a href="(https?://[^"]+)"([^>]*)>',
        r'<a href="\1" target="_blank" rel="noopener"\2>',
        html
    )
    
    # Ensure GitHub issue/PR links have proper attributes
    html = re.sub(
        r'<a href="(https://github\.com/[^"]+)"([^>]*)>',
        r'<a href="\1" target="_blank" rel="noopener"\2>',
        html
    )
    
    return html


def generate_week_detail_html(week_data: WeekData, prev_week: Optional[Tuple[int, int]], next_week: Optional[Tuple[int, int]]) -> str:
    """Generate HTML for a specific week detail page with table of contents."""
    # Navigation
    nav_links = ['<a href="../index.html" class="nav-link">← Calendar</a>']
    if prev_week:
        nav_links.append(f'<a href="{prev_week[0]}-{prev_week[1]:02d}.html" class="nav-link">← Week {prev_week[1]}</a>')
    if next_week:
        nav_links.append(f'<a href="{next_week[0]}-{next_week[1]:02d}.html" class="nav-link">Week {next_week[1]} →</a>')
    
    nav_html = ' | '.join(nav_links)
    
    # Generate table of contents
    toc_items = []
    
    # Add group summaries to TOC if available
    if week_data.group_summaries:
        for group_name in sorted(week_data.group_summaries.keys()):
            toc_items.append(f'<li><a href="#group-{group_name}">📊 {group_name.upper()} Summary</a></li>')
    
    for repo in sorted(week_data.repos.keys()):
        repo_id = repo.replace('/', '-')
        toc_items.append(f'<li><a href="#{repo_id}">{repo}</a></li>')
    
    toc_html = f'''
    <div class="toc">
        <h2>Contents</h2>
        <ul>
            {''.join(toc_items)}
        </ul>
    </div>
    ''' if (len(week_data.repos) > 1 or week_data.group_summaries) else ''
    
    # Group summaries section
    group_summaries_html = []
    if week_data.group_summaries:
        for group_name in sorted(week_data.group_summaries.keys()):
            summary = week_data.group_summaries[group_name]
            summary_sections = []
            
            if summary.short_summary:
                summary_sections.append(f'''
                <div class="summary-highlight">
                    <p class="short-summary">{summary.short_summary}</p>
                </div>
                ''')
            
            if summary.overall_activity:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Overall Activity</h3>
                    {format_markdown_section(summary.overall_activity)}
                </div>
                ''')
            
            if summary.key_achievements:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Key Achievements</h3>
                    {format_markdown_section(summary.key_achievements)}
                </div>
                ''')
            
            if summary.ongoing_initiatives:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Ongoing Initiatives</h3>
                    {format_markdown_section(summary.ongoing_initiatives)}
                </div>
                ''')
            
            if summary.priority_items:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Priority Items</h3>
                    {format_markdown_section(summary.priority_items)}
                </div>
                ''')
            
            if summary.notable_discussions:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Notable Discussions</h3>
                    {format_markdown_section(summary.notable_discussions)}
                </div>
                ''')
            
            if summary.emerging_patterns:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Emerging Patterns</h3>
                    {format_markdown_section(summary.emerging_patterns)}
                </div>
                ''')
            
            if summary.ecosystem_health:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Ecosystem Health</h3>
                    {format_markdown_section(summary.ecosystem_health)}
                </div>
                ''')
            
            if summary.contributors_spotlight:
                summary_sections.append(f'''
                <div class="section">
                    <h3>Contributors Spotlight</h3>
                    {format_markdown_section(summary.contributors_spotlight)}
                </div>
                ''')
            
            repos_included = ', '.join(summary.repositories_included) if summary.repositories_included else 'All repositories'
            
            group_summaries_html.append(f'''
            <section class="group-summary-section" id="group-{group_name}">
                <div class="group-summary-header">
                    <h2 class="group-summary-title">📊 {group_name.upper()} Summary</h2>
                    <div class="summary-meta">
                        <span class="repos-included">Repositories: {repos_included}</span>
                    </div>
                </div>
                <div class="group-summary-content">
                    {''.join(summary_sections)}
                </div>
            </section>
            ''')

    # Repository sections
    repo_sections = []
    for repo in sorted(week_data.repos.keys()):
        report = week_data.repos[repo]
        repo_id = repo.replace('/', '-')
        
        # Build content sections
        sections = []
        
        if report.overall_activity:
            sections.append(f'''
            <div class="section">
                <h3>Overall Activity</h3>
                {format_markdown_section(report.overall_activity)}
            </div>
            ''')
        
        if report.ongoing_projects:
            sections.append(f'''
            <div class="section">
                <h3>Ongoing Projects</h3>
                {format_markdown_section(report.ongoing_projects)}
            </div>
            ''')
        
        if report.priority_items:
            sections.append(f'''
            <div class="section">
                <h3>Priority Items</h3>
                {format_markdown_section(report.priority_items)}
            </div>
            ''')
        
        if report.notable_discussions:
            sections.append(f'''
            <div class="section">
                <h3>Notable Discussions</h3>
                {format_markdown_section(report.notable_discussions)}
            </div>
            ''')
        
        if report.emerging_trends:
            sections.append(f'''
            <div class="section">
                <h3>Emerging Trends</h3>
                {format_markdown_section(report.emerging_trends)}
            </div>
            ''')
        
        if report.good_first_issues:
            sections.append(f'''
            <div class="section">
                <h3>Good First Issues</h3>
                {format_markdown_section(report.good_first_issues)}
            </div>
            ''')
        
        if report.contributors:
            sections.append(f'''
            <div class="section">
                <h3>Contributors</h3>
                {format_markdown_section(report.contributors)}
            </div>
            ''')
        
        repo_sections.append(f'''
        <section class="repo-section" id="{repo_id}">
            <div class="repo-header">
                <h2 class="repo-title">
                    <a href="https://github.com/{repo}" target="_blank" rel="noopener">{repo}</a>
                </h2>
            </div>
            <div class="repo-content">
                {''.join(sections)}
            </div>
        </section>
        ''')
    
    return f'''
    <div class="week-detail">
        <header class="page-header">
            <h1>Week {week_data.week}, {week_data.year}</h1>
            <div class="week-meta">
                <span class="date-range">{week_data.week_range}</span>
                <span class="repo-count">{len(week_data.repos)} repositories</span>
            </div>
            <nav class="week-nav">
                {nav_html}
            </nav>
        </header>
        
        {toc_html}
        
        <main class="repos-container">
            {''.join(group_summaries_html)}
            {''.join(repo_sections)}
        </main>
    </div>
    '''


def generate_main_template() -> str:
    """Generate the main HTML template."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{title}}</title>
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header class="main-header">
        <h1 class="project-title">{{project_name}}</h1>
        <div class="project-meta">
            <span class="description">{{project_description}}</span>
            <span class="generated">Updated: {{generated_date}}</span>
        </div>
        <div class="controls">
            <div class="filters">
                <input type="text" id="repo-filter" placeholder="Filter repositories..." class="filter-input">
                <select id="year-filter" class="filter-select">
                    <option value="">All years</option>
                    {{year_options}}
                </select>
            </div>
            <div class="stats">
                <span class="stat-item">{{total_weeks}} weeks</span>
                <span class="stat-item">{{total_repos}} repos</span>
            </div>
        </div>
    </header>
    
    <main class="calendar-container">
        {{calendar_content}}
    </main>
    
    <footer class="main-footer">
        <p>Generated by <a href="https://github.com/avsm/ruminant">Ruminant</a></p>
    </footer>
    
    <script src="assets/script.js"></script>
</body>
</html>'''


def generate_week_template() -> str:
    """Generate the week detail HTML template."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{week_title}}</title>
    <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
    <div class="week-page">
        {{week_content}}
    </div>
    <script src="../assets/script.js"></script>
</body>
</html>'''


def website_main(
    output_dir: Optional[str] = typer.Option("website", "--output", "-o", help="Output directory for website"),
) -> None:
    """Generate static HTML website from JSON reports."""
    
    try:
        config = load_config()
        data_dir = get_data_dir()
        output_path = Path(output_dir)
        
        step("Collecting and parsing JSON report files...")
        reports, group_summaries = collect_all_reports(data_dir)
        
        if not reports and not group_summaries:
            error("No JSON report files or group summaries found. Run 'ruminant annotate' and/or generate group summaries first.")
            raise typer.Exit(1)
        
        total_group_summaries = sum(len(summaries) for summaries in group_summaries.values())
        info(f"Found {len(reports)} report files and {total_group_summaries} group summaries across {len(group_summaries)} groups")
        
        step("Organizing data by weeks...")
        weeks_data = organize_by_weeks(reports, group_summaries)
        all_repos = get_all_repos(reports)
        
        info(f"Organized {len(weeks_data)} weeks across {len(all_repos)} repositories")
        
        # Create output directory structure
        step("Creating website directory structure...")
        output_path.mkdir(exist_ok=True)
        (output_path / "assets").mkdir(exist_ok=True)
        (output_path / "weeks").mkdir(exist_ok=True)
        
        # Generate CSS and JS
        step("Generating assets...")
        (output_path / "assets" / "style.css").write_text(generate_css())
        (output_path / "assets" / "script.js").write_text(generate_javascript())
        
        # Generate main calendar page
        step("Generating main calendar page...")
        calendar_html = generate_calendar_html(weeks_data, all_repos)
        
        # Get years for filter dropdown
        years = sorted(set(year for (year, week) in weeks_data.keys()), reverse=True)
        year_options = '\n'.join(f'<option value="{year}">{year}</option>' for year in years)
        
        main_html = generate_main_template()
        main_html = main_html.replace('{{title}}', f"{config.project_name} - Activity Dashboard")
        main_html = main_html.replace('{{project_name}}', config.project_name)
        main_html = main_html.replace('{{project_description}}', config.project_description)
        main_html = main_html.replace('{{generated_date}}', datetime.now().strftime('%Y-%m-%d %H:%M'))
        main_html = main_html.replace('{{calendar_content}}', calendar_html)
        main_html = main_html.replace('{{year_options}}', year_options)
        main_html = main_html.replace('{{total_weeks}}', str(len(weeks_data)))
        main_html = main_html.replace('{{total_repos}}', str(len(all_repos)))
        
        (output_path / "index.html").write_text(main_html)
        
        # Generate week detail pages
        step("Generating week detail pages...")
        sorted_weeks = sorted(weeks_data.items())
        
        for i, ((year, week), week_data) in enumerate(sorted_weeks):
            prev_week = sorted_weeks[i-1][0] if i > 0 else None
            next_week = sorted_weeks[i+1][0] if i < len(sorted_weeks) - 1 else None
            
            week_html = generate_week_detail_html(week_data, prev_week, next_week)
            week_template = generate_week_template()
            week_page = week_template.replace('{{week_title}}', f"Week {week}, {year} - {config.project_name}")
            week_page = week_page.replace('{{week_content}}', week_html)
            
            week_filename = f"{year}-{week:02d}.html"
            (output_path / "weeks" / week_filename).write_text(week_page)
        
        success(f"Website generated successfully in {output_path}")
        success(f"Generated {len(sorted_weeks)} week pages")
        info(f"Open {output_path}/index.html in your browser")
        
    except Exception as e:
        error(f"Website generation failed: {e}")
        raise typer.Exit(1)


def generate_css() -> str:
    """Generate improved CSS with better layout and typography."""
    return '''/* Modern, clean website styling */
:root {
    --primary-color: #0066cc;
    --secondary-color: #666;
    --background: #f8f9fa;
    --card-bg: #ffffff;
    --border-color: #dee2e6;
    --text-primary: #212529;
    --text-secondary: #6c757d;
    --activity-none: #f8f9fa;
    --activity-low: #d1f2eb;
    --activity-medium: #81e4cd;
    --activity-high: #52d3aa;
    --activity-very-high: #22c58b;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    background: var(--background);
    color: var(--text-primary);
}

/* Main Header */
.main-header {
    background: var(--card-bg);
    border-bottom: 1px solid var(--border-color);
    padding: 1.5rem;
    position: sticky;
    top: 0;
    z-index: 1000;
    box-shadow: 0 2px 4px rgba(0,0,0,0.04);
}

.project-title {
    font-size: 1.75rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
}

.project-meta {
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-bottom: 1rem;
    display: flex;
    gap: 1rem;
    align-items: center;
}

.controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 1rem;
}

.filters {
    display: flex;
    gap: 0.75rem;
    align-items: center;
}

.filter-input, .filter-select {
    font-size: 0.875rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: 0.375rem;
    background: var(--card-bg);
    transition: border-color 0.15s ease;
}

.filter-input:focus, .filter-select:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.1);
}

.filter-input {
    width: 200px;
}

.stats {
    display: flex;
    gap: 1rem;
    font-size: 0.875rem;
}

.stat-item {
    color: var(--text-secondary);
    font-weight: 500;
}

/* Calendar Container */
.calendar-container {
    padding: 1.5rem;
    max-width: 1400px;
    margin: 0 auto;
}

.year-section {
    margin-bottom: 2rem;
}

.year-header {
    font-size: 1.25rem;
    font-weight: 600;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid var(--border-color);
    color: var(--text-primary);
}

.calendar-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1rem;
}

/* Week Cards */
.week-card {
    border: 1px solid var(--border-color);
    border-radius: 0.5rem;
    background: var(--card-bg);
    transition: all 0.2s ease;
    overflow: hidden;
}

.week-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

.week-card.hidden {
    display: none;
}

.week-link {
    display: block;
    text-decoration: none;
    color: inherit;
    padding: 1rem;
}

.week-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border-color);
}

.week-number {
    font-size: 1.125rem;
    font-weight: 600;
    color: var(--text-primary);
}

.week-dates {
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
}

.repo-count {
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
    font-weight: 500;
}

.repos-list {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}

.repo-item {
    font-size: 0.8125rem;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.repo-name {
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    color: var(--primary-color);
    font-weight: 500;
}

.repo-item.more {
    font-style: italic;
    color: var(--text-secondary);
    opacity: 0.7;
}

/* Activity Colors */
.activity-none {
    background: var(--activity-none);
}

.activity-low {
    background: linear-gradient(135deg, #ffffff 0%, var(--activity-low) 100%);
}

.activity-medium {
    background: linear-gradient(135deg, #ffffff 0%, var(--activity-medium) 100%);
}

.activity-high {
    background: linear-gradient(135deg, #ffffff 0%, var(--activity-high) 100%);
}

.activity-very-high {
    background: linear-gradient(135deg, #ffffff 0%, var(--activity-very-high) 100%);
}

/* Week Detail Pages */
.week-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 1.5rem;
}

.page-header {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 0.5rem;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.page-header h1 {
    font-size: 1.75rem;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}

.week-meta {
    font-size: 0.875rem;
    color: var(--text-secondary);
    display: flex;
    gap: 1.5rem;
    margin-bottom: 1rem;
}

.week-nav {
    display: flex;
    gap: 1rem;
    font-size: 0.875rem;
}

.nav-link {
    color: var(--primary-color);
    text-decoration: none;
    padding: 0.375rem 0.75rem;
    border-radius: 0.25rem;
    background: var(--background);
    transition: background-color 0.15s ease;
}

.nav-link:hover {
    background: var(--border-color);
}

/* Table of Contents */
.toc {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 0.5rem;
    padding: 1rem;
    margin-bottom: 1.5rem;
}

.toc h2 {
    font-size: 1rem;
    margin-bottom: 0.75rem;
    color: var(--text-primary);
}

.toc ul {
    list-style: none;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 0.5rem;
}

.toc a {
    color: var(--primary-color);
    text-decoration: none;
    font-size: 0.875rem;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
}

.toc a:hover {
    text-decoration: underline;
}

/* Group Summary Sections */
.group-summary-section {
    border: 2px solid var(--primary-color);
    border-radius: 0.5rem;
    background: var(--card-bg);
    overflow: hidden;
    margin-bottom: 1.5rem;
}

.group-summary-header {
    background: linear-gradient(135deg, var(--primary-color) 0%, #0099ff 100%);
    padding: 1rem 1.5rem;
    color: white;
}

.group-summary-title {
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
}

.summary-meta {
    font-size: 0.875rem;
    opacity: 0.9;
}

.group-summary-content {
    padding: 1.5rem;
}

.summary-highlight {
    background: var(--background);
    border-left: 4px solid var(--primary-color);
    padding: 1rem;
    margin-bottom: 1.5rem;
    border-radius: 0.25rem;
}

.short-summary {
    font-size: 1.125rem;
    font-weight: 500;
    color: var(--text-primary);
    margin: 0;
}

/* Repository Sections */
.repos-container {
    display: grid;
    gap: 1.5rem;
}

.repo-section {
    border: 1px solid var(--border-color);
    border-radius: 0.5rem;
    background: var(--card-bg);
    overflow: hidden;
}

.repo-header {
    background: linear-gradient(135deg, var(--background) 0%, #ffffff 100%);
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border-color);
}

.repo-title {
    font-size: 1.25rem;
    font-weight: 600;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
}

.repo-title a {
    color: var(--primary-color);
    text-decoration: none;
}

.repo-title a:hover {
    text-decoration: underline;
}

.repo-content {
    padding: 1.5rem;
}

.section {
    margin-bottom: 1.5rem;
}

.section:last-child {
    margin-bottom: 0;
}

.section h3 {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.75rem;
    color: var(--text-primary);
    padding-bottom: 0.25rem;
    border-bottom: 1px solid var(--border-color);
}

.section p {
    margin-bottom: 0.75rem;
    color: var(--text-primary);
    line-height: 1.6;
}

.section ul {
    margin: 0.75rem 0 0.75rem 1.5rem;
}

.section li {
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}

.section code {
    background: var(--background);
    border: 1px solid var(--border-color);
    border-radius: 0.25rem;
    padding: 0.125rem 0.25rem;
    font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
    font-size: 0.875em;
}

.section pre {
    background: var(--background);
    border: 1px solid var(--border-color);
    border-radius: 0.375rem;
    padding: 1rem;
    overflow-x: auto;
    margin: 1rem 0;
}

.section pre code {
    background: none;
    border: none;
    padding: 0;
}

.section a {
    color: var(--primary-color);
    text-decoration: none;
}

.section a:hover {
    text-decoration: underline;
}

.section strong {
    font-weight: 600;
    color: var(--text-primary);
}

/* Footer */
.main-footer {
    text-align: center;
    padding: 2rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
    border-top: 1px solid var(--border-color);
    margin-top: 3rem;
}

.main-footer a {
    color: var(--primary-color);
    text-decoration: none;
}

/* Responsive Design */
@media (max-width: 768px) {
    .calendar-grid {
        grid-template-columns: 1fr;
    }
    
    .controls {
        flex-direction: column;
        align-items: stretch;
    }
    
    .filters {
        width: 100%;
    }
    
    .filter-input {
        flex: 1;
    }
    
    .toc ul {
        grid-template-columns: 1fr;
    }
}

/* Print Styles */
@media print {
    .nav-link, .controls, .main-footer {
        display: none;
    }
    
    .week-card {
        break-inside: avoid;
    }
    
    body {
        font-size: 11pt;
    }
}

/* Animations */
@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.week-card {
    animation: fadeIn 0.3s ease;
}'''


def generate_javascript() -> str:
    """Generate improved JavaScript with better filtering."""
    return '''// Enhanced filtering and navigation
document.addEventListener('DOMContentLoaded', function() {
    const repoFilter = document.getElementById('repo-filter');
    const yearFilter = document.getElementById('year-filter');
    const weekCards = document.querySelectorAll('.week-card');
    
    function filterWeeks() {
        const repoQuery = repoFilter?.value.toLowerCase() || '';
        const yearQuery = yearFilter?.value || '';
        
        let visibleCount = 0;
        
        weekCards.forEach(card => {
            const weekData = card.dataset.week || '';
            const repos = card.dataset.repos || '';
            
            let showCard = true;
            
            // Year filter
            if (yearQuery && !weekData.startsWith(yearQuery)) {
                showCard = false;
            }
            
            // Repository filter
            if (repoQuery && showCard) {
                if (!repos.toLowerCase().includes(repoQuery)) {
                    showCard = false;
                }
            }
            
            // Show/hide card with animation
            if (showCard) {
                card.classList.remove('hidden');
                card.style.animationDelay = `${visibleCount * 0.02}s`;
                visibleCount++;
            } else {
                card.classList.add('hidden');
            }
        });
        
        updateStats(visibleCount);
    }
    
    function updateStats(visibleCount) {
        const stats = document.querySelector('.stats');
        if (stats) {
            const totalWeeks = weekCards.length;
            if (visibleCount !== totalWeeks) {
                let filterStat = stats.querySelector('.filter-stat');
                if (!filterStat) {
                    filterStat = document.createElement('span');
                    filterStat.className = 'stat-item filter-stat';
                    stats.appendChild(filterStat);
                }
                filterStat.textContent = `Showing ${visibleCount} of ${totalWeeks} weeks`;
            } else {
                const filterStat = stats.querySelector('.filter-stat');
                if (filterStat) {
                    filterStat.remove();
                }
            }
        }
    }
    
    // Attach event listeners
    if (repoFilter) {
        repoFilter.addEventListener('input', filterWeeks);
        
        // Add clear button
        if (repoFilter.value) {
            addClearButton(repoFilter);
        }
        
        repoFilter.addEventListener('input', function() {
            if (this.value) {
                addClearButton(this);
            } else {
                removeClearButton(this);
            }
        });
    }
    
    if (yearFilter) {
        yearFilter.addEventListener('change', filterWeeks);
    }
    
    function addClearButton(input) {
        if (!input.nextElementSibling || !input.nextElementSibling.classList.contains('clear-btn')) {
            const clearBtn = document.createElement('button');
            clearBtn.className = 'clear-btn';
            clearBtn.innerHTML = '×';
            clearBtn.onclick = function() {
                input.value = '';
                filterWeeks();
                removeClearButton(input);
            };
            input.parentNode.style.position = 'relative';
            input.parentNode.insertBefore(clearBtn, input.nextSibling);
        }
    }
    
    function removeClearButton(input) {
        const clearBtn = input.nextElementSibling;
        if (clearBtn && clearBtn.classList.contains('clear-btn')) {
            clearBtn.remove();
        }
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Focus filter on '/' key
        if (e.key === '/' && document.activeElement !== repoFilter) {
            e.preventDefault();
            if (repoFilter) {
                repoFilter.focus();
                repoFilter.select();
            }
        }
        
        // Clear filters on Escape
        if (e.key === 'Escape') {
            if (repoFilter) {
                repoFilter.value = '';
                removeClearButton(repoFilter);
            }
            if (yearFilter) {
                yearFilter.value = '';
            }
            filterWeeks();
            
            // Unfocus any input
            if (document.activeElement) {
                document.activeElement.blur();
            }
        }
    });
    
    // Initialize
    updateStats(weekCards.length);
});

// Week detail page enhancements
if (window.location.pathname.includes('/weeks/')) {
    document.addEventListener('DOMContentLoaded', function() {
        // Add smooth scrolling for TOC links
        const tocLinks = document.querySelectorAll('.toc a');
        tocLinks.forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                const targetId = this.getAttribute('href').substring(1);
                const targetElement = document.getElementById(targetId);
                if (targetElement) {
                    targetElement.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                    
                    // Add highlight effect
                    targetElement.classList.add('highlight');
                    setTimeout(() => {
                        targetElement.classList.remove('highlight');
                    }, 2000);
                }
            });
        });
        
        // Keyboard navigation
        document.addEventListener('keydown', function(e) {
            // Navigate between weeks with arrow keys
            if (e.key === 'ArrowLeft') {
                const prevLink = document.querySelector('.nav-link:nth-child(2)');
                if (prevLink && prevLink.textContent.includes('Week')) {
                    window.location.href = prevLink.href;
                }
            } else if (e.key === 'ArrowRight') {
                const nextLink = document.querySelector('.nav-link:last-child');
                if (nextLink && nextLink.textContent.includes('Week')) {
                    window.location.href = nextLink.href;
                }
            }
            
            // Go back to calendar with 'c' key
            if (e.key === 'c' && !e.ctrlKey && !e.metaKey) {
                window.location.href = '../index.html';
            }
        });
    });
}

// Add some CSS for dynamic elements
const style = document.createElement('style');
style.textContent = `
    .clear-btn {
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        background: none;
        border: none;
        font-size: 20px;
        color: #999;
        cursor: pointer;
        padding: 0 4px;
        line-height: 1;
    }
    
    .clear-btn:hover {
        color: #666;
    }
    
    .highlight {
        animation: highlight 2s ease;
    }
    
    @keyframes highlight {
        0% { background-color: rgba(0, 102, 204, 0.2); }
        100% { background-color: transparent; }
    }
`;
document.head.appendChild(style);'''