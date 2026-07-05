from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Issue, Tag, SavedIssue
from templates_app.models import Template

def issue_list_view(request):
    query = request.GET.get('q', '').strip()
    language = request.GET.get('lang', '').strip()
    difficulty = request.GET.get('diff', '').strip()
    tag_slug = request.GET.get('tag', '').strip()

    issues = Issue.objects.filter(status='open').select_related('repo').prefetch_related('tags').order_by('-created_at')

    if query:
        issues = issues.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(repo__name__icontains=query))
    if language:
        issues = issues.filter(repo__language__iexact=language)
    if difficulty:
        issues = issues.filter(difficulty=difficulty)
    if tag_slug:
        issues = issues.filter(tags__slug=tag_slug)

    # Distinct languages for filter dropdown
    languages = Issue.objects.filter(status='open').exclude(repo__language='').values_list('repo__language', flat=True).distinct()
    tags = Tag.objects.all()

    paginator = Paginator(issues, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Saved issue IDs for current user to show saved state
    saved_ids = set()
    if request.user.is_authenticated:
        saved_ids = set(SavedIssue.objects.filter(user=request.user).values_list('issue_id', flat=True))

    context = {
        'page_obj': page_obj,
        'languages': sorted(set(languages)),
        'tags': tags,
        'q': query,
        'selected_lang': language,
        'selected_diff': difficulty,
        'selected_tag': tag_slug,
        'saved_ids': saved_ids,
    }
    return render(request, 'issues/issue_list.html', context)

def issue_detail_view(request, id):
    issue = get_object_or_404(Issue.objects.select_related('repo', 'posted_by').prefetch_related('tags'), id=id)

    # View count increment once per session per issue
    session_key = f"viewed_issue_{issue.id}"
    if not request.session.get(session_key, False):
        issue.view_count += 1
        issue.save(update_fields=['view_count'])
        request.session[session_key] = True

    is_saved = False
    if request.user.is_authenticated:
        is_saved = SavedIssue.objects.filter(user=request.user, issue=issue).exists()

    # Get template files to display
    templates = Template.objects.all()

    return render(request, 'issues/issue_detail.html', {
        'issue': issue,
        'is_saved': is_saved,
        'templates': templates,
    })

@require_POST
def toggle_save_view(request, id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login_required'}, status=403)

    issue = get_object_or_404(Issue, id=id)
    saved_obj = SavedIssue.objects.filter(user=request.user, issue=issue).first()

    if saved_obj:
        saved_obj.delete()
        return JsonResponse({'status': 'unsaved', 'issue_id': issue.id})
    else:
        SavedIssue.objects.create(user=request.user, issue=issue)
        return JsonResponse({'status': 'saved', 'issue_id': issue.id})
