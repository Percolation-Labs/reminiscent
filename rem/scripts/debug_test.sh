#!/bin/bash
# Debug structured output detection

# Get ONLY the API keys from siggy .env (not the postgres connection)
export OPENAI_API_KEY=$(grep "^OPENAI_API_KEY=" /Users/sirsh/code/mr_saoirse/siggy-code/application/backend/.env | cut -d= -f2-)
export ANTHROPIC_API_KEY=$(grep "^ANTHROPIC_API_KEY=" /Users/sirsh/code/mr_saoirse/siggy-code/application/backend/.env | cut -d= -f2-)

# Use staging database connection
export POSTGRES__CONNECTION_STRING='postgresql://remuser:wOUr49zYvkELlYMUUk2IQ3O78ysAdqN@localhost:5433/remdb'
export LLM__DEFAULT_MODEL='openai:gpt-4.1'

cd /Users/sirsh/code/mr_saoirse/remstack/rem

echo "Connection: $POSTGRES__CONNECTION_STRING"
echo "Running debug test (full output)..."
uv run python -m rem.cli.main ask test_orchestrator \
  "Please analyze this message: I love this feature!" \
  --no-stream 2>&1 | head -80
