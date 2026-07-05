from django.contrib import admin
from django.urls import path, include
from core import views as core_views

urlpatterns = [
    # Built-in django admin renamed to /django-admin/ per spec
    path('django-admin/', admin.site.urls),
    
    # Landing page & Dashboard
    path('', core_views.landing_page, name='landing'),
    path('dashboard/', core_views.dashboard_view, name='dashboard'),
    path('dashboard/saved/', core_views.saved_issues_list_view, name='saved_issues'),
    path('dashboard/switch-role/', core_views.switch_role_view, name='switch_role'),
    
    # Auth
    path('accounts/', include('accounts.urls')),
    
    # Apps
    path('issues/', include('issues.urls')),
    path('templates/', include('templates_app.urls')),
    path('cheatsheet/', include('cheatsheet.urls')),
    path('editor/', include('repos.editor_urls')),
    path('admin-panel/', include('core.admin_panel_urls')),
]
