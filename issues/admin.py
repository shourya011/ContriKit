from django.contrib import admin
from .models import Tag, Issue, SavedIssue

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'color')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ('title', 'repo', 'difficulty', 'estimated_hours', 'status', 'is_featured', 'view_count')
    list_filter = ('difficulty', 'status', 'is_featured', 'tags')
    search_fields = ('title', 'description')

@admin.register(SavedIssue)
class SavedIssueAdmin(admin.ModelAdmin):
    list_display = ('user', 'issue', 'saved_at')
