#!/usr/bin/env python3
"""Debug batch search indexing - deep trace."""
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
    client._call('register', ['debug-trace', 'test', 'benchpass'])
except Exception as e:
    print('  Register: {}'.format(e))

ws = client.create_workspace('dbg-trace-' + str(int(time.time())), 'debug', '')
ws_id = ws.get('id', '')
print('Workspace: {}'.format(ws_id))

# Single store first for baseline
print('\n=== Single store baseline ===')
r = client.store(ws_id, 'Caroline went to LGBTQ support group on March 15th [Session 2]', memory_type='test')
print('Store result: {}'.format(json.dumps(r, default=str)[:100]))

time.sleep(1)

mems = client._query('memory', workspace_id=ws_id)
print('Memories after single store: {}'.format(len(mems)))
for m in mems:
    content = m.get('content', '')
    mid = m.get('id', '')
    print('  content[:100] = {}'.format(content[:100]))
    print('  content_is_encrypted = {}'.format('OK' if content and content.startswith('Caroline') else 'ENCRYPTED?'))

# Now batch store
print('\n=== Batch store ===')
items = [
    {'content': 'Melanie painted a beautiful sunrise last week [Session 3]', 'summary': 'Test 2', 'memory_type': 'test', 'confidence': 1.0},
    {'content': 'Caroline gave a speech at school about diversity [Session 4]', 'summary': 'Test 3', 'memory_type': 'test', 'confidence': 1.0},
]
results = client.store_batch(workspace_id=ws_id, items=items)
print('Batch stored: {} items'.format(len(results)))

# Check all memories now
time.sleep(0.5)
mems = client._query('memory', workspace_id=ws_id)
print('\nAll memories ({}):'.format(len(mems)))
for m in mems:
    mid = m.get('id', '?')
    content = m.get('content', '')
    created = m.get('created_at', 0)
    print('  [{}] id={}.. content[:80]={}'.format(created, mid[:16], content[:80]))
    print('           content[:100] match: {}'.format(
        content[:100] if content[:100] == items[0]['content'][:100] or content[:100] == items[1]['content'][:100] else 'NO MATCH'
    ))

# Check search_index
si = client._query('search_index', workspace_id=ws_id)
print('\nSearch index entries: {}'.format(len(si)))
for s in si[:5]:
    print('  entity_id={} score={:.4f}'.format(s.get('entity_id', '?')[:16], s.get('cosine_score', 0)))

# Search
time.sleep(1)
print('\nSearch:')
for q in ['Melanie sunrise', 'school speech diversity']:
    results = client.search(ws_id, q, memory_type='', limit=5, semantic=True, cross_encoder=True)
    print('  "{}": {} results'.format(q[:50], len(results)))
