from django.urls import path
from . import views

urlpatterns = [
    path('', views.template_list_view, name='template_list'),
    path('<slug:slug>/', views.template_detail_view, name='template_detail'),
]
