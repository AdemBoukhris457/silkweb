# Contributing to Silkweb

Thanks for helping improve Silkweb. This document is the single place for **how we expect contributions** to be prepared and reviewed.

## Community

Keep discussion constructive and respectful. Assume good intent. If you are unsure whether an idea fits the project, open an issue first and outline the problem and your proposed direction.

## Ways to contribute

- **Bug reports:** reproducible steps, expected vs actual behavior, Python version, and a minimal code sample when possible.
- **Documentation:** fixes, clarifications, or examples in `docs/` and the root `README.md`.
- **Features:** prefer an issue describing the use case before large or API-changing work so maintainers can align on design.

Search [existing issues](https://github.com/AdemBoukhris457/silkweb/issues) before filing a duplicate.

On GitHub, use the **issue templates** (bug report, feature request, documentation, question) so the right labels and fields are applied and triage stays fast.

## Labels (maintainers)

Label names and colors are defined in `.github/labels.yml`. The **Sync labels** workflow updates GitHub when that file changes on `main`, or when you run it manually under **Actions**. Keep that file as the source of truth so issue templates and automation stay aligned.

## Pull requests

- Open PRs against **`main`**.
- Prefer **small, focused PRs** (one logical change per PR). Large refactors are easier to review when split.
- **Describe what changed and why** in the PR description so reviewers do not have to infer intent from the diff alone.
- Link related issues with `Fixes #123` or `Closes #123` when applicable.

### What we merge

- Changes that match the project’s style and testing expectations (see below).
- **Stable public API:** exports and behavior intended for users live in `silkweb/__init__.py` and documented surfaces. Avoid breaking changes without discussion.
- **Tests** for non-trivial behavior or regressions you fix.
- **No secrets:** do not commit API keys, tokens, or personal data. Use a local `.env` (gitignored) for keys.

### Repository layout notes

- `examples/` and `notebooks/` are **gitignored** in this repo’s workflow; do not rely on them being present for others. Prefer tests under `tests/` and user-facing examples in docs when appropriate.

## Development setup

- **Python 3.10+** (CI runs on 3.11 and 3.12).
- Editable install with dev and test extras:

```bash
python -m pip install -U pip wheel
python -m pip install -e ".[test]"
```

For a full local environment matching optional integrations (browser, LLM extras, etc.):

```bash
python -m pip install -e ".[all]"
```

Create a local **`.env`** for API keys when needed; it must not be committed.

## Checks to run before opening a PR

CI runs **`python -m pytest`** on Ubuntu for Python 3.11 and 3.12. Run the same locally:

```bash
python -m pytest
```

**Lint and format** with Ruff (configuration in `pyproject.toml`):

```bash
ruff check .
ruff format .
```

**Type checking** is not run in CI today, but the codebase uses strict Mypy settings for `silkweb/`. After substantive changes, run:

```bash
python -m mypy silkweb
```

**Documentation** (if you change `docs/`, `mkdocs.yml`, or nav-related content):

```bash
python -m pip install -e ".[docs]"
python -m mkdocs build --strict
```

## Code and design guidelines

- Match **existing patterns** in the module you touch (naming, error handling, logging, typing).
- Prefer **clear, minimal diffs** over drive-by refactors in unrelated files.
- **Docstrings:** Google style where the surrounding code already uses them; keep public symbols documented when behavior is not obvious.
- **Dependencies:** new dependencies need a clear justification and should stay optional when they pull in heavy or platform-specific stacks (follow existing `optional-dependencies` patterns in `pyproject.toml`).

## License

By contributing, you agree that your contributions will be licensed under the same terms as the project (**MIT**). See [`LICENSE`](LICENSE).
