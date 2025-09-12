"""Generate Atom feeds and OPML from JSON summaries."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import pytz
from feedgen.feed import FeedGenerator
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from ..config import load_config
from ..utils.logging import console, success, error, info
from ..utils.paths import get_data_dir


def create_atom_feed(group_name: str, summaries: List[Dict[str, Any]], config: Any) -> FeedGenerator:
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
    feed_id = f"{base_url}/feeds/{group_name}.atom"
    fg.id(feed_id)
    fg.title(f"{group_title} - Weekly Activity")
    fg.author({'name': author_name, 'email': author_email})
    fg.link(href=feed_id, rel='self')
    fg.link(href=f"{base_url}/groups/{group_name}", rel='alternate')
    fg.subtitle(group_description)
    fg.language('en')
    
    # Sort summaries by date (newest first)
    sorted_summaries = sorted(
        summaries,
        key=lambda x: (x.get('year', 0), x.get('week', 0)),
        reverse=True
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
        fe.link(href=entry_id)
        
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
        
        if summary.get('group_overview'):
            content_parts.append(f"<h2>Group Overview</h2>\n{markdown_to_html(summary['group_overview'])}")
        
        if summary.get('cross_repository_work'):
            content_parts.append(f"<h2>Cross-Repository Work</h2>\n{markdown_to_html(summary['cross_repository_work'])}")
        
        if summary.get('key_projects'):
            content_parts.append(f"<h2>Key Projects and Initiatives</h2>\n{markdown_to_html(summary['key_projects'])}")
        
        if summary.get('priority_items'):
            content_parts.append(f"<h2>Priority Items</h2>\n{markdown_to_html(summary['priority_items'])}")
        
        if summary.get('notable_discussions'):
            content_parts.append(f"<h2>Notable Discussions</h2>\n{markdown_to_html(summary['notable_discussions'])}")
        
        if summary.get('emerging_trends'):
            content_parts.append(f"<h2>Emerging Trends</h2>\n{markdown_to_html(summary['emerging_trends'])}")
        
        content = '\n'.join(content_parts)
        fe.content(content, type='html')
        
        # Add summary
        summary_text = brief or f"Activity report for {group_name} - Week {week}, {year}"
        fe.summary(summary_text)
    
    # Update feed's updated time to the most recent entry
    if sorted_summaries:
        latest = sorted_summaries[0]
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


def markdown_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML for feed content."""
    import markdown2
    
    if not markdown_text:
        return ""
    
    # Convert markdown to HTML with GitHub-flavored markdown support
    html = markdown2.markdown(
        markdown_text,
        extras=['fenced-code-blocks', 'tables']
    )
    
    return html


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
    
    # Add outline for each feed
    for group_name, feed_path in sorted(feeds.items()):
        group_config = config.groups.get(group_name, None)
        group_title = group_config.name if group_config else group_name.title()
        group_description = group_config.description if group_config else ""
        
        outline = SubElement(body, 'outline',
                           text=group_title,
                           title=group_title,
                           type='rss',
                           xmlUrl=f"{base_url}/feeds/{group_name}.atom",
                           htmlUrl=f"{base_url}/groups/{group_name}")
        
        if group_description:
            outline.set('description', group_description)
    
    # Pretty print the XML
    rough_string = tostring(opml, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding='UTF-8').decode('utf-8')


def atom_main(output_dir: str, pretty: bool = False) -> None:
    """Main function for generating Atom feeds."""
    try:
        config = load_config()
        data_dir = get_data_dir()
        groups_dir = data_dir / "groups"
        output_path = Path(output_dir)
        
        # Create output directories
        output_path.mkdir(exist_ok=True)
        feeds_dir = output_path / "feeds"
        feeds_dir.mkdir(exist_ok=True)
        
        info(f"Generating Atom feeds in {output_path}")
        
        # Track generated feeds for OPML
        generated_feeds = {}
        
        # Process each group
        for group_name in config.groups.keys():
            group_data_dir = groups_dir / group_name
            
            if not group_data_dir.exists():
                console.print(f"[yellow]⚠️  No data found for group: {group_name}[/yellow]")
                continue
            
            # Collect all JSON summaries for this group
            json_files = sorted(group_data_dir.glob("week-*.json"))
            summaries = []
            
            for json_file in json_files:
                try:
                    with open(json_file, 'r') as f:
                        summary = json.load(f)
                        summaries.append(summary)
                except Exception as e:
                    error(f"Failed to read {json_file}: {e}")
                    continue
            
            if not summaries:
                console.print(f"[yellow]⚠️  No summaries found for group: {group_name}[/yellow]")
                continue
            
            # Generate Atom feed for this group
            try:
                fg = create_atom_feed(group_name, summaries, config)
                
                # Save the feed
                feed_path = feeds_dir / f"{group_name}.atom"
                fg.atom_file(str(feed_path), pretty=pretty)
                
                generated_feeds[group_name] = str(feed_path)
                success(f"Generated Atom feed: {feed_path}")
                
            except Exception as e:
                error(f"Failed to generate feed for {group_name}: {e}")
                continue
        
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
        
        # Summary
        console.print(f"\n✨ Generated {len(generated_feeds)} Atom feeds")
        if generated_feeds:
            console.print("\nFeeds generated for groups:")
            for group_name in sorted(generated_feeds.keys()):
                console.print(f"  • {group_name}")
        
    except Exception as e:
        error(f"Failed to generate Atom feeds: {e}")
        raise typer.Exit(1)