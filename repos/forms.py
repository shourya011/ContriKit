from django import forms
from .models import Repo

class RepoForm(forms.ModelForm):
    github_url = forms.URLField(
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://github.com/owner/repo'}),
        help_text="Paste a GitHub repository URL. We will validate it and auto-fill details."
    )

    class Meta:
        model = Repo
        fields = ('github_url',)
