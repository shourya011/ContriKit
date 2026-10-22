"""OAuth backends that surface configuration problems on the login page."""

from social_core.backends.github import GithubOAuth2
from social_core.exceptions import AuthMissingParameter


class ConfiguredGithubOAuth2(GithubOAuth2):
    """GitHub backend that refuses to start without explicit credentials."""

    def start(self):
        if not self.setting('KEY'):
            raise AuthMissingParameter(self, 'GITHUB_OAUTH2_CLIENT_ID')
        if not self.setting('SECRET'):
            raise AuthMissingParameter(self, 'GITHUB_OAUTH2_CLIENT_SECRET')
        return super().start()
