"""Generate Atom feeds and OPML from JSON summaries."""

import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import pytz
from feedgen.feed import FeedGenerator
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from ..config import load_config
from ..utils.logging import console, success, error, info, warning
from ..utils.paths import get_data_dir


def create_atom_feed(group_name: str, summaries: List[Dict[str, Any]], config: Any, users_data: Optional[Dict[str, Any]] = None) -> FeedGenerator:
    """Create an Atom feed for a specific group."""
    fg = FeedGenerator()
    
    # Get atom config from config file
    atom_config = config.atom if hasattr(config, 'atom') else None
    if not atom_config:
        # Use defaults if not configured
        base_url = "https://ocaml.org/ruminant"
        author_name = "OCaml Community"
        author_email = "community@ocaml.org"
    else:
        base_url = atom_config.base_url
        author_name = atom_config.author_name
        author_email = atom_config.author_email
    
    # Get group config
    group_config = config.groups.get(group_name, None)
    group_title = group_config.name if group_config else group_name.title()
    group_description = group_config.description if group_config else f"Activity reports for {group_name}"
    
    # Set feed metadata
    feed_id = f"{base_url}/feeds/{group_name}.xml"
    fg.id(feed_id)
    fg.title(f"{group_title} (Weekly)")
    fg.author({'name': author_name, 'email': author_email})
    fg.link(href=feed_id, rel='self')
    fg.link(href=f"{base_url}/", rel='alternate')
    fg.subtitle(group_description)
    fg.language('en')
    
    # Sort summaries by date (oldest first for feedgen which reverses order)
    sorted_summaries = sorted(
        summaries,
        key=lambda x: (x.get('year', 0), x.get('week', 0)),
        reverse=False  # Changed to False because feedgen reverses the order
    )
    
    # Add entries for each week
    for summary in sorted_summaries:
        year = summary.get('year', 0)
        week = summary.get('week', 0)
        week_range = summary.get('week_range', '')
        brief = summary.get('brief_summary', '')
        
        # Create entry
        fe = fg.add_entry()
        entry_id = f"{base_url}/groups/{group_name}/{year}/week-{week}"
        fe.id(entry_id)
        fe.title(f"Week {week}, {year}: {brief}")
        fe.link(href=f"{base_url}/")
        
        # Calculate publication date (use end of week)
        try:
            # Parse week_range to get the end date
            if week_range and ' to ' in week_range:
                end_date_str = week_range.split(' to ')[1].strip()
                pub_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                pub_date = pub_date.replace(tzinfo=pytz.UTC)
                fe.published(pub_date)
                fe.updated(pub_date)
        except:
            pass
        
        # Build content from sections
        content_parts = []

        if summary.get('new_features'):
            content_parts.append(f"<h2>New Features</h2>\n{markdown_to_html(summary['new_features'], users_data, config)}")

        if summary.get('group_overview'):
            content_parts.append(f"<h2>Group Overview</h2>\n{markdown_to_html(summary['group_overview'], users_data, config)}")

        if summary.get('cross_repository_work'):
            content_parts.append(f"<h2>Cross-Repository Work</h2>\n{markdown_to_html(summary['cross_repository_work'], users_data, config)}")

        if summary.get('key_projects'):
            content_parts.append(f"<h2>Key Projects and Initiatives</h2>\n{markdown_to_html(summary['key_projects'], users_data, config)}")

        if summary.get('notable_discussions'):
            content_parts.append(f"<h2>Notable Discussions</h2>\n{markdown_to_html(summary['notable_discussions'], users_data, config)}")

        if summary.get('emerging_trends'):
            content_parts.append(f"<h2>Emerging Trends</h2>\n{markdown_to_html(summary['emerging_trends'], users_data, config)}")
        
        # Add CSS at the beginning of content
        if content_parts:
            content = get_feed_css() + '\n'.join(content_parts)
        else:
            content = ''
        fe.content(content, type='html')
        
        # Add summary
        summary_text = brief or f"Activity report for {group_name} - Week {week}, {year}"
        fe.summary(summary_text)
    
    # Update feed's updated time to the most recent entry
    if sorted_summaries:
        latest = sorted_summaries[-1]  # Changed to -1 since we're now sorting oldest first
        week_range = latest.get('week_range', '')
        if week_range and ' to ' in week_range:
            try:
                end_date_str = week_range.split(' to ')[1].strip()
                update_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                update_date = update_date.replace(tzinfo=pytz.UTC)
                fg.updated(update_date)
            except:
                fg.updated(datetime.now(pytz.UTC))
    else:
        fg.updated(datetime.now(pytz.UTC))
    
    return fg


