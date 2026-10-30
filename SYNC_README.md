# GitHub Issue Synchronization

ContribKit no longer relies on editors to post issues manually. A management
command pulls issues from tracked GitHub repositories into the local issue
board, keeps their status in sync, and leaves viewers with a curated, current
list of beginner-friendly work.

## What gets imported

An issue is imported only when **all** of the following are true:

1. It comes from a repository listed at `/admin-panel/repositories/` and marked
   **Active**.
2. It carries at least one tracked label (case-insensitive, matched exactly):
   - `good first issue`
   - `good-first-issue`
   - `beginner`
   - `easy`
   - `starter`
   - `documentation`
   - `docs`
   - `help wanted`
   - `first-timers-only`
3. It is **not** a pull request. GitHub returns PRs through the issues endpoint;
   they are always discarded.
4. It has a numeric GitHub issue id and a valid `html_url`.

Title keywords alone never qualify an issue.

## Setup

1. **Install dependencies** (only `requests` is required beyond Django):

   ```bash
   pip install -r requirements.txt
   ```

2. **Create a token.** A classic personal access token with `public_repo` scope,
   or a fine-grained token with public-repository read access to issues, is
   sufficient. The token is used only for GitHub API reads.

3. **Configure `.env`:**

   ```dotenv
   GITHUB_TOKEN=ghp_your_token_here
   GITHUB_SYNC_INTERVAL=120
   GITHUB_SYNC_FULL_INTERVAL=3600
   ```

   `GITHUB_PAT` is still accepted as a backwards-compatible alias. Never commit
   a real token, and never log it: the client sends it only in the
   `Authorization` header and error messages never include it.

4. **Apply migrations:**

   ```bash
   python manage.py migrate
   ```

   Migration `issues/0002_github_sync` relocates `Repo` into the `issues` app
   while keeping the physical table name `repos_repo`, so existing repository
   rows, issues, and saved-issue bookmarks are preserved in place. It also adds
   the synchronization bookkeeping columns and removes the obsolete
   `repos_repo.editor_id` column if an older database still has it.

5. **Track repositories** at `/admin-panel/repositories/` (admin login required)
   or via Django admin. Adding a repository performs a best-effort metadata
   lookup (language, stars, description); it still succeeds if GitHub is
   unreachable.

6. **Seed the board** (optional, for demo data):

   ```bash
   python manage.py seed_data
   ```

## Running the synchronizer

One pass over every active repository:

```bash
python manage.py sync_github_issues
```

Single repository, forced full reconciliation:

```bash
python manage.py sync_github_issues --repo django/django --full
```

`--repo` accepts either the display name (`django/django`) or the stored URL
form and can be repeated. `--include-inactive` also includes paused
repositories.

Continuous worker (the production mode):

```bash
python manage.py sync_github_issues --watch
```

`--watch` runs one pass every `--interval` seconds (default
`GITHUB_SYNC_INTERVAL`, 120; minimum 30) until `SIGINT`/`SIGTERM`. In this mode
the interval timer starts after each pass, so a slow pass never overlaps the
next one.

Run the worker as a separate long-lived process (for example under a process
supervisor or in a second terminal). A Django request never triggers a sync, so
a worker restart only delays the next pass; it does not lose data.

## How a pass works

- **Incremental by default.** After a successful pass the repository stores a
  checkpoint (the pass start time minus a 60-second overlap for clock skew).
  The next pass sends that checkpoint as GitHub's `since` parameter, so only
  recently updated issues are fetched.
- **Hourly full reconciliation.** When `last_full_sync_at` is older than
  `GITHUB_SYNC_FULL_INTERVAL` (3600 seconds), or no checkpoint exists, the pass
  uses `state=all` without `since`. This is the only mode that can observe
  closures and deletions, because a closed issue is not returned by an
  incremental query.
- **Pagination.** Pages of up to `GITHUB_SYNC_PAGE_SIZE` (100) are followed via
  the `Link` header. The next-page URL is persisted after each fully processed
  page, so an interrupted run resumes from the exact page instead of restarting.
