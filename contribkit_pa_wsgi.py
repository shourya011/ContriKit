# PythonAnywhere WSGI configuration for ContribKit.
#
# Copy this file's contents into the WSGI file PythonAnywhere generated for
# your web app (/var/www/<username>_pythonanywhere_com_wsgi.py), or keep this
# file in the project and point the web app at it. The project path defaults
# to ~/contribkit; override it with CONTRIKIT_PROJECT_DIR if you cloned the
# repository somewhere else (for example ~/mysite).

import os
import sys

PROJECT_DIR = os.environ.get(
    "CONTRIKIT_PROJECT_DIR",
    os.path.expanduser("~/contribkit"),
)
if not os.path.isdir(PROJECT_DIR):
    # The file may be copied outside the project, so __file__ is not a
    # reliable fallback. Fail loudly instead of serving 404s from the
    # default PythonAnywhere placeholder app.
    raise RuntimeError(
        f"ContribKit project not found at {PROJECT_DIR!r}. Set the "
        "CONTRIKIT_PROJECT_DIR environment variable (or edit this file) to "
        "the directory containing manage.py, then reload the web app."
    )

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ["DJANGO_SETTINGS_MODULE"] = "contribkit.settings.prod"

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
