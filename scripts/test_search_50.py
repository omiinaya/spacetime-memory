#!/usr/bin/env python3
"""Quick search quality test with LoCoMo data - 50 items only."""
import json, os, sys, time, secrets, urllib.request
sys.path.insert(0, 'sdk/python')
import httpx
from spacetime_memory import Client

DB_ID = os.environ['SPACETIMEDB_DB']
STDB_URL = 'http://localhost:3001'

resp = httpx.get('{}/v1/database/{}'.format(STDB_URL, DB_ID), timeout=10)
token = resp.headers.get('spacetime-identity-token', '')
client = Client(database=DB_ID, token=token)
uid = secrets.token_hex(8)
try:
    client._call('register', ['sq50-{}'.format(uid), 'test', 'benchpass'])
except Exception as e:
    print('Register: {}'.format(e))

ws = client.create_workspace('sq50-{}'.format(int(time.time())), 'debug', '')
ws_id = ws.get('id', '')
print('Workspace: {}'.format(ws_id))

url = 'https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json'
data = json.loads(urllib.request.urlopen(url, timeout=30).read())
conv = data[0]
conv_data = conv['conversation']
speaker_a = conv_data.get('speaker_a', 'A')
speaker_b = conv_data.get('speaker_b', 'B')

print('Conversation: {}, speakers: {}, {}'.format(conv['sample_id'], speaker_a, speaker_b))

# Only use first 50 turns
session_keys = sorted(
    [k for k in conv_data.keys() if k.startswith('session_') and not k.endswith('_date_time')],
    key=lambda x: int(x.split('_')[1]),
)

turn_count = 0
batch_items = []
for sk in session_keys:
    snum = int(sk.split('_')[1])
    dt_key = 'session_{}_date_time'.format(snum)
    session_dt = conv_data.get(dt_key, 'Session {}'.format(snum))
    turns = conv_data[sk]
    for t in turns:
        if turn_count >= 50:
            break
        turn_count += 1
        speaker = t.get('speaker', '')
        speaker_name = speaker_a if 'a' in speaker.lower() else speaker_b
        text = t.get('text', '')
        content = text + ' [Session {}]'.format(snum)
        batch_items.append({
            'content': content,
            'summary': content[:200],
            'memory_type': 'locomo_turn',
            'confidence': 1.0,
            'entities_json': json.dumps([
                {'name': speaker_a, 'entity_type': 'person'},
                {'name': speaker_b, 'entity_type': 'person'},
                {'name': 'session_{}'.format(snum), 'entity_type': 'session'},
                {'name': session_dt, 'entity_type': 'datetime'},
            ]),
        })
    if turn_count >= 50:
        break

print('Ingesting {} items...'.format(len(batch_items)))
t0 = time.time()
results = client.store_batch(workspace_id=ws_id, items=batch_items)
print('Done in {:.1f}s'.format(time.time() - t0))

time.sleep(3)

# Check search_index
si = client._query('search_index', workspace_id=ws_id)
print('Search index entries: {}'.format(len(si)))

# Search
print('\n=== SEARCH QUALITY ===')
search_queries = [
    'When did Caroline go to LGBTQ support group',
    'Caroline identity transgender',
    'Melanie painted a sunrise',
    'Where did Caroline move from',
    'Caroline relationship status',
    'Melanie charity race mental health',
    'What does Melanie do for fun art pottery',
    'Caroline passed adoption interview',
    'Melanie camping trip family',
    'Caroline LGBTQ conference pride parade',
]

for q in search_queries:
    results = client.search(ws_id, q, memory_type='', limit=5, semantic=True, cross_encoder=True)
    rc = len(results)
    top_content = ''
    top_score = 0.0
    if rc > 0:
        r = results[0]
        top_content = r.get('content', r.get('memory_content', ''))[:100].replace('\n', ' ')
        top_score = r.get('score', 0.0)
    print('  [{:.4f}] {} => {}'.format(top_score, q[:45], top_content[:60]))
