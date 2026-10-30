from django.contrib import admin

from .models import Issue, Repo, SavedIssue, Tag


@admin.register(Repo)
class RepoAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'language',
        'stars',
        'is_active',
        'last_synced_at',
        'last_full_sync_at',
    )
    list_filter = ('language', 'is_active')
    search_fields = ('name', 'description', 'github_url')
    readonly_fields = (
        'created_at',
        'sync_checkpoint',
        'sync_cursor',
        'sync_mode',
        'sync_started_at',
        'last_synced_at',
        'last_full_sync_at',
        'last_sync_error',
    )
    actions = ('mark_active', 'mark_inactive', 'reset_sync_checkpoint')

    @admin.action(description='Mark selected repositories as active')
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Mark selected repositories as inactive')
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description='Reset synchronization checkpoint (force full sync)')
    def reset_sync_checkpoint(self, request, queryset):
        queryset.update(
            sync_checkpoint=None,
            sync_cursor='',
            sync_mode='',
            sync_started_at=None,
            last_sync_error='',
        )


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'color')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'repo',
        'github_id',
        'difficulty',
        'estimated_hours',
        'status',
        'is_featured',
        'view_count',
    )
    list_filter = ('difficulty', 'status', 'is_featured', 'tags')
    search_fields = ('title', 'description', 'github_id', 'github_issue_url')
    readonly_fields = ('github_id', 'labels')


@admin.register(SavedIssue)
class SavedIssueAdmin(admin.ModelAdmin):
    list_display = ('user', 'issue', 'saved_at')
