from django.contrib import admin
from .models import CheatSheetSection, CheatSheetCommand

class CheatSheetCommandInline(admin.TabularInline):
    model = CheatSheetCommand
    extra = 1

@admin.register(CheatSheetSection)
class CheatSheetSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'order')
    inlines = [CheatSheetCommandInline]

@admin.register(CheatSheetCommand)
class CheatSheetCommandAdmin(admin.ModelAdmin):
    list_display = ('command', 'section', 'description', 'order')
    list_filter = ('section',)
