"""Website command for generating static HTML from summaries."""

import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

import typer

from ..config import load_config
from ..utils.dates import get_week_date_range, format_week_range
from ..utils.paths import get_data_dir
from ..utils.logging import success, error, info, step


@dataclass
class SummaryData:
    """Structured data from a summary file."""
    org: str
    repo: str
    year: int
    week: int
    date_range: str
    title: str
    content: str
    file_path: Path
    summary_text: str  # Brief summary for calendar view


@dataclass
class WeekData:
    """All activity for a specific week."""
    year: int
    week: int
    date_range: str
    repos: Dict[str, SummaryData]  # repo_key -> SummaryData
    total_activity: int = 0


def parse_summary_file(file_path: Path) -> Optional[SummaryData]:
    """Parse a single report markdown file."""
    try:
        # Extract org, repo, year, week from path
        # Expected: data/reports/{org}/{repo}/week-{week}-{year}.md
        parts = file_path.parts
        if len(parts) < 4 or not file_path.name.startswith('week-'):
            return None
            
        org = parts[-3]
        repo = parts[-2]
        
        # Parse week-{week}-{year}.md
        week_match = re.match(r'week-(\d+)-(\d+)\.md', file_path.name)
        if not week_match:
            return None
            
        week = int(week_match.group(1))
        year = int(week_match.group(2))
        
        # Read and parse content
        content = file_path.read_text(encoding='utf-8')
        
        # Extract title (first line starting with #)
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else f"{org}/{repo} Week {week} {year}"
        
        # Extract date range from title or generate it
        date_range_match = re.search(r'(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})', title)
        if date_range_match:
            date_range = f"{date_range_match.group(1)} to {date_range_match.group(2)}"
        else:
            date_range = format_week_range(year, week)
        
        # Extract brief summary from "Overall Activity Summary" section
        summary_text = extract_brief_summary(content)
        
        return SummaryData(
            org=org,
            repo=repo,
            year=year,
            week=week,
            date_range=date_range,
            title=title,
            content=content,
            file_path=file_path,
            summary_text=summary_text
        )
        
    except Exception as e:
        error(f"Failed to parse {file_path}: {e}")
        return None


def extract_brief_summary(content: str) -> str:
    """Extract a brief summary from the markdown content."""
    # Look for "Overall Activity Summary" section
    summary_match = re.search(
        r'##\s+Overall Activity Summary\s*\n\n(.+?)(?=\n##|\n\n##|$)', 
        content, 
        re.DOTALL | re.IGNORECASE
    )
    
    if summary_match:
        summary = summary_match.group(1).strip()
        # Take first sentence or up to 150 characters
        first_sentence = re.split(r'[.!?]\s+', summary)[0]
        if len(first_sentence) > 150:
            first_sentence = first_sentence[:150] + "..."
        return first_sentence
    
    # Fallback: look for any activity count in the content
    activity_match = re.search(r'(\d+)\s+pull requests?', content, re.IGNORECASE)
    if activity_match:
        return f"{activity_match.group(1)} pull requests this week"
    
    return "Activity summary available"


def collect_all_summaries(data_dir: Path) -> List[SummaryData]:
    """Collect and parse all report files (post-processed with GitHub links)."""
    summaries = []
    reports_dir = data_dir / "reports"
    
    if not reports_dir.exists():
        return summaries
    
    # Find all .md files in reports directory (these have been annotated with GitHub links)
    for report_file in reports_dir.rglob("*.md"):
        summary_data = parse_summary_file(report_file)
        if summary_data:
            summaries.append(summary_data)
    
    # Sort by year, week, org, repo
    summaries.sort(key=lambda x: (x.year, x.week, x.org, x.repo))
    return summaries


