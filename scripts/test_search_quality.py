#!/usr/bin/env python3
"""Quick search quality test with LoCoMo data."""
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
    client._call('register', ['sq-{}'.format(uid), 'test', 'benchpass'])
except Exception as e:
    print('Register: {}'.format(e))

ws = client.create_workspace('sq-{}'.format(int(time.time())), 'debug', '')
ws_id = ws.get('id', '')
print('Workspace: {}'.format(ws_id))

# Download and extract conversations
url = 'https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json'
data = json.loads(urllib.request.urlopen(url, timeout=30).read())
conv = data[0]  # conv-26
conv_data = conv['conversation']
speaker_a = conv_data.get('speaker_a', 'A')
speaker_b = conv_data.get('speaker_b', 'B')

print('Conversation: {}, speakers: {}, {}'.format(conv['sample_id'], speaker_a, speaker_b))

# Build batch items
session_keys = sorted(
    [k for k in conv_data.keys() if k.startswith('session_') and not k.endswith('_date_time')],
    key=lambda x: int(x.split('_')[1]),
)

batch_items = []
for sk in session_keys:
    snum = int(sk.split('_')[1])
    dt_key = 'session_{}_date_time'.format(snum)
    session_dt = conv_data.get(dt_key, 'Session {}'.format(snum))
    turns = conv_data[sk]
    for t in turns:
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

print('Ingesting {} items...'.format(len(batch_items)))
t0 = time.time()
client.store_batch(workspace_id=ws_id, items=batch_items)
print('Done in {:.1f}s'.format(time.time() - t0))

# Wait for Tantivy indexing
time.sleep(3)

# Search for key facts across categories
print('\n=== SEARCH QUALITY TEST ===')
search_queries = [
    ('When did Caroline go to LGBTQ support group', 'temporal'),
    ('Caroline identity transgender', 'single-hop'),
    ('Melanie painted a sunrise', 'single-hop'),
    ('When did Melanie paint a sunrise', 'temporal'),
    ('Caroline speech school assembly diversity', 'single-hop'),
    ('Where did Caroline move from', 'single-hop'),
    ('Caroline relationship status dating', 'single-hop'),
    ('Melanie charity race mental health', 'temporal'),
    ('What does Melanie do for fun art pottery', 'single-hop'),
    ('Caroline research subject area study', 'single-hop'),
    ('Caroline passed adoption interview', 'temporal'),
    ('Melanie camping trip family', 'temporal'),
    ('Caroline LGBTQ conference', 'temporal'),
    ('What career path is Caroline pursuing counseling', 'single-hop'),
    ('Caroline adoption agency interview passed', 'temporal'),
]

results_log = []
for q, cat in search_queries:
    try:
        results = client.search(ws_id, q, memory_type='', limit=5, semantic=True, cross_encoder=True)
        rc = len(results)
        if rc > 0:
            top = results[0]
            content = top.get('content', top.get('memory_content', ''))[:120]
            score = top.get('score', 0.0)
            results_log.append((q, cat, 'OK', rc, score, content))
        else:
            results_log.append((q, cat, 'EMPTY', 0, 0.0, ''))
    except Exception as e:
        results_log.append((q, cat, 'ERROR', -1, 0.0, str(e)[:60]))

# Print summary
passed = sum(1 for r in results_log if r[2] == 'OK')
print('\nSearch results: {}/{} passed'.format(passed, len(results_log)))
for q, cat, status, rc, score, content in results_log:
    if status == 'OK':
        print('  [{}] {:.4f} | {}'.format(cat[:4], score, content[:80]))
    else:
        print('  [{}] {} | {}'.format(cat[:4], status, q[:60]))
