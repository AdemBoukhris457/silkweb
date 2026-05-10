# Publishing Silkweb to PyPI

This guide walks through publishing **`silkweb`** as an installable package on [PyPI](https://pypi.org/) so users can run `pip install silkweb` (and optional extras such as `pip install "silkweb[browser]"`).

The project uses **Hatchling** (`pyproject.toml` → `[build-system]`) and a standard **`README.md`** for the long-form description shown on PyPI.

---

## 1. PyPI account and tokens

1. Register at [https://pypi.org/account/register/](https://pypi.org/account/register/) (and optionally [https://test.pypi.org/](https://test.pypi.org/) for a dry run).
2. Enable **two-factor authentication (2FA)** on PyPI (required for uploads).
3. Create an **API token** under **Account settings → API tokens**:
   - For the first upload, a **whole-account** token is fine.
   - After the project exists on PyPI, prefer a **project-scoped** token for `silkweb`.

Keep tokens secret; never commit them to the repository.

---

## 2. Metadata in `pyproject.toml` (before each release)

Check and update:

| Item | Notes |
|------|--------|
| **`[project] version`** | Must be **unique** on PyPI for every upload. Example: `0.1.0`, then `0.1.1`, etc. |
| **`[project.urls]`** | `Homepage`, `Repository`, `Documentation`, `Issues`, etc. should point at your real URLs (not placeholders). |
| **`readme`** | Must match the file you ship (e.g. `README.md`). |
| **Package name** | `name = "silkweb"` must match the name you want on PyPI. Confirm it is not taken: [https://pypi.org/project/silkweb/](https://pypi.org/project/silkweb/). |

After editing, commit and push as usual.

---

## 3. Build, check, test, and upload

Run these from the **repository root** (the directory that contains `pyproject.toml`).

### 3a — Install tools and clean `dist/`

```powershell
cd C:\Users\ademb\Desktop\libraries_to_deploy\more_libs\silkweb

python -m pip install -U pip build twine

if (Test-Path dist) { Remove-Item -Recurse -Force dist }
```

On macOS or Linux:

```bash
cd /path/to/silkweb
python -m pip install -U pip build twine
rm -rf dist
```

### 3b — Build the wheel and sdist

```powershell
python -m build
```

Expected artifacts under **`dist/`** (version comes from `pyproject.toml`):

- `silkweb-<version>-py3-none-any.whl`
- `silkweb-<version>.tar.gz`

### 3c — Validate artifacts

```powershell
twine check dist/*
```

Fix any reported issues (README rendering, metadata, classifiers) before uploading.

### 3d — Smoke-test the wheel (recommended)

```powershell
python -m venv .tmp-publish-check
.\.tmp-publish-check\Scripts\Activate.ps1
pip install (Get-Item .\dist\silkweb-*-py3-none-any.whl).FullName
python -c "import silkweb; print(silkweb.__version__)"
deactivate
Remove-Item -Recurse -Force .tmp-publish-check
```

### 3e — (Optional) Upload to TestPyPI

Use a **TestPyPI** token from [https://test.pypi.org/manage/account/token/](https://test.pypi.org/manage/account/token/).

```powershell
python -m twine upload --repository testpypi dist/*
```

Credentials:

- **Username:** `__token__`
- **Password:** the TestPyPI API token (value only, or as documented with your token type).

Install from TestPyPI to verify:

```powershell
python -m pip install -i https://test.pypi.org/simple/ silkweb==<your-version>
```

### 3f — Upload to production PyPI

Use a **production** token from [https://pypi.org/manage/account/token/](https://pypi.org/manage/account/token/).

```powershell
python -m twine upload dist/*
```

Credentials:

- **Username:** `__token__`
- **Password:** the PyPI API token.

### 3g — Verify the release

```powershell
pip install silkweb==<your-version>
python -c "import silkweb; print(silkweb.__version__)"
```

Open the project on PyPI, for example:

`https://pypi.org/project/silkweb/<your-version>/`

---

## 4. Every future release

1. Bump **`version`** in **`pyproject.toml`**.
2. Update **`[project.urls]`** if links changed (changelog/releases URL, docs site, etc.).
3. Commit and tag in git if your team uses tags (optional but common).
4. Repeat **section 3**: clean **`dist/`**, **`python -m build`**, **`twine check`**, upload with **`twine upload`**.

PyPI **does not allow re-uploading** the same version; each upload must use a **new** version string.

---

## 5. Optional: CI publishing (trusted publishing)

To avoid long-lived tokens in GitHub Actions, configure **trusted publishing** (OpenID Connect) between GitHub and PyPI. See the official guide:

[https://docs.pypi.org/trusted-publishers/](https://docs.pypi.org/trusted-publishers/)

---

## 6. Notes specific to this repository

- **Extras** are defined under `[project.optional-dependencies]` in `pyproject.toml` (for example `browser`, `stealth`, `test`, `docs`, `all`).
- **`Development Status :: 2 - Pre-Alpha`** in classifiers is appropriate for early releases; you can tighten it later.
- **`README.md`** is long; PyPI will render it. That is valid but can make the project page heavy—trim later if you want a shorter PyPI landing page.
