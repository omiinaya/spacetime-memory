#!/usr/bin/env python3
"""Debug batch search indexing."""
import json, os, sys, time
sys.path.insert(0, 'sdk/python')
import httpx
from spacetime_memory import Client

DB_ID = os.environ['SPACETIMEDB_DB']
STDB_URL = 'http://localhost:3001'

resp = httpx.get('{}/v1/database/{}'.format(STDB_URL, DB_ID), timeout=10)
token = resp.headers.get('spacetime-identity-token', '')
client = Client(database=DB_ID, token=token)
try:
    client._call('register', ['debug-batch3', 'test', 'benchpass'])
except Exception as e:
    print('  Register: {}'.format(e))

# Create workspace
ws = client.create_workspace('dbg-batch-' + str(int(time.time())), 'debug', '')
ws_id = ws.get('id', '')
print('Workspace: {}'.format(ws_id))

# Store 3 items via batch
items = [
    {'content': 'Caroline went to LGBTQ support group on March 15th [Session 2]', 'summary': 'Test 1', 'memory_type': 'test', 'confidence': 1.0},
    {'content': 'Melanie painted a beautiful sunrise last week [Session 3]', 'summary': 'Test 2', 'memory_type': 'test', 'confidence': 1.0},
    {'content': 'Caroline gave a speech at school about diversity [Session 4]', 'summary': 'Test 3', 'memory_type': 'test', 'confidence': 1.0},
]
results = client.store_batch(workspace_id=ws_id, items=items)
print('Batch stored: {} items'.format(len(results)))

# Check memory table
time.sleep(0.5)
mems = client._query('memory', workspace_id=ws_id)
print('Memories in table: {}'.format(len(mems)))
for m in mems:
    mid = m.get('id', '?')
    content = m.get('content', '')[:80]
    print('  id={}.. content={}'.format(mid[:16], content))

# Check search_index
try:
    si = client._query('search_index', workspace_id=ws_id)
    print('Search index entries: {}'.format(len(si)))
except Exception as e:
    print('Search index error: {}'.format(e))

# Check term_index
try:
    ti = client._query('term_index', workspace_id=ws_id)
    print('Term index entries: {}'.format(len(ti)))
except Exception as e:
    print('Term index error: {}'.format(e))

# Search
time.sleep(2)
print('\nSearch results:')
for q in ['Caroline LGBTQ support group', 'Melanie sunrise painting', 'school speech diversity']:
    results = client.search(ws_id, q, memory_type='', limit=5, semantic=True, cross_encoder=True)
    rc = len(results)
    print('  "{}": {} results'.format(q[:50], rc))
    for r in results[:3]:
        content = r.get('content', r.get('memory_content', ''))[:80]
        score = r.get('score', 0)
        print('    [{:.4f}] {}'.format(score, content))
