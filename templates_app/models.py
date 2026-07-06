from django.db import models
from django.conf import settings
from django.utils.text import slugify


class Template(models.Model):
    CATEGORY_CHOICES = [
        ("community_health", "Community Health"),
        ("documentation", "Documentation"),
        ("contributing", "Contributing"),
        ("issue_templates", "Issue Templates"),
        ("pr_templates", "Pull Request Templates"),
        ("github_config", "GitHub Configuration"),
        ("issue_forms", "GitHub Issue Forms"),
        ("discussions", "GitHub Discussions"),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    category = models.CharField(
        max_length=30, choices=CATEGORY_CHOICES, default="documentation"
    )
    description = models.CharField(max_length=500, blank=True)
    content = models.TextField()
    tags = models.CharField(max_length=500, blank=True, help_text="Comma-separated tags")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "title"]

    def __str__(self):
        return self.title

    @property
    def preview(self):
        """Auto-generate preview from first few lines of content."""
        lines = self.content.strip().split("\n")
        preview_lines = []
        for line in lines:
            if line.startswith("#") or line.startswith("---"):
                continue
            stripped = line.strip()
            if stripped and not stripped.startswith("["):
                preview_lines.append(stripped)
            if len(preview_lines) >= 3:
                break
        preview = " ".join(preview_lines)
        if len(preview) > 200:
            preview = preview[:197] + "..."
        return preview if preview else self.description[:200]

    @property
    def tag_list(self):
        if not self.tags:
            return []
        return [t.strip() for t in self.tags.split(",") if t.strip()]