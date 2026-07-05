from django.db import models
from django.conf import settings
from repos.models import Repo

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
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    github_issue_url = models.URLField()
    difficulty = models.CharField(max_length=15, choices=DIFFICULTY_CHOICES)
    estimated_hours = models.DecimalField(max_digits=4, decimal_places=1)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    is_featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    tags = models.ManyToManyField(Tag, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
