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
   python manage.py test            # Unit tests, incl. the full Google OAuth round trip
   python manage.py runserver
   ```
   Visit `http://127.0.0.1:8000/` in your browser.


   Added Deploy Link:- https://shouryano01.pythonanywhere.com/ 

---

## AI Contribution Assistant (LLM setup)

The floating assistant (`templates/ai/widget.html` + `static/js/ai_chat.js`) talks
to **your own server only**, via `POST /ai/chat/`. The server then calls **Groq**
— `AI_GROQ_API_KEY` lives in `.env` and never reaches the browser. Groq is the
only LLM backend; OpenAI, Gemini, and Anthropic are not used.

**With no Groq key the assistant cannot work, and it fails quietly:** `/ai/chat/`
answers `503 {"code": "ai_unavailable"}` and the router short-circuits *before*
making any outbound call, so nothing is ever sent to Groq and the Groq dashboard
shows no request. `manage.py check` / `runserver` print the `ai.W001` warning at
startup so this is visible immediately.

### 1. Put your Groq key in `.env`

```dotenv
AI_PROVIDERS=groq
AI_GROQ_API_KEY=gsk-...          # Groq (api.groq.com)
AI_GROQ_MODEL=openai/gpt-oss-120b
```

### 2. Verify the credentials before debugging the UI

```bash
python manage.py ai_test                          # one real Groq call, no DB/UI needed
python manage.py ai_test "Explain git rebase" --model openai/gpt-oss-120b
curl http://127.0.0.1:8000/ai/health/             # provider status; no secrets, no API call
```

### Troubleshooting

| Symptom | Cause |
| --- | --- |
| `ai.W001` warning at startup; chat replies "The AI assistant is not configured yet." (`code: ai_not_configured`) | No `AI_GROQ_API_KEY` in `.env` — see step 1. No Groq request is made in this state. |
| Chat replies "…rejected the API key" (`code: provider_auth_failed`) | A key **is** set but Groq answered 401/403 — the key is wrong, revoked, or pasted with extra characters. Keys start with `gsk_`. |
| Chat replies "…rejected this request" (`code: provider_error`) and Groq logs show HTTP 404 | `AI_GROQ_MODEL` is a retired ID (e.g. `llama-3.3-70b-versatile`, shut down 2026-08-16). Set `AI_GROQ_MODEL=openai/gpt-oss-120b` and reload. |
| Chat replies "…unreachable" (`code: ai_unavailable`) | Network/firewall issue reaching `api.groq.com`, or the circuit breaker is open after repeated failures. |
| "The AI provider is busy" | Groq rate limit (429); the router retries with backoff. |
| Widget shows "I could not read your security token" | The page has no CSRF token — reload once. `base.html` publishes it as `<meta name="csrf-token">`. |
| Nothing at all happens and DevTools shows no `/ai/chat/` request | A JavaScript error before the request; check DevTools → Console. |

#### Still says "not configured" after adding the key to `.env`?

Run the full diagnostic first — it prints the exact `.env` path Django reads,
whether it exists, any encoding/BOM or duplicate-key problems, what the OS
environment holds, and what Django actually loaded (values are masked):

```bash
python manage.py ai_env            # full report
python manage.py ai_env --verbose  # also list every key found in .env
```

Then verify the key end to end (one real Groq call, no UI/DB):

```bash
python manage.py ai_test
```

If the key is **MISSING**, check, in this order:

1. **A leftover environment variable shadows `.env` (most common cause on
   Windows).** python-decouple checks the OS environment **before** `.env`,
   so an `AI_GROQ_API_KEY` variable still set in your terminal — even an
   **empty** one — silently wins. Check it:

   ```powershell
   $env:AI_GROQ_API_KEY        # if this prints anything (even nothing that
                               # shows as empty), it is overriding .env
   ```
   * `Remove-Item Env:AI_GROQ_API_KEY` (PowerShell) or `unset AI_GROQ_API_KEY`
     (bash), or better: **open a brand-new terminal** — old PowerShell/cmd
     sessions keep stale variables (a common cause: `setx`, editing env vars
     earlier, or running Django from a shell where the variable was set).
2. **Exact variable name.** It must be `AI_GROQ_API_KEY=gsk_...` — not
   `GROQ_API_KEY`, `GROQ_KEY`, or `OPENAI_API_KEY`.
3. **The file the server actually reads.** ContribKit pins `.env` to the
   **project root** (the folder containing `manage.py`, resolved via
   `contribkit/settings/_env.py` — no guessing from the caller path anymore).
   The file must not be commented out with `#`; an empty value
   (`AI_GROQ_API_KEY=`) counts as "not configured". `ai_env` prints the exact
   path Django uses.
