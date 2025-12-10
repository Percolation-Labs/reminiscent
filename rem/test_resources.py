import asyncio
from src.rem.api.mcp_router.resources import load_resource

async def test():
    print('=== Testing load_resource with all resource types ===')

    tests = [
        'rem://agents',           # Regular resource (list agents)
        'rem://agents/ask_rem',   # Parameterized (specific agent)
        'rem://agents/agent-builder',  # Another agent
        'rem://status',           # Regular resource
        'rem://schema/entities',  # Another regular
        'rem://agents/nonexistent',    # Should return 'not found' message (but not error)
        'rem://totally/wrong',    # Should error
    ]

    for uri in tests:
        try:
            result = await load_resource(uri)
            # Show first 150 chars of result
            preview = str(result)[:150].replace('\n', ' ')
            print(f'✓ {uri}')
            print(f'  -> {preview}...')
        except ValueError as e:
            print(f'✗ {uri}')
            print(f'  -> ERROR: {e}')
        print()

asyncio.run(test())
