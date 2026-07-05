from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from .forms import CustomUserCreationForm

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('/dashboard/')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome to ContribKit, {user.username}! You are signed up as a Viewer.")
            return redirect('/dashboard/')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/signup.html', {'form': form})