4. **No stray `.env` / `settings.ini` anywhere up the tree.** Older code used
   python-decouple's auto-detection, which searches **upward from the
   settings package** — so a stray `contribkit/settings/.env` (even an empty
   one) or `settings.ini` won and your project-root `.env` was ignored.
   `ai_env` tells you if the wrong file is close by.
5. **One definition per key.** If `AI_GROQ_API_KEY` appears twice in `.env`,
   python-decouple uses the **last** line. `ai_env` flags duplicates.
6. **Plain UTF-8, no BOM, no re-save weirdness.** A UTF-8 BOM on line 1 makes
   the first key invisible to decouple; a UTF-16 file is unreadable. `ai_env`
   detects both.
7. **Restart the server.** Django reads `.env` at startup and the AI service is
   cached per process. After editing `.env`, restart `runserver` (or click
   **Reload** on PythonAnywhere) — a running process keeps the old settings.
8. **The key is valid.** `gsk_...` keys are what Groq issues at
   [console.groq.com](https://console.groq.com). A 401/403 from
   `python manage.py ai_test` means the key is wrong/revoked.

> Note: the chat endpoint previously answered 503 `ai_unavailable` with
> "not configured yet" for **every** failure — including a bad key or a
> network problem. It now reports the real cause:
> `ai_not_configured`, `provider_auth_failed`, `provider_error`,
> `ai_unavailable`, `ai_timeout`, or `provider_rate_limited`.

---

## Sign in with Google (OAuth 2.0)

Handled by [python-social-auth](https://python-social-auth.readthedocs.io/) (`social-auth-app-django`), which exposes `/login/google-oauth2/` (start) and `/complete/google-oauth2/` (callback).

### 1. Create the credentials

Google Cloud Console → **APIs & Services → Credentials → Create Credentials → OAuth client ID → Web application**.

### 2. Register the authorized redirect URI

This is the step that most often gets missed. The callback path is **`/complete/google-oauth2/`** on whatever host you browse the site from — including the trailing slash. `localhost` and `127.0.0.1` count as *different* origins, so register each one you actually use:

| Where you run it | Authorized redirect URI |
| --- | --- |
| `runserver`, browsing `localhost` | `http://localhost:8000/complete/google-oauth2/` |
| `runserver`, browsing `127.0.0.1` | `http://127.0.0.1:8000/complete/google-oauth2/` |
| PythonAnywhere | `https://yourusername.pythonanywhere.com/complete/google-oauth2/` |

A missing entry produces `Error 400: redirect_uri_mismatch` from Google.

### 3. Put the credentials in `.env`

```dotenv
GOOGLE_OAUTH2_CLIENT_ID=1234-abcdefghijklmnop.apps.googleusercontent.com
GOOGLE_OAUTH2_CLIENT_SECRET=GOCSPX-...
```

`base.py` reads these into `SOCIAL_AUTH_GOOGLE_OAUTH2_KEY` / `..._SECRET`. Never commit them.

### 4. Migrate

`python manage.py migrate` creates the `social_django` tables (`usersocialauth`, `nonce`, `association`, `partial`).

### Troubleshooting

**The button does nothing, and the server log shows `"POST /login/google-oauth2/ HTTP/1.1" 302 0`.**
Django did its job — it returned a correct 302 to `https://accounts.google.com/o/oauth2/auth?...` — but the *browser* refused to follow it. `core/csp_middleware.py` sends a `Content-Security-Policy` header, and Chrome/Chromium/Safari enforce the `form-action` directive across the **entire redirect chain** of a form submission (Firefox does not). Since the Google button posts a same-origin form whose 302 target is Google, `form-action 'self'` alone blocks the hop and the page just sits there. The fix is to list the IdP host:

```python
# contribkit/settings/base.py
CSP_FORM_ACTION_EXTRA = ['https://accounts.google.com']
```

Add another entry here whenever you wire up an extra OAuth provider. Open DevTools → Console to confirm; a blocked hop is reported as `Refused to send form data to ... because it violates the following Content Security Policy directive: "form-action 'self'"`.

**`Error 400: redirect_uri_mismatch`** — see step 2.

**The callback works but you get bounced back to the login page** — social-auth caught an exception. `SOCIAL_AUTH_RAISE_EXCEPTIONS = False` routes it through `SocialAuthExceptionMiddleware` as a flash message instead of a stack trace, so read the message on the login page rather than the traceback.

**Everything 301-redirects to `https://localhost:8000` and the page won't load** — you are running the *prod* settings module, where `SECURE_SSL_REDIRECT=True`. `manage.py` selects dev settings by default, so this only happens if `DJANGO_SETTINGS_MODULE=contribkit.settings.prod` was exported in your shell. Unset it for local work.
