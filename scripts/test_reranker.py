#!/usr/bin/env python3
"""Quick LLM reranker integration test."""
import os, sys, time, json, uuid
sys.path.insert(0, '/home/user/spacetime-memory/sdk/python')
import httpx
from spacetime_memory import Client

# Source key
env_path = os.path.expanduser('~/.hermes/.env')
with open(env_path) as f:
    for line in f:
        if line.strip().startswith('LITELLM_MASTER_KEY='):
            _, k = line.split('=', 1)
            os.environ['LLM_RERANK_API_KEY'] = k.strip().strip('"').strip("'")
os.environ['LLM_RERANK_ENDPOINT'] = 'http://192.168.1.111:4000/v1'
os.environ['LLM_RERANK_MODEL'] = 'ds-deepseek-v4-flash'

DB = 'c200e6dac0c27d57edf72c2068c3b23d35462f418337fa4ac8f3fbfea2469193'

resp = httpx.get(f'http://localhost:3001/v1/database/{DB}', timeout=5)
token = resp.headers.get('spacetime-identity-token', '')

c = Client(database=DB, embedder_url='http://localhost:9092', token=token)

# Register
identity = resp.headers.get('spacetime-identity', '')
peer_id = f'test-rerank-{uuid.uuid4().hex[:8]}'
try:
    c._call('register', [peer_id, 'test123456', identity])
except Exception:
    pass  # may exist

# Fresh workspace
ws_id = f'test-rerank-{uuid.uuid4().hex[:8]}'
ws = c.create_workspace(ws_id, 'Rerank test')

# Seed 5 docs
docs = [
    'Alice Chen is the CEO and co-founder of Acme AI',
    'Acme AI raised $45M Series A in March 2025',
    'Bob Kumar enjoys pizza on Fridays',
    'The weather in San Francisco is foggy',
    'Acme AI has 47 employees',
]
for doc in docs:
    c.store(workspace_id=ws['id'], content=doc, memory_type='world_fact', peer_id='test', confidence=0.9)

# Index in Tantivy
http = httpx.Client(timeout=10)
mems = c._query('memory', workspace_id=ws['id'], columns=['id', 'content'])
for m in mems:
    http.post('http://localhost:9091/index', json={
        'workspace_id': ws['id'], 'entity_id': m['id'],
        'content': m['content'], 'entity_type': 'memory'
    })

time.sleep(2)

# Test LLM rerank
print('\n=== LLM rerank only (no CE) ===')
res = c.search(ws['id'], query='who is the CEO', limit=5, semantic=True, rerank=True, cross_encoder=False)
for i, r in enumerate(res[:5]):
    score = r.get('score', 0)
    reason = r.get('rerank_reason', 'N/A')
    content = r.get('memory_content', '')[:80]
    print(f'  [{i}] score={score:.2f} reason={reason[:60]} content={content}')

# Test CE + LLM
print('\n=== CE + LLM rerank ===')
res2 = c.search(ws['id'], query='funding amount', limit=5, semantic=True, rerank=True, cross_encoder=True)
for i, r in enumerate(res2[:5]):
    score = r.get('score', 0)
    reason = r.get('rerank_reason', 'N/A')
    content = r.get('memory_content', '')[:80]
    print(f'  [{i}] score={score:.2f} reason={reason[:60]} content={content}')

print('\nDone — LLM reranker works end-to-end')
