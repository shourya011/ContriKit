from django.db import models
from django.conf import settings

class Template(models.Model):
    TYPE_CHOICES = [
        ("readme", "README"),
        ("contributing", "CONTRIBUTING.md"),
        ("issue_tmpl", "Issue Template"),
        ("pr_tmpl", "PR Template"),
        ("code_of_conduct", "Code of Conduct")
    ]
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    content = models.TextField()
    description = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