def create_repository_atom_feed(repo_name: str, summaries: List[Dict[str, Any]], config: Any, users_data: Optional[Dict[str, Any]] = None) -> FeedGenerator:
    """Create an Atom feed for a specific repository."""
    fg = FeedGenerator()

    # Get atom config from config file
    atom_config = config.atom if hasattr(config, 'atom') else None
    if not atom_config:
        base_url = "https://ocaml.org/ruminant"
        author_name = "OCaml Community"
        author_email = "community@ocaml.org"
    else:
        base_url = atom_config.base_url
        author_name = atom_config.author_name
        author_email = atom_config.author_email

    # Clean repo name for URL (replace / with -)
    repo_slug = repo_name.replace('/', '-')

    # Set feed metadata
    feed_id = f"{base_url}/feeds/repos/{repo_slug}.xml"
    fg.id(feed_id)
    fg.title(f"{repo_name} (Weekly)")
    fg.author({'name': author_name, 'email': author_email})
    fg.link(href=feed_id, rel='self')
    fg.link(href=f"{base_url}/", rel='alternate')

    # Get repository description if available
    repo_description = f"Weekly activity reports for {repo_name}"
    for repo_config in config.repository_configs:
        if repo_config.name == repo_name:
            # Could enhance this with actual repo description if available
            break

    fg.subtitle(repo_description)
    fg.language('en')

    # Sort summaries by date (oldest first for feedgen which reverses order)
    sorted_summaries = sorted(
        summaries,
        key=lambda x: (x.get('year', 0), x.get('week', 0)),
        reverse=False  # feedgen reverses the order
    )

    # Add entries for each week
    for summary in sorted_summaries:
        year = summary.get('year', 0)
        week = summary.get('week', 0)
        week_range = summary.get('week_range', '')
        brief = summary.get('brief_summary', '')

        # Create entry
        fe = fg.add_entry()
        entry_id = f"{base_url}/repos/{repo_slug}/{year}/week-{week}"
        fe.id(entry_id)
        fe.title(f"Week {week}, {year}: {brief}")
        fe.link(href=f"{base_url}/")

        # Calculate publication date (use end of week)
        try:
            if week_range and ' to ' in week_range:
                end_date_str = week_range.split(' to ')[1].strip()
                pub_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                pub_date = pub_date.replace(tzinfo=pytz.UTC)
                fe.published(pub_date)
                fe.updated(pub_date)
        except:
            pass

        # Build content from sections
        content_parts = []

        if summary.get('summary'):
            content_parts.append(f"<h2>Summary</h2>\n{markdown_to_html(summary['summary'], users_data, config)}")

        if summary.get('activity'):
            content_parts.append(f"<h2>Activity</h2>\n{markdown_to_html(summary['activity'], users_data, config)}")

        if summary.get('merged_prs'):
            content_parts.append(f"<h2>Merged PRs</h2>\n{markdown_to_html(summary['merged_prs'], users_data, config)}")

        if summary.get('opened_prs'):
            content_parts.append(f"<h2>Opened PRs</h2>\n{markdown_to_html(summary['opened_prs'], users_data, config)}")

        if summary.get('opened_issues'):
            content_parts.append(f"<h2>Opened Issues</h2>\n{markdown_to_html(summary['opened_issues'], users_data, config)}")

        # Add CSS at the beginning of content
        if content_parts:
            content = get_feed_css() + '\n'.join(content_parts)
        else:
            content = f"<p>Activity report for {repo_name} - Week {week}, {year}</p>"
        fe.content(content, type='html')

        # Add summary
        summary_text = brief or f"Activity report for {repo_name} - Week {week}, {year}"
        fe.summary(summary_text)

    # Update feed's updated time to the most recent entry
    if sorted_summaries:
        latest = sorted_summaries[-1]  # Last one since we're sorting oldest first
        week_range = latest.get('week_range', '')
        if week_range and ' to ' in week_range:
            try:
                end_date_str = week_range.split(' to ')[1].strip()
                update_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                update_date = update_date.replace(tzinfo=pytz.UTC)
                fg.updated(update_date)
            except:
                fg.updated(datetime.now(pytz.UTC))
    else:
        fg.updated(datetime.now(pytz.UTC))

    return fg


def markdown_to_html(markdown_text: str, users_data: Optional[Dict[str, Any]] = None, config: Any = None) -> str:
    """Convert markdown to HTML for feed content with enhanced processing."""
    import markdown2
    import re

    if not markdown_text:
        return ""

    # Pre-process RUMINANT tags before markdown conversion
    # Replace __RUMINANT:groupname__ with links to group feeds
    def replace_ruminant_tags(match):
        group_name = match.group(1)

        # Get base URL from config
        base_url = "https://ocaml.org/ruminant"
        if config and hasattr(config, 'atom'):
            base_url = config.atom.base_url

        # Get group display name from config
        group_title = group_name.title()
        if config and hasattr(config, 'groups'):
            group_config = config.groups.get(group_name)
            if group_config:
                group_title = group_config.name

        # Return a link to the group's Atom feed
        return f'<a href="{base_url}/feeds/{group_name}.xml" class="ruminant-group-link" title="View {group_title} feed">{group_title}</a>'

    markdown_text = re.sub(r'__RUMINANT:([^_]+)__', replace_ruminant_tags, markdown_text)

    # Pre-process markdown to enhance user links with full names
    if users_data:
        # Replace [@username](url) with full name if available
        def replace_user_mention(match):
            user_text = match.group(1)
            url = match.group(2)
            username = user_text.replace('@', '')

            # Check if it's a GitHub user URL
            github_match = re.match(r'https://github\.com/([^/]+)/?$', url)
            if github_match:
                username = github_match.group(1)

            if username in users_data:
                user_info = users_data[username]
                if user_info.get('name'):
                    # Include both name and username for clarity in feeds
                    return f"[{user_info['name']} (@{username})]({url})"

            return match.group(0)

        markdown_text = re.sub(r'\[(@[^\]]+)\]\(([^)]+)\)', replace_user_mention, markdown_text)

        # Also replace plain GitHub user profile links
        def replace_user_link(match):
            link_text = match.group(1)
            url = match.group(2)

            # Check if it's a GitHub user profile link
            if 'github.com/' in url and url.count('/') == 3:
                username = url.split('/')[-1]
                if username in users_data:
                    user_info = users_data[username]
                    if user_info.get('name') and link_text != user_info['name']:
                        # Don't replace if the link text already is the full name
                        return f"[{user_info['name']}]({url})"

            return match.group(0)

        markdown_text = re.sub(r'\[([^\]]+)\]\((https://github\.com/[^/)]+)\)', replace_user_link, markdown_text)

    # Convert markdown to HTML with GitHub-flavored markdown support
    html = markdown2.markdown(
        markdown_text,
        extras=['fenced-code-blocks', 'tables', 'break-on-newline']
    )

    # Post-process HTML to add achievement linking
    html = link_achievements_in_html(html)

    # Use CSS classes instead of inline styles
    html = html.replace('<strong>', '<strong class="achievement">')

    return html


