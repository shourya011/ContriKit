"""Integration tests for the ContribKit-aware tools (uses the test database).

Every tool is exercised against real seeded models — no LLM or external API
calls (GitHub HTTP is mocked).
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ai.services.tools import GetCurrentIssueContextTool, GetCurrentTemplateContextTool
from ai.services.tools import GetGitHubBeginnerIssuesTool, GetGitHubRepositoryTool
from ai.services.tools import GetIssueDetailsTool, GetTemplateTool, GetUserContextTool
from ai.services.tools import RecommendIssuesTool, RecommendTemplatesTool, SearchGitCommandsTool
from ai.services.tools import SearchIssuesTool, SearchTemplatesTool
from ai.services.tools import ToolContext, build_default_tool_registry
from ai.services.tools.cheatsheet import SearchGitCommandsTool as CSSearch
from cheatsheet.models import CheatSheetCommand, CheatSheetSection
from issues.models import Issue, SavedIssue, Tag
from repos.models import Repo
from templates_app.models import Template

User = get_user_model()

TOOL_NAMES = sorted([
    "search_issues",
    "get_issue_details",
    "recommend_issues",
    "search_templates",
    "get_template",
    "recommend_templates",
    "search_git_commands",
    "get_github_repository",
    "get_github_beginner_issues",
    "get_user_context",
    "get_current_issue_context",
    "get_current_template_context",
])


class ToolsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_a = User.objects.create_user(username="alice", password="pw")
        cls.user_b = User.objects.create_user(username="bob", password="pw")
        cls.editor = User.objects.create_user(username="carol", password="pw", role="editor")

        cls.python_tag = Tag.objects.create(name="Python", slug="python", color="#3776ab")
        cls.docs_tag = Tag.objects.create(name="Documentation", slug="documentation", color="#6366f1")
        cls.testing_tag = Tag.objects.create(name="Testing", slug="testing", color="#7c3aed")
        cls.css_tag = Tag.objects.create(name="CSS/HTML", slug="css-html", color="#e11d48")

        cls.repo = Repo.objects.create(
            editor=cls.editor,
            github_url="https://github.com/django/django",
            name="django/django",
            language="Python",
            stars=81200,
            description="The web framework for perfectionists with deadlines.",
        )
        cls.repo_js = Repo.objects.create(
            editor=cls.editor,
            github_url="https://github.com/twbs/bootstrap",
            name="twbs/bootstrap",
            language="JavaScript",
            stars=170500,
            description="HTML CSS JS library.",
        )

        cls.issue_docs = Issue.objects.create(
            repo=cls.repo, posted_by=cls.editor,
            title="Fix typo in tutorial documentation header",
            description="Misspelling in docs/intro/tutorial01.txt. Fix and verify with make html.",
            github_issue_url="https://github.com/django/django/issues/101",
            difficulty="beginner", estimated_hours=1.0, status="open",
        )
        cls.issue_docs.tags.set([cls.docs_tag, cls.python_tag])

        cls.issue_tests = Issue.objects.create(
            repo=cls.repo, posted_by=cls.editor,
            title="Write unit tests for url_for helper edge cases",
            description="Add pytest cases in tests/test_helpers.py.",
            github_issue_url="https://github.com/django/django/issues/102",
            difficulty="intermediate", estimated_hours=3.5, status="open",
        )
        cls.issue_tests.tags.set([cls.testing_tag, cls.python_tag])

        cls.issue_js = Issue.objects.create(
            repo=cls.repo_js, posted_by=cls.editor,
            title="Convert alert dismiss button to SVG icon component",
            description="Replace background-image with inline SVG in _alerts.scss.",
            github_issue_url="https://github.com/twbs/bootstrap/issues/103",
            difficulty="beginner", estimated_hours=4.0, status="open",
        )
        cls.issue_js.tags.set([cls.css_tag])

        cls.issue_closed = Issue.objects.create(
            repo=cls.repo, posted_by=cls.editor,
            title="Closed issue should not appear in board",
            description="Secret closed task.",
            github_issue_url="https://github.com/django/django/issues/104",
            difficulty="beginner", estimated_hours=1.0, status="closed",
        )

        SavedIssue.objects.create(user=cls.user_a, issue=cls.issue_docs)
        SavedIssue.objects.create(user=cls.user_b, issue=cls.issue_tests)

        cls.contributing_tmpl = Template.objects.create(
            title="CONTRIBUTING.md",
            slug="contributing-md",
            category="contributing",
            description="How to contribute to a repository.",
            content="# Contributing\n## How to contribute\nOpen a PR after testing.",
            tags="contributing, git, workflow",
            created_by=cls.editor,
        )
        cls.pr_tmpl = Template.objects.create(
            title="PULL_REQUEST_TEMPLATE.md",
            slug="pr-template",
            category="pr_templates",
            description="Standard pull request description template.",
            content="# Pull Request\nDescribe your changes and testing steps.",
            tags="pull-request, pr, review",
            created_by=cls.editor,
        )

        cls.section = CheatSheetSection.objects.create(title="Branching", order=1)
        cls.cmd = CheatSheetCommand.objects.create(
            section=cls.section,
            command="git checkout -b feature/name",
            description="Create and switch to a new branch.",
            example="git checkout -b fix-typo",
        )

    # ── Issue Board tools ──────────────────────────────────────────────
    def test_search_issues_keyword(self):
        result = SearchIssuesTool().run(ToolContext(), q="url_for")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["issue"]["id"], self.issue_tests.id)

    def test_search_issues_language_difficulty_tag(self):
        by_lang = SearchIssuesTool().run(ToolContext(), language="Python")
        self.assertEqual(by_lang["count"], 2)

        by_diff = SearchIssuesTool().run(ToolContext(), difficulty="beginner")
        self.assertEqual(by_diff["count"], 2)

        by_tag = SearchIssuesTool().run(ToolContext(), tag="documentation")
        self.assertEqual(by_tag["count"], 1)
        self.assertEqual(by_tag["results"][0]["issue"]["id"], self.issue_docs.id)

    def test_search_issues_excludes_closed(self):
        result = SearchIssuesTool().run(ToolContext(), q="Closed issue")
        self.assertEqual(result["count"], 0)

    def test_get_issue_details(self):
        result = GetIssueDetailsTool().run(ToolContext(), issue_id=self.issue_docs.id)
        self.assertEqual(result["issue"]["title"], self.issue_docs.title)
        self.assertIn("description", result["issue"])
        self.assertEqual(result["issue"]["repo"]["name"], "django/django")
        self.assertEqual(result["issue"]["posted_by"], "carol")

    def test_get_issue_details_missing(self):
        result = GetIssueDetailsTool().run(ToolContext(), issue_id=999999)
        self.assertIn("error", result)

    def test_recommend_issues_ranks_by_signal(self):
        result = RecommendIssuesTool().run(
            ToolContext(), preference="python documentation fix"
        )
        self.assertGreater(result["count"], 0)
        self.assertEqual(result["results"][0]["issue"]["id"], self.issue_docs.id)
        self.assertIn("documentation", result["results"][0]["matched_terms"])

    def test_recommend_issues_respects_filters(self):
        result = RecommendIssuesTool().run(
            ToolContext(), preference="frontend accessibility", language="JavaScript"
        )
        ids = [item["issue"]["id"] for item in result["results"]]
        self.assertIn(self.issue_js.id, ids)
        self.assertNotIn(self.issue_docs.id, ids)

    # ── Template Library tools ──────────────────────────────────────────
    def test_search_templates(self):
        result = SearchTemplatesTool().run(ToolContext(), q="pull request")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["slug"], "pr-template")
        self.assertIsNone(result["results"][0]["content"])

    def test_search_templates_by_category(self):
        result = SearchTemplatesTool().run(ToolContext(), category="contributing")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["slug"], "contributing-md")

    def test_get_template_content(self):
        result = GetTemplateTool().run(ToolContext(), slug="contributing-md")
        self.assertIn("How to contribute", result["template"]["content"])
        self.assertFalse(result["template"]["content_truncated"])

    def test_get_template_missing(self):
        result = GetTemplateTool().run(ToolContext(), slug="nope")
        self.assertIn("error", result)

    def test_recommend_templates(self):
        result = RecommendTemplatesTool().run(ToolContext(), preference="how to contribute to a repo")
        self.assertEqual(result["results"][0]["slug"], "contributing-md")

    # ── Git Cheat Sheet tools ───────────────────────────────────────────
    def test_search_git_commands(self):
        result = SearchGitCommandsTool().run(ToolContext(), q="checkout")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["command"], "git checkout -b feature/name")
        self.assertEqual(result["results"][0]["section"], "Branching")

    def test_search_git_commands_by_section(self):
        result = CSSearch().run(ToolContext(), section="Branching")
        self.assertEqual(result["count"], 1)
        result_none = CSSearch().run(ToolContext(), section="Deploying")
        self.assertEqual(result_none["count"], 0)

    # ── GitHub tools (mock the shared client's HTTP) ────────────────────
    @mock.patch("repos.github_api.requests.get")
    def test_get_github_repository_ok(self, mock_get):
        mock_response = mock.Mock(status_code=200)
        mock_response.headers = {}
        mock_response.json.return_value = {
            "full_name": "django/django",
            "description": "The web framework",
            "language": "Python",
            "stargazers_count": 81200,
            "forks_count": 4000,
            "open_issues_count": 500,
            "topics": ["python", "web"],
            "html_url": "https://github.com/django/django",
            "default_branch": "main",
        }
        mock_get.return_value = mock_response

        result = GetGitHubRepositoryTool().run(
            ToolContext(), url="https://github.com/django/django"
        )
        self.assertEqual(result["repository"]["full_name"], "django/django")
        self.assertEqual(result["repository"]["stars"], 81200)

    @mock.patch("repos.github_api.requests.get")
    def test_get_github_repository_404_is_controlled_error(self, mock_get):
        mock_get.return_value = mock.Mock(
            status_code=404, headers={}, json=lambda: {}, text="nf"
        )
        result = GetGitHubRepositoryTool().run(ToolContext(), owner="x", repo="missing")
        self.assertIn("error", result)
        self.assertEqual(result["status_code"], 404)

    @override_settings(GITHUB_PAT="ghp_super_secret")
    @mock.patch("repos.github_api.requests.get")
    def test_github_pat_used_server_side_only(self, mock_get):
        mock_get.return_value = mock.Mock(
            status_code=200, headers={},
            json=lambda: {"full_name": "a/b", "topics": []},
        )
        GetGitHubRepositoryTool().run(ToolContext(), owner="a", repo="b")
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "token ghp_super_secret")
        # The result dict must never contain the token.
        result = GetGitHubRepositoryTool().run(ToolContext(), owner="a", repo="b")
        self.assertNotIn("ghp_super_secret", str(result))

    @mock.patch("repos.github_api.requests.get")
    def test_get_github_beginner_issues(self, mock_get):
        issue_payload = [
            {
                "id": 1, "title": "Easy docs fix", "body": "Fix a typo.",
                "html_url": "https://github.com/x/y/issues/1", "comments": 2,
                "created_at": "2026-01-01T00:00:00Z",
                "labels": [{"name": "good first issue"}],
            },
            {
                "id": 2, "title": "PR not an issue", "body": "",
                "html_url": "https://github.com/x/y/pull/2", "comments": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "labels": [], "pull_request": {},
            },
        ]
        mock_get.return_value = mock.Mock(
            status_code=200, headers={}, json=lambda: issue_payload
        )
        result = GetGitHubBeginnerIssuesTool().run(ToolContext(), owner="x", repo="y")
        self.assertEqual(result["count"], 1)  # PR excluded
        self.assertEqual(result["results"][0]["title"], "Easy docs fix")
        self.assertIn("body_preview", result["results"][0])

    # ── User Context tool (permission scoping) ──────────────────────────
    def test_user_context_own_data_only(self):
        result = GetUserContextTool().run(ToolContext(user=self.user_a))
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["username"], "alice")
        self.assertEqual(result["saved_issues_count"], 1)
        self.assertEqual(result["saved_issues"][0]["id"], self.issue_docs.id)
        self.assertNotIn(self.issue_tests.id, [i["id"] for i in result["saved_issues"]])

    def test_user_context_anonymous(self):
        result = GetUserContextTool().run(ToolContext(user=None))
        self.assertEqual(result, {"authenticated": False})

    def test_user_context_editor(self):
        result = GetUserContextTool().run(ToolContext(user=self.editor))
        self.assertEqual(result["role"], "editor")
        self.assertEqual(result["posted_issues_count"], 4)
        self.assertEqual(result["linked_repos_count"], 2)

    # ── Page context tools ──────────────────────────────────────────────
    def test_current_issue_context_from_path(self):
        ctx = ToolContext(page_path=f"/issues/{self.issue_docs.id}/")
        result = GetCurrentIssueContextTool().run(ctx)
        self.assertTrue(result["available"])
        self.assertEqual(result["title"], self.issue_docs.title)
        self.assertEqual(result["repo"]["name"], "django/django")

    def test_current_issue_context_explicit_id(self):
        ctx = ToolContext(issue_id=self.issue_js.id)
        result = GetCurrentIssueContextTool().run(ctx)
        self.assertTrue(result["available"])
        self.assertEqual(result["issue_id"], self.issue_js.id)

    def test_current_issue_context_unavailable(self):
        result = GetCurrentIssueContextTool().run(ToolContext(page_path="/dashboard/"))
        self.assertFalse(result["available"])

    def test_current_template_context(self):
        result = GetCurrentTemplateContextTool().run(
            ToolContext(page_path="/templates/contributing-md/")
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["title"], "CONTRIBUTING.md")

    # ── Default registry ────────────────────────────────────────────────
    def test_default_registry_has_all_expected_tools(self):
        registry = build_default_tool_registry()
        self.assertEqual(registry.names(), TOOL_NAMES)
        specs = registry.specs()
        self.assertEqual(len(specs), len(TOOL_NAMES))
        for spec in specs:
            self.assertTrue(spec.name)
            self.assertTrue(spec.description)
            self.assertIn("properties", spec.parameters)
