#!/bin/bash
# Quick mypy runner with timestamped reports in .mypy/ folder
set -e

# Create .mypy directory if it doesn't exist
mkdir -p .mypy

# Generate timestamped report filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE=".mypy/report_${TIMESTAMP}.txt"

echo "🔍 Running mypy type checker..."
echo "📝 Report will be saved to: ${REPORT_FILE}"
echo ""

# Run mypy and save report
uv run mypy src/rem --pretty 2>&1 | tee "${REPORT_FILE}"

# Show summary
echo ""
echo "✅ Type checking complete!"
echo "📊 Full report: ${REPORT_FILE}"
echo ""
echo "Summary:"
grep "^Found" "${REPORT_FILE}" || echo "✓ No errors found!"
