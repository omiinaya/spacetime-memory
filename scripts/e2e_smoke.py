#!/usr/bin/env python3
"""
E2E smoke test for spacetime-memory module.
Usage: python3 scripts/e2e_smoke.py [--db DB_ID]

Tests the full lifecycle against a live published module:
  register → create_workspace → store_memory → hybrid_search

Requires:
  - SpacetimeDB running on localhost:3001
  - Embedder sidecar on :9090 (optional, falls back to keyword)
  - Tantivy sidecar on :9091 (optional, falls back)
"""

import sys, requests, json, uuid, os, argparse

def main():
    parser = argparse.ArgumentParser(description='E2E smoke test for spacetime-memory')
    parser.add_argument('--stdb', default='http://localhost:3001',
                        help='SpacetimeDB base URL')
    parser.add_argument('--db', default='spacetime-memory-v2',
                        help='Database name or identity')
    args = parser.parse_args()

    # Resolve DB identity
    stdb = args.stdb
    db = args.db

    # If it looks like a name (not a hex identity), resolve it
    if '-' in db and len(db) < 40:
        import subprocess
        res = subprocess.run(
            ['spacetime', 'list', '--server', stdb],
            capture_output=True, text=True, timeout=10
        )
        for line in res.stdout.split('\n'):
            if db in line:
                db = line.split('|')[-1].strip()
                break

    print(f'STDB: {stdb}  DB: {db}')
    base = f'{stdb}/v1/database/{db}'

    # 1. Register
    suf = uuid.uuid4().hex[:6]
    r = requests.post(f'{base}/call/register', json=[f'e2e-{suf}', f'E2E {suf}', 'test123456'])
    assert r.status_code == 200, f'Register: {r.status_code}'
    token = r.headers.get('spacetime-identity-token', '')
    assert token, 'No identity token'
    h = {'Authorization': f'Bearer {token}'}
    print(f'  REGISTER: OK')

    # 2. Create workspace
    ws = f'ws-{suf}'
    r = requests.post(f'{base}/call/create_workspace', headers=h, json=[ws, 'E2E', ws])
    assert r.status_code == 200, f'Workspace: {r.status_code}'
    print(f'  WORKSPACE: OK')

    # 3. Store memory
    r = requests.post(f'{base}/call/store_memory', headers=h,
        json=[ws, '', '', 'general', 'Rust systems programming is memory-safe', '', '', 0.9, '', '', '[]'])
    assert r.status_code == 200, f'Store: {r.status_code}'
    print(f'  STORE: OK')

    # 4. Hybrid search
    r = requests.post(f'{base}/call/hybrid_search', headers=h,
        json=[ws, 'Rust programming', '', 'all', '', 5, '', 0, False])
    assert r.status_code == 200, f'Search: {r.status_code}'
    print(f'  SEARCH: OK')

    print(f'\n✅ E2E SMOKE TEST PASSED')
    return 0

if __name__ == '__main__':
    sys.exit(main())
