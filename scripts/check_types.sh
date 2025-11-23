#!/bin/bash
set -e

echo "🔍 Running type checker (mypy)..."
cd rem

# Create .mypy directory if it doesn't exist
mkdir -p .mypy

# Generate timestamped report filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE=".mypy/report_${TIMESTAMP}.txt"

# Run mypy and save report
echo "📝 Saving report to ${REPORT_FILE}"
uv run mypy src/rem --pretty 2>&1 | tee "${REPORT_FILE}"

# Show summary
echo ""
echo "✅ Type checking complete!"
echo "📊 Full report saved to: ${REPORT_FILE}"
grep "^Found" "${REPORT_FILE}" || echo "No errors found!"
