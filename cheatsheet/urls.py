from django.urls import path
from . import views

urlpatterns = [
    path('', views.cheatsheet_view, name='cheatsheet'),
]
