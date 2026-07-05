from django.db import models
from django.conf import settings

class Repo(models.Model):
    editor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="repos")
    github_url = models.URLField(unique=True)
    name = models.CharField(max_length=200)
    language = models.CharField(max_length=50, blank=True)
    stars = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
