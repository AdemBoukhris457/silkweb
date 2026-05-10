## Contributing

Thanks for helping improve Silkweb.

### Development setup

- Python **3.10+**
- Install in editable mode:

```bash
python -m pip install -e ".[all]"
```

The repository includes a root `.gitignore` (do not commit `*.example` files). Create a local `.env` for API keys when needed; do not commit it.

### Linting / formatting

```bash
ruff check .
ruff format .
```

### Guidelines

- Keep the public API in `silkweb/__init__.py` stable.
- Prefer small, focused PRs.
- Add or update tests when implementing non-trivial behavior.

