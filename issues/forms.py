from django import forms
from .models import Issue, Tag

class IssueForm(forms.ModelForm):
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
        help_text="Hold Ctrl/Cmd to select multiple tech tags."
    )

    class Meta:
        model = Issue
        fields = ('repo', 'title', 'description', 'github_issue_url', 'difficulty', 'estimated_hours', 'status', 'tags')
        widgets = {
            'repo': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Add validation to search form'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': '5', 'placeholder': 'Provide clear context and steps for the beginner...'}),
            'github_issue_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://github.com/owner/repo/issues/123'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            'estimated_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'placeholder': '2.0'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit repos to user's repos if not admin
        if not user.is_platform_admin:
            self.fields['repo'].queryset = user.repos.filter(is_active=True)
