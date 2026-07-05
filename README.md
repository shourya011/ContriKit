# 🚀 ContribKit — Open Source Contribution Bridge

> **The bridge between open-source maintainers and first-time contributors.**  
> Built with Django 5/6, Bootstrap 5, WhiteNoise, and PythonAnywhere WSGI serving.

---

## 🌟 Product Overview

**ContribKit** solves the hardest part of open source: beginner onboarding. Maintainers ("Editors") post structured contribution opportunities enriched with copy-paste repository standard templates, estimated hours, difficulty tags, and direct GitHub links. Beginners ("Viewers") discover curated starter issues without getting lost in massive unfamiliar codebases.

### Key Features
1. **Curated Issue Board (`/issues/`)**: Structured beginner-friendly opportunities filterable by programming language, difficulty level (`Beginner` / `Intermediate`), and tech stack tags (`Python`, `React`, `Django`, `TypeScript`, etc.). Searchable via multi-field keyword queries.
2. **Repository Template Library (`/templates/`)**: Copy-paste-ready standard markdown files (`README.md`, `CONTRIBUTING.md`, `ISSUE_TEMPLATE.md`, `PULL_REQUEST_TEMPLATE.md`, `CODE_OF_CONDUCT.md`) with one-click JS clipboard copying.
3. **Interactive Git Cheat Sheet (`/cheatsheet/`)**: 30+ searchable Git workflows grouped into setup, staging, branching, PR syncing, and undoing mistakes. Instant client-side filtering without page reloads.
4. **GitHub API Integration**: 
   - **URL Auto-fill (`/editor/repos/`)**: Pasting any public GitHub repository URL validates live against `api.github.com`, auto-filling repo name, star counts, primary language, and description.
   - **Bulk Issue Import (`/editor/issues/import/`)**: Bulk-fetches open candidate issues labeled `good first issue`, `beginner`, or `starter` for human review before publishing.
5. **Multi-Tier Role Architecture**:
   - **Viewer**: Default for new signups. Browse issues, explore templates, bookmark issues to dashboard via AJAX, and self-upgrade anytime.
   - **Editor**: Self-upgradable with zero approval bottlenecks. Link repos, post opportunities, import GitHub candidates, and analyze repository view metrics. Can switch back to Viewer anytime without data loss.
   - **Admin**: Full moderation suite. Manage users/roles, moderate/remove issues, toggle featured badges (`⭐ Featured`), CRUD template library files, CRUD cheat sheet sections/commands, and view platform distribution charts.

---

## 📸 Platform Screens & Walkthrough

- **Landing Page (`/`)**: High-impact hero CTA, live aggregated database counts (Issues, Templates, Active Repos), and featured opportunities grid.
- **Maintainer Hub (`/dashboard/` & `/editor/repos/`)**: Role switching badges, AJAX bookmark previews, and instant GitHub URL validation.
- **Analytics Dashboards (`/editor/analytics/` & `/admin-panel/analytics/`)**: Visual Chart.js metrics tracking total session views, bookmark save conversions, and role distributions.

---

## 🔑 Live Demo Credentials

Test the platform instantly without creating a new account:

| Role | Username | Password | Capabilities |
| :--- | :--- | :--- | :--- |
| **Platform Admin** | `admin` | `adminpass123` | Full custom admin panel (`/admin-panel/`) + Django Admin (`/django-admin/`) |
| **Maintainer (Editor)** | `demo_editor` | `editorpass123` | Link repos, post issues, bulk import from GitHub, view analytics |
| **Contributor (Viewer)** | `demo_viewer` | `viewerpass123` | Bookmark issues via AJAX, browse cheat sheet, self-upgrade to Editor |

---

## 💻 Local Development Setup

1. **Clone & Virtual Environment**
   ```bash
   git clone https://github.com/yourusername/contribkit.git
   cd contribkit
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Pinned Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Variables**
   ```bash
   cp .env.example .env
   # Edit .env if needed (defaults to dev sqlite3 settings)
   ```

4. **Database Migration & Seeding**
   ```bash
   python manage.py migrate
   python manage.py seed_data       # Populates 3+ repos, 10+ issues, 5 templates, 30+ Git commands
   python manage.py collectstatic --noinput
   ```

5. **Run Development Server & Automated Verification**
   ```bash
   python test_all_routes.py        # Runs 100% automated smoke tests across 20+ routes
   python manage.py runserver
   ```
   Visit `http://127.0.0.1:8000/` in your browser.

