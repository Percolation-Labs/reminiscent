# Publishing remdb to PyPI

## Prerequisites

```bash
# Install build tools
pip install build twine

# Set up PyPI credentials (use API token)
# Create ~/.pypirc with your credentials
```

## Publishing Process

### 1. Update Version

Edit `pyproject.toml`:
```toml
version = "0.1.1"  # Increment version
```

### 2. Build Distribution

```bash
cd rem/

# Clean old builds
rm -rf dist/ build/ *.egg-info/

# Build wheel and source distribution
python -m build
```

This creates:
- `dist/remdb-0.1.1-py3-none-any.whl`
- `dist/remdb-0.1.1.tar.gz`

### 3. Test on TestPyPI (Optional but Recommended)

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Test installation from TestPyPI
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ remdb[all]
```

### 4. Publish to PyPI

```bash
# Upload to PyPI (uses credentials from ~/.pypirc or environment)
python -m twine upload dist/*

# Or with explicit token
python -m twine upload dist/* --username __token__ --password $PYPI_API_KEY
```

### 5. Verify Installation

```bash
# In a fresh environment
pip install remdb[all]

# Test CLI
rem --help
```

## Using PyPI API Token

Recommended approach - use an API token instead of username/password:

1. Go to https://pypi.org/manage/account/token/
2. Create a new API token with scope for the `remdb` project
3. Set environment variable:
   ```bash
   export PYPI_API_KEY="pypi-..."
   ```

4. Publish:
   ```bash
   python -m twine upload dist/* --username __token__ --password $PYPI_API_KEY
   ```

## Automation with GitHub Actions

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install build tools
        run: pip install build twine

      - name: Build package
        run: python -m build
        working-directory: rem

      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: python -m twine upload dist/*
        working-directory: rem
```

Add `PYPI_API_TOKEN` to GitHub repository secrets.

## Version Naming Convention

- **0.1.x** - Alpha releases (breaking changes expected)
- **0.2.x** - Beta releases (stabilizing API)
- **1.0.0** - First stable release
- **1.x.y** - Stable releases (semantic versioning)

## Quick Publish Script

Save as `publish.sh`:

```bash
#!/bin/bash
set -e

# Load PyPI token from environment
if [ -z "$PYPI_API_KEY" ]; then
    echo "Error: PYPI_API_KEY not set"
    exit 1
fi

# Clean and build
rm -rf dist/ build/ *.egg-info/
python -m build

# Upload to PyPI
python -m twine upload dist/* --username __token__ --password "$PYPI_API_KEY"

echo "✓ Published successfully!"
```

Make executable and run:
```bash
chmod +x publish.sh
./publish.sh
```