def organize_by_weeks(summaries: List[SummaryData]) -> Dict[Tuple[int, int], WeekData]:
    """Organize summaries by (year, week)."""
    weeks = {}
    
    for summary in summaries:
        week_key = (summary.year, summary.week)
        repo_key = f"{summary.org}/{summary.repo}"
        
        if week_key not in weeks:
            weeks[week_key] = WeekData(
                year=summary.year,
                week=summary.week,
                date_range=summary.date_range,
                repos={}
            )
        
        weeks[week_key].repos[repo_key] = summary
    
    # Calculate activity levels based on content length and activity indicators
    for week_data in weeks.values():
        total_activity = 0
        for repo_summary in week_data.repos.values():
            # Simple heuristic: content length + PR mentions
            activity_score = len(repo_summary.content) // 1000  # 1 point per 1000 chars
            pr_matches = re.findall(r'\d+\s+pull requests?', repo_summary.content, re.IGNORECASE)
            if pr_matches:
                activity_score += sum(int(re.search(r'(\d+)', match).group(1)) for match in pr_matches) // 10
            total_activity += activity_score
        week_data.total_activity = total_activity
    
    return weeks


def get_all_repos(summaries: List[SummaryData]) -> Set[str]:
    """Get all unique repository names."""
    return set(f"{s.org}/{s.repo}" for s in summaries)