def get_feed_css() -> str:
    """Generate CSS for Atom feed content."""
    return """
<style>
    /* Base styles */
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }
    h1, h2, h3 { margin-top: 1.5em; margin-bottom: 0.5em; color: #1a1a1a; }
    h1 { font-size: 1.8em; border-bottom: 2px solid #f0f0f0; padding-bottom: 0.3em; }
    h2 { font-size: 1.4em; }
    h3 { font-size: 1.2em; color: #444; }
    p { margin: 0.8em 0; }

    /* Links */
    a { color: #0366d6; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Code blocks */
    code { background: #f6f8fa; padding: 2px 6px; border-radius: 3px; font-family: 'SF Mono', Consolas, monospace; font-size: 0.9em; }
    pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
    pre code { background: none; padding: 0; }

    /* Lists */
    ul, ol { padding-left: 1.5em; margin: 0.8em 0; }
    li { margin: 0.3em 0; }

    /* Achievement highlights */
    .achievement { color: #cc6600; font-weight: 600; }

    /* RUMINANT group links */
    .ruminant-group-link {
        color: #6b46c1;
        font-weight: 500;
        padding: 2px 6px;
        background: rgba(107, 70, 193, 0.1);
        border-radius: 3px;
        text-decoration: none;
    }
    .ruminant-group-link:hover {
        background: rgba(107, 70, 193, 0.2);
        text-decoration: none;
    }

    /* Repository links */
    .repo-inline { color: #0366d6; font-weight: 500; }

    /* Sections */
    section { margin: 2em 0; }

    /* Tables */
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { padding: 8px 12px; border: 1px solid #ddd; text-align: left; }
    th { background: #f6f8fa; font-weight: 600; }
    tr:nth-child(even) { background: #f9f9f9; }
</style>
"""


def link_achievements_in_html(html: str) -> str:
    """Link achievements to their associated issues in HTML."""
    import re
    from html.parser import HTMLParser
    
    class AchievementLinker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.result = []
            self.in_li = False
            self.current_li = []
            self.issue_links = []
        
        def handle_starttag(self, tag, attrs):
            if tag == 'li':
                self.in_li = True
                self.current_li = []
                self.issue_links = []
            
            attrs_str = ' '.join(f'{k}="{v}"' for k, v in attrs)
            if attrs_str:
                self.current_li.append(f'<{tag} {attrs_str}>')
            else:
                self.current_li.append(f'<{tag}>')
            
            # Track issue links
            if tag == 'a' and self.in_li:
                for k, v in attrs:
                    if k == 'href' and ('/issues/' in v or '/pull/' in v):
                        self.issue_links.append(v)
                        break
        
        def handle_endtag(self, tag):
            self.current_li.append(f'</{tag}>')
            
            if tag == 'li':
                # Process the completed list item
                li_html = ''.join(self.current_li)
                
                # Check if there's a <strong> tag (achievement) and an issue link
                if '<strong>' in li_html and self.issue_links:
                    # Link the first <strong> tag to the first issue link
                    first_issue = self.issue_links[0]
                    # Replace the first <strong>...</strong> with a linked version
                    li_html = re.sub(
                        r'<strong([^>]*)>([^<]+)</strong>',
                        f'<a href="{first_issue}" style="text-decoration: none;"><strong\\1>\\2</strong></a>',
                        li_html,
                        count=1
                    )
                
                self.result.append(li_html)
                self.in_li = False
            elif not self.in_li:
                self.result.append(f'</{tag}>')
        
        def handle_data(self, data):
            if self.in_li:
                self.current_li.append(data)
            else:
                self.result.append(data)
    
    try:
        parser = AchievementLinker()
        parser.feed(html)
        return ''.join(parser.result)
    except:
        # If parsing fails, return original HTML
        return html


