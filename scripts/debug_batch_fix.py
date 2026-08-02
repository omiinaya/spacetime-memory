#!/usr/bin/env python3
"""Debug batch search indexing."""
import json, os, sys, time, secrets
sys.path.insert(0, 'sdk/python')
import httpx
from spacetime_memory import Client

DB_ID = os.environ['SPACETIMEDB_DB']
STDB_URL = 'http://localhost:3001'

resp = httpx.get('{}/v1/database/{}'.format(STDB_URL, DB_ID), timeout=10)
token = resp.headers.get('spacetime-identity-token', '')
client = Client(database=DB_ID, token=token)

# Use unique username to avoid clashes
uid = secrets.token_hex(8)
try:
    client._call('register', ['dbg-{}'.format(uid), 'test-{}'.format(uid), 'benchpass'])
except Exception as e:
    print('  Register: {}'.format(e))

ws = client.create_workspace('dbg-{}'.format(int(time.time())), 'debug', '')
ws_id = ws.get('id', '')
print('Workspace: {}'.format(ws_id))

items = [
    {'content': 'Caroline went to LGBTQ support group on March 15th [Session 2]', 'summary': 'Test 1', 'memory_type': 'test', 'confidence': 1.0},
    {'content': 'Melanie painted a beautiful sunrise last week [Session 3]', 'summary': 'Test 2', 'memory_type': 'test', 'confidence': 1.0},
]
results = client.store_batch(workspace_id=ws_id, items=items)
print('Batch stored: {} items'.format(len(results)))

mems = client._query('memory', workspace_id=ws_id)
print('Memories: {}'.format(len(mems)))

si = client._query('search_index', workspace_id=ws_id)
print('Search index entries: {}'.format(len(si)))

time.sleep(2)
print('\nSearch:')
for q in ['Caroline LGBTQ support group', 'Melanie sunrise painting']:
    results = client.search(ws_id, q, memory_type='', limit=5, semantic=True, cross_encoder=True)
    print('  "{}": {} results'.format(q[:50], len(results)))
