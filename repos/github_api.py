"""Shared GitHub API client.

Centralizes the GitHub interaction logic that previously lived inside
``repos/views.py`` so both the repositories app and the AI tool layer use the
exact same integration. The optional ``GITHUB_PAT`` environment variable is
read from Django settings (server-side only) and raises GitHub's unauthenticated
rate limit from 60 to 5000 requests/hour.

Nothing in this module ever returns the token.
"""

from urllib.parse import urlparse

import requests
from django.conf import settings

# Labels GitHub stars contributors use for beginner-friendly issues.
BEGINNER_LABELS = ["good first issue", "good-first-issue", "beginner", "easy", "starter"]

DEFAULT_TIMEOUT = 10


def parse_github_url(url):
    """Extract (owner, repo_name) from a GitHub repository URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip('/').split('/') if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def _github_headers(pat=None):
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = pat or getattr(settings, "GITHUB_PAT", "") or None
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def get_repository(owner, repo_name, timeout=DEFAULT_TIMEOUT):
    """Fetch public repository metadata.

    Returns a normalized result dict:
        {"ok": True, "status_code": 200, "data": {...}, "error": None}
        {"ok": False, "status_code": <int|None>, "data": None, "error": str,
         "rate_limited": bool}
    """
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo_name}",
            headers=_github_headers(),
            timeout=timeout,
        )
    except requests.RequestException:
        return {
            "ok": False,
            "status_code": None,
            "data": None,
            "error": "Network timeout contacting GitHub API. Please try again.",
            "rate_limited": False,
        }

    if response.status_code == 200:
        return {
            "ok": True,
            "status_code": 200,
            "data": response.json(),
            "error": None,
            "rate_limited": False,
        }

    rate_limited = response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0"
    if rate_limited:
        error = "GitHub rate limit reached, please try again in a few minutes."
    elif response.status_code == 404:
        error = "We couldn't find that repository — check the URL and try again."
    else:
        error = f"GitHub API error (Status {response.status_code})."
    return {
        "ok": False,
        "status_code": response.status_code,
        "data": None,
        "error": error,
        "rate_limited": rate_limited,
    }


def fetch_github_issues_api(owner, repo, github_pat=None, timeout=DEFAULT_TIMEOUT):
    """Fetch open candidate issues labeled for beginners (PRs are excluded).

    Returns a list of normalized issue dicts, or [] when nothing is found.
    """
    all_issues, seen_ids = [], set()
    for label in BEGINNER_LABELS:
        try:
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                params={"labels": label, "state": "open", "per_page": 30},
                headers=_github_headers(github_pat),
                timeout=timeout,
            )
            if response.status_code != 200:
                continue
            for issue in response.json():
                if "pull_request" in issue:
                    continue
                if issue["id"] not in seen_ids:
                    seen_ids.add(issue["id"])
                    all_issues.append({
                        "github_id": issue["id"],
                        "title": issue["title"],
                        "body": issue["body"] or "",
                        "url": issue["html_url"],
                        "comments": issue["comments"],
                        "created_at": issue["created_at"],
                        "labels": [label["name"] for label in issue["labels"]],
                    })
        except (requests.RequestException, ValueError):
            continue
    return all_issues
