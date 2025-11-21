#!/bin/bash
set -e

echo "🚀 Publishing remdb to PyPI"
echo "============================="

# Check for PyPI token
if [ -z "$PYPI_API_KEY" ]; then
    echo "❌ Error: PYPI_API_KEY environment variable not set"
    echo "   Export your PyPI API token:"
    echo "   export PYPI_API_KEY='pypi-...'"
    exit 1
fi

# Get current version from pyproject.toml
VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
echo "📦 Building version: $VERSION"

# Clean previous builds
echo "🧹 Cleaning old builds..."
rm -rf dist/ build/

# Build package
echo "🔨 Building package..."
uv run python -m build

# Show built files
echo ""
echo "📁 Built files:"
ls -lh dist/

# Confirm before publishing
echo ""
read -p "⚠️  Publish remdb $VERSION to PyPI? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Publishing cancelled"
    exit 1
fi

# Publish to PyPI
echo "📤 Publishing to PyPI..."
uv run python -m twine upload dist/* --username __token__ --password "$PYPI_API_KEY"

echo ""
echo "✅ Successfully published remdb $VERSION to PyPI!"
echo "📦 Install with: pip install remdb[all]"
