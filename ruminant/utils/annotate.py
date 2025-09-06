"""Annotation utilities adapted from annotate.py."""

import json
import re
import requests
from pathlib import Path
from typing import Dict, Optional, Set
import uuid

from .logging import warning, error, info


# Cache directory for user data
USERS_CACHE_DIR = Path("data") / "users"


def ensure_users_dir():
    """Ensure the users cache directory exists."""
    USERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_user_cache(username: str) -> Optional[Dict]:
    """Load cached user data if it exists."""
    ensure_users_dir()
    cache_file = USERS_CACHE_DIR / f"{username}.json"
    
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            warning(f"Error loading cache for {username}: {e}")
    return None


def save_user_cache(username: str, user_data: Dict):
    """Save user data to cache."""
    ensure_users_dir()
    cache_file = USERS_CACHE_DIR / f"{username}.json"
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        warning(f"Error saving cache for {username}: {e}")


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
            warning(f"User {username} not found on GitHub")
        else:
            warning(f"Error fetching user {username}: HTTP {response.status_code}")
    except Exception as e:
        warning(f"Error fetching user info for {username}: {e}")
    
    # Return username as fallback
    return username


def extract_repo_from_path(file_path: Path) -> Optional[str]:
    """Extract repository owner/name from the file path structure."""
    # Expected structure: data/summaries/owner/repo/week-NN-YYYY.md or data/reports/owner/repo/week-NN-YYYY.md
    parts = file_path.parts
    
    # Find data directory in path
    try:
        data_idx = parts.index('data')
        if len(parts) > data_idx + 3:
            # Skip the type directory (summaries/reports)
            owner = parts[data_idx + 2]
            repo = parts[data_idx + 3]
            return f"{owner}/{repo}"
    except (ValueError, IndexError):
        pass
    
    return None


def add_github_links(text: str, repo: Optional[str], token: Optional[str]) -> str:
    """Convert @username references to GitHub links with full names."""
    
    # First, protect existing markdown links by temporarily replacing them
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
    
    # Add issue/PR links if we know the repository
    if repo:
        # Pattern to match #1234 (issue/PR references) but not if already in a link
        issue_pattern = r'(?<!\[)#(\d+)(?!\])'
        
        def replace_issue_reference(match):
            issue_number = match.group(1)
            url = f"https://github.com/{repo}/issues/{issue_number}"
            return f"[#{issue_number}]({url})"
        
        # Apply issue/PR transformations
        text = re.sub(issue_pattern, replace_issue_reference, text)
        
        # Add repository link if it's not already linked
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
    seen_usernames: Set[str] = set()
    unique_contributors = []
    
    for display_name, github_path in contributor_links:
        # Skip if this is an issue/PR link (contains /issues/ or /pull/)
        if '/issues/' in github_path or '/pull/' in github_path:
            continue
        
        # Skip if the display name starts with # (it's a PR/issue reference)
        if display_name.startswith('#'):
            continue
            
        username = github_path
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


def annotate_file(input_file: Path, output_file: Path, token: Optional[str]) -> bool:
    """Annotate a single markdown file with GitHub links."""
    try:
        # Read the file
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract repository from path
        repo = extract_repo_from_path(input_file)
        if repo:
            info(f"Processing {input_file.name} for repository {repo}")
        else:
            info(f"Processing {input_file.name} (repository not detected from path)")
        
        # Add GitHub links
        annotated_content = add_github_links(content, repo, token)
        
        # Deduplicate contributors section
        annotated_content = deduplicate_contributors_section(annotated_content)
        
        # Write the annotated content
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(annotated_content)
        
        return True
        
    except Exception as e:
        error(f"Error processing {input_file}: {e}")
        return False


def clear_user_cache() -> int:
    """Clear the user cache and return the number of files removed."""
    if not USERS_CACHE_DIR.exists():
        return 0
    
    cache_files = list(USERS_CACHE_DIR.glob("*.json"))
    count = len(cache_files)
    
    for cache_file in cache_files:
        try:
            cache_file.unlink()
        except Exception as e:
            warning(f"Error removing cache file {cache_file}: {e}")
    
    try:
        USERS_CACHE_DIR.rmdir()
    except Exception:
        # Directory might not be empty due to errors above
        pass
    
    return count


def get_cache_stats() -> Dict:
    """Get statistics about the user cache."""
    if not USERS_CACHE_DIR.exists():
        return {"count": 0, "size": 0, "users": []}
    
    cache_files = list(USERS_CACHE_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in cache_files)
    
    users = []
    for cache_file in cache_files[:10]:  # Sample first 10
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                users.append({
                    "username": cache_file.stem,
                    "name": data.get('name', 'N/A')
                })
        except Exception:
            users.append({
                "username": cache_file.stem,
                "name": "(error reading)"
            })
    
    return {
        "count": len(cache_files),
        "size": total_size,
        "users": users
    }