<!--
  Thanks for contributing to Silkweb.
  Delete sections that do not apply. Short, concrete PRs are easier to review.
-->

## Summary

<!-- What problem does this solve, and what did you change? (1–3 sentences.) -->

## Test plan

<!-- How you verified this: commands you ran, or manual steps. Use “N/A” for trivial doc typo fixes. -->

## Checklist

### Required

- [ ] I have read [CONTRIBUTING.md](CONTRIBUTING.md).
- [ ] `python -m pytest` passes locally.
- [ ] `ruff check .` passes; I ran `ruff format .` if I changed Python formatting.
- [ ] No secrets, API keys, or `.env` files are in this PR.

### If you changed documentation

- [ ] `python -m mkdocs build --strict` passes (after `pip install -e ".[docs]"` if needed).

### If you changed public API or types

- [ ] I ran `python -m mypy silkweb`, or I explain below why it was skipped / not applicable.
- [ ] I did not change stable exports in `silkweb/__init__.py` without discussion, **or** I documented the breaking change below.

## Breaking changes / migration

<!-- Write “None”, or describe what users must change and why. -->

## Related issues

<!-- e.g. Fixes #42 — see https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue -->
