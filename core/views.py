from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum
from django.http import JsonResponse
from issues.models import Issue, SavedIssue, Tag
from repos.models import Repo
from templates_app.models import Template

def landing_page(request):
    issue_count = Issue.objects.filter(status='open').count()
    template_count = Template.objects.count()
    repo_count = Repo.objects.filter(is_active=True).count()
    featured_issues = Issue.objects.filter(status='open', is_featured=True).select_related('repo')[:8]
    if not featured_issues.exists():
        featured_issues = Issue.objects.filter(status='open').select_related('repo')[:8]
    featured_templates = Template.objects.all()[:3]

    saved_ids = set()
    if request.user.is_authenticated:
        saved_ids = set(
            SavedIssue.objects.filter(user=request.user).values_list('issue_id', flat=True)
        )

    context = {
        'issue_count': issue_count,
        'template_count': template_count,
        'repo_count': repo_count,
        'featured_issues': featured_issues,
        'featured_templates': featured_templates,
        'saved_ids': saved_ids,
    }
    return render(request, 'core/landing.html', context)

@login_required
def dashboard_view(request):
    user = request.user
    saved_qs = SavedIssue.objects.filter(user=user).select_related('issue', 'issue__repo')
    saved_issues = saved_qs.order_by('-saved_at')[:4]
    total_saved = saved_qs.count()
    saved_repos_count = saved_qs.values('issue__repo').distinct().count()

    context = {
        'saved_issues': saved_issues,
        'total_saved': total_saved,
        'saved_repos_count': saved_repos_count,
        'open_issues_count': Issue.objects.filter(status='open').count(),
    }

    if user.is_editor:
        context['posted_issues_count'] = Issue.objects.filter(posted_by=user).count()
        context['editor_repos_count'] = Repo.objects.filter(editor=user).count()

    return render(request, 'core/dashboard.html', context)

@login_required
def saved_issues_list_view(request):
    saved_issues = SavedIssue.objects.filter(user=request.user).select_related('issue', 'issue__repo').order_by('-saved_at')
    return render(request, 'core/saved_issues.html', {'saved_issues': saved_issues})

@login_required
def switch_role_view(request):
    if request.method == 'POST':
        new_role = request.POST.get('role', 'editor')
        if new_role == 'editor':
            request.user.role = 'editor'
            request.user.save()
            messages.success(request, "Congratulations! You are now an Editor. You can post issues and manage repositories.")
            return redirect('/editor/repos/')
        elif new_role == 'viewer':
            if not request.user.is_superuser and request.user.role != 'admin':
                request.user.role = 'viewer'
                request.user.save()
                messages.info(request, "You have switched back to Viewer role. Your editor data is safely preserved.")
            return redirect('/dashboard/')
    return redirect('/dashboard/')
