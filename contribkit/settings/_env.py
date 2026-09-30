"""Single, deterministic python-decouple configuration for ContribKit.

Why this module exists
----------------------
``decouple.config`` is a process-wide ``AutoConfig()`` that guesses where
``.env`` lives from the *caller's* module path at the first ``config(...)``
call. That heuristic is fragile:

- on Windows (especially inside OneDrive paths),
- when the server is started from a different working directory,
- when another ``.env`` or ``settings.ini`` exists closer to the settings
  package than the project root,

it can silently read the wrong file — or no file at all — while ``.env`` next
to ``manage.py`` looks perfect.

Every settings module therefore uses the ``config`` defined here, which is
always bound to ``BASE_DIR/.env`` (the project root, i.e. the folder
containing ``manage.py``). Values in the process environment STILL win:
python-decouple checks ``os.environ`` first by design, so exported variables
keep overriding ``.env`` (that precedence is documented and intentional).
"""

from pathlib import Path

from decouple import Config, RepositoryEmpty, RepositoryEnv

# Project root: <repo>/contribkit/settings/_env.py -> <repo>
BASE_DIR = Path(__file__).resolve().parent.parent.parent

ENV_FILE = BASE_DIR / ".env"

# Recorded when the .env file exists but cannot be parsed, so
# `python manage.py ai_env` / `manage.py check` can explain it.
ENV_FILE_ERROR = None

if ENV_FILE.is_file():
    try:
        config = Config(RepositoryEnv(str(ENV_FILE)))
    except (OSError, UnicodeDecodeError) as exc:  # e.g. UTF-16 encoded file
        config = Config(RepositoryEmpty())
        ENV_FILE_ERROR = f"{type(exc).__name__}: {exc}"
else:
    config = Config(RepositoryEmpty())
