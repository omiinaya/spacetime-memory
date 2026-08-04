#!/usr/bin/env python3
"""Check which modules have trace_span on all their reducers."""
import os, re, subprocess, sys

src = os.path.expanduser('~/spacetime-memory/server/spacetimedb/src')

for f in sorted(os.listdir(src)):
    if not f.endswith('.rs'): continue
    path = os.path.join(src, f)
    with open(path) as fh:
        text = fh.read()
    
    # Count #[reducer] annotations (actual, not in comments)
    reducer_count = 0
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped == '#[reducer]':
            reducer_count += 1
    
    # Count trace_span! usage
    trace_count = text.count('trace_span!')
    
    if reducer_count > 0:
        status = 'OK' if reducer_count == trace_count else f'MISMATCH'
        print(f"{status:8s} {f:25s} reducers={reducer_count:3d} trace_spans={trace_count:3d}")
