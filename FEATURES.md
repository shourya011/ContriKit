# ContribKit — Implemented Features

A complete inventory of features currently implemented in the codebase (Django 5/6, Bootstrap 5, WhiteNoise, PythonAnywhere WSGI).

Live deploy: [https://shouryano01.pythonanywhere.com/](https://shouryano01.pythonanywhere.com/)

---

## 1. Product overview

**ContribKit** is an open-source contribution bridge between maintainers (“Editors”) and first-time contributors (“Viewers”).

- Maintainers post structured beginner opportunities with difficulty, estimated hours, tags, and GitHub links.
- Beginners discover curated starter issues, copy-paste repo templates, and searchable Git workflows — without getting lost in large unfamiliar codebases.

---

## 2. Roles & access control

Three roles on the custom `accounts.User` model (`AbstractUser`):

| Role | Default | What they can do |
| --- | --- | --- |
| **Viewer** | New signups | Browse issues/templates/cheatsheet, bookmark issues, use dashboard, self-upgrade to Editor |
| **Editor** | Self-upgrade (no approval) | Everything a Viewer can, plus link repos, post/edit/delete own issues, bulk-import GitHub issues, view repo analytics. Can switch back to Viewer without data loss |
| **Admin** | Superusers auto-assigned | Full moderation suite (`/admin-panel/…`) plus Django admin. Cannot be demoted via “switch to Viewer” |

Decorators:

- `@login_required` — dashboard, saved issues, role switch
- `@editor_required` — `/editor/*` (editors + admins)
- `@admin_required` — `/admin-panel/*` (admins + superusers)

Navbar context (`core.context_processors.role_context`) exposes `is_viewer`, `is_editor`, `is_platform_admin`, and `user_role_label` on every page.

---

## 3. Public site

### Landing page (`/`)

- Hero with CTAs to issues and templates
- Live aggregated counts: open issues, templates, active repos
- Featured issues grid (falls back to latest open issues if none are featured)
- Featured template preview (first 3) with one-click copy
- Git cheat sheet teaser with copyable example commands
- About section with live platform stats
- Maintainer CTA banner (hidden when logged in)
- AJAX save/unsave on featured issue cards for authenticated users

### Issue board (`/issues/`)

- Open issues only, newest first
- Multi-field keyword search (`title`, `description`, `repo.name`)
- Filters: language, difficulty (`beginner` / `intermediate`), tech tag
- Pagination (12 per page) that preserves filter query params
- Cards show repo, featured badge, difficulty, language, colored tags, estimated hours
- AJAX bookmark toggle (login redirect if anonymous)
- Direct “Open on GitHub” link
- Empty-state with reset-filters CTA
- Editors see a “Post New Issue” shortcut

### Issue detail (`/issues/<id>/`)

- Full description, tags, difficulty, hours, view count, featured badge
- Session-scoped view counting (increments once per session per issue)
- Save/unsave AJAX
- “Open on GitHub” CTA
- Linked repository sidebar (stars, language, description, GitHub URL)
- Poster username + date
- Related repository-standard templates
- Shortcut to Git cheat sheet

### Template library (`/templates/`)

Copy-paste-ready markdown for GitHub repos, grouped into categories:

- Community Health
- Documentation
- Contributing
- Issue Templates
- Pull Request Templates
- GitHub Configuration
- GitHub Issue Forms
- GitHub Discussions

Features:

- Search by title, category, tags, description (debounced auto-submit)
- Category filter
- Sort: by category, alphabetical, newest
- Result count
- Card preview auto-generated from first content lines
- One-click clipboard copy from the grid

### Template detail (`/templates/<slug>/`)

- Syntax-highlighted markdown (highlight.js)
- Copy to clipboard
- Download as `.md` file (Blob download)
- Sidebar: category, tags, character count, last updated
- Related templates in the same category (up to 3)
- Breadcrumb navigation

### Git cheat sheet (`/cheatsheet/`)

- 30+ commands (seeded) grouped into:
  1. Setup & Configuration
  2. Daily Workflow & Staging
  3. Branching & Switching
  4. Pull Requests & Syncing
  5. Undoing Mistakes & Stashing
- Instant client-side search across command, description, and example
- Clear-search button
- Per-command copy button
- Empty / no-results states

### Custom error pages

- `403.html` — permission denied, with dashboard/home links
- `404.html` — not found, with home/issues links
- `500.html` — internal server error

---

## 4. Authentication & accounts

### Local auth (`/accounts/`)

- Signup (`CustomUserCreationForm`): username, required email, optional GitHub username, password validators (min 8, similarity, common, numeric)
- Login (`CustomAuthenticationForm`) with Bootstrap-styled fields; authenticated users are redirected away
- Logout (POST) → home
- Password change + confirmation page
- Password reset URLs are present but commented out until an email backend is configured

### Sign in with Google (OAuth 2.0)

Handled by `social-auth-app-django`:

- Start: `POST /login/google-oauth2/`
- Callback: `/complete/google-oauth2/`
- Scopes: OpenID, email, profile
- Pipeline includes `associate_by_email` so an existing account with the same verified Google email is linked instead of duplicated
- Failures/cancellations redirect to login with a flash message (`SOCIAL_AUTH_RAISE_EXCEPTIONS = False`)
- New Google users land as **Viewer** on `/dashboard/`
- Production forces HTTPS redirect URIs (`SOCIAL_AUTH_REDIRECT_IS_HTTPS`)

### Login lockout (django-axes)

- 5 failed attempts → 30-minute cool-off
- Counter resets on successful login
- Custom lockout template (`registration/locked_out.html`)
- Reverse-proxy IP support in production (`X-Forwarded-For`)

### User profile fields

`github_username`, `bio`, `avatar_url`, plus Django’s built-in user fields. Superusers are forced to `role=admin` on save.

---

## 5. Contributor dashboard

### Dashboard (`/dashboard/`, login required)

- Greeting + role badge
- Stats: saved issues, tracked repos, open opportunities, posted issues (editors)
- Preview of 4 most recently saved issues
- Quick nav to issues, templates, cheat sheet
- **Become an Editor** modal (viewers) — instant upgrade, no approval
- **Editor Hub** shortcut (editors)

### Saved issues (`/dashboard/saved/`)

- Full list of bookmarked issues
- AJAX unsave removes the card in-place and shows an empty state when the list is empty

### Role switch (`POST /dashboard/switch-role/`)

- Viewer → Editor (redirects to `/editor/repos/`)
- Editor → Viewer (admins/superusers cannot demote themselves this way)
- Editor data (repos, posted issues) is preserved when switching down

---

## 6. Editor / maintainer hub (`/editor/`, editor required)

### Repositories (`/editor/repos/`)

- List own repos (admins see all)
- Paste a public GitHub URL → live `api.github.com` lookup
- Auto-fills: full name, stars, primary language, description
- Handles invalid URL, 404, rate-limit (403), and network timeout
- Unique `github_url` constraint

### Repo detail (`/editor/repos/<id>/`)

- Ownership-scoped (admins can open any)
- Toggle active/inactive
- Delete repo (cascades issues)
- List of issues on that repo

### Posted issues (`/editor/issues/`)

- List own issues (admins see all)
- Toggle open/closed
- Delete
- Create (`/editor/issues/create/`) and edit (`/editor/issues/edit/<id>/`)
- Form fields: repo (limited to the editor’s active repos unless admin), title, description, GitHub issue URL, difficulty, estimated hours, status, multi-select tags

### Bulk GitHub import (`/editor/issues/import/`)

- Pick a linked active repo
- Fetches open issues labeled `good first issue`, `good-first-issue`, `beginner`, `easy`, or `starter`
- Skips pull requests and de-duplicates by GitHub issue id
- Human review: select candidates, adjust title/difficulty/hours, then publish
- Skips URLs already imported
- Optional GitHub PAT support in the fetch helper for higher rate limits

### Editor analytics (`/editor/analytics/`)

- Total views (sum of issue `view_count`)
- Total bookmark saves
- Top 5 issues by views
- Chart.js bar chart of views per repository

---

## 7. Admin panel (`/admin-panel/`, admin required)

Custom UI (separate from Django admin):

| Screen | Capabilities |
| --- | --- |
| **Users** | List all users; change role; activate/deactivate; superusers cannot be modified by non-superusers |
| **Issues** | Moderate all issues; delete; toggle ⭐ Featured |
| **Templates** | Create / edit / delete library files |
| **Cheat sheet** | CRUD sections and commands |
| **Analytics** | Totals (users, repos, issues, templates) + Chart.js pie of role distribution |

Navbar admin dropdown also links to the raw Django admin (`/admin/`).

Django admin registrations exist for User (custom fieldsets), Tag, Issue, SavedIssue, Repo, Template, cheat sheet models.

---

## 8. Data model highlights

- **User** — roles, GitHub username, bio, avatar
- **Repo** — editor, unique GitHub URL, name, language, stars, description, `is_active`
- **Tag** — unique name/slug + color
- **Issue** — repo, poster, title, description, GitHub URL, difficulty, estimated hours, status, featured flag, view count, M2M tags
- **SavedIssue** — unique `(user, issue)` bookmark
- **Template** — title, slug, category, description, content, comma-separated tags, creator, timestamps; `preview` and `tag_list` helpers
- **CheatSheetSection / CheatSheetCommand** — ordered sections and commands with examples

---

## 9. UI / frontend

- Custom design system: CSS variables, base, navbar, hero, cards, footer, responsive
- Inter + JetBrains Mono fonts, Bootstrap 5.3, Bootstrap Icons
- Sticky navbar with scroll state, desktop + mobile menus, issue search in the nav
- Role badges and role-specific dropdowns (Admin / Editor / user)
- Flash messages + toast notifications (save, copy, errors)
- Clipboard copy with “Copied!” feedback
- Chart.js on analytics pages
- highlight.js on template detail
- Tooltips, empty states, breadcrumbs, pagination

---

## 10. Security

- CSRF on all mutating forms; AJAX save sends `X-CSRFToken`
- Session cookies: HTTP-only, SameSite=Lax, 2-week age; Secure in production
- CSRF cookie SameSite=Lax (readable by JS for AJAX)
- `X-Frame-Options: DENY`, `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY=same-origin`
- Custom **CSP middleware**:
  - Allows Bootstrap, Chart.js, highlight.js CDNs
  - `connect-src` includes `https://api.github.com`
  - `frame-ancestors 'none'`, `object-src 'none'`
  - `form-action` includes `'self'` **and** `https://accounts.google.com` so Chrome/Safari follow the Google OAuth redirect chain
- Permissions-Policy disables camera, mic, geolocation, payment, USB, sensors
- Production: SSL redirect, HSTS (1 year, includeSubDomains, preload), secure cookies, trusted proxy header
- Upload size cap 5 MB
- Axes brute-force protection (see §4)
- Secrets via `.env` / `python-decouple` — never committed (`SECRET_KEY`, Google OAuth client id/secret, DB credentials)

---

## 11. DevOps, seeding & tests

### Settings split

- `contribkit.settings.dev` — DEBUG, SQLite, `ALLOWED_HOSTS=*`
- `contribkit.settings.prod` — env-driven secret, SQLite or MySQL, WhiteNoise-ready static storage, HTTPS, logging, Axes behind reverse proxy
- `manage.py` defaults to dev; PythonAnywhere WSGI (`contribkit_pa_wsgi.py`) forces prod

### Seeding (`python manage.py seed_data`)

Idempotent demo data:

- Users: `admin` / `demo_editor` / `demo_viewer` with known passwords
- 8 tech tags (Python, JavaScript, TypeScript, Django, React, CSS/HTML, Documentation, Testing)
- 4 sample repos (Django, Bootstrap, Flask, React)
- 10 beginner/intermediate issues (some featured)
- Saved issues for the demo viewer
- Templates loaded from `templates_app/data/seed_data.json`
- 5 cheat sheet sections / 30+ Git commands

### Tests & smoke checks

- `python test_all_routes.py` — HTTP 200 smoke tests across public, viewer, editor, and admin routes
- `core/tests.py` — CSP `form-action` tests + full Google OAuth round trip (token/userinfo mocked): create user, login session, no duplicate on second login

### Dependencies

Django 5.x–6.x, requests, WhiteNoise, python-decouple, django-axes, social-auth-app-django.

---

## 12. Route map

| Path | Feature |
| --- | --- |
| `/` | Landing |
| `/issues/` | Issue board |
| `/issues/<id>/` | Issue detail |
| `/issues/<id>/toggle-save/` | AJAX bookmark |
| `/templates/` | Template library |
| `/templates/<slug>/` | Template detail |
| `/cheatsheet/` | Git cheat sheet |
| `/accounts/signup/` | Signup |
| `/accounts/login/` | Login |
| `/accounts/logout/` | Logout |
| `/accounts/password-change/` | Password change |
| `/login/google-oauth2/` | Google OAuth start |
| `/complete/google-oauth2/` | Google OAuth callback |
| `/dashboard/` | User dashboard |
| `/dashboard/saved/` | Saved issues |
| `/dashboard/switch-role/` | Viewer ↔ Editor |
| `/editor/repos/` | Link & list repos |
| `/editor/repos/<id>/` | Repo detail |
| `/editor/issues/` | Manage posted issues |
| `/editor/issues/create/` | Post issue |
| `/editor/issues/edit/<id>/` | Edit issue |
| `/editor/issues/import/` | Bulk GitHub import |
| `/editor/analytics/` | Editor analytics |
| `/admin-panel/users/` | User moderation |
| `/admin-panel/issues/` | Issue moderation |
| `/admin-panel/templates/` | Template CRUD |
| `/admin-panel/cheatsheet/` | Cheat sheet CRUD |
| `/admin-panel/analytics/` | Platform analytics |
| `/admin/` | Django admin |

---

*This document reflects features present in the repository as of the current `main` snapshot.*
