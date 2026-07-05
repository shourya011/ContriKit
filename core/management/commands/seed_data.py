from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.models import User
from repos.models import Repo
from issues.models import Tag, Issue, SavedIssue
from templates_app.models import Template
from cheatsheet.models import CheatSheetSection, CheatSheetCommand

class Command(BaseCommand):
    help = "Seeds the ContribKit database with realistic open-source platforms, issues, templates, and Git workflows."

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")

        # 1. Create Users
        admin_user, _ = User.objects.get_or_create(username="admin", defaults={
            "email": "admin@contribkit.com",
            "role": "admin",
            "is_superuser": True,
            "is_staff": True,
            "bio": "ContribKit Platform Admin"
        })
        if not admin_user.check_password("adminpass123"):
            admin_user.set_password("adminpass123")
            admin_user.save()

        editor_user, _ = User.objects.get_or_create(username="demo_editor", defaults={
            "email": "editor@contribkit.com",
            "role": "editor",
            "github_username": "torvalds",
            "bio": "Open source maintainer passionate about beginner onboarding."
        })
        if not editor_user.check_password("editorpass123"):
            editor_user.set_password("editorpass123")
            editor_user.save()

        viewer_user, _ = User.objects.get_or_create(username="demo_viewer", defaults={
            "email": "viewer@contribkit.com",
            "role": "viewer",
            "github_username": "first_timer_coder",
            "bio": "Learning Git and looking for my first PR!"
        })
        if not viewer_user.check_password("viewerpass123"):
            viewer_user.set_password("viewerpass123")
            viewer_user.save()

        self.stdout.write(self.style.SUCCESS("✓ Users seeded (admin, demo_editor, demo_viewer)"))

        # 2. Create Tags
        tags_data = [
            ("Python", "python", "#3776ab"),
            ("JavaScript", "javascript", "#d97706"),
            ("TypeScript", "typescript", "#2563eb"),
            ("Django", "django", "#059669"),
            ("React", "react", "#0284c7"),
            ("CSS/HTML", "css-html", "#e11d48"),
            ("Documentation", "documentation", "#6366f1"),
            ("Testing", "testing", "#7c3aed"),
        ]
        tag_objs = {}
        for name, slug, color in tags_data:
            t, _ = Tag.objects.update_or_create(slug=slug, defaults={"name": name, "color": color})
            tag_objs[slug] = t

        self.stdout.write(self.style.SUCCESS("✓ Tech Tags seeded"))

        # 3. Create Repos
        repos_data = [
            ("https://github.com/django/django", "django/django", "Python", 81200, "The Web framework for perfectionists with deadlines."),
            ("https://github.com/twbs/bootstrap", "twbs/bootstrap", "JavaScript", 170500, "The most popular HTML, CSS, and JS library in the world."),
            ("https://github.com/pallets/flask", "pallets/flask", "Python", 67800, "A micro web framework written in Python."),
            ("https://github.com/facebook/react", "facebook/react", "JavaScript", 225000, "The library for web and native user interfaces."),
        ]
        repo_objs = {}
        for url, name, lang, stars, desc in repos_data:
            r, _ = Repo.objects.update_or_create(github_url=url, defaults={
                "editor": editor_user,
                "name": name,
                "language": lang,
                "stars": stars,
                "description": desc,
                "is_active": True
            })
            repo_objs[name] = r

        self.stdout.write(self.style.SUCCESS("✓ Repositories seeded"))

        # 4. Create Issues
        issues_data = [
            ("Fix typo in tutorial documentation header", "django/django", "beginner", 1.0, True, 12, ["documentation", "python"],
             "In `docs/intro/tutorial01.txt` line 45, the word 'asynchronous' is misspelled as 'asyncronous'.\n\n**Steps to resolve:**\n1. Fork the repo and create a branch `fix-doc-typo`.\n2. Locate the file and correct the spelling.\n3. Run `make html` in the docs directory to verify no broken formatting.\n4. Submit your PR referencing this issue!"),
            
            ("Add aria-label attributes to pagination buttons", "twbs/bootstrap", "beginner", 2.0, True, 24, ["css-html", "javascript"],
             "Screen readers currently announce raw page numbers without context on our docs site pagination.\n\n**Requirements:**\n- Update `site/layouts/partials/pagination.html`.\n- Add `aria-label=\"Page X\"` to each numbered item.\n- Verify accessibility audit score improves in Chrome DevTools Lighthouse."),
            
            ("Write unit tests for url_for helper edge cases", "pallets/flask", "intermediate", 3.5, False, 8, ["testing", "python"],
             "The `url_for` helper function in `src/flask/helpers.py` lacks test coverage when handling anchor `#` identifiers combined with query parameters.\n\n**Guidance:**\n- Look at `tests/test_helpers.py` for pattern examples.\n- Add pytest test cases verifying correct URL generation.\n- Run `pytest tests/test_helpers.py` locally."),
            
            ("Create good first issue onboarding checklist guide", "facebook/react", "beginner", 1.5, True, 35, ["documentation"],
             "New contributors often ask how to run the React compiler benchmarks locally. We need a clean markdown guide inside `fixtures/README.md` explaining the `yarn test` commands.\n\nKeep instructions concise and beginner-friendly!"),
            
            ("Handle empty search string validation in admin searchbar", "django/django", "beginner", 2.0, False, 15, ["django", "python"],
             "Submitting an empty whitespace query `   ` in the Django admin filter hits the DB unnecessarily.\n\n**Task:**\n- In `django/contrib/admin/views/main.py`, strip query parameters before executing `get_queryset()`.\n- Add a regression test in `tests/admin_views/test_search.py`."),
            
            ("Convert alert dismiss button to SVG icon component", "twbs/bootstrap", "intermediate", 4.0, False, 19, ["css-html", "javascript"],
             "We are migrating away from background-image inline CSS for close buttons in alert banners.\n\n**Steps:**\n1. Check `scss/_alerts.scss`.\n2. Replace inline data URI with embedded SVG symbol.\n3. Ensure contrast ratio remains compliant across dark/light themes."),
            
            ("Add type hints to cli.py command dispatcher", "pallets/flask", "beginner", 2.5, True, 29, ["python", "testing"],
             "Modern Python 3.10+ type annotations (`dict[str, Any]`, `list[str]`) should be added to `src/flask/cli.py`.\n\nRun `mypy src/flask/cli.py` to verify strict type checking passes without warnings."),
            
            ("Warn user when calling setState inside unmounted component hook", "facebook/react", "intermediate", 4.5, False, 42, ["react", "javascript"],
             "Add a DEV-only console warning when an asynchronous effect attempts state updates on an unmounted fiber node.\n\nCheck `packages/react-reconciler/src/ReactFiberHooks.js`."),
            
            ("Add support for custom date formatting in logging middleware", "django/django", "beginner", 2.0, False, 11, ["django", "python"],
             "Allow developers to specify `LOGGING_DATE_FORMAT` in `settings.py`.\n\nUpdate `django/utils/log.py` and document the setting in `docs/ref/settings.txt`."),
            
            ("Improve error message when port 5000 is already in use", "pallets/flask", "beginner", 1.0, False, 7, ["python"],
             "When running `flask run` and port 5000 is occupied, socket.error raises a cryptic traceback. Catch `OSError` and output a clean message: 'Port 5000 is occupied. Use --port to choose another.'")
        ]

        for title, repo_name, diff, hrs, feat, views, tag_slugs, desc in issues_data:
            r = repo_objs.get(repo_name)
            if r:
                url = f"https://github.com/{r.name}/issues/{abs(hash(title)) % 9000 + 100}"
                iss, _ = Issue.objects.update_or_create(title=title, defaults={
                    "repo": r,
                    "posted_by": editor_user,
                    "description": desc,
                    "github_issue_url": url,
                    "difficulty": diff,
                    "estimated_hours": hrs,
                    "status": "open",
                    "is_featured": feat,
                    "view_count": views
                })
                for ts in tag_slugs:
                    if ts in tag_objs:
                        iss.tags.add(tag_objs[ts])

        self.stdout.write(self.style.SUCCESS("✓ 10 Beginner Opportunities seeded"))

        # Seed some saved issues for demo viewer
        first_issue = Issue.objects.first()
        last_issue = Issue.objects.last()
        if first_issue and last_issue:
            SavedIssue.objects.get_or_create(user=viewer_user, issue=first_issue)
            SavedIssue.objects.get_or_create(user=viewer_user, issue=last_issue)

        # 5. Create Templates
        templates_data = [
            ("README.md Standard Template", "readme", "readme", "Comprehensive README with shields, installation steps, and usage guide.",
             """# Project Name

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

> A brief, catchy one-line description of what your open source project does.

## 📖 Table of Contents
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [License](#license)

## ✨ Features
- **Fast & Lightweight** — Zero bloat dependencies.
- **Easy Integration** — Works out of the box in 5 minutes.
- **Accessible** — Fully WCAG 2.1 AA compliant.

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/username/project.git
cd project

# Install dependencies
npm install  # or pip install -r requirements.txt

# Run local dev server
npm run dev
```

## 🤝 Contributing
We love community contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details."""),

            ("CONTRIBUTING.md Guide", "contributing", "contributing", "Clear onboarding rules, Git workflow instructions, and dev setup.",
             """# Contributing Guidelines

First off, thank you for considering contributing to this project! It's people like you that make open source such a welcoming community.

## 🛠 Getting Started
1. **Fork** the repository on GitHub.
2. **Clone** your fork locally: `git clone https://github.com/YOUR_USER/repo.git`
3. **Create a branch** for your work: `git checkout -b feature/my-new-feature`
4. **Make your changes** and verify local tests pass.

## 📐 Coding Standards
- Write clean, self-documenting code.
- Add unit tests for any new logic or bug fixes.
- Ensure no trailing whitespace or lint errors exist.

## 📬 Submitting a Pull Request
- Reference the issue number in your PR title (e.g. `Fix #123: Correct header spacing`).
- Describe the changes clearly and include screenshots for UI modifications.
- Request a review from maintainers when ready!"""),

            ("Issue Report Template", "issue_tmpl", "issue_tmpl", "Structured bug report and feature request template.",
             """---
name: Bug Report or Feature Request
about: Create a clear and actionable issue for maintainers
title: "[ISSUE]: "
labels: needs-triage
assignees: ''
---

## 🐛 Bug Description / 💡 Feature Idea
*A clear and concise description of what the bug is or what feature you are proposing.*

## 🔄 Steps to Reproduce (if bug)
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## 🖥 Expected Behavior
*A clear description of what you expected to happen.*

## 📸 Screenshots / Logs
*If applicable, paste terminal output or UI screenshots to help explain your problem.*

## ⚙️ Environment
- OS: [e.g. macOS 14, Ubuntu 22.04]
- Python/Node Version: [e.g. Python 3.12, Node 20]
- Version: [e.g. 1.2.0]"""),

            ("Pull Request Template", "pr_tmpl", "pr_tmpl", "Standard PR checklist ensuring tests and documentation are complete.",
             """## 🔗 Related Issue
Fixes #(issue number)

## 📝 Summary of Changes
- *Added X to handle Y*
- *Updated helper logic in Z*

## ✅ Contributor Checklist
- [ ] My code follows the code style guidelines of this repository.
- [ ] I have performed a self-review of my own code.
- [ ] I have commented my code in hard-to-understand areas.
- [ ] I have added tests that prove my fix is effective or that my feature works.
- [ ] New and existing unit tests pass locally with my changes.

## 📸 Screenshots (if UI change)
*Paste before/after comparisons here.*"""),

            ("Code of Conduct", "code_of_conduct", "code_of_conduct", "Contributor Covenant standardizing community behavior and safety.",
             """# Contributor Covenant Code of Conduct

## Our Pledge
We as members, contributors, and leaders pledge to make participation in our community a harassment-free experience for everyone, regardless of age, body size, visible or invisible disability, ethnicity, sex characteristics, gender identity and expression, level of experience, education, socio-economic status, nationality, personal appearance, race, religion, or sexual identity and orientation.

## Our Standards
Examples of behavior that contributes to a positive environment:
- Demonstrating empathy and kindness toward other people
- Being respectful of differing opinions, viewpoints, and experiences
- Giving and gracefully accepting constructive feedback
- Focusing on what is best not just for us as individuals, but for the overall community

## Enforcement
Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the community leaders. All complaints will be reviewed and investigated promptly and fairly.""")
        ]

        for title, slug, t_type, desc, content in templates_data:
            Template.objects.update_or_create(slug=slug, defaults={
                "title": title,
                "type": t_type,
                "description": desc,
                "content": content,
                "created_by": admin_user
            })

        self.stdout.write(self.style.SUCCESS("✓ 5 Standard Templates seeded"))

        # 6. Create CheatSheet Sections & Commands
        sections_data = [
            ("Setup & Configuration", 1, [
                ("git config --global user.name \"John Doe\"", "Set your global Git name attached to commits", "git config --global user.name \"Jane Smith\""),
                ("git config --global user.email \"you@email.com\"", "Set your email address attached to commits", "git config --global user.email \"jane@opensource.org\""),
                ("git config --global init.defaultBranch main", "Set default branch name for new repos to main", "git config --global init.defaultBranch main"),
                ("git clone <repo_url>", "Clone an existing remote repository onto your local computer", "git clone https://github.com/django/django.git"),
                ("git remote add upstream <url>", "Connect your fork to the original parent repository", "git remote add upstream https://github.com/original/repo.git"),
                ("git remote -v", "List all connected remote URLs (origin and upstream)", "git remote -v"),
            ]),
            ("Daily Workflow & Staging", 2, [
                ("git status", "Check which files are modified, staged, or untracked", "git status"),
                ("git add <file>", "Stage a specific modified file for the next commit", "git add src/index.js"),
                ("git add .", "Stage all modified and new files in the directory", "git add ."),
                ("git diff", "View exact line-by-line code changes before staging", "git diff src/app.py"),
                ("git commit -m \"message\"", "Save staged changes with a concise descriptive message", "git commit -m \"Fix navigation header overflow on mobile\""),
                ("git commit --amend -m \"new msg\"", "Change the commit message of your very last commit", "git commit --amend -m \"Fix #42: Header mobile spacing\""),
                ("git log --oneline -5", "View a compact list of your 5 most recent commits", "git log --oneline -5"),
            ]),
            ("Branching & Switching", 3, [
                ("git branch", "List all local branches on your machine", "git branch"),
                ("git checkout -b <branch>", "Create a new branch and switch to it immediately", "git checkout -b fix-button-style"),
                ("git switch <branch>", "Switch to an existing local branch", "git switch main"),
                ("git branch -d <branch>", "Delete a branch locally after it has been merged", "git branch -d fix-button-style"),
                ("git branch -M main", "Rename your current branch to main", "git branch -M main"),
                ("git merge <branch>", "Merge another branch into your current active branch", "git merge feature/login"),
            ]),
            ("Pull Requests & Syncing", 4, [
                ("git fetch upstream", "Download latest commits from original upstream repository", "git fetch upstream"),
                ("git pull upstream main", "Fetch and merge upstream main branch into your branch", "git pull upstream main"),
                ("git push origin <branch>", "Upload your local branch commits to your GitHub fork", "git push origin fix-button-style"),
                ("git push -u origin <branch>", "Push branch and set remote upstream tracking", "git push -u origin feature-auth"),
                ("git push origin --delete <branch>", "Delete a remote branch on GitHub after PR merge", "git push origin --delete fix-button-style"),
            ]),
            ("Undoing Mistakes & Stashing", 5, [
                ("git restore <file>", "Discard local uncommitted edits in a modified file", "git restore src/settings.py"),
                ("git restore --staged <file>", "Unstage a file that you accidentally ran git add on", "git restore --staged .env"),
                ("git reset --soft HEAD~1", "Undo last commit but keep your code edits staged", "git reset --soft HEAD~1"),
                ("git reset --hard HEAD~1", "Permanently delete last commit and wipe local edits", "git reset --hard HEAD~1"),
                ("git stash", "Temporarily shelter uncommitted edits to work on another branch", "git stash -m \"wip auth form\""),
                ("git stash list", "List all sheltered stashed work packages", "git stash list"),
                ("git stash pop", "Restore your most recent stashed edits onto active branch", "git stash pop"),
                ("git stash drop", "Discard the top stashed package permanently", "git stash drop"),
            ]),
        ]

        CheatSheetSection.objects.all().delete()
        for sec_title, order, cmds in sections_data:
            sec = CheatSheetSection.objects.create(title=sec_title, order=order)
            for cmd_str, desc_str, ex_str in cmds:
                CheatSheetCommand.objects.create(
                    section=sec,
                    command=cmd_str,
                    description=desc_str,
                    example=ex_str
                )

        self.stdout.write(self.style.SUCCESS("✓ 30+ Git Cheat Sheet Commands seeded"))
        self.stdout.write(self.style.SUCCESS("\n🎉 Database seeding completed successfully!"))
