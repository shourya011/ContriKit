from django.contrib import admin
from .models import Template

@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'slug', 'updated_at')
    list_filter = ('type',)
    prepopulated_fields = {'slug': ('title',)}
