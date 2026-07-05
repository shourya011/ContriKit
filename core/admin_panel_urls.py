from django.urls import path
from . import admin_panel_views as views

urlpatterns = [
    path('users/', views.admin_users_view, name='admin_users'),
    path('issues/', views.admin_issues_view, name='admin_issues'),
    path('templates/', views.admin_templates_view, name='admin_templates'),
    path('cheatsheet/', views.admin_cheatsheet_view, name='admin_cheatsheet'),
    path('analytics/', views.admin_analytics_view, name='admin_analytics'),
]