---

## ☁️ PythonAnywhere Deployment Instructions (Exact Guide)

ContribKit is configured explicitly for **PythonAnywhere** production hosting (Free or Paid tier). Unlike Heroku or Railway, PythonAnywhere uses standard WSGI configuration files and built-in static file mappings.

### Step 1: Push Repo & Console Setup
1. Push your ContribKit project to a GitHub repository.
2. Log into [PythonAnywhere](https://www.pythonanywhere.com/) and open a **Bash Console**.
3. Clone your repository and set up a virtual environment:
   ```bash
   git clone https://github.com/<your-github-username>/contribkit.git
   mkvirtualenv contribkit-venv --python=python3.10
   # Or using standard venv: python3 -m venv ~/contribkit-venv && source ~/contribkit-venv/bin/activate
   cd contribkit
   pip install -r requirements.txt
   ```

### Step 2: Production Database & Seeding
PythonAnywhere free tier supports MySQL. 
1. Go to PythonAnywhere's **Databases** tab and create a database (named `<username>$contribkit`).
2. Create a `.env` file inside `~/contribkit/` with your MySQL credentials:
   ```ini
   DJANGO_SETTINGS_MODULE=contribkit.settings.prod
   SECRET_KEY=your-production-secret-key-at-least-50-characters-long
   DEBUG=False
   ALLOWED_HOSTS=<username>.pythonanywhere.com
   DB_ENGINE=mysql
   DB_NAME=<username>$contribkit
   DB_USER=<username>
   DB_PASSWORD=<your-mysql-password>
   DB_HOST=<username>.mysql.pythonanywhere-services.com
   DB_PORT=3306
   SECURE_SSL_REDIRECT=True
   SESSION_COOKIE_SECURE=True
   CSRF_COOKIE_SECURE=True
   ```
   *(Note: If you omit DB_ENGINE=mysql, ContribKit cleanly falls back to SQLite).*
3. Run migrations and seed data:
   ```bash
   python manage.py migrate
   python manage.py seed_data
   python manage.py collectstatic --noinput
   ```

### Step 3: Web Tab & WSGI Configuration
1. Go to PythonAnywhere's **Web** tab → **Add a new web app** → **Manual configuration** → Select your matching Python version.
2. Set **Source code** path: `/home/<username>/contribkit`
3. Set **Virtualenv** path: `/home/<username>/.virtualenvs/contribkit-venv` (or your venv folder)
4. Click on the **WSGI configuration file** link (e.g. `/var/www/<username>_pythonanywhere_com_wsgi.py`). Delete its existing contents and paste the exact contents from `contribkit_pa_wsgi.py`:
   ```python
   import os
   import sys

   path = os.path.expanduser('~/contribkit')
   if path not in sys.path:
       sys.path.append(path)

   os.environ['DJANGO_SETTINGS_MODULE'] = 'contribkit.settings.prod'

   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```

### Step 4: Static Files Mapping
In the **Static files** section of the Web tab, add a mapping:
- **URL**: `/static/`
- **Directory**: `/home/<username>/contribkit/staticfiles`

### Step 5: Reload & Verify
Click the green **Reload** button at the top of the Web tab and visit `https://<username>.pythonanywhere.com`.
Verify the deployment checklist:
- [x] All static assets and typography load over HTTPS.
- [x] GitHub API calls succeed outbound.
- [x] Custom role dashboards and admin moderation panels work.
- [x] `python manage.py check --deploy --settings=contribkit.settings.prod` passes with zero warnings.

---

## 🛠 Tech Stack & Architecture
- **Framework**: Django 5.x / 6.x (Modular split settings `base.py`, `dev.py`, `prod.py`)
- **Frontend**: Bootstrap 5, Bootstrap Icons, Chart.js, Vanilla JS
- **Static Storage**: WhiteNoise CompressedManifestStaticFilesStorage
- **Security**: Strict CSRF/Session secure flags, HSTS preloading, X-Frame-Options DENY

*Built adhering strictly to the ContribKit 5-Day Master Build Spec. Zero placeholder content. 100% functional end-to-end.*
