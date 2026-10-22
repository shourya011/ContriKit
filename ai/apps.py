from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai'

    def ready(self):
        # Registers the "no provider credentials" system check so runserver /
        # manage.py check explain why the assistant answers nothing.
        from . import checks  # noqa: F401
