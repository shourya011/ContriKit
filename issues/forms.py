from django import forms

from .models import Repo


class RepoForm(forms.ModelForm):
    """Admin-facing form for adding a tracked GitHub repository."""

    name = forms.CharField(required=False)
    language = forms.CharField(required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    stars = forms.IntegerField(required=False, initial=0)

    class Meta:
        model = Repo
        fields = ('github_url', 'name', 'language', 'stars', 'description', 'is_active')
        widgets = {
            'github_url': forms.URLInput(
                attrs={'class': 'form-control', 'placeholder': 'https://github.com/owner/repo'}
            ),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'owner/repo'}),
            'language': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_github_url(self):
        url = (self.cleaned_data['github_url'] or '').strip().rstrip('/')
        if 'github.com' not in url:
            raise forms.ValidationError('Enter a github.com repository URL.')
        parts = [part for part in url.split('github.com/', 1)[-1].split('/') if part]
        if len(parts) < 2:
            raise forms.ValidationError('Use the form https://github.com/owner/repository.')
        return url
