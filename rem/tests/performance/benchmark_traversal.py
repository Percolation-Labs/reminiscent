import asyncio
import time
import statistics
import logging
from rem.services.postgres import PostgresService

# Disable logs to avoid noise during benchmark
logging.basicConfig(level=logging.WARNING)

async def benchmark():
    pg = PostgresService()
    await pg.connect()
    
    root_key = "Project Plan"
    tenant_id = "test-graph-traversal"
    max_depth = 5
    iterations = 1000
    
    query = "SELECT * FROM rem_traverse($1, $2, $3)"
    
    print(f"Benchmarking rem_traverse for '{root_key}' (Depth: {max_depth})")
    print(f"Iterations: {iterations}")
    
    # Warmup
    await pg.fetch(query, root_key, tenant_id, max_depth)
    
    times = []
    
    try:
        for i in range(iterations):
            start = time.perf_counter()
            await pg.fetch(query, root_key, tenant_id, max_depth)
            end = time.perf_counter()
            times.append((end - start) * 1000) # Convert to ms
            
        avg_time = statistics.mean(times)
        median_time = statistics.median(times)
        p95 = statistics.quantiles(times, n=20)[18] # 95th percentile
        
        print(f"\nResults:")
        print(f"  Average: {avg_time:.4f} ms")
        print(f"  Median:  {median_time:.4f} ms")
        print(f"  P95:     {p95:.4f} ms")
        print(f"  Min:     {min(times):.4f} ms")
        print(f"  Max:     {max(times):.4f} ms")
        
    finally:
        await pg.disconnect()

if __name__ == "__main__":
    asyncio.run(benchmark())
