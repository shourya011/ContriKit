"""Reusable GitHub issue synchronization service.

Responsibilities
----------------
* Fetch tracked repositories' issues from the GitHub REST API.
* Keep only issues carrying one of the configured labels and never import
  pull requests.
* Create or update :class:`issues.models.Issue` rows keyed by ``github_id``.
* Track open/closed state, closing issues that no longer qualify and reopening
  issues that become open again.
* Persist a per-repository checkpoint/cursor so an interrupted run resumes
  where it stopped instead of starting over.
* Isolate failures per repository and return a structured summary.

The service is intentionally independent from views so it can be reused by the
management commands, tests, or a future admin action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from issues.github_api import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubMalformedResponse,
    TRACKED_LABELS_LOWER,
    _issue_labels,
    github_token,
    parse_github_url,
)
from issues.models import Issue, Repo, Tag

logger = logging.getLogger(__name__)

# A full reconciliation pass (state=all) still catches closures and issues
# whose labels changed. Incremental ``since`` passes run in between.
DEFAULT_FULL_SYNC_INTERVAL = 3600  # seconds
DEFAULT_PAGE_SIZE = 100
DEFAULT_HOURS = "2.0"
MAX_TITLE_LENGTH = 200


@dataclass
class SyncSummary:
    """Counts and failures collected during one synchronization run."""

    repositories: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    closed: int = 0
    reopened: int = 0
    errors: list = field(default_factory=list)
    per_repository: dict = field(default_factory=dict)
    aborted: bool = False

    def record_repo(self, repo_name, repo_summary):
        self.per_repository[repo_name] = repo_summary

    def as_dict(self):
        return {
            "repositories": self.repositories,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "closed": self.closed,
            "reopened": self.reopened,
            "errors": list(self.errors),
            "aborted": self.aborted,
        }

    def __str__(self):
        return (
            f"repositories={self.repositories} created={self.created} "
            f"updated={self.updated} skipped={self.skipped} failed={self.failed} "
            f"closed={self.closed} reopened={self.reopened}"
        )


class RepositorySyncResult:
    def __init__(self, repo):
        self.repo = repo
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0
        self.closed = 0
        self.reopened = 0
        self.error = None

    def add_to(self, summary):
        summary.repositories += 1
        summary.created += self.created
        summary.updated += self.updated
        summary.skipped += self.skipped
        summary.failed += self.failed
        summary.closed += self.closed
        summary.reopened += self.reopened
        if self.error:
            summary.errors.append(self.error)


def _normalize_label_slug(label):
    return "-".join(str(label).strip().lower().replace("_", " ").split())


def _tag_map():
    """Existing tags keyed by normalized label slug (never auto-created)."""
    return {tag.slug: tag for tag in Tag.objects.all()}


def _tags_for_labels(labels, tag_map):
    tags = []
    for label in labels:
        tag = tag_map.get(_normalize_label_slug(label))
        if tag is not None:
            tags.append(tag)
    return tags


def _clean_title(value):
    title = (value or "").strip() or "Untitled GitHub issue"
    return title[:MAX_TITLE_LENGTH]


def _clean_body(value):
    if isinstance(value, str):
        return value
    return ""


def _valid_issue_url(value):
    if not isinstance(value, str) or not value.startswith("http"):
        return None
    return value


def _is_open(issue_payload):
    return (issue_payload.get("state") or "").lower() == "open"


class GitHubSyncService:
    """Synchronize tracked GitHub repositories into the issue board."""

    def __init__(self, client=None, *, token=None, now=None, full_interval=None, page_size=None):
        self.client = client or GitHubClient(token=token)
        self.token = token if token is not None else github_token()
        self.now = now or timezone.now
        self.full_interval = (
            full_interval
            if full_interval is not None
            else getattr(settings, "GITHUB_SYNC_FULL_INTERVAL", DEFAULT_FULL_SYNC_INTERVAL)
        )
        self.page_size = page_size or getattr(settings, "GITHUB_SYNC_PAGE_SIZE", DEFAULT_PAGE_SIZE)

    # ── Public API ─────────────────────────────────────────────────────
    def sync_all(self, repos=None, *, force_full=False, require_token=True):
        summary = SyncSummary()

        if require_token and not self.token:
            message = "GITHUB_TOKEN is not configured; GitHub synchronization was skipped."
            summary.aborted = True
            summary.errors.append(message)
            logger.error(message)
            return summary

        if repos is None:
            repos = Repo.objects.filter(is_active=True).order_by("name")

        for repo in repos:
            result = self.sync_repository(repo, force_full=force_full)
            result.add_to(summary)
            summary.record_repo(repo.name or str(repo.pk), result)

        logger.info("GitHub sync finished: %s", summary)
        return summary

    def sync_repository(self, repo, *, force_full=False):
        result = RepositorySyncResult(repo)
        owner, repo_name = self._owner_and_name(repo)
        if not owner or not repo_name:
            result.error = f"{repo}: could not determine owner/repository name."
            logger.error(result.error)
            self._store_error(repo, result.error)
            return result

        started_at = self.now()
        resuming = bool(repo.sync_cursor)
        if force_full:
            full_sync = True
        elif resuming:
            full_sync = repo.sync_mode == "full"
        else:
            full_sync = self._needs_full_sync(repo)
        mode = "full" if full_sync else "incremental"

        # Persist the pass identity before the first request so an interrupted
        # run can be resumed from the stored next-page cursor.
        if not resuming:
            repo.sync_cursor = ""
            repo.sync_mode = mode
            repo.sync_started_at = started_at
            repo.save(update_fields=["sync_cursor", "sync_mode", "sync_started_at"])
        else:
            started_at = repo.sync_started_at or started_at
            mode = repo.sync_mode or mode
            full_sync = mode == "full"

        since = None if full_sync else repo.sync_checkpoint
        next_url = repo.sync_cursor or None
        seen_ids = set()

        logger.info(
            "Syncing %s (%s mode%s)",
            repo.name,
            mode,
            f", since={since.isoformat()}" if since else "",
        )

        tag_map = _tag_map()
        pages = 0
        try:
            while True:
                payload, next_url = self.client.list_issues_page(
                    owner,
                    repo_name,
                    state="all",
                    since=since,
                    start_url=next_url,
                    per_page=self.page_size,
                )
                if not isinstance(payload, list):
                    raise GitHubMalformedResponse("GitHub returned a malformed issue page.")
                pages += 1
                failed_before = result.failed
                for raw_issue in payload:
                    self._process_issue(repo, raw_issue, result, tag_map, seen_ids, full_sync)

                if result.failed > failed_before:
                    # Do not advance the checkpoint past a page that was not
                    # processed completely; the next run retries this page.
                    raise GitHubError(
                        f"{result.failed - failed_before} issue(s) failed on page {pages}."
                    )

                # Persist progress only after the page is fully processed.
                repo.sync_cursor = next_url or ""
                repo.save(update_fields=["sync_cursor"])

                if not next_url:
                    break
                if pages >= getattr(settings, "GITHUB_SYNC_MAX_PAGES", 100):
                    raise GitHubMalformedResponse(
                        "Pagination exceeded the configured safety limit."
                    )

            if full_sync and not resuming:
                # Closure detection needs the complete set of ids for the
                # pass. A resumed pass only saw the remaining pages, so skip
                # closure and leave ``last_full_sync_at`` unchanged; the next
                # uninterrupted pass reconciles it.
                self._close_missing(repo, seen_ids, started_at, result)
                repo.last_full_sync_at = started_at

            repo.sync_cursor = ""
            repo.sync_mode = ""
            repo.sync_started_at = None
            repo.sync_checkpoint = self._checkpoint_value(started_at)
            repo.last_synced_at = self.now()
            repo.last_sync_error = ""
            repo.save(
                update_fields=[
                    "sync_cursor",
                    "sync_mode",
                    "sync_started_at",
                    "sync_checkpoint",
                    "last_synced_at",
                    "last_sync_error",
                    "last_full_sync_at",
                ]
            )
        except GitHubAuthError as exc:
            self._handle_failure(repo, result, exc, "authentication failed")
        except GitHubError as exc:
            self._handle_failure(repo, result, exc, "API failure")
        except (ValueError, TypeError, KeyError) as exc:
            self._handle_failure(
                repo,
                result,
                GitHubMalformedResponse(f"Malformed GitHub payload: {type(exc).__name__}"),
                "malformed response",
            )
        except Exception as exc:  # pragma: no cover - defensive isolation
            self._handle_failure(
                repo,
                result,
                GitHubError(f"Unexpected synchronization error: {type(exc).__name__}"),
                "unexpected failure",
            )

        logger.info(
            "Repository %s sync result: created=%s updated=%s skipped=%s failed=%s closed=%s reopened=%s",
            repo.name,
            result.created,
            result.updated,
            result.skipped,
            result.failed,
            result.closed,
            result.reopened,
        )
        return result

    # ── Internals ──────────────────────────────────────────────────────
    def _checkpoint_value(self, started_at):
        """Watermark for ``since`` with a small overlap against clock skew."""
        overlap = getattr(settings, "GITHUB_SYNC_CHECKPOINT_OVERLAP", 60)
        try:
            return started_at - timedelta(seconds=max(0, int(overlap)))
        except (TypeError, ValueError, AttributeError):
            return started_at

    def _owner_and_name(self, repo):
        owner, name = parse_github_url(repo.github_url)
        if owner and name:
            return owner, name
        return repo.owner, repo.repo_name

    def _needs_full_sync(self, repo):
        if not repo.sync_checkpoint:
            return True
        if repo.last_full_sync_at is None:
            return True
        if not self.full_interval:
            return False
        return self.now() - repo.last_full_sync_at >= timedelta(seconds=self.full_interval)

    def _apply_fields(self, issue, fields):
        changed = False
        for name, value in fields.items():
            if name == "repo":
                if issue.repo_id != getattr(value, "pk", None):
                    issue.repo = value
                    changed = True
                continue
            if getattr(issue, name) != value:
                setattr(issue, name, value)
                changed = True
        return changed

    def _process_issue(self, repo, raw, result, tag_map, seen_ids, full_sync):
        if not isinstance(raw, dict):
            result.failed += 1
            logger.warning("Skipping malformed issue payload for %s", repo.name)
            return

        if "pull_request" in raw:
            result.skipped += 1
            return

        github_id = raw.get("id")
        if not isinstance(github_id, int):
            result.failed += 1
            logger.warning("Skipping issue without a numeric id for %s", repo.name)
            return

        labels = _issue_labels(raw)
        qualifies = any(label.lower() in TRACKED_LABELS_LOWER for label in labels)
        existing = Issue.objects.filter(github_id=github_id).first()

        if not qualifies:
            # A previously synchronized issue that lost every tracked label no
            # longer belongs on the open board. Keep the row (and its saved
            # bookmarks/history) but close it.
            if existing is not None and existing.status == "open":
                existing.status = "closed"
                existing.labels = labels
                existing.save(update_fields=["status", "labels", "updated_at"])
                result.updated += 1
                result.closed += 1
                logger.info("Closed issue %s: no tracked labels remain", github_id)
            else:
                result.skipped += 1
            return

        url = _valid_issue_url(raw.get("html_url"))
        if not url:
            result.failed += 1
            logger.warning("Skipping issue %s without a valid URL", github_id)
            return

        new_status = "open" if _is_open(raw) else "closed"
        fields = {
            "repo": repo,
            "title": _clean_title(raw.get("title")),
            "description": _clean_body(raw.get("body")),
            "github_issue_url": url,
            "labels": labels,
            "status": new_status,
        }

        try:
            if existing is None:
                # Legacy imported rows have no github_id; link the existing
                # record by its GitHub URL instead of creating a duplicate.
                issue = Issue.objects.filter(
                    github_issue_url=url, github_id__isnull=True
                ).first()
                created = issue is None
                if created:
                    issue = Issue(
                        github_id=github_id,
                        difficulty="beginner",
                        estimated_hours=DEFAULT_HOURS,
                    )
            else:
                issue = existing
                created = False

            previous_status = issue.status
            labels_changed = list(issue.labels or []) != labels
            changed = self._apply_fields(issue, fields)
            linked = issue.github_id != github_id
            issue.github_id = github_id

            if created:
                issue.save()
                issue.tags.set(_tags_for_labels(labels, tag_map))
                result.created += 1
                seen_ids.add(github_id)
                logger.info("Created issue %s (%s)", github_id, url)
                return

            if not changed and not linked and not labels_changed:
                result.skipped += 1
                seen_ids.add(github_id)
                return

            issue.save()
            if labels_changed:
                issue.tags.set(_tags_for_labels(labels, tag_map))
            result.updated += 1
            if new_status == "open" and previous_status == "closed":
                result.reopened += 1
                logger.info("Reopened issue %s", github_id)
            elif new_status == "closed" and previous_status == "open":
                result.closed += 1
                logger.info("Closed issue %s", github_id)
            seen_ids.add(github_id)
        except IntegrityError:
            result.failed += 1
            logger.exception("Duplicate github_id %s encountered for %s", github_id, repo.name)
        except Exception as exc:  # pragma: no cover - per-issue isolation
            result.failed += 1
            logger.exception("Failed to store issue %s for %s: %s", github_id, repo.name, exc)

    def _close_missing(self, repo, seen_ids, started_at, result):
        """Close open issues that a complete full pass did not return.

        ``state=all`` returns every issue (including closed ones), so an issue
        that is absent was deleted or made inaccessible. Missing detection only
        considers rows created before this pass started, which avoids touching
        issues from a later concurrent pass.
        """
        candidates = Issue.objects.filter(
            repo=repo,
            github_id__isnull=False,
            status="open",
            created_at__lte=started_at,
        ).exclude(github_id__in=seen_ids)
        closed = candidates.update(status="closed", updated_at=self.now())
        if closed:
            result.updated += closed
            result.closed += closed
            logger.info("Closed %s issue(s) no longer returned by %s", closed, repo.name)

    def _store_error(self, repo, message):
        repo.last_sync_error = message[:2000]
        repo.save(update_fields=["last_sync_error"])

    def _handle_failure(self, repo, result, exc, description):
        result.error = f"{repo.name}: {description}: {exc}"
        # Do not count a whole repository as failed issues; record the error.
        logger.error("GitHub sync failed for %s (%s): %s", repo.name, description, exc)
        self._store_error(repo, result.error)
        # Keep cursor and checkpoint so the next run can resume; never clear
        # them on failure.


def sync_repository(repo, **kwargs):
    return GitHubSyncService(**{k: v for k, v in kwargs.items() if k in ("client", "token")}).sync_repository(
        repo, force_full=kwargs.get("force_full", False)
    )


def sync_all_repositories(**kwargs):
    return GitHubSyncService(
        client=kwargs.get("client"), token=kwargs.get("token")
    ).sync_all(
        repos=kwargs.get("repos"),
        force_full=kwargs.get("force_full", False),
        require_token=kwargs.get("require_token", True),
    )
