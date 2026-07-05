from django.shortcuts import render
from .models import CheatSheetSection

def cheatsheet_view(request):
    sections = CheatSheetSection.objects.prefetch_related('commands').all()
    return render(request, 'cheatsheet/cheatsheet.html', {'sections': sections})