def create_daily_atom_feed(daily_summaries: List[Dict], config: Any, users_data: Dict) -> FeedGenerator:
    """Create an Atom feed for daily summaries."""
    fg = FeedGenerator()

    # Get atom config
    atom_config = config.atom if hasattr(config, 'atom') else None
    if not atom_config:
        base_url = "https://ocaml.org/ruminant"
        title = "OCaml Ecosystem Daily Updates"
    else:
        base_url = atom_config.base_url
        title = "OCaml Ecosystem Daily Updates"

    feed_url = f"{base_url}/feeds/daily.xml"

    # Configure feed metadata
    fg.id(feed_url)
    fg.title(title)
    fg.author({'name': atom_config.author if atom_config and hasattr(atom_config, 'author') else 'OCaml Community'})
    fg.link(href=feed_url, rel='self')
    fg.link(href=base_url, rel='alternate')
    fg.subtitle('Daily activity summaries from the OCaml ecosystem')
    fg.language('en')
    fg.updated(datetime.now(pytz.UTC))

    # Add each daily summary as an entry
    for daily in sorted(daily_summaries, key=lambda x: x.get('date', ''), reverse=True):
        fe = fg.add_entry()

        date_str = daily.get('date', '')
        day_name = daily.get('day_name', '')

        # Create entry ID
        entry_id = f"{base_url}/daily/{date_str}"
        fe.id(entry_id)
        fe.link(href=base_url, rel='alternate')

        # Title
        fe.title(f"{day_name} - {date_str}")

        # Build content HTML
        content_html = f"{get_feed_css()}\n"
        content_html += '<div class="feed-content">\n'

        # Highlights section
        if daily.get('highlights'):
            content_html += '<h3>Key Highlights</h3>\n<ul>\n'
            for highlight in daily['highlights']:
                content_html += f'<li>{highlight}</li>\n'
            content_html += '</ul>\n\n'

        # Notable commits section
        if daily.get('commits'):
            content_html += '<h3>Notable Commits</h3>\n<ul>\n'
            for commit in daily['commits']:
                repo = commit.get('repo', '')
                desc = commit.get('description', '')
                content_html += f'<li><strong>{repo}</strong>: {desc}</li>\n'
            content_html += '</ul>\n\n'

        # Active discussions section
        if daily.get('discussions'):
            content_html += '<h3>Active Discussions</h3>\n<ul>\n'
            for discussion in daily['discussions']:
                content_html += f'<li>{discussion}</li>\n'
            content_html += '</ul>\n\n'

        # Community activity
        if daily.get('community'):
            content_html += f'<h3>Community Activity</h3>\n<p>{daily["community"]}</p>\n\n'

        # Overall summary
        if daily.get('summary'):
            content_html += f'<h3>Summary</h3>\n<p>{daily["summary"]}</p>\n'

        content_html += '</div>'

        # Process markdown and user links
        content_html = markdown_to_html(content_html, config)
        content_html = post_process_html_with_user_links(content_html, users_data)

        fe.content(content_html, type='html')
        fe.summary(daily.get('summary', 'Daily activity summary'))

        # Set published date
        try:
            pub_date = datetime.strptime(date_str, '%Y-%m-%d')
            pub_date = pub_date.replace(tzinfo=pytz.UTC)
            fe.published(pub_date)
            fe.updated(pub_date)
        except:
            fe.updated(datetime.now(pytz.UTC))

    return fg


def create_opml(feeds: Dict[str, str], config: Any) -> str:
    """Create an OPML file listing all the Atom feeds."""
    # Get atom config
    atom_config = config.atom if hasattr(config, 'atom') else None
    if not atom_config:
        base_url = "https://ocaml.org/ruminant"
        title = "OCaml Community Activity Feeds"
    else:
        base_url = atom_config.base_url
        title = atom_config.opml_title if hasattr(atom_config, 'opml_title') else "Activity Feeds"
    
    # Create OPML structure
    opml = Element('opml', version='2.0')
    
    # Head section
    head = SubElement(opml, 'head')
    SubElement(head, 'title').text = title
    SubElement(head, 'dateCreated').text = datetime.now(pytz.UTC).isoformat()
    
    # Body section
    body = SubElement(opml, 'body')

    # Separate feeds into groups and repositories
    group_feeds = {}
    repo_feeds = {}

    for feed_name, feed_path in feeds.items():
        if feed_name.startswith('repo:'):
            repo_name = feed_name[5:]  # Remove 'repo:' prefix
            repo_feeds[repo_name] = feed_path
        else:
            group_feeds[feed_name] = feed_path

    # Add group/summary feeds section
    if group_feeds:
        groups_folder = SubElement(body, 'outline', text='Groups & Summaries', title='Groups & Summaries')

        for group_name, feed_path in sorted(group_feeds.items()):
            if group_name == 'weekly':
                outline = SubElement(groups_folder, 'outline',
                                   text='OCaml Ecosystem (All Weeklies)',
                                   title='OCaml Ecosystem (All Weeklies)',
                                   type='rss',
                                   xmlUrl=f"{base_url}/feeds/weekly.xml",
                                   htmlUrl=f"{base_url}/",
                                   description="Comprehensive weekly summaries across all OCaml ecosystem activity")
            else:
                group_config = config.groups.get(group_name, None)
                group_title = f"{group_config.name} (Weekly)" if group_config else f"{group_name.title()} (Weekly)"
                group_description = group_config.description if group_config else ""

                outline = SubElement(groups_folder, 'outline',
                                   text=group_title,
                                   title=group_title,
                                   type='rss',
                                   xmlUrl=f"{base_url}/feeds/{group_name}.xml",
                                   htmlUrl=f"{base_url}/")

                if group_description:
                    outline.set('description', group_description)

    # Add repository feeds section
    if repo_feeds:
        repos_folder = SubElement(body, 'outline', text='Repository Feeds', title='Repository Feeds')

        for repo_name, feed_path in sorted(repo_feeds.items()):
            repo_slug = repo_name.replace('/', '-')
            outline = SubElement(repos_folder, 'outline',
                               text=f"{repo_name} (Weekly)",
                               title=f"{repo_name} (Weekly)",
                               type='rss',
                               xmlUrl=f"{base_url}/feeds/repos/{repo_slug}.xml",
                               htmlUrl=f"{base_url}/",
                               description=f"Weekly activity reports for {repo_name}")
    
    # Pretty print the XML
    rough_string = tostring(opml, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding='UTF-8').decode('utf-8')