def generate_calendar_html(weeks_data: Dict[Tuple[int, int], WeekData], all_repos: Set[str]) -> str:
    """Generate the main calendar HTML."""
    # Sort weeks chronologically
    sorted_weeks = sorted(weeks_data.items())
    
    if not sorted_weeks:
        return "<p>No summaries found</p>"
    
    # Group weeks by year for better organization
    years = defaultdict(list)
    for (year, week), week_data in sorted_weeks:
        years[year].append((week, week_data))
    
    html_parts = []
    
    # Generate calendar for each year
    for year in sorted(years.keys()):
        year_weeks = sorted(years[year])
        
        html_parts.append(f'<div class="year-section">')
        html_parts.append(f'<h2 class="year-header">{year}</h2>')
        html_parts.append('<div class="calendar-grid">')
        
        for week_num, week_data in year_weeks:
            # Determine activity intensity class
            activity_class = get_activity_class(week_data.total_activity)
            
            # Create prev/next links
            prev_week, next_week = get_adjacent_weeks(sorted_weeks, (year, week_num))
            nav_links = []
            if prev_week:
                nav_links.append(f'<a href="weeks/{prev_week[0]}-{prev_week[1]:02d}.html" class="nav-link">←</a>')
            if next_week:
                nav_links.append(f'<a href="weeks/{next_week[0]}-{next_week[1]:02d}.html" class="nav-link">→</a>')
            
            nav_html = ' '.join(nav_links) if nav_links else ''
            
            # Create repo activity summary
            repo_summaries = []
            for repo in sorted(week_data.repos.keys()):
                repo_summary = week_data.repos[repo]
                repo_summaries.append(f'<div class="repo-item"><span class="repo-name">{repo}</span>: {repo_summary.summary_text}</div>')
            
            repos_html = ''.join(repo_summaries)
            
            html_parts.append(f'''
            <div class="week-card {activity_class}" data-week="{year}-{week_num:02d}">
                <div class="week-header">
                    <div class="week-info">
                        <div class="week-number">W{week_num}</div>
                        <div class="week-dates">{week_data.date_range}</div>
                    </div>
                    <div class="week-nav">{nav_html}</div>
                </div>
                <div class="week-content">
                    <a href="weeks/{year}-{week_num:02d}.html" class="week-link">
                        <div class="repo-count">{len(week_data.repos)} repos active</div>
                        <div class="repos-preview">{repos_html}</div>
                    </a>
                </div>
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
    elif activity_level < 15:
        return "activity-medium"
    elif activity_level < 30:
        return "activity-high"
    else:
        return "activity-very-high"


def get_adjacent_weeks(sorted_weeks: List[Tuple[Tuple[int, int], WeekData]], current_week: Tuple[int, int]) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Get the previous and next week keys."""
    week_keys = [week_key for week_key, _ in sorted_weeks]
    
    try:
        current_idx = week_keys.index(current_week)
        prev_week = week_keys[current_idx - 1] if current_idx > 0 else None
        next_week = week_keys[current_idx + 1] if current_idx < len(week_keys) - 1 else None
        return prev_week, next_week
    except ValueError:
        return None, None


def generate_week_detail_html(week_data: WeekData, prev_week: Optional[Tuple[int, int]], next_week: Optional[Tuple[int, int]]) -> str:
    """Generate HTML for a specific week detail page."""
    # Navigation
    nav_links = ['<a href="../index.html" class="nav-link">← Calendar</a>']
    if prev_week:
        nav_links.append(f'<a href="{prev_week[0]}-{prev_week[1]:02d}.html" class="nav-link">← W{prev_week[1]} {prev_week[0]}</a>')
    if next_week:
        nav_links.append(f'<a href="{next_week[0]}-{next_week[1]:02d}.html" class="nav-link">W{next_week[1]} {next_week[0]} →</a>')
    
    nav_html = ' '.join(nav_links)
    
    # Repository sections
    repo_sections = []
    for repo in sorted(week_data.repos.keys()):
        summary = week_data.repos[repo]
        # Convert markdown to basic HTML (simplified)
        content_html = markdown_to_html(summary.content)
        
        repo_sections.append(f'''
        <section class="repo-section">
            <div class="repo-header">
                <h2 class="repo-title">{repo}</h2>
                <div class="repo-meta">
                    <span class="file-path">{summary.file_path.name}</span>
                </div>
            </div>
            <div class="repo-content">
                {content_html}
            </div>
        </section>
        ''')
    
    return f'''
    <div class="week-detail">
        <header class="week-header">
            <h1>Week {week_data.week} {week_data.year}</h1>
            <div class="week-meta">
                <span class="date-range">{week_data.date_range}</span>
                <span class="repo-count">{len(week_data.repos)} repositories</span>
            </div>
        </header>
        
        <nav class="week-nav">
            {nav_html}
        </nav>
        
        <main class="repos-container">
            {''.join(repo_sections)}
        </main>
    </div>
    '''


def markdown_to_html(markdown_content: str) -> str:
    """Convert markdown to proper HTML."""
    html = markdown_content
    
    # Headers
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
    
    # Bold and italic (handle nested cases properly)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<em>\1</em>', html)
    
    # Links with GitHub issues/PRs
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', html)
    
    # GitHub mentions (only if not already linked)
    html = re.sub(r'(?<!\[)@([a-zA-Z0-9_-]+)(?!\])', r'<a href="https://github.com/\1" target="_blank">@\1</a>', html)
    
    # Issue/PR references - these should already be linked in reports, but handle plain ones too
    # Don't convert if already inside a link
    html = re.sub(r'(?<!\[)#(\d+)(?!\])', r'<a href="#" class="issue-ref">#\1</a>', html)
    
    # Code blocks (triple backticks)
    html = re.sub(r'```(\w+)?\n(.*?)```', r'<pre><code class="\1">\2</code></pre>', html, flags=re.DOTALL)
    
    # Inline code
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    
    # Process lists first, then paragraphs
    lines = html.split('\n')
    processed_lines = []
    in_list = False
    
    for line in lines:
        stripped = line.strip()
        
        # Handle list items
        if stripped.startswith('- '):
            if not in_list:
                processed_lines.append('<ul>')
                in_list = True
            list_content = stripped[2:]  # Remove '- '
            processed_lines.append(f'  <li>{list_content}</li>')
        else:
            if in_list:
                processed_lines.append('</ul>')
                in_list = False
            processed_lines.append(line)
    
    if in_list:
        processed_lines.append('</ul>')
    
    html = '\n'.join(processed_lines)
    
    # Convert paragraphs (split by double newlines, but preserve HTML blocks)
    sections = html.split('\n\n')
    html_sections = []
    
    for section in sections:
        section = section.strip()
        if not section:
            continue
        
        # Skip if it's already HTML (starts with <)
        if section.startswith('<'):
            html_sections.append(section)
        else:
            # Convert to paragraph, but handle multi-line content
            lines = section.split('\n')
            if len(lines) == 1:
                html_sections.append(f'<p>{section}</p>')
            else:
                # Multi-line content - join with <br> for line breaks
                content = '<br>'.join(lines)
                html_sections.append(f'<p>{content}</p>')
    
    return '\n\n'.join(html_sections)


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
            <span class="generated">Generated: {{generated_date}}</span>
        </div>
        <div class="controls">
            <div class="filters">
                <input type="text" id="repo-filter" placeholder="Filter repositories..." class="filter-input">
                <select id="year-filter" class="filter-select">
                    <option value="">All years</option>
                    {{year_options}}
                </select>
            </div>
        </div>
    </header>
    
    <main class="calendar-container">
        {{calendar_content}}
    </main>
    
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
    """Generate static HTML website from all summaries."""
    
    try:
        config = load_config()
        data_dir = get_data_dir()
        output_path = Path(output_dir)
        
        step("Collecting and parsing report files...")
        summaries = collect_all_summaries(data_dir)
        
        if not summaries:
            error("No report files found. Run 'ruminant annotate' first to generate reports with GitHub links.")
            raise typer.Exit(1)
        
        info(f"Found {len(summaries)} report files")
        
        step("Organizing data by weeks...")
        weeks_data = organize_by_weeks(summaries)
        all_repos = get_all_repos(summaries)
        
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
        years = sorted(set(year for (year, week) in weeks_data.keys()))
        year_options = '\n'.join(f'<option value="{year}">{year}</option>' for year in years)
        
        main_html = generate_main_template()
        main_html = main_html.replace('{{title}}', f"{config.project_name} - Activity Calendar")
        main_html = main_html.replace('{{project_name}}', config.project_name)
        main_html = main_html.replace('{{project_description}}', config.project_description)
        main_html = main_html.replace('{{generated_date}}', datetime.now().strftime('%Y-%m-%d %H:%M'))
        main_html = main_html.replace('{{calendar_content}}', calendar_html)
        main_html = main_html.replace('{{year_options}}', year_options)
        
        (output_path / "index.html").write_text(main_html)
        
        # Generate week detail pages
        step("Generating week detail pages...")
        sorted_weeks = sorted(weeks_data.items())
        
        for i, ((year, week), week_data) in enumerate(sorted_weeks):
            prev_week = sorted_weeks[i-1][0] if i > 0 else None
            next_week = sorted_weeks[i+1][0] if i < len(sorted_weeks) - 1 else None
            
            week_html = generate_week_detail_html(week_data, prev_week, next_week)
            week_template = generate_week_template()
            week_page = week_template.replace('{{week_title}}', f"Week {week} {year} - {config.project_name}")
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
    """Generate compact but readable CSS."""
    return '''/* Compact website styling */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 12px;
    line-height: 1.3;
    background: #fafafa;
    color: #333;
}

