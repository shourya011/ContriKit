import os
import django
from django.test import Client

os.environ['DJANGO_SETTINGS_MODULE'] = 'contribkit.settings.dev'
django.setup()

from accounts.models import User
from issues.models import Issue
from repos.models import Repo
from templates_app.models import Template

def run_tests():
    c = Client()
    print("--- 1. Testing Public Routes ---")
    routes = [
        ('/', 'Landing Page'),
        ('/issues/', 'Issues Board'),
        ('/templates/', 'Template Library Grid'),
        ('/cheatsheet/', 'Git Cheat Sheet'),
        ('/accounts/login/', 'Login Page'),
        ('/accounts/signup/', 'Signup Page'),
    ]
    for url, name in routes:
        resp = c.get(url)
        assert resp.status_code == 200, f"Failed {name} ({url}): {resp.status_code}"
        print(f"✓ [{resp.status_code}] {name}")

    tmpl = Template.objects.first()
    if tmpl:
        url = f"/templates/{tmpl.slug}/"
        resp = c.get(url)
        assert resp.status_code == 200
        print(f"✓ [200] Template Detail ({tmpl.slug})")

    issue = Issue.objects.first()
    if issue:
        url = f"/issues/{issue.id}/"
        resp = c.get(url)
        assert resp.status_code == 200
        print(f"✓ [200] Issue Detail ({issue.title[:30]}...)")

    print("\n--- 2. Testing Authenticated Viewer Routes ---")
    viewer = User.objects.get(username="demo_viewer")
    c.force_login(viewer)
    resp = c.get('/dashboard/')
    assert resp.status_code == 200
    print("✓ [200] Viewer Dashboard")
    resp = c.get('/dashboard/saved/')
    assert resp.status_code == 200
    print("✓ [200] Saved Issues List")

    print("\n--- 3. Testing Authenticated Editor Routes ---")
    editor = User.objects.get(username="demo_editor")
    c.force_login(editor)
    editor_routes = [
        ('/editor/repos/', 'Manage Repos'),
        ('/editor/issues/', 'Manage Posted Issues'),
        ('/editor/issues/create/', 'Post Issue Form'),
        ('/editor/issues/import/', 'Bulk Import Page'),
        ('/editor/analytics/', 'Editor Analytics'),
    ]
    for url, name in editor_routes:
        resp = c.get(url)
        assert resp.status_code == 200, f"Failed {name} ({url}): {resp.status_code}"
        print(f"✓ [{resp.status_code}] {name}")

    repo = Repo.objects.first()
    if repo:
        resp = c.get(f"/editor/repos/{repo.id}/")
        assert resp.status_code == 200
        print(f"✓ [200] Repo Detail ({repo.name})")

    print("\n--- 4. Testing Authenticated Admin Panel Routes ---")
    admin = User.objects.get(username="admin")
    c.force_login(admin)
    admin_routes = [
        ('/admin-panel/users/', 'Manage Users'),
        ('/admin-panel/issues/', 'Moderate Issues'),
        ('/admin-panel/templates/', 'Template CRUD'),
        ('/admin-panel/cheatsheet/', 'Cheat Sheet CRUD'),
        ('/admin-panel/analytics/', 'Platform Analytics'),
    ]
    for url, name in admin_routes:
        resp = c.get(url)
        assert resp.status_code == 200, f"Failed {name} ({url}): {resp.status_code}"
        print(f"✓ [{resp.status_code}] {name}")

    print("\n🎉 ALL ROUTES RESOLVED SUCCESSFULLY WITH HTTP 200 OK!")

if __name__ == '__main__':
    run_tests()