def create_weekly_atom_feed(weeks_data: List[Dict[str, Any]], config: Any, users_data: Optional[Dict[str, Any]] = None) -> FeedGenerator:
    """Create an Atom feed for weekly summaries including group summaries."""
    fg = FeedGenerator()

    # Get atom config from config file
    atom_config = config.atom if hasattr(config, 'atom') else None
    if not atom_config:
        base_url = "https://ocaml.org/ruminant"
        author_name = "OCaml Community"
        author_email = "community@ocaml.org"
    else:
        base_url = atom_config.base_url
        author_name = atom_config.author_name
        author_email = atom_config.author_email

    # Set feed metadata
    feed_id = f"{base_url}/feeds/weekly.xml"
    fg.id(feed_id)
    fg.title("OCaml Ecosystem (All Weeklies)")
    fg.author({'name': author_name, 'email': author_email})
    fg.link(href=feed_id, rel='self')
    fg.link(href=f"{base_url}/", rel='alternate')
    fg.subtitle("Comprehensive weekly summaries across all OCaml ecosystem activity")
    fg.language('en')

    # Sort weeks by date (oldest first for feedgen which reverses order)
    sorted_weeks = sorted(
        weeks_data,
        key=lambda x: (x.get('year', 0), x.get('week', 0)),
        reverse=False  # Changed to False because feedgen reverses the order
    )

    # Add entries for each week
    for week_data in sorted_weeks:
        year = week_data.get('year', 0)
        week = week_data.get('week', 0)
        week_range = week_data.get('week_range', '')

        # Skip weeks without a weekly summary
        weekly_summary = week_data.get('weekly_summary')
        if not weekly_summary:
            continue

        fe = fg.add_entry()
        entry_id = f"{base_url}/weekly/{year}/week-{week}"
        fe.id(entry_id)

        # Use brief_summary for title if available
        brief_summary = weekly_summary.get('brief_summary', '')
        if brief_summary:
            fe.title(f"Week {week}, {year}: {brief_summary}")
        else:
            fe.title(f"Week {week}, {year} - Ecosystem Summary")

        fe.link(href=f"{base_url}/")

        # Set publication date
        try:
            if week_range and ' to ' in week_range:
                end_date_str = week_range.split(' to ')[1].strip()
                pub_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                pub_date = pub_date.replace(tzinfo=pytz.UTC)
                fe.published(pub_date)
                fe.updated(pub_date)
        except:
            pass

        # Build HTML content from weekly summary
        content_parts = []
        content_parts.append("<h1>Weekly Summary</h1>")

        if weekly_summary.get('executive_summary'):
            content_parts.append(f"<h2>Executive Summary</h2>\n{markdown_to_html(weekly_summary['executive_summary'], users_data, config)}")

        if weekly_summary.get('new_features'):
            content_parts.append(f"<h2>New Features</h2>\n{markdown_to_html(weekly_summary['new_features'], users_data, config)}")

        if weekly_summary.get('major_releases'):
            content_parts.append(f"<h2>Major Releases</h2>\n{markdown_to_html(weekly_summary['major_releases'], users_data, config)}")

        if weekly_summary.get('key_developments'):
            content_parts.append(f"<h2>Key Developments</h2>\n{markdown_to_html(weekly_summary['key_developments'], users_data, config)}")

        if weekly_summary.get('trending_topics'):
            content_parts.append(f"<h2>Trending Topics</h2>\n{markdown_to_html(weekly_summary['trending_topics'], users_data, config)}")

        if weekly_summary.get('looking_ahead'):
            content_parts.append(f"<h2>Looking Ahead</h2>\n{markdown_to_html(weekly_summary['looking_ahead'], users_data, config)}")

        # Add group summaries
        group_summaries = week_data.get('group_summaries', [])
        if group_summaries:
            content_parts.append("<h1>Group Activity Summaries</h1>")

            for group_summary in group_summaries:
                group_name = group_summary.get('group', '')
                group_config = config.groups.get(group_name, None)
                group_title = group_config.name if group_config else group_name.title()

                content_parts.append(f"<h2>{group_title}</h2>")

                if group_summary.get('brief_summary'):
                    content_parts.append(f"<p><strong>{group_summary['brief_summary']}</strong></p>")

                if group_summary.get('new_features'):
                    content_parts.append(f"<h3>New Features</h3>\n{markdown_to_html(group_summary['new_features'], users_data, config)}")

                if group_summary.get('group_overview'):
                    content_parts.append(f"<h3>Overview</h3>\n{markdown_to_html(group_summary['group_overview'], users_data, config)}")

                if group_summary.get('activity'):
                    content_parts.append(f"<h3>Activity</h3>\n{markdown_to_html(group_summary['activity'], users_data, config)}")

                if group_summary.get('notable_discussions'):
                    content_parts.append(f"<h3>Notable Discussions</h3>\n{markdown_to_html(group_summary['notable_discussions'], users_data, config)}")

                if group_summary.get('emerging_trends'):
                    content_parts.append(f"<h3>Emerging Trends</h3>\n{markdown_to_html(group_summary['emerging_trends'], users_data, config)}")

        # Add CSS at the beginning of content
        if content_parts:
            html_content = get_feed_css() + '\n'.join(content_parts)
        else:
            html_content = f"<p>Weekly ecosystem summary for Week {week}, {year}</p>"
        fe.content(html_content, type='html')

        # Use brief_summary or executive_summary for feed summary
        feed_summary = (
            weekly_summary.get('brief_summary') or
            weekly_summary.get('executive_summary', '')[:200] or
            f"Weekly ecosystem summary for Week {week}, {year}"
        )

        fe.summary(feed_summary)
    
    fg.updated(datetime.now(pytz.UTC))
    return fg


