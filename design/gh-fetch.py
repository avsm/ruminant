#!/usr/bin/env python3
# /// script
# dependencies = [
#     "requests",
#     "python-dateutil",
#     "pytz",
# ]
# ///
"""
GitHub data fetcher for weekly activity reports.
This script fetches and caches GitHub issues, PRs, and discussions data.
"""

import os
import sys
import argparse
import json
import pickle
import time
from datetime import datetime, timedelta
import requests
from dateutil.parser import parse
import pytz
import logging

logging.basicConfig(level=logging.INFO)

# Cache file paths
CACHE_FILE = ".gh-weekly-cache.pkl"
CACHE_DIR = ".cache"


def load_cache():
    """Load the persistent cache from disk."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"Warning: Error loading cache file: {e}")
    return {
        'repo_items': {},  # repo -> {number: type} mapping
        'users': {},       # username -> full_name mapping
        'last_updated': {}  # track when cache entries were last updated
    }


def save_cache(cache):
    """Save the persistent cache to disk."""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"Warning: Error saving cache file: {e}")


def get_cache_file_path(repo, year, week):
    """Get the cache file path for a specific repo and week."""
    owner, name = repo.split("/")
    cache_dir = os.path.join(CACHE_DIR, owner, name)
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"week-{week:02d}-{year}.json")


def load_week_cache(repo, year, week, max_age_hours=24):
    """Load cached data for a specific repo and week."""
    cache_file = get_cache_file_path(repo, year, week)
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Check if cache is fresh
                cache_time = datetime.fromisoformat(data['metadata']['cached_at'])
                age_seconds = (datetime.now() - cache_time).total_seconds()
                if age_seconds < max_age_hours * 3600:
                    print(f"✓ Using cached data for {repo} week {week} of {year} (age: {age_seconds/3600:.1f}h)")
                    return data
                else:
                    print(f"Cache expired for {repo} week {week} of {year} (age: {age_seconds/3600:.1f}h)")
        except Exception as e:
            print(f"Warning: Error loading cache file {cache_file}: {e}")
    return None


def save_week_cache(repo, year, week, data):
    """Save data for a specific repo and week."""
    cache_file = get_cache_file_path(repo, year, week)
    
    # Add metadata
    week_start, week_end = get_week_date_range(year, week)
    cache_data = {
        'metadata': {
            'repo': repo,
            'year': year,
            'week': week,
            'week_start': week_start.strftime('%Y-%m-%d'),
            'week_end': week_end.strftime('%Y-%m-%d'),
            'cached_at': datetime.now().isoformat(),
        },
        'issues': data['issues'],
        'prs': data['prs'],
        'good_first_issues': data['good_first_issues'],
        'discussions': data['discussions']
    }
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"✓ Cached data saved to {cache_file}")
    except Exception as e:
        print(f"✗ Error saving cache file {cache_file}: {e}")


def get_week_date_range(year, week):
    """Get the start and end dates for a given year and week number (ISO 8601)."""
    # Get the first day of the year
    jan_4 = datetime(year, 1, 4, tzinfo=pytz.utc)
    # Find the start of week 1 (Monday)
    week_1_start = jan_4 - timedelta(days=jan_4.weekday())
    # Calculate the start of the requested week
    week_start = week_1_start + timedelta(weeks=week - 1)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return week_start, week_end


def get_last_complete_week():
    """Get the year and week number of the last complete week."""
    now = datetime.now()
    last_week = now - timedelta(days=7)
    return last_week.isocalendar()[0], last_week.isocalendar()[1]


def get_week_list(num_weeks, end_year=None, end_week=None):
    """Get a list of (year, week) tuples for the last num_weeks weeks."""
    if end_year is None or end_week is None:
        end_year, end_week = get_last_complete_week()
    
    weeks = []
    current_year, current_week = end_year, end_week
    
    for i in range(num_weeks):
        weeks.append((current_year, current_week))
        
        # Move to previous week
        current_week -= 1
        if current_week < 1:
            # Move to previous year
            current_year -= 1
            # Get the last week of the previous year
            dec_31 = datetime(current_year, 12, 31)
            current_week = dec_31.isocalendar()[1]
    
    # Return in chronological order (oldest first)
    return list(reversed(weeks))


def get_github_api_token():
    """Get GitHub API token from environment variables or .gh-key file."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            with open(".gh-key", "r") as f:
                token = f.read().strip()
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Warning: Error reading .gh-key file: {e}")
    
    if not token:
        print(
            "Warning: GitHub API token not found. Set the GITHUB_TOKEN environment variable or create a .gh-key file."
        )
        print("Without a token, API rate limits will be lower.")
    return token


