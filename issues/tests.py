"""Tests for the GitHub synchronization service and the editor removal.

GitHub HTTP is always mocked at ``issues.github_api.requests.get`` so no
network access is required.
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from issues.github_api import GitHubClient, parse_link_header
from issues.models import Issue, Repo, SavedIssue, Tag
from issues.services.github_sync import GitHubSyncService

User = get_user_model()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def issue_payload(github_id, *, title="Fix docs typo", state="open", labels=("good first issue",),
                  url=None, body="A beginner friendly issue.", pull_request=False):
    data = {
        "id": github_id,
        "number": github_id,
        "title": title,
        "body": body,
        "state": state,
        "html_url": url or f"https://github.com/acme/widgets/issues/{github_id}",
        "labels": [{"name": label} for label in labels],
        "updated_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
    }
    if pull_request:
        data["pull_request"] = {"url": "https://api.github.com/repos/acme/widgets/pulls/1"}
    return data


class RepoFactoryMixin:
    def make_repo(self, name="acme/widgets", **kwargs):
        defaults = {
            "github_url": f"https://github.com/{name}",
            "name": name,
            "language": "Python",
            "is_active": True,
        }
        defaults.update(kwargs)
        return Repo.objects.create(**defaults)


@override_settings(GITHUB_TOKEN="test-token", GITHUB_SYNC_MAX_RETRIES=0, GITHUB_SYNC_BACKOFF=0)
class GitHubSyncServiceTests(RepoFactoryMixin, TestCase):
    def setUp(self):
        self.repo = self.make_repo()
        self.service = GitHubSyncService(client=GitHubClient(token="test-token", max_retries=0, backoff=0))

    def run_sync(self, responses, **kwargs):
        with mock.patch("issues.github_api.requests.get", side_effect=responses) as mocked:
            summary = self.service.sync_all(repos=[self.repo], **kwargs)
        return summary, mocked

    # ── Creation, update, duplicates ──────────────────────────────────
    def test_creates_qualifying_issue(self):
        summary, _ = self.run_sync([FakeResponse(payload=[issue_payload(101)])])
        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.failed, 0)
        issue = Issue.objects.get(github_id=101)
        self.assertEqual(issue.repo, self.repo)
        self.assertEqual(issue.title, "Fix docs typo")
        self.assertEqual(issue.status, "open")
        self.assertEqual(issue.labels, ["good first issue"])
        self.assertEqual(issue.github_issue_url, "https://github.com/acme/widgets/issues/101")

    def test_updates_existing_issue_without_duplicating(self):
        self.run_sync([FakeResponse(payload=[issue_payload(102)])])
        self.repo.refresh_from_db()
        self.repo.sync_checkpoint = None
        self.repo.last_full_sync_at = None
        self.repo.save()

        summary, _ = self.run_sync(
            [FakeResponse(payload=[issue_payload(102, title="Updated title", body="New body")])]
        )
        self.assertEqual(summary.created, 0)
        self.assertEqual(summary.updated, 1)
        self.assertEqual(Issue.objects.filter(github_id=102).count(), 1)
        issue = Issue.objects.get(github_id=102)
        self.assertEqual(issue.title, "Updated title")
        self.assertEqual(issue.description, "New body")

    def test_links_legacy_issue_by_url_instead_of_duplicating(self):
        legacy = Issue.objects.create(
            repo=self.repo,
            title="Legacy import",
            description="old",
            github_issue_url="https://github.com/acme/widgets/issues/103",
            difficulty="beginner",
            estimated_hours="2.0",
        )
        summary, _ = self.run_sync([FakeResponse(payload=[issue_payload(103)])])
        self.assertEqual(summary.created, 0)
        legacy.refresh_from_db()
        self.assertEqual(legacy.github_id, 103)
        self.assertEqual(Issue.objects.count(), 1)

    def test_legacy_issue_keeps_null_github_id_when_unmatched(self):
        legacy = Issue.objects.create(
            repo=self.repo,
            title="Offline",
            description="old",
            github_issue_url="https://github.com/acme/widgets/issues/999",
            difficulty="beginner",
            estimated_hours="2.0",
        )
        self.run_sync([FakeResponse(payload=[issue_payload(555)])])
        legacy.refresh_from_db()
        self.assertIsNone(legacy.github_id)
        self.assertEqual(legacy.status, "open")

    # ── Label filtering and PR exclusion ──────────────────────────────
    def test_label_filtering_and_pull_request_exclusion(self):
        payload = [
            issue_payload(201, labels=("good first issue",)),
            issue_payload(202, labels=("documentation",)),
            issue_payload(203, labels=("bug", "enhancement")),
            issue_payload(204, labels=("help wanted",), pull_request=True),
            issue_payload(205, labels=("first-timers-only",)),
        ]
        summary, _ = self.run_sync([FakeResponse(payload=payload)])
        ids = set(Issue.objects.exclude(github_id=None).values_list("github_id", flat=True))
        self.assertEqual(ids, {201, 202, 205})
        self.assertEqual(summary.created, 3)
        self.assertEqual(summary.skipped, 2)

    def test_untracked_label_does_not_create_issue(self):
        summary, _ = self.run_sync([FakeResponse(payload=[issue_payload(301, labels=("bug",))])])
        self.assertEqual(summary.created, 0)
        self.assertFalse(Issue.objects.exists())

    # ── Closure and reopening ─────────────────────────────────────────
    def test_closed_issue_is_imported_as_closed(self):
        self.run_sync([FakeResponse(payload=[issue_payload(401, state="closed")])])
        self.assertEqual(Issue.objects.get(github_id=401).status, "closed")

    def test_reopens_previously_closed_issue(self):
        self.run_sync([FakeResponse(payload=[issue_payload(402, state="closed")])])
        self.repo.refresh_from_db()
        self.repo.sync_checkpoint = None
        self.repo.last_full_sync_at = None
        self.repo.save()
        summary, _ = self.run_sync([FakeResponse(payload=[issue_payload(402, state="open")])])
        self.assertEqual(summary.reopened, 1)
        self.assertEqual(Issue.objects.get(github_id=402).status, "open")

    def test_closes_issue_that_disappears_from_full_sync(self):
        self.run_sync([FakeResponse(payload=[issue_payload(403)])])
        self.repo.refresh_from_db()
        self.repo.sync_checkpoint = None
        self.repo.last_full_sync_at = None
        self.repo.save()

        summary, _ = self.run_sync([FakeResponse(payload=[])])
        self.assertEqual(summary.closed, 1)
        self.assertEqual(Issue.objects.get(github_id=403).status, "closed")

    def test_closes_issue_that_loses_tracked_label(self):
        self.run_sync([FakeResponse(payload=[issue_payload(404)])])
        self.repo.refresh_from_db()
        self.repo.sync_checkpoint = None
        self.repo.last_full_sync_at = None
        self.repo.save()
        self.run_sync([FakeResponse(payload=[issue_payload(404, labels=("bug",))])])
        self.assertEqual(Issue.objects.get(github_id=404).status, "closed")

    def test_saved_issue_survives_closure(self):
        user = User.objects.create_user(username="keeper", password="pw")
        self.run_sync([FakeResponse(payload=[issue_payload(405)])])
        issue = Issue.objects.get(github_id=405)
        SavedIssue.objects.create(user=user, issue=issue)
        self.repo.refresh_from_db()
        self.repo.sync_checkpoint = None
        self.repo.last_full_sync_at = None
        self.repo.save()
        self.run_sync([FakeResponse(payload=[])])
        self.assertTrue(SavedIssue.objects.filter(user=user, issue=issue).exists())

    # ── Pagination, incremental sync, checkpoint recovery ────────────
    def test_pagination_follows_link_header(self):
        page_one = FakeResponse(
            payload=[issue_payload(501)],
            headers={"Link": '<https://api.github.com/repos/acme/widgets/issues?page=2>; rel="next"'},
        )
        page_two = FakeResponse(payload=[issue_payload(502)])
        summary, mocked = self.run_sync([page_one, page_two])
        self.assertEqual(summary.created, 2)
        self.assertEqual(mocked.call_count, 2)
        self.assertIn("page=2", mocked.call_args_list[1].args[0])

    def test_incremental_sync_uses_since_and_checkpoint(self):
        checkpoint = timezone.now() - timedelta(hours=2)
        self.repo.sync_checkpoint = checkpoint
        self.repo.last_full_sync_at = timezone.now()
        self.repo.save()
        summary, mocked = self.run_sync([FakeResponse(payload=[issue_payload(601)])])
        params = mocked.call_args.kwargs["params"]
        self.assertIn("since", params)
        self.assertTrue(params["since"].endswith("Z"))
        self.assertEqual(summary.created, 1)
        self.repo.refresh_from_db()
        self.assertIsNotNone(self.repo.last_synced_at)

    def test_interrupted_sync_persists_cursor_and_resumes(self):
        next_url = "https://api.github.com/repos/acme/widgets/issues?page=2"
        page_one = FakeResponse(payload=[issue_payload(701)], headers={"Link": f'<{next_url}>; rel="next"'})
        failure = FakeResponse(status_code=500)
        summary, _ = self.run_sync([page_one, failure])
        self.assertTrue(summary.errors)
        self.repo.refresh_from_db()
        self.assertEqual(self.repo.sync_cursor, next_url)
        self.assertIsNone(self.repo.sync_checkpoint)
        self.assertTrue(self.repo.last_sync_error)
        self.assertTrue(Issue.objects.filter(github_id=701).exists())

        summary, mocked = self.run_sync([FakeResponse(payload=[issue_payload(702)])])
        self.assertEqual(summary.created, 1)
        self.assertEqual(mocked.call_args.args[0], next_url)
        self.repo.refresh_from_db()
        self.assertEqual(self.repo.sync_cursor, "")
        self.assertIsNotNone(self.repo.sync_checkpoint)

    def test_resumed_full_pass_does_not_falsely_close(self):
        next_url = "https://api.github.com/repos/acme/widgets/issues?page=2"
        self.run_sync([FakeResponse(payload=[issue_payload(801)])])
        self.repo.refresh_from_db()
        self.repo.sync_cursor = next_url
        self.repo.sync_mode = "full"
        self.repo.sync_started_at = timezone.now()
        self.repo.save()

        summary, _ = self.run_sync([FakeResponse(payload=[issue_payload(802)])])
        self.assertEqual(summary.closed, 0)
        self.assertEqual(Issue.objects.get(github_id=801).status, "open")

    # ── Token, rate limit, timeout, API failures ──────────────────────
    @override_settings(GITHUB_TOKEN="")
    def test_missing_token_aborts_without_requests(self):
        service = GitHubSyncService(client=GitHubClient(token=""))
        with mock.patch("issues.github_api.requests.get") as mocked:
            summary = service.sync_all(repos=[self.repo])
        self.assertTrue(summary.aborted)
        self.assertFalse(mocked.called)
        self.assertTrue(summary.errors)

    def test_invalid_token_is_isolated_and_reported(self):
        summary, _ = self.run_sync([FakeResponse(status_code=401, payload={})])
        self.assertTrue(summary.errors)
        self.assertIn("token", summary.errors[0].lower())
        self.repo.refresh_from_db()
        self.assertIn("token", self.repo.last_sync_error.lower())

    def test_rate_limit_is_reported(self):
        limited = FakeResponse(
            status_code=403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"},
            text="API rate limit exceeded",
        )
        summary, _ = self.run_sync([limited])
        self.assertTrue(summary.errors)
        self.assertIn("rate limit", summary.errors[0].lower())

    def test_timeout_is_reported_and_retried(self):
        import requests
        summary, mocked = self.run_sync([requests.Timeout("slow")])
        self.assertTrue(summary.errors)
        self.assertIn("timed out", summary.errors[0].lower())
        self.assertEqual(mocked.call_count, 1)

    def test_malformed_json_is_reported(self):
        summary, _ = self.run_sync([FakeResponse(payload={"not": "a list"})])
        self.assertTrue(summary.errors)
        self.assertIn("unexpected", summary.errors[0].lower())

    def test_api_500_is_reported(self):
        summary, _ = self.run_sync([FakeResponse(status_code=500, payload={})])
        self.assertTrue(summary.errors)
        self.assertIn("500", summary.errors[0])

    def test_token_never_appears_in_error_log(self):
        service = GitHubSyncService(client=GitHubClient(token="super-secret-token", max_retries=0))
        with mock.patch("issues.github_api.requests.get", return_value=FakeResponse(status_code=401)), \
                self.assertLogs("issues.services.github_sync", level="ERROR") as logs:
            summary = service.sync_all(repos=[self.repo])
        joined = "\n".join(logs.output) + "\n".join(summary.errors)
        self.assertNotIn("super-secret-token", joined)

    # ── Failure isolation ─────────────────────────────────────────────
    def test_one_repository_failure_does_not_stop_others(self):
        failing = self.make_repo("acme/broken")
        healthy = self.make_repo("acme/healthy")

        def respond(url, **kwargs):
            if "acme/broken" in url:
                return FakeResponse(status_code=404, payload={})
            return FakeResponse(payload=[issue_payload(901)])

        with mock.patch("issues.github_api.requests.get", side_effect=respond):
            summary = self.service.sync_all(repos=[failing, healthy])

        self.assertEqual(summary.repositories, 2)
        self.assertEqual(summary.created, 1)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("acme/broken", summary.errors[0])
        failing.refresh_from_db()
        self.assertTrue(failing.last_sync_error)

    def test_repository_metadata_refresh_is_optional(self):
        # The service never needs repository metadata to sync issue pages.
        with mock.patch("issues.github_api.requests.get", return_value=FakeResponse(payload=[])) as mocked:
            GitHubSyncService(client=GitHubClient(token="x", max_retries=0)).sync_all(repos=[self.repo])
        self.assertEqual(mocked.call_count, 1)


class LinkHeaderTests(TestCase):
    def test_parse_link_header(self):
        header = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=5>; rel="last"'
        self.assertEqual(parse_link_header(header), "https://api.github.com/x?page=2")
        self.assertIsNone(parse_link_header(""))
        self.assertIsNone(parse_link_header("garbage"))


class SyncCommandTests(RepoFactoryMixin, TestCase):
    @override_settings(GITHUB_TOKEN="test-token")
    def test_command_reports_summary(self):
        self.make_repo()
        out = StringIO()
        page = FakeResponse(payload=[issue_payload(1001)])
        with mock.patch("issues.github_api.requests.get", return_value=page):
            call_command("sync_github_issues", stdout=out)
        self.assertIn("GitHub sync summary", out.getvalue())
        self.assertTrue(Issue.objects.filter(github_id=1001).exists())

    @override_settings(GITHUB_TOKEN="")
    def test_command_warns_when_token_missing(self):
        self.make_repo()
        out, err = StringIO(), StringIO()
        call_command("sync_github_issues", stdout=out, stderr=err)
        self.assertIn("GITHUB_TOKEN", err.getvalue())

    def test_command_rejects_unknown_repo(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("sync_github_issues", repo="nope/nope", stdout=StringIO())


class EditorRemovalTests(RepoFactoryMixin, TestCase):
    def setUp(self):
        self.repo = self.make_repo()
        self.viewer = User.objects.create_user(username="viewer1", password="pw")
        self.admin = User.objects.create_user(username="admin1", password="pw", role="admin")

    def test_editor_routes_are_gone(self):
        for path in (
            "/editor/repos/",
            "/editor/issues/",
            "/editor/issues/create/",
            "/editor/issues/import/",
            "/editor/analytics/",
        ):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_switch_role_route_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse("switch_role")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post("/dashboard/switch-role/").status_code, 404)

    def test_role_choices_exclude_editor(self):
        self.assertEqual(dict(User.ROLE_CHOICES), {"viewer": "Viewer", "admin": "Admin"})
        self.assertFalse(hasattr(self.viewer, "is_editor"))
        self.assertFalse(User.objects.filter(role="editor").exists())

    def test_repo_model_keeps_legacy_table_name(self):
        self.assertEqual(Repo._meta.db_table, "repos_repo")
        self.assertFalse(any(f.name == "editor" for f in Repo._meta.get_fields()))

    def test_editor_navigation_is_not_rendered(self):
        self.client.force_login(self.admin)
        html = self.client.get("/dashboard/").content.decode()
        self.assertNotIn("/editor/", html)
        self.assertNotIn("Editor Hub", html)
        self.assertNotIn("Become an Editor", html)


class ViewerAdminBehaviourTests(RepoFactoryMixin, TestCase):
    def setUp(self):
        self.repo = self.make_repo()
        self.viewer = User.objects.create_user(username="viewer2", password="pw")
        self.admin = User.objects.create_user(username="admin2", password="pw", role="admin")
        self.open_issue = Issue.objects.create(
            repo=self.repo,
            title="Open opportunity",
            description="visible",
            github_issue_url="https://github.com/acme/widgets/issues/1",
            difficulty="beginner",
            estimated_hours="2.0",
            status="open",
        )
        self.closed_issue = Issue.objects.create(
            repo=self.repo,
            title="Closed opportunity",
            description="hidden",
            github_issue_url="https://github.com/acme/widgets/issues/2",
            difficulty="beginner",
            estimated_hours="2.0",
            status="closed",
        )

    def test_issue_list_only_shows_open_issues(self):
        response = self.client.get("/issues/")
        self.assertContains(response, "Open opportunity")
        self.assertNotContains(response, "Closed opportunity")

    def test_dashboard_and_saved_issues_for_viewer(self):
        SavedIssue.objects.create(user=self.viewer, issue=self.open_issue)
        self.client.force_login(self.viewer)
        dashboard = self.client.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Open opportunity")
        saved = self.client.get("/dashboard/saved/")
        self.assertContains(saved, "Open opportunity")

    def test_viewer_cannot_open_admin_panel(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/admin-panel/issues/").status_code, 302)

    def test_admin_can_moderate_and_feature(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/admin-panel/issues/").status_code, 200)
        response = self.client.post(
            "/admin-panel/issues/",
            {"issue_id": self.open_issue.id, "action": "toggle_featured"},
        )
        self.assertEqual(response.status_code, 302)
        self.open_issue.refresh_from_db()
        self.assertTrue(self.open_issue.is_featured)

    def test_admin_can_track_a_repository(self):
        self.assertTrue(self.admin.is_platform_admin)
        self.assertTrue(Repo.objects.filter(pk=self.repo.pk).exists())


class EditorColumnMigrationTests(TransactionTestCase):
    """The relocation migration must drop ``editor_id`` without losing rows."""

    def test_remove_editor_column_preserves_repository_rows(self):
        from importlib import import_module

        remove_editor_column = import_module(
            "issues.migrations.0002_github_sync"
        ).remove_editor_column

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(repos_repo)")
            columns = {row[1] for row in cursor.fetchall()}
            if "editor_id" in columns:
                self.skipTest("editor_id already absent")
            cursor.execute("ALTER TABLE repos_repo ADD COLUMN editor_id integer")
            cursor.execute("CREATE INDEX repos_repo_editor_idx ON repos_repo(editor_id)")
            cursor.execute(
                "INSERT INTO repos_repo (github_url, name, language, stars, description, is_active, created_at, sync_cursor, sync_mode, last_sync_error, editor_id) "
                "VALUES ('https://github.com/legacy/repo', 'legacy/repo', 'Python', 1, '', 1, '2026-01-01 00:00:00', '', '', '', 42)"
            )

        with connection.schema_editor() as schema_editor:
            remove_editor_column(None, schema_editor)

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(repos_repo)")
            columns = {row[1] for row in cursor.fetchall()}
            cursor.execute("SELECT name, github_url FROM repos_repo WHERE name='legacy/repo'")
            row = cursor.fetchone()
        self.assertNotIn("editor_id", columns)
        self.assertEqual(row, ("legacy/repo", "https://github.com/legacy/repo"))
