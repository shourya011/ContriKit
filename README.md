# ContribKit — Open Source Contribution Bridge

> **The bridge between open-source maintainers and first-time contributors.**  
> Built with Django 5/6, Bootstrap 5, WhiteNoise, and PythonAnywhere WSGI serving.

---

## Product Overview

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

## Platform Screens & Walkthrough

- **Landing Page (`/`)**: High-impact hero CTA, live aggregated database counts (Issues, Templates, Active Repos), and featured opportunities grid.
- **Maintainer Hub (`/dashboard/` & `/editor/repos/`)**: Role switching badges, AJAX bookmark previews, and instant GitHub URL validation.
- **Analytics Dashboards (`/editor/analytics/` & `/admin-panel/analytics/`)**: Visual Chart.js metrics tracking total session views, bookmark save conversions, and role distributions.

---

## Local Development Setup

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


   Added Deploy Link:- https://shouryano01.pythonanywhere.com/
