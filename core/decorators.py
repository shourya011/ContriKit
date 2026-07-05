from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import UserPassesTestMixin

def viewer_required(view_func):
    """Viewers are default logged-in users."""
    return user_passes_test(lambda u: u.is_authenticated)(view_func)

def editor_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_editor)(view_func)

def admin_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_platform_admin)(view_func)

class EditorRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_editor

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_platform_admin
