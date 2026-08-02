#!/usr/bin/env python3
"""Quick smoke test for client-side search (no STDB reducer = no energy budget exhaustion)."""
import sys, os, json, urllib.request, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk', 'python'))
os.environ['STDB_URL'] = 'http://127.0.0.1:3001'
os.environ['SPACETIMEDB_DB'] = 'spacetime-memory-v2'
os.environ['EMBEDDER_URL'] = 'http://127.0.0.1:9090'
os.environ['TANTIVY_URL'] = 'http://127.0.0.1:9091'
os.environ['PYTHONUNBUFFERED'] = '1'

STDB_URL = os.environ['STDB_URL']
DB_NAME = os.environ['SPACETIMEDB_DB']

# Step 1: Get fresh identity (creates a new STDB identity + token)
_resp = urllib.request.urlopen(f'{STDB_URL}/v1/database/{DB_NAME}', timeout=10)
_token = _resp.headers.get('spacetime-identity-token', '')
_identity = _resp.headers.get('spacetime-identity', '')

from spacetime_memory import Client
client = Client(host='127.0.0.1', port='3001', database=DB_NAME, token=_token or None)

# Step 2: Register unique user — client captures updated auth token
uname = f'smoke-{int(time.time())}'
client.register(uname, 'Smoke Test', 'test123')
print(f'Registered as {uname} (identity: {_identity[:16]}...)')

# Step 3: Create workspace → extract ID string
ws_resp = client.create_workspace('smoke-test-ws')
ws = ws_resp['id']
print(f'Workspace ID: {ws}')

# Step 4: Store test memories via store_batch (includes embedding + indexing)
batch = [
    {'content': 'Dr. Elena Vasquez is the Chief Scientific Officer at NeuroLink Labs, a biotechnology company specializing in neural interfaces.',
     'summary': 'CSO NeuroLink', 'memory_type': 'fact'},
    {'content': 'Project Chimera is owned by Phoenix Dynamics (51% stake) and Horizon Energy. It is headquartered in Geneva, Switzerland.',
     'summary': 'Project Chimera ownership', 'memory_type': 'fact'},
    {'content': 'The quarterly all-hands meeting is scheduled for Friday, July 24, 2026 at 10:00 AM in the main auditorium.',
     'summary': 'All-hands meeting', 'memory_type': 'fact'},
]
result = client.store_batch(ws, batch)
print(f'Stored {len(batch)} memories ({len(result)} results)')

# Step 5: Create KG node for entity search
try:
    client._call('create_node', [ws, 'Elena Vasquez', 'person', 'Chief Scientific Officer of NeuroLink Labs'])
    print('Created KG node: Elena Vasquez')
except Exception as e:
    print(f'KG node: {e}')

# Step 6: Search (this was previously crashing with "energy budget exhausted")
print('\n=== SEARCH TESTS (no energy budget errors) ===')
test_cases = [
    'Who is the CSO of NeuroLink Labs?',
    'Who owns Project Chimera?',
    'When is the all-hands meeting?',
    'Phoenix Dynamics',
    'biotechnology neural interfaces',
]

all_passed = True
for query in test_cases:
    try:
        results = client.search(ws, query, limit=5, cross_encoder=False)
        status = '✅' if len(results) > 0 else '⚠️'
        if len(results) == 0:
            all_passed = False
        print(f'{status} Q: "{query}" → {len(results)} results')
        for i, r in enumerate(results[:3]):
            strat = r.get('strategy', '?')
            score = r.get('fused_score', r.get('score', 0))
            content = (r.get('content', '') or '')[:80]
            print(f'     [{strat}] score={score:.3f}: {content}')
    except Exception as e:
        import traceback
        print(f'❌ Q: "{query}" → ERROR: {e}')
        traceback.print_exc()
        all_passed = False

# Step 7: Semantic search specifically
print('\n=== SEMANTIC SEARCH ===')
try:
    results = client.search(ws, 'neural biotechnology company', limit=5, cross_encoder=False)
    print(f'  {len(results)} results')
    for i, r in enumerate(results[:3]):
        print(f'  [{r.get("strategy","?")}] {r.get("content","")[:60]}')
except Exception as e:
    print(f'  Error: {e}')

print(f'\n{"=" * 40}')
if all_passed:
    print('✅ ALL TESTS PASSED — Client-side search works, no energy budget exhaustion!')
else:
    print('⚠️ Some searches returned 0 results (may need more indexing time)')
print(f'Worker identity: {_identity[:16]}...')
print(f'Workspace: {ws}')
