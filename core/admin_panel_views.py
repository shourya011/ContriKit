import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count
from core.decorators import admin_required
from accounts.models import User
from issues.models import Issue, Tag
from templates_app.models import Template
from cheatsheet.models import CheatSheetSection, CheatSheetCommand

@admin_required
def admin_users_view(request):
    users = User.objects.all().order_by('-date_joined')
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        new_role = request.POST.get('role')
        action = request.POST.get('action')
        target_user = get_object_or_404(User, id=user_id)

        if target_user.is_superuser and not request.user.is_superuser:
            messages.error(request, "Cannot modify platform superuser.")
        elif action == 'toggle_active':
            target_user.is_active = not target_user.is_active
            target_user.save()
            messages.success(request, f"User {target_user.username} {'activated' if target_user.is_active else 'deactivated'}.")
        elif new_role in dict(User.ROLE_CHOICES):
            target_user.role = new_role
            target_user.save()
            messages.success(request, f"Updated role for {target_user.username} to {new_role}.")
        return redirect('/admin-panel/users/')

    return render(request, 'core/admin_panel/users.html', {'users': users, 'role_choices': User.ROLE_CHOICES})

@admin_required
def admin_issues_view(request):
    issues = Issue.objects.all().select_related('repo', 'posted_by').order_by('-created_at')
    if request.method == 'POST':
        issue_id = request.POST.get('issue_id')
        action = request.POST.get('action')
        issue_obj = get_object_or_404(Issue, id=issue_id)

        if action == 'delete':
            issue_obj.delete()
            messages.success(request, "Issue removed by moderator.")
        elif action == 'toggle_featured':
            issue_obj.is_featured = not issue_obj.is_featured
            issue_obj.save()
            messages.success(request, f"Issue {'featured ⭐' if issue_obj.is_featured else 'unfeatured'}.")
        return redirect('/admin-panel/issues/')

    return render(request, 'core/admin_panel/issues.html', {'issues': issues})

@admin_required
def admin_templates_view(request):
    templates = Template.objects.all().order_by('type')
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
            tmpl_type = request.POST.get('type')
            desc = request.POST.get('description', '')
            content = request.POST.get('content', '')
            if tmpl_id:
                t = get_object_or_404(Template, id=tmpl_id)
                t.title = title
                t.slug = slug
                t.type = tmpl_type
                t.description = desc
                t.content = content
                t.save()
                messages.success(request, "Template updated.")
            else:
                Template.objects.create(
                    title=title,
                    slug=slug,
                    type=tmpl_type,
                    description=desc,
                    content=content,
                    created_by=request.user
                )
                messages.success(request, "New template created.")
            return redirect('/admin-panel/templates/')

    edit_tmpl = None
    if request.GET.get('edit'):
        edit_tmpl = get_object_or_404(Template, id=request.GET.get('edit'))

    return render(request, 'core/admin_panel/templates.html', {
        'templates': templates,
        'type_choices': Template.TYPE_CHOICES,
        'edit_tmpl': edit_tmpl
    })

@admin_required
def admin_cheatsheet_view(request):
    sections = CheatSheetSection.objects.prefetch_related('commands').all()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_section':
            title = request.POST.get('title')
            order = request.POST.get('order', 0)
            if title:
                CheatSheetSection.objects.create(title=title, order=int(order or 0))
                messages.success(request, "Section created.")
        elif action == 'delete_section':
            sec_id = request.POST.get('sec_id')
            CheatSheetSection.objects.filter(id=sec_id).delete()
            messages.success(request, "Section deleted.")
        elif action == 'add_command':
            sec_id = request.POST.get('section_id')
            cmd = request.POST.get('command')
            desc = request.POST.get('description')
            ex = request.POST.get('example', '')
            if sec_id and cmd and desc:
                CheatSheetCommand.objects.create(section_id=sec_id, command=cmd, description=desc, example=ex)
                messages.success(request, "Command added.")
        elif action == 'delete_command':
            cmd_id = request.POST.get('cmd_id')
            CheatSheetCommand.objects.filter(id=cmd_id).delete()
            messages.success(request, "Command deleted.")
        return redirect('/admin-panel/cheatsheet/')

    return render(request, 'core/admin_panel/cheatsheet.html', {'sections': sections})

@admin_required
def admin_analytics_view(request):
    total_users = User.objects.count()
    total_repos = Issue.objects.values('repo').distinct().count()
    total_issues = Issue.objects.count()
    total_templates = Template.objects.count()

    role_dist = User.objects.values('role').annotate(count=Count('id'))
    pie_labels = [r['role'].capitalize() for r in role_dist]
    pie_data = [r['count'] for r in role_dist]

    return render(request, 'core/admin_panel/analytics.html', {
        'total_users': total_users,
        'total_repos': total_repos,
        'total_issues': total_issues,
        'total_templates': total_templates,
        'pie_labels': pie_labels,
        'pie_data': pie_data,
    })
