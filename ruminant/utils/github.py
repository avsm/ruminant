"""GitHub API utilities adapted from the original gh-fetch.py."""

import time
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from .dates import is_in_week_range
from .logging import error, warning, info


def fetch_graphql_data(query: str, variables: Dict[str, Any], headers: Dict[str, str]) -> Optional[Dict]:
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
                    for graphql_error in result["errors"]:
                        error_type = graphql_error.get("type", "UNKNOWN")
                        message = graphql_error.get("message", "Unknown error")
                        error(f"GraphQL Error ({error_type}): {message}")
                        
                        # Handle specific error types
                        if error_type == "FORBIDDEN":
                            error("This is likely due to token permissions or repository access restrictions.")
                            if "fine-grained personal access tokens" in message:
                                error("Try using a classic personal access token or adjust your token's lifetime.")
                            return None
                        elif error_type in ["NOT_FOUND", "UNAUTHORIZED"]:
                            error("Check that the repository exists and your token has access to it.")
                            return None
                    
                    # If we have other errors but data is still present, continue with warnings
                    if result.get("data") is None:
                        return None
                
                # Check if data is missing
                if "data" not in result or result["data"] is None:
                    error("No data returned from GraphQL API")
                    return None
                    
                return result
            elif response.status_code == 403:
                # Handle rate limiting and forbidden access
                error(f"HTTP 403 Forbidden: Access denied or rate limit exceeded")
                
                # Check for rate limit headers
                rate_limit_remaining = response.headers.get('X-RateLimit-Remaining')
                rate_limit_reset = response.headers.get('X-RateLimit-Reset')
                
                if rate_limit_remaining == '0':
                    reset_time = datetime.fromtimestamp(int(rate_limit_reset)) if rate_limit_reset else None
                    if reset_time:
                        wait_time = (reset_time - datetime.now()).total_seconds()
                        error(f"Rate limit exceeded. Resets at {reset_time} (in {wait_time:.0f} seconds)")
                    else:
                        error("Rate limit exceeded. Please wait before retrying.")
                else:
                    error("Access forbidden. Check your token permissions and repository access.")
                
                # Don't retry on 403 errors
                return None
            elif response.status_code in [502, 503, 504]:
                if attempt < max_retries - 1:
                    warning(f"GitHub API returned {response.status_code}, retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                    continue
            else:
                error(f"Error fetching data: {response.status_code}")
                return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                warning(f"Request failed: {e}, retrying in {2 ** attempt} seconds...")
                time.sleep(2 ** attempt)
                continue
            else:
                error(f"Failed to fetch data after {max_retries} attempts: {e}")
                return None
    
    return None


def has_activity_in_week(item: Dict[str, Any], week_start: datetime, week_end: datetime) -> bool:
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


def format_issue_entry(issue: Dict[str, Any]) -> Dict[str, Any]:
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
        "created_at": issue["createdAt"],
        "updated_at": issue["updatedAt"],
        "closed_at": issue.get("closedAt"),
        "body": issue.get("bodyText", "") or "",
        "labels": [label["name"] for label in issue.get("labels", {}).get("nodes", [])],
        "state": issue["state"].lower(),
        "comments": comments_list,
    }


def format_pr_entry(pr: Dict[str, Any]) -> Dict[str, Any]:
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
        "created_at": pr["createdAt"],
        "updated_at": pr["updatedAt"],
        "closed_at": pr.get("closedAt"),
        "merged_at": pr.get("mergedAt"),
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


def is_good_first_issue(item: Dict[str, Any]) -> bool:
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


