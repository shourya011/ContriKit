"""GitHub REST API client used for issue synchronization and AI tools.

Authentication comes from ``GITHUB_TOKEN`` (an environment variable read by
Django settings). The token is applied server-side only and is never included
in return values, logs, or error messages.

The client deliberately uses module-level ``requests.get`` so tests can patch
``issues.github_api.requests.get`` with a single seam.
"""

import logging
import time
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

# Labels that mark a GitHub issue as suitable for this board. An issue only
# needs at least one of them (GitHub label matching is case-insensitive).
TRACKED_LABELS = (
    "good first issue",
    "good-first-issue",
    "beginner",
    "easy",
    "starter",
    "documentation",
    "docs",
    "help wanted",
    "first-timers-only",
)
TRACKED_LABELS_LOWER = frozenset(label.lower() for label in TRACKED_LABELS)

# Backwards-compatible name used by the AI helper.
BEGINNER_LABELS = list(TRACKED_LABELS)

GITHUB_API_ROOT = "https://api.github.com"
DEFAULT_TIMEOUT = 10
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF = 1.0
MAX_RATE_LIMIT_WAIT = 60
PER_PAGE = 100


class GitHubError(Exception):
    """Base class for controlled GitHub failures."""

    def __init__(self, message, *, status_code=None, kind="error", rate_limited=False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.kind = kind
        self.rate_limited = rate_limited

    def __str__(self):
        return self.message


class GitHubAuthError(GitHubError):
    def __init__(self, message="GitHub rejected the access token."):
        super().__init__(message, status_code=401, kind="auth")


class GitHubNotFoundError(GitHubError):
    def __init__(self, message="The GitHub repository could not be found."):
        super().__init__(message, status_code=404, kind="not_found")


class GitHubRateLimitError(GitHubError):
    def __init__(self, message="GitHub rate limit reached; retry later.", status_code=403):
        super().__init__(message, status_code=status_code, kind="rate_limit", rate_limited=True)


class GitHubServerError(GitHubError):
    def __init__(self, message="GitHub returned a server error.", status_code=500):
        super().__init__(message, status_code=status_code, kind="server")


class GitHubNetworkError(GitHubError):
    def __init__(self, message="Could not reach the GitHub API."):
        super().__init__(message, status_code=None, kind="network")


class GitHubMalformedResponse(GitHubError):
    def __init__(self, message="GitHub returned an unexpected response."):
        super().__init__(message, status_code=None, kind="malformed")


def parse_github_url(url):
    """Extract ``(owner, repo_name)`` from a GitHub repository URL."""
    parsed = urlparse(url or "")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def github_token():
    """Return the configured token without ever logging it."""
    token = getattr(settings, "GITHUB_TOKEN", "") or ""
    return token.strip()


def _headers(token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = github_token() if token is None else token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _header(response, name, default=""):
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get(name, default)
    except AttributeError:
        return default
    if value is None or not isinstance(value, (str, int, float)):
        return default
    return str(value)


def _response_text(response):
    text = getattr(response, "text", "")
    return text if isinstance(text, str) else ""


def _retry_after_seconds(response):
    value = _header(response, "Retry-After")
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        pass
    reset = _header(response, "X-RateLimit-Reset")
    try:
        return max(0, int(float(reset)) - int(time.time()))
    except (TypeError, ValueError):
        return None


def _is_rate_limited(response):
    if getattr(response, "status_code", None) == 429:
        return True
    if getattr(response, "status_code", None) != 403:
        return False
    if _header(response, "X-RateLimit-Remaining") == "0":
        return True
    text = _response_text(response).lower()
    return "rate limit" in text or "secondary rate" in text


def parse_link_header(value):
    """Return the ``rel="next"`` URL from a GitHub ``Link`` header, if any."""
    if not value or not isinstance(value, str):
        return None
    for part in value.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip()
        if not (url.startswith("<") and url.endswith(">")):
            continue
        for attr in segments[1:]:
            attr = attr.strip()
            if attr in ('rel="next"', "rel=next"):
                return url[1:-1]
    return None


def _safe_next_url(url):
    """Only follow pagination URLs that point at the GitHub API."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise GitHubMalformedResponse("GitHub returned an unsafe pagination URL.")
    return url


def _iso_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime(str(value))
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def parse_github_datetime(value):
    if value is None:
        return None
    dt = parse_datetime(str(value))
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


class GitHubClient:
    """Small GitHub REST client with timeout, retry, and rate-limit handling."""

    def __init__(self, token=None, timeout=None, max_retries=None, backoff=None, sleep=None):
        self.token = github_token() if token is None else token
        self.timeout = timeout if timeout is not None else getattr(
            settings, "GITHUB_SYNC_TIMEOUT", DEFAULT_TIMEOUT
        )
        self.max_retries = max_retries if max_retries is not None else getattr(
            settings, "GITHUB_SYNC_MAX_RETRIES", DEFAULT_MAX_RETRIES
        )
        self.backoff = backoff if backoff is not None else getattr(
            settings, "GITHUB_SYNC_BACKOFF", DEFAULT_BACKOFF
        )
        self.sleep = sleep or time.sleep

    def _request(self, url, params=None):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=_headers(self.token),
                    timeout=self.timeout,
                )
            except requests.Timeout:
                last_error = GitHubNetworkError("GitHub request timed out.")
                if attempt < self.max_retries:
                    self.sleep(min(self.backoff * (2 ** attempt), 10))
                    continue
                raise last_error
            except requests.RequestException:
                last_error = GitHubNetworkError("Could not reach the GitHub API.")
                if attempt < self.max_retries:
                    self.sleep(min(self.backoff * (2 ** attempt), 10))
                    continue
                raise last_error

            status = getattr(response, "status_code", None)
            if status == 200:
                return response

            if _is_rate_limited(response):
                wait = _retry_after_seconds(response)
                if attempt < self.max_retries and wait is not None and wait <= MAX_RATE_LIMIT_WAIT:
                    self.sleep(max(wait, 1))
                    continue
                raise GitHubRateLimitError(
                    "GitHub rate limit reached"
                    + (f"; retry after {wait}s." if wait else "; retry later."),
                    status_code=status,
                )

            if status in (401, 403):
                raise GitHubAuthError(
                    "GitHub rejected the access token (401/403). Check GITHUB_TOKEN."
                )

            if status == 404:
                raise GitHubNotFoundError()

            if status is not None and status >= 500:
                last_error = GitHubServerError(f"GitHub returned HTTP {status}.", status_code=status)
                if attempt < self.max_retries:
                    self.sleep(min(self.backoff * (2 ** attempt), 10))
                    continue
                raise last_error

            raise GitHubError(f"GitHub API error (HTTP {status}).", status_code=status)

        raise last_error or GitHubError("GitHub request failed.")

    def get_repository(self, owner, repo_name):
        response = self._request(f"{GITHUB_API_ROOT}/repos/{owner}/{repo_name}")
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise GitHubMalformedResponse("GitHub returned invalid repository JSON.")
        if not isinstance(data, dict):
            raise GitHubMalformedResponse("GitHub returned an unexpected repository payload.")
        return data

    def list_issues_page(
        self,
        owner,
        repo_name,
        *,
        state="all",
        since=None,
        start_url=None,
        per_page=PER_PAGE,
        sort="updated",
        direction="asc",
    ):
        """Return ``(issues, next_url)`` for one page of a repository's issues."""
        if start_url:
            url = _safe_next_url(start_url)
            params = None
        else:
            url = f"{GITHUB_API_ROOT}/repos/{owner}/{repo_name}/issues"
            params = {
                "state": state,
                "per_page": max(1, min(int(per_page), 100)),
                "sort": sort,
                "direction": direction,
            }
            since_value = _iso_utc(since)
            if since_value:
                params["since"] = since_value

        response = self._request(url, params=params)
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise GitHubMalformedResponse("GitHub returned invalid issue JSON.")
        if not isinstance(data, list):
            raise GitHubMalformedResponse("GitHub returned an unexpected issue payload.")
        next_url = _safe_next_url(parse_link_header(_header(response, "Link")))
        return data, next_url


def get_repository(owner, repo_name, timeout=DEFAULT_TIMEOUT):
    """Fetch public repository metadata as a normalized result dict."""
    client = GitHubClient(timeout=timeout)
    try:
        data = client.get_repository(owner, repo_name)
    except GitHubError as exc:
        return {
            "ok": False,
            "status_code": exc.status_code,
            "data": None,
            "error": exc.message,
            "rate_limited": exc.rate_limited,
        }
    return {
        "ok": True,
        "status_code": 200,
        "data": data,
        "error": None,
        "rate_limited": False,
    }


def _issue_labels(issue):
    labels = issue.get("labels") if isinstance(issue, dict) else None
    names = []
    for label in labels or []:
        if isinstance(label, dict):
            name = label.get("name")
        else:
            name = label
        if name and isinstance(name, str):
            names.append(name)
    return names


def is_tracked_issue(issue):
    """True when an issue carries at least one configured label and is not a PR."""
    if not isinstance(issue, dict) or "pull_request" in issue:
        return False
    return any(label.lower() in TRACKED_LABELS_LOWER for label in _issue_labels(issue))


def fetch_github_issues_api(owner, repo, github_pat=None, timeout=DEFAULT_TIMEOUT):
    """Fetch open tracked issues for the AI helper (PRs excluded)."""
    client = GitHubClient(token=github_pat, timeout=timeout)
    results, seen = [], set()
    start_url = None
    try:
        for _ in range(5):
            page, start_url = client.list_issues_page(
                owner, repo, state="open", start_url=start_url, per_page=30
            )
            for issue in page:
                if not is_tracked_issue(issue):
                    continue
                github_id = issue.get("id")
                if github_id in seen:
                    continue
                seen.add(github_id)
                results.append(
                    {
                        "github_id": github_id,
                        "title": issue.get("title") or "",
                        "body": issue.get("body") or "",
                        "url": issue.get("html_url") or "",
                        "comments": issue.get("comments", 0),
                        "created_at": issue.get("created_at"),
                        "labels": _issue_labels(issue),
                    }
                )
            if not start_url:
                break
    except GitHubError:
        return []
    return results
