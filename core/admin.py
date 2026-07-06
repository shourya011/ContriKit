from django.contrib import admin
from django.contrib import admin
from core.decorators import admin_required
# Register your models here.
@admin_required
def admin_templates_view(request):
    templates = Template.objects.all().order_by('category')
    if request.method == 'POST':
        tmpl_id = request.POST.get('tmpl_id')
        action = request.POST.get('action')
        if action == 'delete' and tmpl_id:
            Template.objects.filter(id=tmpl_id).delete()
            messages.success(request, "Template deleted.")
            return redirect('/admin-panel/templates/')
        elif action == 'save':
            title = request.POST.get('title')
            slug = request.POST.get('slug')
            category = request.POST.get('category')
            desc = request.POST.get('description', '')
            content = request.POST.get('content', '')
            tags = request.POST.get('tags', '')
            if tmpl_id:
                t = get_object_or_404(Template, id=tmpl_id)
                t.title = title
                t.slug = slug
                t.category = category
                t.description = desc
                t.content = content
                t.tags = tags
                t.save()
                messages.success(request, "Template updated.")
            else:
                Template.objects.create(
                    title=title,
                    slug=slug,
                    category=category,
                    description=desc,
                    content=content,
                    tags=tags,
                    created_by=request.user
                )
                messages.success(request, "New template created.")
            return redirect('/admin-panel/templates/')

    edit_tmpl = None
    if request.GET.get('edit'):
        edit_tmpl = get_object_or_404(Template, id=request.GET.get('edit'))

    return render(request, 'core/admin_panel/templates.html', {
        'templates': templates,
        'categories': Template.CATEGORY_CHOICES,
        'edit_tmpl': edit_tmpl
    })