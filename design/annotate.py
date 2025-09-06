#!/usr/bin/env python3
# /// script
# dependencies = [
#     "requests",
# ]
# ///
"""
Annotate markdown reports with GitHub links for usernames and repositories.
Following logic from weekly.py to add hrefs to @username mentions and repo references.
"""

import os
import sys
import argparse
import json
import re
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple
import glob as file_glob

# Cache directory for user data
USERS_DIR = ".users"

def ensure_users_dir():
    """Ensure the users cache directory exists."""
    os.makedirs(USERS_DIR, exist_ok=True)

def get_github_token():
    """Get GitHub API token from environment or .gh-key file."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            with open(".gh-key", "r") as f:
                token = f.read().strip()
        except FileNotFoundError:
            pass
    return token

def load_user_cache(username: str) -> Optional[Dict]:
    """Load cached user data if it exists."""
    ensure_users_dir()
    cache_file = os.path.join(USERS_DIR, f"{username}.json")
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Error loading cache for {username}: {e}")
    return None

def save_user_cache(username: str, user_data: Dict):
    """Save user data to cache."""
    ensure_users_dir()
    cache_file = os.path.join(USERS_DIR, f"{username}.json")
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Error saving cache for {username}: {e}")

def get_user_full_name(username: str, token: Optional[str] = None) -> str:
    """Get the full name for a GitHub username, using cache when possible."""
    # Check cache first
    cached_data = load_user_cache(username)
    if cached_data:
        return cached_data.get('name') or username
    
    # Make API call to get user info
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    
    user_url = f"https://api.github.com/users/{username}"
    try:
        response = requests.get(user_url, headers=headers, timeout=10)
        if response.status_code == 200:
            user_data = response.json()
            full_name = user_data.get('name') or username
            
            # Save to cache
            save_user_cache(username, {
                'login': username,
                'name': full_name,
                'url': user_data.get('html_url', f"https://github.com/{username}"),
                'avatar_url': user_data.get('avatar_url', ''),
                'bio': user_data.get('bio', ''),
                'company': user_data.get('company', ''),
                'location': user_data.get('location', '')
            })
            
            return full_name
        elif response.status_code == 404:
            print(f"Warning: User {username} not found on GitHub")
        else:
            print(f"Warning: Error fetching user {username}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Warning: Error fetching user info for {username}: {e}")
    
    # Return username as fallback
    return username

def extract_repo_from_path(file_path: str) -> Optional[str]:
    """Extract repository owner/name from the file path structure."""
    # Expected structure: .claude-report/owner/repo/week.md
    path_parts = Path(file_path).parts
    
    # Find .claude-report in path
    try:
        claude_idx = path_parts.index('.claude-report')
        if len(path_parts) > claude_idx + 2:
            owner = path_parts[claude_idx + 1]
            repo = path_parts[claude_idx + 2]
            return f"{owner}/{repo}"
    except ValueError:
        pass
    
    return None

def add_github_links(text: str, repo: Optional[str], token: Optional[str]) -> str:
    """Convert @username references to GitHub links with full names."""
    
    # First, protect existing markdown links by temporarily replacing them
    import uuid
    placeholders = {}
    
    # Find and replace existing markdown links with placeholders
    existing_link_pattern = r'\[([^\]]+)\]\([^)]+\)'
    
    def create_placeholder(match):
        placeholder = f"__LINK_PLACEHOLDER_{uuid.uuid4().hex}__"
        placeholders[placeholder] = match.group(0)
        return placeholder
    
    # Replace existing links with placeholders
    text = re.sub(existing_link_pattern, create_placeholder, text)
    
    # Pattern to match @username (but not if already in a link)
    username_pattern = r'@([a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)'
    
    def replace_username_reference(match):
        username = match.group(1)
        full_name = get_user_full_name(username, token)
        url = f"https://github.com/{username}"
        
        # Use full name if different from username, otherwise just use @username
        if full_name != username:
            return f"[{full_name}]({url})"
        else:
            return f"[@{username}]({url})"
    
    # Apply username transformations
    text = re.sub(username_pattern, replace_username_reference, text)
    
    # Add repository link if we can detect it and it's not already linked
    if repo:
        # Add link to the repository in the title if it's not already linked
        repo_pattern = rf'\b{re.escape(repo)}\b(?!\])'
        repo_replacement = f"[{repo}](https://github.com/{repo})"
        
        # Only replace in the title line (first line)
        lines = text.split('\n')
        if lines:
            lines[0] = re.sub(repo_pattern, repo_replacement, lines[0])
            text = '\n'.join(lines)
    
    # Restore the original markdown links
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    
    return text

def deduplicate_contributors_section(text: str) -> str:
    """Remove duplicates from the Contributors section."""
    # Find the Contributors section
    contributors_match = re.search(r'## Contributors\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL)
    if not contributors_match:
        return text
    
    contributors_content = contributors_match.group(1).strip()
    
    # Extract all contributor links using regex
    contributor_links = re.findall(r'\[([^\]]+)\]\(https://github\.com/([^)]+)\)', contributors_content)
    
    # Deduplicate by GitHub username (second group in match)
    seen_usernames = set()
    unique_contributors = []
    
    for display_name, username in contributor_links:
        if username not in seen_usernames:
            seen_usernames.add(username)
            unique_contributors.append(f"[{display_name}](https://github.com/{username})")
    
    # Also check for @username patterns that might not be linked yet
    username_mentions = re.findall(r'@([a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?)', contributors_content)
    for username in username_mentions:
        if username not in seen_usernames:
            seen_usernames.add(username)
            unique_contributors.append(f"[@{username}](https://github.com/{username})")
    
    if unique_contributors:
        # Sort contributors alphabetically by display name
        unique_contributors.sort()
        
        # Create clean contributors section
        new_contributors_section = "## Contributors\n\n"
        new_contributors_section += "Thank you to all contributors for their work during this period:\n\n"
        new_contributors_section += ", ".join(unique_contributors)
        
        # Replace the old section with the new one
        return re.sub(
            r'## Contributors\s*\n.*?(?=\n##|\Z)',
            new_contributors_section,
            text,
            flags=re.DOTALL
        )
    
    return text

def process_file(file_path: str, token: Optional[str], in_place: bool = False, output_dir: Optional[str] = None) -> bool:
    """Process a single markdown file to add annotations."""
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract repository from path
        repo = extract_repo_from_path(file_path)
        if repo:
            print(f"Processing {file_path} for repository {repo}")
        else:
            print(f"Processing {file_path} (repository not detected from path)")
        
        # Add GitHub links
        annotated_content = add_github_links(content, repo, token)
        
        # Deduplicate contributors section
        annotated_content = deduplicate_contributors_section(annotated_content)
        
        # Determine output path
        if in_place:
            output_path = file_path
        elif output_dir:
            # Maintain directory structure in output
            rel_path = os.path.relpath(file_path, '.')
            output_path = os.path.join(output_dir, rel_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        else:
            # Add .annotated suffix
            base, ext = os.path.splitext(file_path)
            output_path = f"{base}.annotated{ext}"
        
        # Write the annotated content
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(annotated_content)
        
        if in_place:
            print(f"✓ Updated {file_path} in place")
        else:
            print(f"✓ Wrote annotated version to {output_path}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error processing {file_path}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Annotate markdown reports with GitHub links for usernames and repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Annotate a single file
  python annotate.py .claude-report/ocaml/opam-repository/35.md
  
  # Annotate all reports for a repository
  python annotate.py '.claude-report/ocaml/opam-repository/*.md'
  
  # Annotate all reports recursively
  python annotate.py '.claude-report/**/*.md'
  
  # Update files in place
  python annotate.py --in-place '.claude-report/**/*.md'
  
  # Output to different directory
  python annotate.py --output-dir annotated-reports '.claude-report/**/*.md'
  
  # Clear user cache
  python annotate.py --clear-cache
        """
    )
    
    parser.add_argument(
        "files",
        nargs='*',
        help="Markdown files to annotate (supports wildcards)"
    )
    
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Modify files in place instead of creating new files"
    )
    
    parser.add_argument(
        "--output-dir",
        help="Directory to write annotated files (maintains structure)"
    )
    
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear the user cache and exit"
    )
    
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show cache statistics"
    )
    
    args = parser.parse_args()
    
    # Handle cache operations
    if args.clear_cache:
        if os.path.exists(USERS_DIR):
            import shutil
            shutil.rmtree(USERS_DIR)
            print(f"✓ Cleared user cache directory: {USERS_DIR}")
        else:
            print(f"No cache directory to clear: {USERS_DIR}")
        return
    
    if args.stats:
        if os.path.exists(USERS_DIR):
            cache_files = list(Path(USERS_DIR).glob("*.json"))
            print(f"User cache statistics:")
            print(f"  Cache directory: {USERS_DIR}")
            print(f"  Cached users: {len(cache_files)}")
            
            total_size = sum(f.stat().st_size for f in cache_files)
            print(f"  Total size: {total_size:,} bytes ({total_size/1024:.1f} KB)")
            
            if cache_files:
                print(f"\nSample cached users:")
                for f in cache_files[:10]:
                    username = f.stem
                    try:
                        with open(f, 'r') as jf:
                            data = json.load(jf)
                            name = data.get('name', 'N/A')
                            print(f"    @{username} -> {name}")
                    except:
                        print(f"    @{username} -> (error reading)")
                
                if len(cache_files) > 10:
                    print(f"    ... and {len(cache_files) - 10} more")
        else:
            print(f"No cache directory found: {USERS_DIR}")
        return
    
    # Validate arguments
    if not args.files:
        parser.error("No files specified to annotate")
    
    # Get GitHub token
    token = get_github_token()
    if not token:
        print("Warning: No GitHub token found. API rate limits will be lower.")
        print("Set GITHUB_TOKEN environment variable or create .gh-key file.")
    
    # Expand wildcards and collect all files
    all_files = []
    for pattern in args.files:
        # Use glob to expand wildcards
        if '*' in pattern or '?' in pattern:
            matches = file_glob.glob(pattern, recursive=True)
            all_files.extend(matches)
        else:
            # Single file
            if os.path.exists(pattern):
                all_files.append(pattern)
            else:
                print(f"Warning: File not found: {pattern}")
    
    # Filter to only .md files
    md_files = [f for f in all_files if f.endswith('.md')]
    
    if not md_files:
        print("No markdown files found to process")
        return
    
    print(f"Found {len(md_files)} markdown file(s) to process")
    
    # Process each file
    success_count = 0
    for file_path in md_files:
        if process_file(file_path, token, args.in_place, args.output_dir):
            success_count += 1
    
    print(f"\n✓ Successfully processed {success_count}/{len(md_files)} files")
    
    # Show cache stats at the end
    if os.path.exists(USERS_DIR):
        cache_files = list(Path(USERS_DIR).glob("*.json"))
        print(f"User cache now contains {len(cache_files)} users")

if __name__ == "__main__":
    main()