# Contributing to Brightbean

Thanks for your interest in contributing! This guide will help you get started.

## Getting Started

1. Fork the repository and clone your fork
2. Follow the setup instructions in [README.md](README.md) (Docker or local development)
3. Install the pre-commit hooks (see [Pre-commit hooks](#pre-commit-hooks) below)
4. Create a branch for your work: `git checkout -b your-branch-name`

### Pre-commit hooks

We use [pre-commit](https://pre-commit.com) to run lint, format, type, and secret-scanning checks on every commit. Install it once after cloning:

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

From then on, the hooks run automatically. To run them against every file in the repo (useful after pulling in large changes):

```bash
pre-commit run --all-files
```

The hooks enforce the same rules as CI, so passing them locally means your PR will pass the automated checks.

## Development Workflow

### Running the app

See the [README](README.md) for full setup instructions. The quick version:

```bash
cp .env.example .env
# Edit .env if needed (defaults work for local dev with Docker PostgreSQL)
docker compose up postgres -d
python manage.py migrate
python manage.py runserver
```

### Running tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=apps --cov-report=term-missing
```

### Code style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [mypy](https://mypy-lang.org/) for type checking. Run these before submitting a PR:

```bash
ruff check .              # lint
ruff format --check .     # format check
mypy apps/ config/ providers/ tests/ --ignore-missing-imports
```

To auto-fix lint and formatting issues:

```bash
ruff check --fix .
ruff format .
```

CI runs all of these checks automatically on every PR, plus a [gitleaks](https://github.com/gitleaks/gitleaks) secret scan. Never commit real API keys, tokens, or passwords. Put them in your local `.env` (which is gitignored) and reference them by name in `.env.example`.

## Submitting Changes

1. **Keep PRs focused.** One feature or fix per PR. Small PRs get reviewed faster.
2. **Write descriptive commit messages.** Explain *what* and *why*, not just *how*.
3. **Add tests** for new features or bug fixes when possible.
4. **Make sure CI passes.** The PR must pass lint, typecheck, and test checks.
5. **Update documentation** if your change affects setup, configuration, or user-facing behavior.

### PR process

1. Push your branch to your fork
2. Open a pull request against `main`
3. Fill out the PR template
4. A maintainer listed in [`.github/CODEOWNERS`](.github/CODEOWNERS) is auto-requested for review
5. Wait for review, we'll try to respond within a few days
6. Address review feedback in new commits (don't force-push until after approval, so reviewers can see the diff)
7. Once approved, a maintainer will squash-merge your PR into `main`

## Project Structure

```
apps/           # Django applications (accounts, composer, calendar, etc.)
providers/      # Social platform API integrations (one file per platform)
config/         # Django settings, URLs, WSGI/ASGI
templates/      # Django HTML templates
theme/          # Tailwind CSS theme (django-tailwind)
static/         # Static assets (JS, favicons)
tests/          # Test suite
```

## Adding a New Social Platform Provider

Providers live in `providers/` with one file per platform. To add a new one:

1. Create `providers/your_platform.py`
2. Implement the provider class following the pattern in existing providers (e.g., `providers/bluesky.py` for a simple example, `providers/facebook.py` for a full OAuth flow)
3. Key methods to implement:
   - `get_authorization_url()` - Build the OAuth redirect URL
   - `exchange_code()` - Exchange the auth code for tokens
   - `refresh_token()` - Refresh expired tokens
   - `publish()` - Publish content to the platform
   - `get_comments()` / `reply_to_comment()` - Inbox support (optional)
4. Register the provider in the platform choices and connection flow
5. Add the platform's required environment variables to `.env.example`
6. Add setup instructions to the README under **Platform Credentials**
7. Add tests in `tests/providers/`

## Reporting Bugs

Use the [bug report template](https://github.com/brightbeanxyz/brightbean-studio/issues/new?template=bug_report.yml) on GitHub. Include:

- Steps to reproduce
- Expected vs actual behavior
- Your environment (Docker/local, OS, browser)

## Requesting Features

Use the [feature request template](https://github.com/brightbeanxyz/brightbean-studio/issues/new?template=feature_request.yml) on GitHub.

## Security Issues

**Do not open a public issue for security vulnerabilities.** See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0 License](LICENSE).
