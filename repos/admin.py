from django.contrib import admin
from .models import Repo

@admin.register(Repo)
class RepoAdmin(admin.ModelAdmin):
    list_display = ('name', 'editor', 'language', 'stars', 'is_active', 'created_at')
    list_filter = ('language', 'is_active')
    search_fields = ('name', 'description', 'github_url')
