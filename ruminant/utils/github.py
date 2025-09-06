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
        "updated_at": issue["updatedAt"],
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
    if response.status_code != 200:
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