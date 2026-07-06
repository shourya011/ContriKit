from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/accounts/login/')
        if request.user.role != 'admin' and not request.user.is_superuser:
            messages.error(request, "Admin access required.")
            return redirect('/')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def editor_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/accounts/login/')
        if request.user.role not in ('editor', 'admin') and not request.user.is_superuser:
            messages.error(request, "Editor access required.")
            return redirect('/')
        return view_func(request, *args, **kwargs)
    return _wrapped_view