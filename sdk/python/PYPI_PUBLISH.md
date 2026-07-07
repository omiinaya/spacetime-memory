# PyPI Publish Guide

## Prerequisites

1. **PyPI API token** set as `PYPI_TOKEN` in GitHub repo secrets (for CI) or in the environment (for manual publish)
2. Package built and verified (see below)

## Version Bumping

Version is defined in two places that must match:

| File | Location |
|------|----------|
| `sdk/python/pyproject.toml` | `[project] version = "..."` |
| `sdk/python/spacetime_memory/__init__.py` | `__version__ = "..."` |

**Update both files** when bumping the version.

## Publish Workflow

The CI workflow `.github/workflows/publish.yml` triggers automatically on `py-v*.*.*` tag push:

```bash
# 1. Update version in both files
# 2. Commit and tag
git add sdk/python/pyproject.toml sdk/python/spacetime_memory/__init__.py
git commit -m "chore: bump version to X.Y.Z"
git tag py-vX.Y.Z
git push origin main --tags
```

The workflow will:
1. Build wheel + sdist via `python -m build`
2. Verify with `twine check dist/*`
3. Upload to PyPI via `pypa/gh-action-pypi-publish`

## Manual Publish (if needed)

```bash
cd sdk/python

# Build
python -m build

# Verify
twine check dist/*

# Upload
export PYPI_TOKEN="pypi-..."
python -m twine upload \
  --username __token__ \
  --password "$PYPI_TOKEN" \
  dist/*
```

## Verify Installation

```bash
pip install spacetime-memory
python -c "import spacetime_memory; print(spacetime_memory.__version__)"
```
