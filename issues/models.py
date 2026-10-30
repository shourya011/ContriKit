from decimal import Decimal
from urllib.parse import urlparse

from django.conf import settings
from django.db import models


LEGACY_REPO_TABLE = 'repos_repo'


class Repo(models.Model):
    """A GitHub repository whose beginner-friendly issues are synchronized.

    The physical table name is kept as ``repos_repo`` so that existing
    installations can migrate without copying or losing repository rows.
    """

    github_url = models.URLField(unique=True)
    name = models.CharField(max_length=200)
    language = models.CharField(max_length=50, blank=True)
    stars = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Sync bookkeeping. The checkpoint is the ``updated_at`` watermark used
    # for GitHub's ``since`` parameter; the cursor is the next page URL for an
    # interrupted run and is cleared only after a complete successful pass.
    sync_checkpoint = models.DateTimeField(null=True, blank=True)
    sync_cursor = models.TextField(blank=True, default='')
    sync_mode = models.CharField(max_length=12, blank=True, default='')
    sync_started_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_full_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default='')

    class Meta:
        db_table = LEGACY_REPO_TABLE
        ordering = ('name',)

    def __str__(self):
        return self.name

    @property
    def owner(self):
        owner, _ = self.owner_and_name
        return owner

    @property
    def repo_name(self):
        _, repo_name = self.owner_and_name
        return repo_name

    @property
    def owner_and_name(self):
        """Return ``(owner, repo)`` parsed from the stored URL or full name."""
        parts = [part for part in urlparse(self.github_url or '').path.strip('/').split('/') if part]
        if len(parts) >= 2:
            return parts[0], parts[1]
        parts = [part for part in (self.name or '').strip('/').split('/') if part]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return None, None


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)
    color = models.CharField(max_length=7, default="#6366f1")

    def __str__(self):
        return self.name


class Issue(models.Model):
    DIFFICULTY_CHOICES = [("beginner", "Beginner"), ("intermediate", "Intermediate")]
    STATUS_CHOICES = [("open", "Open"), ("closed", "Closed")]

    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="issues")
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_issues",
    )
    github_id = models.BigIntegerField(null=True, blank=True, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    github_issue_url = models.URLField()
    labels = models.JSONField(default=list, blank=True)
    difficulty = models.CharField(max_length=15, choices=DIFFICULTY_CHOICES, default="beginner")
    estimated_hours = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal("2.0")
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    is_featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    tags = models.ManyToManyField(Tag, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class SavedIssue(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "issue")

    def __str__(self):
        return f"{self.user} saved {self.issue}"
