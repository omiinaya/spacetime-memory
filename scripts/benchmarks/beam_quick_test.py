#!/usr/bin/env python3
"""Quick BEAM smoke test — store + search + judge for 5 scenarios."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk', 'python'))
sys.path.insert(0, os.path.dirname(__file__))
os.environ['STDB_URL'] = 'http://127.0.0.1:3001'
os.environ['SPACETIMEDB_DB'] = 'spacetime-memory-v2'
os.environ['PYTHONUNBUFFERED'] = '1'

import urllib.request
STDB_URL = os.environ['STDB_URL']
DB_NAME = os.environ['SPACETIMEDB_DB']
_resp = urllib.request.urlopen(f'{STDB_URL}/v1/database/{DB_NAME}', timeout=10)
_token = _resp.headers.get('spacetime-identity-token', '')
_identity = _resp.headers.get('spacetime-identity', '')

from spacetime_memory import Client
client = Client(host='127.0.0.1', port='3001', database=DB_NAME, token=_token or None)
try:
    _uuid = _identity.split('-')[0][:8]
    client._call('register', [f'bench-{_uuid}', 'bench789', _identity])
except:
    pass

from run_beam import load_dataset, store_scenario_stdb

data = load_dataset()
data = data[:5]

# Create workspace
ws = client.create_workspace(f'beam_fast_{int(time.time())}')
ws_id = ws.get('id')
print(f'Workspace: {ws_id}')
sys.stdout.flush()

# Store
print(f'Storing {len(data)} scenarios...')
sys.stdout.flush()
for idx, scenario in enumerate(data):
    t0 = time.time()
    store_scenario_stdb(client, ws_id, scenario)
    print(f'  Stored scenario {idx+1}/{len(data)} in {time.time()-t0:.1f}s')
    sys.stdout.flush()

# Search test
print(f'\nSearch test:')
sys.stdout.flush()
results = client.search(ws_id, 'Elena Vasquez NeuroLink Labs', limit=5, semantic=True)
print(f'  Results: {len(results)}')
for r in results[:3]:
    print(f'    [{r.get("score",0):.4f}] {str(r.get("content",""))[:80]}')
sys.stdout.flush()

print('\nDONE')
