from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = [("viewer", "Viewer"), ("editor", "Editor"), ("admin", "Admin")]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="viewer")
    github_username = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = "admin"
        super().save(*args, **kwargs)

    @property
    def is_viewer(self):
        return self.role == "viewer"

    @property
    def is_editor(self):
        return self.role == "editor" or self.role == "admin"

    @property
    def is_platform_admin(self):
        return self.role == "admin" or self.is_superuser
