# PyPI Publish Instructions

Package is built, tested, and pass `twine check`.

## Publish

```bash
cd sdk/python
export PYPI_TOKEN="pypi-..."

# Via twine (recommended):
.venv/bin/python -m twine upload \
  --username __token__ \
  --password "$PYPI_TOKEN" \
  dist/*

# Or via .pypirc:
cat > ~/.pypirc << 'PYPI'
[pypi]
username = __token__
password = ${PYPI_TOKEN}
PYPI

.venv/bin/python -m twine upload dist/*
```

## Verify

```bash
pip install spacetime-memory
python -c "import spacetime_memory; print(spacetime_memory.__version__)"
```
