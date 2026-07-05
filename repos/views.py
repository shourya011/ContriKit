import requests
from urllib.parse import urlparse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from core.decorators import editor_required
from .models import Repo
from .forms import RepoForm
from issues.models import Issue, Tag, SavedIssue
from issues.forms import IssueForm

def parse_github_url(url):
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip('/').split('/') if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None

@editor_required
def repos_list_view(request):
    repos = Repo.objects.filter(editor=request.user).order_by('-created_at')
    if request.user.is_platform_admin:
        repos = Repo.objects.all().order_by('-created_at')

    if request.method == 'POST':
        form = RepoForm(request.POST)
        if form.is_valid():
            url = form.cleaned_data['github_url']
            owner, repo_name = parse_github_url(url)
            if not owner or not repo_name:
                form.add_error('github_url', "Invalid GitHub repository URL format.")
            else:
                try:
                    resp = requests.get(f"https://api.github.com/repos/{owner}/{repo_name}", timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        repo_obj = form.save(commit=False)
                        repo_obj.editor = request.user
                        repo_obj.name = data.get('full_name') or f"{owner}/{repo_name}"
                        repo_obj.stars = data.get('stargazers_count', 0)
                        repo_obj.language = data.get('language') or ""
                        repo_obj.description = data.get('description') or ""
                        repo_obj.save()
                        messages.success(request, f"Successfully linked repository: {repo_obj.name}!")
                        return redirect('/editor/repos/')
                    elif resp.status_code == 404:
                        form.add_error('github_url', "We couldn't find that repository — check the URL and try again.")
                    elif resp.status_code == 403 and resp.headers.get('X-RateLimit-Remaining') == '0':
                        form.add_error('github_url', "GitHub rate limit reached, please try again in a few minutes.")
                    else:
                        form.add_error('github_url', f"GitHub API error (Status {resp.status_code}).")
                except requests.RequestException:
                    form.add_error('github_url', "Network timeout contacting GitHub API. Please try again.")
    else:
        form = RepoForm()

    return render(request, 'repos/repos_list.html', {'repos': repos, 'form': form})

@editor_required
def repo_detail_view(request, id):
    if request.user.is_platform_admin:
        repo = get_object_or_404(Repo, id=id)
    else:
        repo = get_object_or_404(Repo, id=id, editor=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            repo.delete()
            messages.success(request, "Repository deleted.")
            return redirect('/editor/repos/')
        elif action == 'toggle_active':
            repo.is_active = not repo.is_active
            repo.save()
            messages.success(request, f"Repository {'activated' if repo.is_active else 'deactivated'}.")
            return redirect(f'/editor/repos/{repo.id}/')

    issues = repo.issues.all().order_by('-created_at')
    return render(request, 'repos/repo_detail.html', {'repo': repo, 'issues': issues})

@editor_required
def editor_issues_list_view(request):
    if request.user.is_platform_admin:
        issues = Issue.objects.all().select_related('repo').order_by('-created_at')
    else:
        issues = Issue.objects.filter(posted_by=request.user).select_related('repo').order_by('-created_at')

    if request.method == 'POST':
        issue_id = request.POST.get('issue_id')
        action = request.POST.get('action')
        issue_obj = get_object_or_404(Issue, id=issue_id)
        if not request.user.is_platform_admin and issue_obj.posted_by != request.user:
            messages.error(request, "Permission denied.")
        else:
            if action == 'delete':
                issue_obj.delete()
                messages.success(request, "Issue deleted.")
            elif action == 'toggle_status':
                issue_obj.status = 'closed' if issue_obj.status == 'open' else 'open'
                issue_obj.save()
                messages.success(request, f"Issue marked as {issue_obj.status}.")
        return redirect('/editor/issues/')

    return render(request, 'repos/editor_issues_list.html', {'issues': issues})

@editor_required
def issue_create_view(request):
    if request.method == 'POST':
        form = IssueForm(request.user, request.POST)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.posted_by = request.user
            issue.save()
            form.save_m2m()
            messages.success(request, "Contribution issue published live!")
            return redirect('/editor/issues/')
    else:
        form = IssueForm(request.user)

    return render(request, 'repos/issue_form.html', {'form': form, 'title': 'Post Contribution Opportunity'})

@editor_required
def issue_edit_view(request, id):
    if request.user.is_platform_admin:
        issue = get_object_or_404(Issue, id=id)
    else:
        issue = get_object_or_404(Issue, id=id, posted_by=request.user)

    if request.method == 'POST':
        form = IssueForm(request.user, request.POST, instance=issue)
        if form.is_valid():
            form.save()
            messages.success(request, "Issue updated successfully.")
            return redirect('/editor/issues/')
    else:
        form = IssueForm(request.user, instance=issue)

    return render(request, 'repos/issue_form.html', {'form': form, 'title': 'Edit Issue', 'issue': issue})

BEGINNER_LABELS = ["good first issue", "good-first-issue", "beginner", "easy", "starter"]

def fetch_github_issues_api(owner, repo, github_pat=None):
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_pat:
        headers["Authorization"] = f"token {github_pat}"

    all_issues, seen_ids = [], set()
    for label in BEGINNER_LABELS:
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                params={"labels": label, "state": "open", "per_page": 30},
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            for issue in resp.json():
                if "pull_request" in issue:
                    continue
                if issue["id"] not in seen_ids:
                    seen_ids.add(issue["id"])
                    all_issues.append({
                        "github_id": issue["id"],
                        "title": issue["title"],
                        "body": issue["body"] or "",
                        "url": issue["html_url"],
                        "comments": issue["comments"],
                        "created_at": issue["created_at"],
                        "labels": [l["name"] for l in issue["labels"]],
                    })
        except requests.RequestException:
            continue
    return all_issues

@editor_required
def bulk_import_view(request):
    user_repos = Repo.objects.filter(editor=request.user, is_active=True)
    if request.user.is_platform_admin:
        user_repos = Repo.objects.filter(is_active=True)

    imported_candidates = []
    selected_repo = None

    if request.method == 'GET' and 'repo_id' in request.GET:
        repo_id = request.GET.get('repo_id')
        selected_repo = get_object_or_404(user_repos, id=repo_id)
        owner, repo_name = parse_github_url(selected_repo.github_url)
        if owner and repo_name:
            imported_candidates = fetch_github_issues_api(owner, repo_name)
            if not imported_candidates:
                messages.info(request, "No open beginner issues found on GitHub with standard beginner labels.")

    elif request.method == 'POST':
        repo_id = request.POST.get('repo_id')
        selected_repo = get_object_or_404(user_repos, id=repo_id)
        selected_indices = request.POST.getlist('selected_issues')
        
        count = 0
        all_tags = list(Tag.objects.all())
        default_tag = all_tags[0] if all_tags else None

        for idx in selected_indices:
            title = request.POST.get(f'title_{idx}')
            url = request.POST.get(f'url_{idx}')
            body = request.POST.get(f'body_{idx}', '')
            diff = request.POST.get(f'diff_{idx}', 'beginner')
            hours = request.POST.get(f'hours_{idx}', '2.0')
            
            if title and url:
                if not Issue.objects.filter(github_issue_url=url).exists():
                    new_issue = Issue.objects.create(
                        repo=selected_repo,
                        posted_by=request.user,
                        title=title[:200],
                        description=body[:2000] if body else "No detailed description provided on GitHub.",
                        github_issue_url=url,
                        difficulty=diff,
                        estimated_hours=float(hours or 2.0),
                        status='open'
                    )
                    if default_tag:
                        new_issue.tags.add(default_tag)
                    count += 1

        messages.success(request, f"Successfully imported and published {count} issues to ContribKit!")
        return redirect('/editor/issues/')

    return render(request, 'repos/bulk_import.html', {
        'user_repos': user_repos,
        'selected_repo': selected_repo,
        'candidates': imported_candidates
    })

@editor_required
def editor_analytics_view(request):
    if request.user.is_platform_admin:
        user_issues = Issue.objects.all()
        user_repos = Repo.objects.all()
    else:
        user_issues = Issue.objects.filter(posted_by=request.user)
        user_repos = Repo.objects.filter(editor=request.user)

    total_views = user_issues.aggregate(Sum('view_count'))['view_count__sum'] or 0
    total_saves = SavedIssue.objects.filter(issue__in=user_issues).count()
    top_issues = user_issues.order_by('-view_count')[:5]

    # Views per repo for chart
    repo_stats = user_repos.annotate(
        issue_count=Count('issues'),
        repo_views=Sum('issues__view_count')
    ).values('name', 'issue_count', 'repo_views')

    chart_labels = [r['name'] for r in repo_stats]
    chart_data = [r['repo_views'] or 0 for r in repo_stats]

    return render(request, 'repos/editor_analytics.html', {
        'total_views': total_views,
        'total_saves': total_saves,
        'top_issues': top_issues,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
    })
