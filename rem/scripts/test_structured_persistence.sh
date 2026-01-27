#!/bin/bash
# Test structured output persistence entirely within rem

# Use staging database
export POSTGRES__CONNECTION_STRING='postgresql://remuser:wOUr49zYvkELlYMUUk2IQ3O78ysAdqN@localhost:5433/remdb'
export LLM__DEFAULT_MODEL='openai:gpt-4.1'

# Get API key from siggy .env
export OPENAI_API_KEY=$(grep "^OPENAI_API_KEY=" /Users/sirsh/code/mr_saoirse/siggy-code/application/backend/.env | cut -d= -f2-)

cd /Users/sirsh/code/mr_saoirse/remstack/rem

echo "=================================================="
echo "Testing Structured Output Database Persistence"
echo "=================================================="
echo "Database: $POSTGRES__CONNECTION_STRING"
echo "Model: $LLM__DEFAULT_MODEL"
echo ""

# Test 1: Direct call to structured output agent
echo "TEST 1: Direct call to test_structured_output"
echo "----------------------------------------------"
uv run python -m rem.cli.main ask test_structured_output \
  "I love using this new feature! It makes everything so much easier." \
  --no-stream 2>&1

echo ""
echo ""

# Test 2: Orchestrator delegating to structured output agent
echo "TEST 2: Orchestrator delegating to test_structured_output"
echo "----------------------------------------------------------"
SESSION_OUTPUT=$(uv run python -m rem.cli.main ask test_orchestrator \
  "Please analyze this message: I love using this new feature! It makes everything so much easier." \
  --no-stream 2>&1)

echo "$SESSION_OUTPUT"

# Extract session ID from output
SESSION_ID=$(echo "$SESSION_OUTPUT" | grep -o 'Session ID: [a-f0-9-]*' | cut -d: -f2 | tr -d ' ')

echo ""
echo ""
echo "=================================================="
echo "CHECKING DATABASE FOR TOOL MESSAGES"
echo "=================================================="

if [ -n "$SESSION_ID" ]; then
  echo "Session ID: $SESSION_ID"
  echo ""

  # Query database to check for tool messages
  uv run python -c "
import asyncio
from rem.services.postgres import get_postgres_service

async def check_messages():
    pg = get_postgres_service()
    await pg.connect()
    try:
        rows = await pg.fetch('''
            SELECT message_type,
                   metadata->>'tool_name' as tool_name,
                   metadata->>'tool_call_id' as tool_call_id,
                   LEFT(content, 200) as content_preview
            FROM messages
            WHERE session_id = \$1
            ORDER BY created_at ASC
        ''', '$SESSION_ID')

        print(f'Found {len(rows)} messages in session')
        print()
        for i, row in enumerate(rows):
            print(f'[{i+1}] {row[\"message_type\"]}')
            if row['tool_name']:
                print(f'    Tool: {row[\"tool_name\"]}')
            if row['tool_call_id']:
                print(f'    Tool Call ID: {row[\"tool_call_id\"]}')
            if row['content_preview']:
                print(f'    Content: {row[\"content_preview\"]}...')
            print()

        # Specifically check for structured output tool message
        tool_msgs = [r for r in rows if r['message_type'] == 'tool']
        structured_msgs = [r for r in tool_msgs if r['tool_call_id'] and 'structured_output' in str(r['tool_call_id'])]

        print('='*50)
        if structured_msgs:
            print('✓ SUCCESS: Found structured output persisted as tool message!')
            print(f'  Tool messages: {len(tool_msgs)}')
            print(f'  Structured output messages: {len(structured_msgs)}')
        else:
            print('⚠ No structured output tool message found')
            print(f'  Total tool messages: {len(tool_msgs)}')
        print('='*50)
    finally:
        await pg.disconnect()

asyncio.run(check_messages())
" 2>&1
else
  echo "Could not extract session ID from output"
fi
