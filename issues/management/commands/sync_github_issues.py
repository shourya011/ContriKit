"""Synchronize tracked GitHub repositories into the ContribKit issue board.

Examples
--------
``python manage.py sync_github_issues``
    Run one synchronization pass for every active repository.

``python manage.py sync_github_issues --watch``
    Run continuously, one pass every ``GITHUB_SYNC_INTERVAL`` seconds
    (default 120), until SIGINT/SIGTERM.

``python manage.py sync_github_issues --repo django/django --full``
    Force a full reconciliation for a single repository.
"""

import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from issues.models import Repo
from issues.services.github_sync import GitHubSyncService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Import and update beginner-friendly issues from tracked GitHub "
        "repositories. Runs once by default; use --watch for a 120s loop."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repo",
            action="append",
            default=None,
            metavar="OWNER/NAME",
            help="Only sync this repository (repeatable).",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Ignore the incremental checkpoint and reconcile every issue.",
        )
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Keep running, syncing every --interval seconds.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=None,
            help="Seconds between passes in --watch mode (default 120).",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Also sync repositories marked inactive.",
        )

    def handle(self, *args, **options):
        interval = options["interval"] or getattr(settings, "GITHUB_SYNC_INTERVAL", 120)
        if interval < 30:
            raise CommandError("--interval must be at least 30 seconds.")

        repos = self._select_repos(options)
        if not repos and not options["watch"]:
            self.stdout.write(self.style.WARNING("No repositories to synchronize."))
            return

        if not getattr(settings, "GITHUB_TOKEN", ""):
            self.stderr.write(
                self.style.ERROR(
                    "GITHUB_TOKEN is not set; GitHub synchronization cannot run. "
                    "See SYNC_README.md."
                )
            )
            return

        if not options["watch"]:
            summary = self._run_once(repos, options["full"])
            self._report(summary)
            return

        self.stdout.write(
            f"Starting GitHub sync worker (every {interval}s). Press Ctrl+C to stop."
        )
        self._install_signal_handlers()
        self._running = True
        while self._running:
            started = time.monotonic()
            summary = self._run_once(self._select_repos(options), options["full"])
            self._report(summary)
            elapsed = time.monotonic() - started
            remaining = max(0, interval - elapsed)
            self.stdout.write(
                f"Next sync in {int(remaining)}s "
                f"({timezone.now().isoformat(timespec='seconds')})."
            )
            self._sleep(remaining)

    def _select_repos(self, options):
        queryset = Repo.objects.all() if options["include_inactive"] else Repo.objects.filter(is_active=True)
        names = options.get("repo")
        if names:
            wanted = {name.strip().lower() for name in names if name.strip()}
            selected = [
                repo
                for repo in queryset.order_by("name")
                if (repo.name or "").lower() in wanted
                or f"{repo.owner}/{repo.repo_name}".lower() in wanted
            ]
            missing = wanted - {
                (repo.name or "").lower() for repo in selected
            } - {f"{repo.owner}/{repo.repo_name}".lower() for repo in selected}
            if missing:
                raise CommandError(
                    "Unknown repository selection: " + ", ".join(sorted(missing))
                )
            return selected
        return list(queryset.order_by("name"))

    def _run_once(self, repos, force_full):
        service = GitHubSyncService()
        return service.sync_all(repos=repos, force_full=force_full)

    def _report(self, summary):
        for repo_name, result in summary.per_repository.items():
            if result.error:
                self.stderr.write(self.style.ERROR(result.error))
        style = self.style.ERROR if summary.errors else self.style.SUCCESS
        self.stdout.write(style(f"GitHub sync summary: {summary}"))
        if summary.errors:
            self.stdout.write(self.style.WARNING(f"Errors: {len(summary.errors)}"))
        self.stdout.write(
            f"Created {summary.created}, updated {summary.updated}, "
            f"skipped {summary.skipped}, failed {summary.failed}, "
            f"closed {summary.closed}, reopened {summary.reopened}."
        )

    def _install_signal_handlers(self):
        def _stop(signum, frame):
            self._running = False
            self.stdout.write("Stopping after the current pass...")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _stop)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                pass

    def _sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
