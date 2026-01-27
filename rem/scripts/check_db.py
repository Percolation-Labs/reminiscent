"""Check database for structured output messages."""
import asyncio
import os

# Set env before importing rem
os.environ['POSTGRES__CONNECTION_STRING'] = 'postgresql://remuser:wOUr49zYvkELlYMUUk2IQ3O78ysAdqN@localhost:5433/remdb'

from rem.services.postgres import get_postgres_service

SESSION_ID = "a9df6359-6b02-4ee8-bf81-6fd5bdf1fd04"  # From last test

async def check():
    pg = get_postgres_service()
    await pg.connect()
    try:
        rows = await pg.fetch('''
            SELECT message_type,
                   metadata->>'tool_name' as tool_name,
                   metadata->>'tool_call_id' as tool_call_id,
                   content
            FROM messages
            WHERE session_id = $1
            ORDER BY created_at ASC
        ''', SESSION_ID)

        print(f'Found {len(rows)} messages in session {SESSION_ID}')
        print()
        for i, row in enumerate(rows):
            print(f'[{i+1}] {row["message_type"]}')
            if row['tool_name']:
                print(f'    Tool: {row["tool_name"]}')
            if row['tool_call_id']:
                print(f'    Tool Call ID: {row["tool_call_id"]}')
            if row['content']:
                # Truncate content for display
                content = row['content']
                if len(content) > 300:
                    content = content[:300] + '...'
                print(f'    Content: {content}')
            print()

        # Check for our structured output marker
        tool_msgs = [r for r in rows if r['message_type'] == 'tool']
        print(f'Total tool messages: {len(tool_msgs)}')
        for tm in tool_msgs:
            tool_id = tm.get('tool_call_id', '')
            print(f'  - Tool ID: {tool_id}, Tool Name: {tm.get("tool_name")}')
            if 'structured_output' in (tool_id or ''):
                print(f'    ✓ FOUND structured_output marker!')

    finally:
        await pg.disconnect()

asyncio.run(check())
