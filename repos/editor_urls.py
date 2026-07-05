from django.urls import path
from . import views

urlpatterns = [
    path('repos/', views.repos_list_view, name='editor_repos'),
    path('repos/<int:id>/', views.repo_detail_view, name='editor_repo_detail'),
    path('issues/', views.editor_issues_list_view, name='editor_issues'),
    path('issues/create/', views.issue_create_view, name='editor_issue_create'),
    path('issues/edit/<int:id>/', views.issue_edit_view, name='editor_issue_edit'),
    path('issues/import/', views.bulk_import_view, name='editor_bulk_import'),
    path('analytics/', views.editor_analytics_view, name='editor_analytics'),
]