def atom_info(feed_dir: Optional[str] = None) -> None:
    """Display metadata information about generated Atom feeds."""
    try:
        config = load_config()

        # Default to website-atom if not specified
        if feed_dir:
            feed_path = Path(feed_dir)
        else:
            feed_path = Path("website-atom")

        if not feed_path.exists():
            error(f"Feed directory does not exist: {feed_path}")
            info("Have you run 'ruminant atom' to generate feeds first?")
            import typer
            raise typer.Exit(1)

        feeds_dir = feed_path / "feeds"
        if not feeds_dir.exists():
            error(f"No feeds directory found at {feeds_dir}")
            import typer
            raise typer.Exit(1)

        console.print("\n[bold]Atom Feed Metadata[/bold]")
        console.print("=" * 50)

        # Get atom config for display
        atom_config = config.atom if hasattr(config, 'atom') else None
        if atom_config:
            console.print(f"\n[cyan]Base URL:[/cyan] {atom_config.base_url}")
            console.print(f"[cyan]Author:[/cyan] {atom_config.author_name} <{atom_config.author_email}>")
            console.print(f"[cyan]OPML Title:[/cyan] {atom_config.opml_title}")

        # List available feeds
        feed_files = list(feeds_dir.glob("*.xml"))
        repos_dir = feeds_dir / "repos"
        repo_feed_files = []
        if repos_dir.exists():
            repo_feed_files = list(repos_dir.glob("*.xml"))

        total_feeds = len(feed_files) + len(repo_feed_files)
        if total_feeds == 0:
            warning("No feed files found")
            return

        console.print(f"\n[bold]Available Feeds:[/bold] {total_feeds} feeds found")

        if feed_files:
            console.print(f"\n[cyan]Group & Summary Feeds:[/cyan] {len(feed_files)} feeds\n")

        # Parse and display info for each feed
        for feed_file in sorted(feed_files):
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(feed_file)
                root = tree.getroot()

                # Handle namespace
                ns = {'atom': 'http://www.w3.org/2005/Atom'}

                # Get feed metadata
                title = root.find('atom:title', ns)
                subtitle = root.find('atom:subtitle', ns)
                updated = root.find('atom:updated', ns)
                entries = root.findall('atom:entry', ns)

                feed_name = feed_file.stem

                # Check if it's a group feed
                if feed_name in config.groups:
                    group_config = config.groups[feed_name]
                    console.print(f"[green]📘 {feed_name}.xml[/green] (Group Feed)")
                elif feed_name == "weekly":
                    console.print(f"[green]📚 {feed_name}.xml[/green] (Weekly Summary Feed)")
                else:
                    console.print(f"[green]📄 {feed_name}.xml[/green]")

                if title is not None and title.text:
                    console.print(f"  Title: {title.text}")

                if subtitle is not None and subtitle.text:
                    console.print(f"  Description: {subtitle.text}")

                if updated is not None and updated.text:
                    console.print(f"  Last Updated: {updated.text}")

                console.print(f"  Entries: {len(entries)}")

                # Show latest entry if available
                if entries:
                    latest = entries[0]
                    entry_title = latest.find('atom:title', ns)
                    if entry_title is not None and entry_title.text:
                        console.print(f"  Latest: {entry_title.text[:60]}..." if len(entry_title.text) > 60 else f"  Latest: {entry_title.text}")

                # Show URL
                if atom_config:
                    if feed_name == "weekly":
                        console.print(f"  URL: {atom_config.base_url}/feeds/weekly.xml")
                    else:
                        console.print(f"  URL: {atom_config.base_url}/feeds/{feed_name}.xml")

                console.print()

            except Exception as e:
                warning(f"Could not parse {feed_file.name}: {e}")

        # Display repository feeds if available
        if repo_feed_files:
            console.print(f"\n[cyan]Repository Feeds:[/cyan] {len(repo_feed_files)} feeds\n")

            for feed_file in sorted(repo_feed_files)[:10]:  # Show first 10 repos
                try:
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(feed_file)
                    root = tree.getroot()

                    # Handle namespace
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}

                    # Get feed metadata
                    title = root.find('atom:title', ns)
                    updated = root.find('atom:updated', ns)
                    entries = root.findall('atom:entry', ns)

                    feed_name = feed_file.stem
                    console.print(f"[blue]📦 {feed_name}.xml[/blue]")

                    if title is not None and title.text:
                        console.print(f"  Title: {title.text}")

                    if updated is not None and updated.text:
                        console.print(f"  Last Updated: {updated.text}")

                    console.print(f"  Entries: {len(entries)}")

                    # Show URL
                    if atom_config:
                        console.print(f"  URL: {atom_config.base_url}/feeds/repos/{feed_name}.xml")

                    console.print()

                except Exception as e:
                    warning(f"Could not parse {feed_file.name}: {e}")

            if len(repo_feed_files) > 10:
                console.print(f"[dim]... and {len(repo_feed_files) - 10} more repository feeds[/dim]\n")

        # Check for OPML file
        opml_file = feed_path / "feeds.opml"
        if opml_file.exists():
            console.print("[bold]OPML File:[/bold]")
            console.print(f"  📑 feeds.opml - Contains all feed references")
            if atom_config:
                console.print(f"  URL: {atom_config.base_url}/feeds.opml")

            try:
                tree = ET.parse(opml_file)
                root = tree.getroot()
                outlines = root.findall('.//outline[@type="rss"]')
                console.print(f"  Contains {len(outlines)} feed references")
            except:
                pass

        console.print("\n✨ Feed metadata displayed successfully")

    except Exception as e:
        error(f"Failed to display feed info: {e}")
        import typer
        raise typer.Exit(1)


