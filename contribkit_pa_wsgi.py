# This file contains the exact WSGI configuration for PythonAnywhere.
# Replace the contents of the generated /var/www/<username>_pythonanywhere_com_wsgi.py file with this:

import os
import sys

# Assuming your project is cloned to /home/<username>/contribkit
path = os.path.expanduser('~/contribkit')
if path not in sys.path:
    sys.path.append(path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'contribkit.settings.prod'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
