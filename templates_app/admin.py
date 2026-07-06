from django.contrib import admin
from .models import Template

@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'slug', 'created_at', 'updated_at')
    list_filter = ('category',)
    prepopulated_fields = {'slug': ('title',)}
    search_fields = ('title', 'description', 'tags')