def role_context(request):
    user = request.user
    if user.is_authenticated:
        return {
            'is_viewer': user.is_viewer,
            'is_editor': user.is_editor,
            'is_platform_admin': user.is_platform_admin,
            'user_role_label': dict(user.ROLE_CHOICES).get(user.role, "Viewer"),
        }
    return {
        'is_viewer': False,
        'is_editor': False,
        'is_platform_admin': False,
        'user_role_label': None,
    }
