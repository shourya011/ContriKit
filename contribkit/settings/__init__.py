import os

if os.environ.get('DJANGO_SETTINGS_MODULE') == 'contribkit.settings.prod':
    from .prod import *
else:
    from .dev import *