.main-header {
    background: #fff;
    border-bottom: 1px solid #ddd;
    padding: 12px 16px;
    position: sticky;
    top: 0;
    z-index: 100;
}

.project-title {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 4px;
}

.project-meta {
    font-size: 11px;
    color: #666;
    margin-bottom: 6px;
}

.controls {
    display: flex;
    gap: 12px;
    align-items: center;
}

.filters {
    display: flex;
    gap: 8px;
}

.filter-input, .filter-select {
    font-size: 11px;
    padding: 4px 6px;
    border: 1px solid #ccc;
    border-radius: 3px;
    background: #fff;
}

.filter-input {
    width: 140px;
}

.filter-select {
    width: 90px;
}

.calendar-container {
    padding: 12px;
}

.year-section {
    margin-bottom: 16px;
}

.year-header {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 8px;
    padding: 6px 0;
    border-bottom: 1px solid #eee;
}

.calendar-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 8px;
}

.week-card {
    border: 1px solid #ddd;
    border-radius: 4px;
    background: #fff;
    padding: 6px;
    transition: all 0.2s ease;
}

.week-card:hover {
    border-color: #999;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.week-card.hidden {
    display: none;
}

.week-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 4px;
    padding-bottom: 3px;
    border-bottom: 1px solid #f0f0f0;
}

.week-number {
    font-size: 13px;
    font-weight: 600;
    font-family: monospace;
}

