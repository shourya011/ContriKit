from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.ai_health_view, name="ai_health"),
    path("chat/", views.ai_chat_view, name="ai_chat"),
]