def fetch_graphql_data(query, variables, headers):
    """Fetch data from GraphQL API with retries."""
    url = "https://api.github.com/graphql"
    
    # Retry logic for GraphQL API
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url, json={"query": query, "variables": variables}, headers=headers, timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Check for GraphQL errors
                if "errors" in result and result["errors"]:
                    for error in result["errors"]:
                        error_type = error.get("type", "UNKNOWN")
                        message = error.get("message", "Unknown error")
                        print(f"❌ GraphQL Error ({error_type}): {message}")
                        
                        # Handle specific error types
                        if error_type == "FORBIDDEN":
                            print("💡 This is likely due to token permissions or repository access restrictions.")
                            if "fine-grained personal access tokens" in message:
                                print("💡 Try using a classic personal access token or adjust your token's lifetime.")
                            sys.exit(1)
                        elif error_type in ["NOT_FOUND", "UNAUTHORIZED"]:
                            print("💡 Check that the repository exists and your token has access to it.")
                            sys.exit(1)
                    
                    # If we have other errors but data is still present, continue with warnings
                    if result.get("data") is None:
                        return None
                
                # Check if data is missing
                if "data" not in result or result["data"] is None:
                    print("❌ No data returned from GraphQL API")
                    return None
                    
                return result
            elif response.status_code in [502, 503, 504]:
                if attempt < max_retries - 1:
                    print(f"GitHub API returned {response.status_code}, retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                    continue
            else:
                print(f"Error fetching data: {response.status_code}")
                return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                print(f"Request failed: {e}, retrying in {2 ** attempt} seconds...")
                time.sleep(2 ** attempt)
                continue
            else:
                print(f"Failed to fetch data after {max_retries} attempts: {e}")
                return None
    
    return None


def is_in_week_range(timestamp_str, week_start, week_end):
    """Check if the timestamp falls within the specified week range."""
    timestamp = parse(timestamp_str)
    return week_start <= timestamp <= week_end


def has_activity_in_week(item, week_start, week_end):
    """Check if an issue or PR had any activity during the specified week."""
    # Check if created during the week
    if is_in_week_range(item["createdAt"], week_start, week_end):
        return True
    
    # Check if updated during the week
    if is_in_week_range(item["updatedAt"], week_start, week_end):
        return True
    
    # Check timeline items for activity during the week
    timeline_items = item.get("timelineItems", {}).get("nodes", [])
    for timeline_item in timeline_items:
        # Check various date fields that might exist in timeline items
        date_fields = ["createdAt", "committedDate"]
        for field in date_fields:
            if field in timeline_item:
                if is_in_week_range(timeline_item[field], week_start, week_end):
                    return True
            # Handle nested commit data
            elif "commit" in timeline_item and field in timeline_item["commit"]:
                if is_in_week_range(timeline_item["commit"][field], week_start, week_end):
                    return True
    
    return False


def format_issue_entry(issue):
    """Format a GraphQL issue response into the expected format."""
    comments_data = issue.get("comments", {})
    comments_list = []
    for comment in comments_data.get("nodes", []):
        author = comment["author"]["login"] if comment["author"] else "ghost"
        body = comment.get("bodyText", "")
        if body:
            comments_list.append(f"@{author}: {body}")
    
    return {
        "id": issue["number"],
        "title": issue["title"],
        "url": issue["url"],
        "user": issue["author"]["login"] if issue["author"] else "ghost",
        "updated_at": issue["updatedAt"],
        "body": issue.get("bodyText", "") or "",
        "labels": [label["name"] for label in issue.get("labels", {}).get("nodes", [])],
        "state": issue["state"].lower(),
        "comments": comments_list,
    }


def format_pr_entry(pr):
    """Format a GraphQL PR response into the expected format."""
    comments_data = pr.get("comments", {})
    comments_list = []
    for comment in comments_data.get("nodes", []):
        author = comment["author"]["login"] if comment["author"] else "ghost"
        body = comment.get("bodyText", "")
        if body:
            comments_list.append(f"@{author}: {body}")
    
    return {
        "id": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "user": pr["author"]["login"] if pr["author"] else "ghost",
        "updated_at": pr["updatedAt"],
        "body": pr.get("bodyText", "") or "",
        "labels": [label["name"] for label in pr.get("labels", {}).get("nodes", [])],
        "state": pr["state"].lower(),
        "comments": comments_list,
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changedFiles", 0),
        "mergeable": pr.get("mergeable"),
        "draft": pr.get("isDraft", False),
    }


def is_good_first_issue(item):
    """Check if an item is tagged as a good first issue."""
    label_names = [label["name"].lower() for label in item.get("labels", {}).get("nodes", [])]
    return any(
        name in [
            "good first issue",
            "good-first-issue", 
            "beginner friendly",
            "beginner-friendly",
            "easy",
        ]
        for name in label_names
    )


def fetch_issues(repo, token, week_start, week_end):
    """Fetch issues and PRs from a repository for a specific week using GraphQL."""
    year, week = week_start.isocalendar()[0], week_start.isocalendar()[1]
    
    # Check if we have cached data first
    cached_data = load_week_cache(repo, year, week)
    if cached_data:
        return (
            cached_data['issues'],
            cached_data['prs'], 
            cached_data['good_first_issues']
        )
    
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    # GraphQL query to fetch both issues and PRs with timeline data
    query = """
    query($owner: String!, $name: String!, $issuesAfter: String, $prsAfter: String) {
        repository(owner: $owner, name: $name) {
            issues(first: 25, after: $issuesAfter, orderBy: {field: UPDATED_AT, direction: DESC}) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    number
                    title
                    url
                    author {
                        login
                    }
                    createdAt
                    updatedAt
                    bodyText
                    state
                    labels(first: 20) {
                        nodes {
                            name
                        }
                    }
                    comments(first: 10, orderBy: {field: UPDATED_AT, direction: DESC}) {
                        totalCount
                        nodes {
                            author {
                                login
                            }
                            bodyText
                            createdAt
                            updatedAt
                        }
                    }
                    timelineItems(itemTypes: [ISSUE_COMMENT, LABELED_EVENT, UNLABELED_EVENT, CLOSED_EVENT, REOPENED_EVENT], first: 25) {
                        nodes {
                            ... on IssueComment {
                                createdAt
                            }
                            ... on LabeledEvent {
                                createdAt
                            }
                            ... on UnlabeledEvent {
                                createdAt
                            }
                            ... on ClosedEvent {
                                createdAt
                            }
                            ... on ReopenedEvent {
                                createdAt
                            }
                        }
                    }
                }
            }
            pullRequests(first: 25, after: $prsAfter, orderBy: {field: UPDATED_AT, direction: DESC}) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    number
                    title
                    url
                    author {
                        login
                    }
                    createdAt
                    updatedAt
                    bodyText
                    state
                    labels(first: 20) {
                        nodes {
                            name
                        }
                    }
                    comments(first: 10, orderBy: {field: UPDATED_AT, direction: DESC}) {
                        totalCount
                        nodes {
                            author {
                                login
                            }
                            bodyText
                            createdAt
                            updatedAt
                        }
                    }
                    additions
                    deletions
                    changedFiles
                    mergeable
                    isDraft
                    timelineItems(itemTypes: [PULL_REQUEST_COMMIT, PULL_REQUEST_REVIEW, ISSUE_COMMENT, MERGED_EVENT, CLOSED_EVENT, REOPENED_EVENT], first: 25) {
                        nodes {
                            ... on PullRequestCommit {
                                commit {
                                    committedDate
                                }
                            }
                            ... on PullRequestReview {
                                createdAt
                            }
                            ... on IssueComment {
                                createdAt
                            }
                            ... on MergedEvent {
                                createdAt
                            }
                            ... on ClosedEvent {
                                createdAt
                            }
                            ... on ReopenedEvent {
                                createdAt
                            }
                        }
                    }
                }
            }
        }
    }
    """

    owner, name = repo.split("/")
    issues = []
    prs = []
    good_first_issues = []

    # Fetch all issues and PRs (with pagination if needed)
    issues_after = None
    prs_after = None
    page_count = 0
    max_pages = 20  # Safety limit to prevent infinite loops
    
    while page_count < max_pages:
        page_count += 1
        variables = {
            "owner": owner,
            "name": name,
            "issuesAfter": issues_after,
            "prsAfter": prs_after
        }

        # Fetch data from GraphQL API
        print(f"Fetching page {page_count} from GitHub GraphQL API...")
        result = fetch_graphql_data(query, variables, headers)

        if not result:
            break

        repo_data = result["data"]["repository"]
        if not repo_data:
            return [], [], []

        # Process issues
        issues_data = repo_data.get("issues", {})
        issue_nodes = issues_data.get("nodes", [])
        
        found_issues_this_page = 0
        for issue in issue_nodes:
            if has_activity_in_week(issue, week_start, week_end):
                entry = format_issue_entry(issue)
                issues.append(entry)
                found_issues_this_page += 1
                
                # Check if it's a good first issue
                if is_good_first_issue(issue) and issue["state"] == "OPEN":
                    good_first_issues.append(entry)

        # Process PRs
        prs_data = repo_data.get("pullRequests", {})
        pr_nodes = prs_data.get("nodes", [])
        
        found_prs_this_page = 0
        for pr in pr_nodes:
            if has_activity_in_week(pr, week_start, week_end):
                entry = format_pr_entry(pr)
                prs.append(entry)
                found_prs_this_page += 1

        # Check if we need to paginate
        issues_has_next = issues_data.get("pageInfo", {}).get("hasNextPage", False)
        prs_has_next = prs_data.get("pageInfo", {}).get("hasNextPage", False)
        
        # Update cursors
        new_issues_cursor = issues_data.get("pageInfo", {}).get("endCursor")
        new_prs_cursor = prs_data.get("pageInfo", {}).get("endCursor")
        
        # Break if no more pages or if cursors haven't changed
        if not issues_has_next and not prs_has_next:
            print(f"Finished pagination after {page_count} pages")
            break
        
        if issues_has_next and new_issues_cursor == issues_after:
            print("Issues cursor unchanged, breaking pagination")
            break
        if prs_has_next and new_prs_cursor == prs_after:
            print("PRs cursor unchanged, breaking pagination")
            break
            
        # Update cursors for next iteration
        if issues_has_next:
            issues_after = new_issues_cursor
        else:
            issues_after = None
            
        if prs_has_next:
            prs_after = new_prs_cursor
        else:
            prs_after = None
        
        print(f"Page {page_count}: Found {found_issues_this_page} issues and {found_prs_this_page} PRs in target week")
        
        # Early termination if we're not finding relevant activity
        if page_count > 5 and found_issues_this_page == 0 and found_prs_this_page == 0:
            print(f"No activity found in recent pages, stopping at page {page_count}")
            break

    print(f"Total: {len(issues)} issues, {len(prs)} PRs, {len(good_first_issues)} good first issues found for week {week}")
    
    # Save the fetched data to cache
    data_to_cache = {
        'issues': issues,
        'prs': prs,
        'good_first_issues': good_first_issues,
        'discussions': []  # Will be populated by fetch_discussions
    }
    save_week_cache(repo, year, week, data_to_cache)

    return issues, prs, good_first_issues


def fetch_discussions(repo, token, week_start, week_end):
    """Fetch discussions from a repository for a specific week."""
    year, week = week_start.isocalendar()[0], week_start.isocalendar()[1]
    
    # Check if we have cached data first
    cached_data = load_week_cache(repo, year, week)
    if cached_data and 'discussions' in cached_data:
        return cached_data['discussions']
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    # GraphQL query to fetch discussions
    query = """
    query($owner: String!, $name: String!) {
        repository(owner: $owner, name: $name) {
            discussions(first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
                nodes {
                    number
                    title
                    url
                    author {
                        login
                    }
                    updatedAt
                    bodyText
                    category {
                        name
                    }
                    comments {
                        totalCount
                    }
                    answerChosenAt
                }
            }
        }
    }
    """

    owner, name = repo.split("/")
    variables = {"owner": owner, "name": name}

    url = "https://api.github.com/graphql"
    response = requests.post(
        url, json={"query": query, "variables": variables}, headers=headers
    )

    discussions = []
    if response.status_code != 200:
        print(f"Error fetching discussions: {response.status_code}")
        return discussions

    result = response.json()
    if (
        "data" in result
        and result["data"] is not None
        and "repository" in result["data"]
        and result["data"]["repository"] is not None
        and "discussions" in result["data"]["repository"]
    ):
        for discussion in result["data"]["repository"]["discussions"]["nodes"]:
            # Check if discussion falls within our target week range
            if not is_in_week_range(discussion["updatedAt"], week_start, week_end):
                continue
            
            discussions.append(
                {
                    "id": discussion["number"],
                    "title": discussion["title"],
                    "url": discussion["url"],
                    "user": discussion["author"]["login"]
                    if discussion["author"]
                    else "Anonymous",
                    "updated_at": discussion["updatedAt"],
                    "body": discussion.get("bodyText", "") or "",
                    "category": discussion.get("category", {}).get(
                        "name", "General"
                    ),
                    "comments": discussion.get("comments", {}).get("totalCount", 0),
                    "answered": discussion.get("answerChosenAt") is not None,
                }
            )

    # Update the cache with discussions data
    if cached_data:
        cached_data['discussions'] = discussions
        save_week_cache(repo, year, week, cached_data)
    else:
        # Create new cache entry with just discussions
        data_to_cache = {
            'issues': [],
            'prs': [],
            'good_first_issues': [],
            'discussions': discussions
        }
        save_week_cache(repo, year, week, data_to_cache)

    return discussions


def cache_repository_data(repo, year, week, token, force=False):
    """Cache repository data without generating summaries."""
    week_start, week_end = get_week_date_range(year, week)
    
    # Check if we already have cached data
    if not force:
        cached_data = load_week_cache(repo, year, week, max_age_hours=24)
        if cached_data:
            issues_count = len(cached_data.get('issues', []))
            prs_count = len(cached_data.get('prs', []))
            discussions_count = len(cached_data.get('discussions', []))
            gfi_count = len(cached_data.get('good_first_issues', []))
            print(f"✓ Already cached: {issues_count} issues, {prs_count} PRs, {discussions_count} discussions, {gfi_count} good first issues")
            return issues_count + prs_count + discussions_count
    
    print(f"Fetching data for {repo} week {week} of {year} ({week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')})...")
    
    # Fetch data from GitHub API (this will cache it)
    issues, prs, recent_good_first_issues = fetch_issues(repo, token, week_start, week_end)
    discussions = fetch_discussions(repo, token, week_start, week_end)
    
    print(f"✓ Fetched and cached {len(issues)} issues, {len(prs)} PRs, {len(discussions)} discussions, {len(recent_good_first_issues)} good first issues for {repo}")
    
    return len(issues) + len(prs) + len(discussions)


def parse_repo_list(repo_args):
    """Parse repository arguments which can be individual repos or files containing repo lists."""
    repos = []
    
    for arg in repo_args:
        if os.path.exists(arg) and os.path.isfile(arg):
            # It's a file, read repos from it
            try:
                with open(arg, 'r', encoding='utf-8') as f:
                    file_repos = []
                    for line in f:
                        line = line.strip()
                        # Skip empty lines and comments
                        if line and not line.startswith('#'):
                            # Handle various formats: owner/repo, https://github.com/owner/repo, etc.
                            if line.startswith('https://github.com/'):
                                line = line.replace('https://github.com/', '')
                            if line.endswith('.git'):
                                line = line[:-4]
                            if '/' in line:
                                file_repos.append(line)
                    repos.extend(file_repos)
                    print(f"✓ Loaded {len(file_repos)} repositories from {arg}")
            except Exception as e:
                print(f"Warning: Error reading repository list from {arg}: {e}")
        else:
            # It's a direct repo specification
            repos.append(arg)
    
    return repos


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and cache GitHub repository activity data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single repository for current week
  python gh-fetch.py owner/repo
  
  # Multiple repositories
  python gh-fetch.py owner/repo1 owner/repo2 owner/repo3
  
  # From file containing repository list
  python gh-fetch.py repos.txt
  
  # Multiple weeks
  python gh-fetch.py owner/repo --weeks 4
  
  # Specific week
  python gh-fetch.py owner/repo --year 2025 --week 30
  
  # Force refresh cache
  python gh-fetch.py owner/repo --force
  
Repository list file format (one per line):
  owner/repo1
  owner/repo2
  https://github.com/owner/repo3
  # Comments are ignored
        """
    )
    parser.add_argument(
        "repos", 
        nargs='+', 
        help="GitHub repositories in format owner/repo, or files containing repository lists"
    )
    
    # Week-based arguments
    parser.add_argument(
        "--year", type=int, help="Year for the week (defaults to current year for last complete week)"
    )
    parser.add_argument(
        "--week", type=int, help="Week number (1-53, defaults to last complete week)"
    )
    parser.add_argument(
        "--weeks", type=int, help="Fetch data for the last X weeks. Creates cache for each week."
    )
    
    # Cache options
    parser.add_argument(
        "--force", action="store_true", 
        help="Force refresh cache even if fresh data exists"
    )
    parser.add_argument(
        "--max-age", type=int, default=24,
        help="Maximum cache age in hours before refetching (default: 24)"
    )

    args = parser.parse_args()

    # Parse repository list
    repos = parse_repo_list(args.repos)
    if not repos:
        parser.error("No valid repositories found")
    
    print(f"Processing {len(repos)} repositories: {', '.join(repos)}")
    
    # Load persistent cache
    persistent_cache = load_cache()
    
    token = get_github_api_token()

    # Determine time range
    if args.year and args.week:
        year, week = args.year, args.week
    else:
        # Use last complete week as default
        year, week = get_last_complete_week()

    if args.weeks:
        # Cache multiple weeks for all repositories
        week_list = get_week_list(args.weeks, year, week)
        total_items = 0
        
        for repo in repos:
            print(f"\n=== Processing repository: {repo} ===")
            for w_year, w_week in week_list:
                items_cached = cache_repository_data(repo, w_year, w_week, token, args.force)
                total_items += items_cached
        
        print(f"\n✓ Cached data for {len(repos)} repositories across {len(week_list)} weeks ({total_items} total items)")
    else:
        # Cache single week for all repositories
        total_items = 0
        for repo in repos:
            print(f"\n=== Processing repository: {repo} ===")
            items_cached = cache_repository_data(repo, year, week, token, args.force)
            total_items += items_cached
        
        print(f"\n✓ Cached data for {len(repos)} repositories for week {week} of {year} ({total_items} total items)")
    
    # Save persistent cache
    save_cache(persistent_cache)


if __name__ == "__main__":
    main()