.week-dates {
    font-size: 10px;
    color: #666;
    font-family: monospace;
}

.week-nav {
    display: flex;
    gap: 3px;
}

.nav-link {
    color: #666;
    text-decoration: none;
    font-size: 10px;
    padding: 2px 4px;
    border-radius: 3px;
    background: #f8f8f8;
    font-family: monospace;
}

.nav-link:hover {
    background: #e8e8e8;
    color: #333;
}

.week-link {
    text-decoration: none;
    color: inherit;
    display: block;
}

.repo-count {
    font-size: 10px;
    color: #666;
    margin-bottom: 3px;
}

.repos-preview {
    max-height: 80px;
    overflow: hidden;
}

.repo-item {
    font-size: 10px;
    margin-bottom: 2px;
    line-height: 1.4;
}

.repo-name {
    font-weight: 500;
    font-family: monospace;
    color: #0066cc;
}

/* Activity intensity colors */
.activity-none {
    background: #f8f8f8;
    border-color: #e8e8e8;
}

.activity-low {
    background: #fff5f0;
    border-color: #ffd4c4;
}

.activity-medium {
    background: #fff0e6;
    border-color: #ffb899;
}

.activity-high {
    background: #ffe6d9;
    border-color: #ff9d6e;
}

.activity-very-high {
    background: #ffdbcc;
    border-color: #ff8142;
}

/* Week detail pages */
.week-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 12px;
}

.week-detail .week-header {
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 12px;
    margin-bottom: 12px;
}

.week-detail .week-header h1 {
    font-size: 20px;
    margin-bottom: 4px;
}

.week-meta {
    font-size: 11px;
    color: #666;
    display: flex;
    gap: 16px;
}

.week-nav {
    background: #f8f8f8;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 6px 12px;
    margin-bottom: 12px;
    display: flex;
    gap: 12px;
}

.repos-container {
    display: grid;
    gap: 12px;
}

.repo-section {
    border: 1px solid #ddd;
    border-radius: 4px;
    background: #fff;
    overflow: hidden;
}