def fetch_issues(repo: str, token: Optional[str], week_start: datetime, week_end: datetime) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Fetch issues and PRs from a repository for a specific week using GraphQL."""
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
                    closedAt
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
                    closedAt
                    mergedAt
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
        info(f"Fetching page {page_count} from GitHub GraphQL API...")
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
            info(f"Finished pagination after {page_count} pages")
            break
        
        if issues_has_next and new_issues_cursor == issues_after:
            info("Issues cursor unchanged, breaking pagination")
            break
        if prs_has_next and new_prs_cursor == prs_after:
            info("PRs cursor unchanged, breaking pagination")
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
        
        info(f"Page {page_count}: Found {found_issues_this_page} issues and {found_prs_this_page} PRs in target week")
        
        # Early termination if we're not finding relevant activity
        if page_count > 5 and found_issues_this_page == 0 and found_prs_this_page == 0:
            info(f"No activity found in recent pages, stopping at page {page_count}")
            break

    info(f"Total: {len(issues)} issues, {len(prs)} PRs, {len(good_first_issues)} good first issues found")
    
    return issues, prs, good_first_issues


def fetch_user_info(username: str, token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch detailed user information from GitHub API."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    
    url = f"https://api.github.com/users/{username}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 403:
            # Handle rate limiting
            rate_limit_remaining = response.headers.get('X-RateLimit-Remaining')
            if rate_limit_remaining == '0':
                error(f"Rate limit exceeded when fetching user {username}")
            else:
                error(f"HTTP 403: Access forbidden for user {username}. Check token permissions.")
            return None
        elif response.status_code == 404:
            warning(f"User {username} not found")
            return None
        else:
            error(f"Error fetching user {username}: {response.status_code}")
            return None
    except requests.RequestException as e:
        error(f"Failed to fetch user {username}: {e}")
        return None


def fetch_releases(repo_name: str, token: Optional[str], week_start: datetime, week_end: datetime) -> List[Dict[str, Any]]:
    """Fetch releases from a GitHub repository for a specific week."""
    owner, name = repo_name.split("/")
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    
    releases = []
    page = 1
    per_page = 100
    
    while page <= 10:  # Safety limit
        url = f"https://api.github.com/repos/{owner}/{name}/releases"
        params = {
            "per_page": per_page,
            "page": page
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                page_releases = response.json()
                
                if not page_releases:
                    break
                
                # Filter releases by date
                for release in page_releases:
                    published_at = release.get("published_at")
                    if published_at and is_in_week_range(published_at, week_start, week_end):
                        # Format release data
                        formatted_release = {
                            "tag_name": release.get("tag_name"),
                            "name": release.get("name"),
                            "published_at": published_at,
                            "author": release.get("author", {}).get("login") if release.get("author") else None,
                            "html_url": release.get("html_url"),
                            "body": release.get("body", ""),
                            "prerelease": release.get("prerelease", False),
                            "draft": release.get("draft", False),
                            "assets": [
                                {
                                    "name": asset.get("name"),
                                    "download_count": asset.get("download_count", 0),
                                    "size": asset.get("size", 0)
                                }
                                for asset in release.get("assets", [])
                            ]
                        }
                        releases.append(formatted_release)
                
                # Check if we've gone past our date range
                if page_releases:
                    last_release_date = page_releases[-1].get("published_at")
                    if last_release_date:
                        last_date = datetime.fromisoformat(last_release_date.replace("Z", "+00:00"))
                        if last_date < week_start:
                            break
                
                page += 1
            elif response.status_code == 403:
                # Handle rate limiting
                rate_limit_remaining = response.headers.get('X-RateLimit-Remaining')
                if rate_limit_remaining == '0':
                    error(f"Rate limit exceeded when fetching releases for {repo_name}")
                else:
                    error(f"HTTP 403: Access forbidden for {repo_name}. Check token permissions.")
                break
            else:
                warning(f"Failed to fetch releases for {repo_name}: {response.status_code}")
                break
                
        except requests.RequestException as e:
            error(f"Error fetching releases for {repo_name}: {e}")
            break
    
    info(f"Found {len(releases)} releases for {repo_name} in week")
    return releases


def extract_users_from_data(issues: List[Dict], prs: List[Dict], discussions: List[Dict]) -> set:
    """Extract unique usernames from issues, PRs, discussions, and all @mentions in comments."""
    import re
    users = set()
    
    # Pattern to match @mentions - must start with a letter and can contain letters, numbers, and hyphens
    # This avoids matching things like @15 or @21 which are likely line numbers
    mention_pattern = re.compile(r'@([a-zA-Z][a-zA-Z0-9-]{0,38})')
    
    # Extract from issues
    for issue in issues:
        if issue.get("user"):
            users.add(issue["user"])
        
        # Extract from issue body
        if issue.get("body"):
            mentions = mention_pattern.findall(issue["body"])
            users.update(mentions)
        
        # Extract from comments
        for comment in issue.get("comments", []):
            # Extract comment author (format: "@author: text")
            if comment.startswith("@"):
                parts = comment.split(":", 1)
                if len(parts) >= 1:
                    username = parts[0][1:].strip()  # Remove @ and get username before colon
                    # Validate it's a proper username (starts with letter)
                    if username and username[0].isalpha():
                        users.add(username)
            
            # Extract all @mentions within the comment text
            mentions = mention_pattern.findall(comment)
            users.update(mentions)
    
    # Extract from PRs
    for pr in prs:
        if pr.get("user"):
            users.add(pr["user"])
        
        # Extract from PR body
        if pr.get("body"):
            mentions = mention_pattern.findall(pr["body"])
            users.update(mentions)
        
        # Extract from comments
        for comment in pr.get("comments", []):
            # Extract comment author (format: "@author: text")
            if comment.startswith("@"):
                parts = comment.split(":", 1)
                if len(parts) >= 1:
                    username = parts[0][1:].strip()  # Remove @ and get username before colon
                    # Validate it's a proper username (starts with letter)
                    if username and username[0].isalpha():
                        users.add(username)
            
            # Extract all @mentions within the comment text
            mentions = mention_pattern.findall(comment)
            users.update(mentions)
    
    # Extract from discussions
    for discussion in discussions:
        if discussion.get("user"):
            users.add(discussion["user"])
        
        # Extract from discussion body
        if discussion.get("body"):
            mentions = mention_pattern.findall(discussion["body"])
            users.update(mentions)
    
    # Common words that appear after @ but aren't usernames
    common_words = {
        "ghost", "Anonymous", "github-actions", "github",
        "test", "check", "lint", "doc", "all", "empty", "echo",
        "author", "users", "default", "deprecated", "disable",
        "builtin", "invalid", "immediate", "master", "main",
        "raise", "return", "import", "export", "static", "dynamic",
        "inline", "implicit", "explicit", "param", "params",
        "option", "options", "support", "install", "uninstall",
        "build", "compile", "run", "exec", "execute", "start", "stop",
        "enable", "disable", "true", "false", "yes", "no",
        "foo", "bar", "baz", "example", "sample", "demo",
        "todo", "fixme", "note", "warning", "error", "info",
        "debug", "release", "production", "development", "staging",
        "local", "remote", "origin", "upstream", "downstream",
        "entry", "exit", "init", "cleanup", "setup", "teardown",
        "begin", "end", "open", "close", "read", "write",
        "get", "set", "add", "remove", "delete", "update",
        "list", "lists", "array", "arrays", "map", "maps",
        "string", "strings", "number", "numbers", "bool", "boolean",
        "int", "integer", "float", "double", "char", "character",
        "byte", "bytes", "bit", "bits", "size", "length",
        "count", "total", "sum", "average", "min", "max",
        "first", "last", "next", "prev", "previous", "current",
        "new", "old", "temp", "tmp", "cache", "buffer",
        "input", "output", "result", "results", "value", "values",
        "key", "keys", "item", "items", "element", "elements",
        "node", "nodes", "edge", "edges", "graph", "tree",
        "root", "leaf", "parent", "child", "children", "sibling",
        "copy", "move", "rename", "replace", "swap", "merge",
        "split", "join", "concat", "append", "prepend", "insert",
        "push", "pop", "shift", "unshift", "slice", "splice",
        "filter", "map", "reduce", "fold", "scan", "zip",
        "sort", "reverse", "shuffle", "unique", "distinct", "group",
        "match", "search", "find", "replace", "regex", "pattern",
        "format", "parse", "encode", "decode", "encrypt", "decrypt",
        "hash", "sign", "verify", "validate", "sanitize", "escape",
        "serialize", "deserialize", "marshal", "unmarshal", "pack", "unpack",
        "compress", "decompress", "zip", "unzip", "tar", "untar",
        "upload", "download", "fetch", "pull", "push", "sync",
        "send", "receive", "request", "response", "reply", "forward",
        "connect", "disconnect", "bind", "unbind", "listen", "accept",
        "open", "close", "read", "write", "seek", "tell",
        "lock", "unlock", "acquire", "release", "wait", "notify",
        "start", "stop", "pause", "resume", "cancel", "abort",
        "create", "destroy", "alloc", "free", "malloc", "calloc",
        "realloc", "dealloc", "new", "delete", "construct", "destruct",
        "initialize", "finalize", "register", "unregister", "subscribe", "unsubscribe",
        "attach", "detach", "mount", "unmount", "load", "unload",
        "include", "exclude", "require", "import", "export", "module",
        "package", "library", "framework", "plugin", "extension", "addon",
        "config", "configure", "settings", "preferences", "options", "flags",
        "version", "release", "patch", "major", "minor", "micro",
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta",
        "public", "private", "protected", "internal", "external", "global",
        "static", "const", "final", "abstract", "virtual", "override",
        "interface", "class", "struct", "enum", "union", "typedef",
        "namespace", "using", "alias", "template", "generic", "trait",
        "function", "method", "procedure", "routine", "callback", "handler",
        "event", "signal", "slot", "delegate", "lambda", "closure",
        "async", "await", "promise", "future", "task", "thread",
        "process", "job", "worker", "pool", "queue", "stack",
        "heap", "buffer", "cache", "store", "storage", "memory",
        "disk", "file", "folder", "directory", "path", "url",
        "uri", "urn", "uuid", "guid", "id", "uid",
        "name", "label", "title", "description", "summary", "details",
        "content", "body", "header", "footer", "sidebar", "nav",
        "menu", "toolbar", "statusbar", "panel", "dialog", "modal",
        "button", "link", "input", "output", "form", "field",
        "table", "row", "column", "cell", "grid", "layout",
        "view", "model", "controller", "component", "widget", "element",
        "page", "screen", "window", "frame", "layer", "canvas",
        "image", "icon", "sprite", "texture", "shader", "mesh",
        "sound", "audio", "video", "media", "stream", "player",
        "server", "client", "host", "guest", "peer", "node",
        "network", "socket", "port", "protocol", "packet", "message",
        "request", "response", "query", "command", "action", "operation",
        "transaction", "session", "context", "scope", "environment", "state",
        "data", "metadata", "schema", "table", "index", "key",
        "record", "field", "column", "row", "tuple", "relation",
        "database", "collection", "document", "object", "entity", "model",
        "repository", "service", "provider", "factory", "builder", "manager",
        "helper", "utility", "tool", "lib", "core", "base",
        "common", "shared", "global", "system", "platform", "framework",
        "application", "app", "program", "software", "package", "module",
        "component", "plugin", "extension", "addon", "patch", "update",
        "fix", "hotfix", "bugfix", "feature", "enhancement", "improvement",
        "refactor", "optimize", "performance", "security", "stability", "reliability",
        "compatibility", "portability", "scalability", "flexibility", "extensibility", "maintainability",
        "usability", "accessibility", "internationalization", "localization", "translation", "documentation",
        "comment", "note", "todo", "fixme", "hack", "workaround",
        "deprecated", "obsolete", "legacy", "experimental", "unstable", "beta",
        "release", "version", "tag", "branch", "commit", "merge",
        "rebase", "cherry-pick", "revert", "reset", "stash", "apply",
        "diff", "patch", "blame", "log", "status", "config",
        "clone", "fork", "pull", "push", "fetch", "remote",
        "upstream", "downstream", "origin", "master", "main", "develop",
        "feature", "bugfix", "hotfix", "release", "tag", "branch",
        # OCaml-specific common words
        "type", "module", "sig", "struct", "functor", "val",
        "let", "in", "rec", "and", "or", "not",
        "if", "then", "else", "match", "with", "when",
        "fun", "function", "try", "with", "exception", "raise",
        "begin", "end", "do", "done", "for", "while",
        "to", "downto", "of", "as", "ref", "mutable",
        "open", "include", "module", "type", "class", "object",
        "method", "inherit", "initializer", "constraint", "virtual", "private",
        "lazy", "assert", "external", "rec", "nonrec", "and",
        # Common version-like strings
        "v1", "v2", "v3", "v4", "v5", "v30", "v31",
        # Build/test related
        "runtest", "runtest-js", "runtest-a", "runtest-name",
        "build", "make", "cmake", "configure", "install",
        # Package managers
        "npm", "pip", "gem", "cargo", "opam", "dune",
        # OS/platforms
        "linux", "windows", "macos", "unix", "posix", "win32",
        "ubuntu", "debian", "fedora", "centos", "rhel", "arch",
        # Common tools
        "git", "svn", "hg", "cvs", "bzr", "perforce",
        "gcc", "clang", "msvc", "icc", "llvm", "mingw",
        "make", "cmake", "autoconf", "automake", "libtool", "pkg-config",
        # Email providers (sometimes appear in broken mentions)
        "gmail", "outlook", "yahoo", "hotmail", "protonmail", "icloud",
        # Common test/example names
        "foo", "bar", "baz", "qux", "quux", "corge",
        "alice", "bob", "charlie", "dave", "eve", "frank",
        # Database-related
        "mysql", "postgresql", "sqlite", "mongodb", "redis", "cassandra",
        # Other common technical terms
        "api", "sdk", "cli", "gui", "ui", "ux",
        "http", "https", "ftp", "ssh", "ssl", "tls",
        "json", "xml", "yaml", "toml", "ini", "csv",
        "utf8", "utf16", "ascii", "unicode", "base64", "hex",
        "md5", "sha1", "sha256", "sha512", "crc32", "xxhash",
        # Short common words
        "a", "an", "the", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "should",
        "could", "may", "might", "must", "can", "cannot",
        "it", "its", "this", "that", "these", "those",
        "my", "your", "his", "her", "our", "their",
        "i", "you", "he", "she", "we", "they",
        "me", "him", "her", "us", "them", "myself",
        "at", "by", "for", "from", "in", "of",
        "on", "to", "with", "about", "after", "before",
        "up", "down", "out", "off", "over", "under",
        # OCaml-specific modules/libraries  
        "fmt", "lwt", "async", "core", "base", "stdio",
        "list", "array", "string", "bytes", "buffer", "queue",
        "stack", "heap", "set", "map", "hashtbl", "weak",
        "gc", "sys", "unix", "thread", "mutex", "condition",
        "event", "random", "complex", "bigarray", "dynlink", "str",
        "graphics", "dbm", "labltk", "camlp4", "camlp5", "ppx",
        # Common patterns that look like usernames but aren't
        "regalloc", "docalias", "pkg-lock", "pkg-install", 
        "ocaml-index", "untaged", "untagged", "tangled",
        "cold", "hot", "warm", "cool", "recoil", "specialise",
        "hilbert", "thor", "jane", "alice", "bob",
        "sita", "fedora", "pop-os", "ubuntu", "debian",
        # Specific non-usernames seen in the data
        "anthropic", "janestreet", "ocamlpro", "ocaml",
        "XYZ", "ABC", "TODO", "FIXME", "XXX", "HACK",
        "GLIBC", "POSIX", "ISO", "ANSI", "IEEE",
        # Common prefixes/suffixes that might appear
        "latest", "current", "previous", "next", "first", "last"
    }
    
    # Remove invalid usernames
    users = users - common_words
    users.discard("")  # Remove empty strings
    
    # Additional validation: remove usernames that don't start with a letter
    # and remove hex-like strings (e.g., "d87a1eb", "fe8872fd7ead")
    import re
    hex_pattern = re.compile(r'^[a-f0-9]+$')
    
    valid_users = set()
    for u in users:
        if u and u[0].isalpha():
            # Skip if it looks like a hex string (commit SHA fragment)
            if not hex_pattern.match(u.lower()):
                # Skip if it's too short (likely not a real username)
                if len(u) >= 2:
                    valid_users.add(u)
    
    return valid_users


def fetch_discussions(repo: str, token: Optional[str], week_start: datetime, week_end: datetime) -> List[Dict]:
    """Fetch discussions from a repository for a specific week."""
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
    if response.status_code == 403:
        # Handle rate limiting
        rate_limit_remaining = response.headers.get('X-RateLimit-Remaining')
        if rate_limit_remaining == '0':
            error(f"Rate limit exceeded when fetching discussions for {repo}")
        else:
            error(f"HTTP 403: Access forbidden for {repo} discussions. Check token permissions.")
        return discussions
    elif response.status_code != 200:
        error(f"Error fetching discussions: {response.status_code}")
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

    return discussions