- **Closures.** An open issue is closed when:
  - GitHub reports it closed;
  - it loses every tracked label (the row and any bookmarks are kept);
  - a complete full pass no longer returns it (deleted or made private).

  A resumed full pass deliberately skips closure detection and leaves
  `last_full_sync_at` unchanged, because it did not see the earlier pages. The
  next uninterrupted full pass reconciles missing issues.
- **Reopening.** A previously closed issue that is open on GitHub again is
  reopened locally.
- **Failures.** Authentication errors, rate limits, timeouts, malformed
  payloads, and unexpected exceptions are caught per repository, recorded in
  `last_sync_error`, and do not stop other repositories. If any issue on a page
  fails to store, the cursor is not advanced past that page, so the next run
  retries it rather than silently skipping it.
- **Legacy rows.** Issues imported before synchronization existed have a null
  `github_id`. They are matched by exact `github_issue_url` (never by title) and
  linked to the GitHub id instead of being duplicated.

Counts printed by the command (`created`, `updated`, `skipped`, `failed`,
`closed`, `reopened`) are per pass; `skipped` includes pull requests, issues
without a tracked label, and unchanged issues.

## Settings reference

| Setting | Default | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | empty | API token; sync aborts if missing |
| `GITHUB_SYNC_INTERVAL` | `120` | Default `--watch` cadence (seconds) |
| `GITHUB_SYNC_FULL_INTERVAL` | `3600` | Full reconciliation cadence (seconds) |
| `GITHUB_SYNC_TIMEOUT` | `10` | Per-request timeout (seconds) |
| `GITHUB_SYNC_MAX_RETRIES` | `3` | Retries for timeouts, 5xx, rate limits |
| `GITHUB_SYNC_BACKOFF` | `1.0` | Base exponential backoff (capped at 10s) |
| `GITHUB_SYNC_PAGE_SIZE` | `100` | Issues requested per page |
| `GITHUB_SYNC_MAX_PAGES` | `100` | Safety limit before a pass is aborted |

## Operational notes

- The synchronizer uses the GitHub REST API directly. There is no Celery,
  Redis, or background queue; the `--watch` process is the worker.
- Rate limits are respected: a `Retry-After` value up to 60 seconds is honored,
  otherwise the pass fails with a clear error and the next pass retries.
- Pausing a repository (`is_active=False`) stops future imports but leaves its
  issues on the board. Deleting a repository removes its issues (and their
  bookmarks) through the existing cascade.
- `Reset checkpoint` on the repository admin page clears the cursor, mode, start
  time, and stored error, forcing a full pass next run.
- Repositories are processed one at a time; a slow or failing repository cannot
  block the others.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `GITHUB_TOKEN is not set` | Token missing from `.env` or environment | Add it and restart the worker |
| `GitHub rejected the access token (401/403)` | Expired, revoked, or under-scoped token | Create a new token; check `public_repo`/public read access |
| `rate limit reached` | Unauthenticated or heavily used token | Use an authenticated token, lower the cadence |
| `request timed out` | Network or GitHub slowdown | Transient; retried automatically, then retried next pass |
| Issues never appear | Repository inactive, or issue lacks a tracked label | Activate the repo; add one of the labels above on GitHub |
| Closed issues stay open | Only incremental passes have run | Wait for the hourly full pass, or run `--full` |
| `Pagination exceeded the configured safety limit` | Repository returns more than `GITHUB_SYNC_MAX_PAGES` pages | Raise the limit or narrow the tracked repositories |
| Repository shows an error on the admin page | Last pass failed | Read `last_sync_error`, fix the cause, retry or reset the checkpoint |

## Tests

```bash
python manage.py test issues
```

The suite covers creation and deduplication, label filtering and PR exclusion,
closure/reopening, pagination, incremental checkpoints, interruption and resume,
token/rate-limit/timeout/malformed/5xx handling, token redaction in logs,
per-repository failure isolation, command flags, editor-removal regressions,
viewer/admin behavior, and the legacy editor-column migration.
