from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import CustomAuthenticationForm

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        authentication_form=CustomAuthenticationForm,
        redirect_authenticated_user=True
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),

    # Password change
    path('password-change/', auth_views.PasswordChangeView.as_view(
        template_name='registration/password_change_form.html',
        success_url='/accounts/password-change/done/'
    ), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='registration/password_change_done.html'
    ), name='password_change_done'),

    # Password reset (disabled by default; uncomment when email backend is configured)
    # path('password-reset/', auth_views.PasswordResetView.as_view(
    #     template_name='registration/password_reset_form.html',
    #     email_template_name='registration/password_reset_email.html',
    #     subject_template_name='registration/password_reset_subject.txt',
    #     success_url='/accounts/password-reset/done/'
    # ), name='password_reset'),
    # path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
    #     template_name='registration/password_reset_done.html'
    # ), name='password_reset_done'),
    # path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
    #     template_name='registration/password_reset_confirm.html',
    #     success_url='/accounts/password-reset/complete/'
    # ), name='password_reset_confirm'),
    # path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
    #     template_name='registration/password_reset_complete.html'
    # ), name='password_reset_complete'),
]
