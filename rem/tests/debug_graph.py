import asyncio
import logging
from rem.services.postgres import PostgresService

logging.basicConfig(level=logging.INFO)

async def debug_graph():
    pg = PostgresService()
    await pg.connect()
    
    tenant_id = "test-graph-traversal"
    
    print(f"\n--- Debugging Graph for Tenant: {tenant_id} ---")
    
    # 1. Check Resources
    print("\n[Resources]")
    resources = await pg.fetch("SELECT name, id, graph_edges FROM resources WHERE tenant_id = $1", tenant_id)
    for r in resources:
        print(f"  Name: {r['name']}")
        print(f"  ID: {r['id']}")
        print(f"  Edges: {r['graph_edges']}")
        
    # 2. Check Moments
    print("\n[Moments]")
    moments = await pg.fetch("SELECT name, id, graph_edges FROM moments WHERE tenant_id = $1", tenant_id)
    for m in moments:
        print(f"  Name: {m['name']}")
        print(f"  ID: {m['id']}")
        print(f"  Edges: {m['graph_edges']}")

    # 3. Check Users
    print("\n[Users]")
    users = await pg.fetch("SELECT name, id, graph_edges FROM users WHERE tenant_id = $1", tenant_id)
    for u in users:
        print(f"  Name: {u['name']}")
        print(f"  ID: {u['id']}")
        print(f"  Edges: {u['graph_edges']}")
        
    # 4. Check KV Store
    print("\n[KV Store]")
    kvs = await pg.fetch("SELECT entity_key, entity_type, entity_id FROM kv_store WHERE tenant_id = $1", tenant_id)
    for k in kvs:
        print(f"  Key: {k['entity_key']} | Type: {k['entity_type']} | ID: {k['entity_id']}")

    # 5. Check View
    print("\n[Unified View - all_graph_edges]")
    edges = await pg.fetch("""
        SELECT v.entity_type, r.name, v.graph_edges 
        FROM all_graph_edges v
        JOIN resources r ON r.id = v.id
        WHERE v.tenant_id = $1 AND r.name = 'Meeting Notes'
    """)
    # Note: The JOIN above is lazy, just checking if view works for one resource
    
    await pg.disconnect()

if __name__ == "__main__":
    asyncio.run(debug_graph())