def atom_main(output_dir: str, pretty: bool = False, json_dir: Optional[str] = None) -> None:
    """Main function for generating Atom feeds from JSON output."""
    try:
        config = load_config()
        output_path = Path(output_dir)

        # If json_dir not provided, generate it using ruminant json
        if json_dir:
            json_path = Path(json_dir)
            if not json_path.exists():
                error(f"JSON directory does not exist: {json_dir}")
                import typer
                raise typer.Exit(1)
        else:
            # Generate JSON data using ruminant json command
            json_path = Path("website-json-temp")
            info("Generating JSON data from ruminant json...")
            try:
                result = subprocess.run(
                    ["uv", "run", "ruminant", "json", "--output", str(json_path), "--pretty"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                success("JSON data generated successfully")
            except subprocess.CalledProcessError as e:
                error(f"Failed to generate JSON data: {e.stderr}")
                import typer
                raise typer.Exit(1)

        # Create output directories
        output_path.mkdir(exist_ok=True)
        feeds_dir = output_path / "feeds"
        feeds_dir.mkdir(exist_ok=True)

        info(f"Generating Atom feeds in {output_path}")

        # Load users data from JSON
        users_data = {}
        users_file = json_path / "users.json"
        if users_file.exists():
            info("Loading user data for enhanced feed generation...")
            try:
                with open(users_file, 'r', encoding='utf-8') as f:
                    users_data = json.load(f)
                if users_data:
                    info(f"Loaded data for {len(users_data)} users")
            except Exception as e:
                warning(f"Failed to load users data: {e}")

        # Track generated feeds for OPML
        generated_feeds = {}

        # Process each group by loading their summaries from week files
        weeks_dir = json_path / "weeks"
        if weeks_dir.exists():
            # First, collect all week data
            all_weeks_data = {}
            for week_file in sorted(weeks_dir.glob("*.json")):
                try:
                    with open(week_file, 'r', encoding='utf-8') as f:
                        week_data = json.load(f)
                        week_key = week_data.get('week_key', week_file.stem)
                        all_weeks_data[week_key] = week_data
                except Exception as e:
                    warning(f"Failed to read week file {week_file}: {e}")
                    continue

            # Now process each group's summaries
            for group_name in config.groups.keys():
                group_summaries = []

                # Collect all summaries for this group from week data
                for week_data in all_weeks_data.values():
                    group_sums = week_data.get('group_summaries', [])
                    for group_sum in group_sums:
                        if group_sum.get('group') == group_name:
                            # Add year and week info to the summary
                            group_sum['year'] = week_data.get('year')
                            group_sum['week'] = week_data.get('week')
                            if 'week_range' not in group_sum:
                                group_sum['week_range'] = week_data.get('week_range')
                            group_summaries.append(group_sum)

                if not group_summaries:
                    console.print(f"[yellow]⚠️  No summaries found for group: {group_name}[/yellow]")
                    continue

                # Generate Atom feed for this group
                try:
                    fg = create_atom_feed(group_name, group_summaries, config, users_data)

                    # Save the feed
                    feed_path = feeds_dir / f"{group_name}.xml"
                    fg.atom_file(str(feed_path), pretty=pretty)

                    generated_feeds[group_name] = str(feed_path)
                    success(f"Generated Atom feed: {feed_path}")

                except Exception as e:
                    error(f"Failed to generate feed for {group_name}: {e}")
                    continue

            # Generate weekly summary feed (includes group summaries) using already loaded weeks data
            weeks_data = list(all_weeks_data.values())

            # Generate per-repository feeds
            info("Generating per-repository Atom feeds...")
            repos_dir = feeds_dir / "repos"
            repos_dir.mkdir(exist_ok=True)

            # Collect all repository summaries from week data
            repository_summaries = {}
            for week_data in all_weeks_data.values():
                repo_reports = week_data.get('repositories', [])  # Changed from 'reports' to 'repositories'
                for report in repo_reports:
                    repo_name = report.get('repo')  # Changed from 'repository' to 'repo'
                    if repo_name:
                        if repo_name not in repository_summaries:
                            repository_summaries[repo_name] = []

                        # Create a summary entry for this week
                        repo_summary = {
                            'year': report.get('year') or week_data.get('year'),
                            'week': report.get('week') or week_data.get('week'),
                            'week_range': report.get('week_range') or week_data.get('week_range'),
                            'brief_summary': report.get('brief_summary', ''),
                            'summary': report.get('activity_summary', ''),  # Changed to match actual field
                            'activity': report.get('activity', ''),
                            'merged_prs': report.get('merged_pull_requests', ''),  # Changed to match actual field
                            'opened_prs': report.get('opened_pull_requests', ''),  # Changed to match actual field
                            'opened_issues': report.get('opened_issues', '')
                        }
                        repository_summaries[repo_name].append(repo_summary)

            # Generate feed for each repository
            repo_count = 0
            for repo_name, summaries in repository_summaries.items():
                if not summaries:
                    continue

                try:
                    repo_fg = create_repository_atom_feed(repo_name, summaries, config, users_data)

                    # Save the feed
                    repo_slug = repo_name.replace('/', '-')
                    repo_feed_path = repos_dir / f"{repo_slug}.xml"
                    repo_fg.atom_file(str(repo_feed_path), pretty=pretty)

                    generated_feeds[f"repo:{repo_name}"] = str(repo_feed_path)
                    repo_count += 1

                except Exception as e:
                    warning(f"Failed to generate feed for repository {repo_name}: {e}")
                    continue

            if repo_count > 0:
                success(f"Generated {repo_count} repository feeds in {repos_dir}")

        # Generate weekly summary feed (includes group summaries)
        if weeks_dir.exists() and weeks_data:
            try:
                weekly_fg = create_weekly_atom_feed(weeks_data, config, users_data)
                weekly_feed_path = feeds_dir / "weekly.xml"
                weekly_fg.atom_file(str(weekly_feed_path), pretty=pretty)
                generated_feeds['weekly'] = str(weekly_feed_path)
                success(f"Generated weekly summary feed: {weekly_feed_path}")
            except Exception as e:
                warning(f"Failed to generate weekly summary feed: {e}")

        # Generate daily feed for current week
        current_year = datetime.now().year
        current_week = datetime.now().isocalendar()[1]
        daily_summaries = []

        # Load daily summaries for current week
        week_daily_file = Path(f"data/weekly_daily/{current_year}/week-{current_week:02d}-daily.json")
        if week_daily_file.exists():
            try:
                with open(week_daily_file, 'r', encoding='utf-8') as f:
                    daily_data = json.load(f)
                    # Convert dict to list of summaries
                    daily_summaries = list(daily_data.values())

                if daily_summaries:
                    daily_fg = create_daily_atom_feed(daily_summaries, config, users_data)
                    daily_feed_path = feeds_dir / "daily.xml"
                    daily_fg.atom_file(str(daily_feed_path), pretty=pretty)
                    generated_feeds['daily'] = str(daily_feed_path)
                    success(f"Generated daily feed with {len(daily_summaries)} entries: {daily_feed_path}")
            except Exception as e:
                warning(f"Failed to generate daily feed: {e}")

        # Generate OPML file
        if generated_feeds:
            try:
                opml_content = create_opml(generated_feeds, config)
                opml_path = output_path / "feeds.opml"

                with open(opml_path, 'w', encoding='utf-8') as f:
                    f.write(opml_content)

                success(f"Generated OPML file: {opml_path}")

            except Exception as e:
                error(f"Failed to generate OPML file: {e}")

        # Clean up temporary JSON directory if we created it
        if not json_dir and json_path.exists():
            try:
                shutil.rmtree(json_path)
            except:
                pass

        # Summary
        console.print(f"\n✨ Generated {len(generated_feeds)} Atom feeds")
        if generated_feeds:
            console.print("\nFeeds generated for groups:")
            for group_name in sorted(generated_feeds.keys()):
                console.print(f"  • {group_name}")

    except Exception as e:
        error(f"Failed to generate Atom feeds: {e}")
        import typer
        raise typer.Exit(1)