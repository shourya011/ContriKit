from django.shortcuts import render, get_object_or_404
from .models import Template

def template_list_view(request):
    templates = Template.objects.all().order_by('type', 'title')
    return render(request, 'templates_app/template_list.html', {'templates': templates})

def template_detail_view(request, slug):
    template = get_object_or_404(Template, slug=slug)
    return render(request, 'templates_app/template_detail.html', {'template': template})