.repo-header {
    background: #f8f8f8;
    padding: 8px 12px;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.repo-title {
    font-size: 14px;
    font-weight: 600;
    font-family: monospace;
    color: #0066cc;
}

.repo-meta {
    font-size: 10px;
    color: #666;
}

.repo-content {
    padding: 12px;
    font-size: 11px;
    line-height: 1.5;
}

.repo-content h1 {
    font-size: 16px;
    margin: 12px 0 6px 0;
}

.repo-content h2 {
    font-size: 14px;
    margin: 10px 0 4px 0;
    color: #444;
}

.repo-content h3 {
    font-size: 12px;
    margin: 8px 0 4px 0;
    color: #555;
}

.repo-content h4 {
    font-size: 11px;
    margin: 6px 0 3px 0;
    color: #666;
}

.repo-content p {
    margin-bottom: 8px;
}

.repo-content ul {
    margin: 6px 0 6px 20px;
}

.repo-content li {
    margin-bottom: 3px;
}

.repo-content code {
    background: #f5f5f5;
    border: 1px solid #e8e8e8;
    border-radius: 2px;
    padding: 1px 3px;
    font-family: monospace;
    font-size: 10px;
}

.repo-content pre {
    background: #f8f8f8;
    border: 1px solid #e8e8e8;
    border-radius: 4px;
    padding: 8px;
    overflow-x: auto;
    margin: 8px 0;
}

.repo-content pre code {
    background: none;
    border: none;
    padding: 0;
    font-size: 10px;
}

.repo-content a {
    color: #0066cc;
    text-decoration: none;
}

.repo-content a:hover {
    text-decoration: underline;
}

.repo-content strong {
    font-weight: 600;
}

@media (max-width: 768px) {
    .calendar-grid {
        grid-template-columns: 1fr;
    }
    
    .week-meta {
        flex-direction: column;
        gap: 2px;
    }
    
    .week-nav {
        flex-wrap: wrap;
    }
}

@media print {
    .nav-link, .controls {
        display: none;
    }
    
    .week-card {
        break-inside: avoid;
        page-break-inside: avoid;
    }
    
    body {
        font-size: 10px;
    }
}

.issue-ref {
    color: #666;
    font-family: monospace;
    text-decoration: none;
    font-size: 90%;
}

.filter-count {
    font-weight: normal;
    color: #888;
}'''


def generate_javascript() -> str:
    """Generate client-side filtering JavaScript."""
    return '''// Client-side filtering and navigation
document.addEventListener('DOMContentLoaded', function() {
    const repoFilter = document.getElementById('repo-filter');
    const yearFilter = document.getElementById('year-filter');
    const weekCards = document.querySelectorAll('.week-card');
    
    function filterWeeks() {
        const repoQuery = repoFilter?.value.toLowerCase() || '';
        const yearQuery = yearFilter?.value || '';
        
        weekCards.forEach(card => {
            const weekData = card.dataset.week || '';
            const repoItems = card.querySelectorAll('.repo-item');
            
            let showCard = true;
            
            // Year filter
            if (yearQuery && !weekData.startsWith(yearQuery)) {
                showCard = false;
            }
            
            // Repository filter
            if (repoQuery && showCard) {
                const hasMatchingRepo = Array.from(repoItems).some(item => {
                    return item.textContent.toLowerCase().includes(repoQuery);
                });
                
                if (!hasMatchingRepo) {
                    showCard = false;
                }
            }
            
            // Show/hide card
            if (showCard) {
                card.classList.remove('hidden');
            } else {
                card.classList.add('hidden');
            }
        });
        
        // Update visible counts
        updateVisibleCounts();
    }
    
    function updateVisibleCounts() {
        const visibleCards = document.querySelectorAll('.week-card:not(.hidden)');
        const totalCards = weekCards.length;
        
        // Update header if it exists
        const header = document.querySelector('.main-header');
        if (header) {
            let countSpan = header.querySelector('.filter-count');
            if (!countSpan) {
                countSpan = document.createElement('span');
                countSpan.className = 'filter-count';
                countSpan.style.fontSize = '9px';
                countSpan.style.color = '#666';
                countSpan.style.marginLeft = '8px';
                
                const controls = header.querySelector('.controls');
                if (controls) {
                    controls.appendChild(countSpan);
                }
            }
            
            if (visibleCards.length !== totalCards) {
                countSpan.textContent = `Showing ${visibleCards.length} of ${totalCards} weeks`;
            } else {
                countSpan.textContent = '';
            }
        }
    }
    
    // Attach event listeners
    if (repoFilter) {
        repoFilter.addEventListener('input', filterWeeks);
        repoFilter.addEventListener('keyup', filterWeeks);
    }
    
    if (yearFilter) {
        yearFilter.addEventListener('change', filterWeeks);
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Focus filter on '/' key
        if (e.key === '/' && document.activeElement !== repoFilter) {
            e.preventDefault();
            if (repoFilter) {
                repoFilter.focus();
            }
        }
        
        // Clear filters on Escape
        if (e.key === 'Escape') {
            if (repoFilter) {
                repoFilter.value = '';
            }
            if (yearFilter) {
                yearFilter.value = '';
            }
            filterWeeks();
        }
    });
    
    // Initialize
    updateVisibleCounts();
});

// Add some helpful functionality for week detail pages
if (window.location.pathname.includes('/weeks/')) {
    document.addEventListener('keydown', function(e) {
        const prevLink = document.querySelector('a[href*="-"]:not([href="../index.html"]):first-of-type');
        const nextLink = document.querySelector('a[href*="-"]:not([href="../index.html"]):last-of-type');
        
        // Navigate with arrow keys
        if (e.key === 'ArrowLeft' && prevLink && prevLink !== nextLink) {
            window.location.href = prevLink.href;
        } else if (e.key === 'ArrowRight' && nextLink) {
            window.location.href = nextLink.href;
        }
        
        // Go back to calendar with 'c' key
        if (e.key === 'c' || e.key === 'C') {
            window.location.href = '../index.html';
        }
    });
}'''