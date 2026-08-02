#!/usr/bin/env python3
"""
Add trace_span! wrappers to all #[reducer] functions across all Rust files.

Run: python3 add_trace_span.py
Working dir: $HOME/spacetime-memory/server/spacetimedb/src/
"""

import os
import re
import sys

SRC = os.path.dirname(os.path.abspath(__file__))

# Files already done
ALREADY_DONE = {"memory.rs", "hybrid_query.rs", "tracing.rs", "add_trace_span.py"}

# Manual overrides for TracingSpanKind
KIND_OVERRIDES = {
    # workspace.rs
    "check_space_access": "TracingSpanKind::Read",
    "get_workspace_context": "TracingSpanKind::Read",
    "list_space_members": "TracingSpanKind::Read",
    "get_memory_stats": "TracingSpanKind::Read",
    # session.rs
    "get_session": "TracingSpanKind::Read",
    "get_session_steps": "TracingSpanKind::Read",
    "list_sessions": "TracingSpanKind::Read",
    # connector.rs
    # All Write
    # tag.rs
    "list_tags": "TracingSpanKind::Read",
    "list_tags_by_memory": "TracingSpanKind::Read",
    # entity_linking.rs
    # All Write
    # note.rs
    # All Write
    # message.rs
    # All Write
    # retrieval.rs
    "search": "TracingSpanKind::Read",
    "batch_reindex": "TracingSpanKind::Admin",
    # consolidation.rs
    "get_consolidation_log": "TracingSpanKind::Read",
    "get_consolidation_candidates": "TracingSpanKind::Read",
    "get_rollup_candidates": "TracingSpanKind::Read",
    "get_decay_candidates": "TracingSpanKind::Read",
    # memory_feedback.rs
    "get_peer_reputation": "TracingSpanKind::Read",
    "update_workspace_config": "TracingSpanKind::Admin",
    "run_decay": "TracingSpanKind::Admin",
    # knowledge_graph.rs
    "get_edge_history": "TracingSpanKind::Read",
    "get_citations": "TracingSpanKind::Read",
    # profile_query.rs
    "get_profile_context": "TracingSpanKind::Read",
    "search_profiles": "TracingSpanKind::Read",
    "get_peer_memory_summary": "TracingSpanKind::Read",
    "search_directory_contents": "TracingSpanKind::Read",
    # profile.rs
    "get_profile": "TracingSpanKind::Read",
    "list_profiles": "TracingSpanKind::Read",
    "search_peers": "TracingSpanKind::Read",
    "get_profile_stats": "TracingSpanKind::Read",
    # user.rs
    "get_user": "TracingSpanKind::Read",
    "list_users": "TracingSpanKind::Read",
    "get_user_sessions": "TracingSpanKind::Read",
    # peer.rs
    # All Write
    # graph_traversal.rs
    "graph_bfs": "TracingSpanKind::Read",
    "shortest_path": "TracingSpanKind::Read",
    "get_neighbors": "TracingSpanKind::Read",
    "detect_bridge_nodes": "TracingSpanKind::Read",
    "compute_kg_stats": "TracingSpanKind::Read",
    # document.rs
    # All Write (create_document, add_chunk, delete_document)
    # tour.rs
    # All Write
    # insight.rs
    # All Write
    # context_directory.rs
    "get_children": "TracingSpanKind::Read",
    "traverse_recursive": "TracingSpanKind::Read",
    "get_directory": "TracingSpanKind::Read",
    # context_delta.rs
    "get_delta": "TracingSpanKind::Read",
    # context_compression.rs
    # All Write
    # harmonic_belief.rs
    # All Write
    # auth.rs - auth reducers
    # Read vs Write depending on function
    # change_event.rs
    "get_changes": "TracingSpanKind::Read",
    "get_change_count": "TracingSpanKind::Read",
    "clear_changes": "TracingSpanKind::Admin",
    # proxy_metrics.rs
    # Write
    # replication.rs
    "list_replication_peers": "TracingSpanKind::Read",
    "get_unsynced_entries": "TracingSpanKind::Read",
    "get_replication_status": "TracingSpanKind::Read",
    "get_replication_peer_by_id": "TracingSpanKind::Read",
    # query.rs
    "query_table": "TracingSpanKind::Read",
}

# Workspace_id args: files where most reducers have workspace_id param
# Files where some don't have it
# We'll detect this from the function signature

DEFAULT_KIND = "TracingSpanKind::Write"


def get_kind(fn_name):
    return KIND_OVERRIDES.get(fn_name, DEFAULT_KIND)


def has_workspace_param(fn_body_header):
    """Check if the function signature lines contain a workspace_id parameter."""
    return 'workspace_id:' in fn_body_header or 'workspace_id :' in fn_body_header


def add_imports_if_missing(content):
    """Add trace_span imports after last use crate:: line."""
    lines = content.split('\n')
    
    has_trace_span_import = any('use crate::trace_span;' in l for l in lines)
    has_kind_import = any('use crate::tracing::TracingSpanKind;' in l for l in lines)
    
    if has_trace_span_import and has_kind_import:
        return '\n'.join(lines), False
    
    # Find last 'use crate::' line
    last_idx = -1
    for i, l in enumerate(lines):
        stripped = l.strip()
        if stripped.startswith('use crate::') and not stripped.startswith('use crate::{'):
            last_idx = i
        # Also handle use crate::{...} blocks
        if stripped.startswith('use crate::{'): 
            last_idx = i
    
    if last_idx < 0:
        print("  WARNING: No 'use crate::' import found")
        return '\n'.join(lines), False
    
    insert_lines = []
    if not has_trace_span_import:
        insert_lines.append('use crate::trace_span;')
    if not has_kind_import:
        insert_lines.append('use crate::tracing::TracingSpanKind;')
    
    # Insert after last_idx
    result = lines[:last_idx+1] + insert_lines + lines[last_idx+1:]
    return '\n'.join(result), True


def find_matching_brace(lines, open_line_idx):
    """Find the matching closing } for the brace at open_line_idx."""
    open_line = lines[open_line_idx]
    brace_idx_in_line = open_line.index('{')
    
    depth = 0
    for i in range(open_line_idx, len(lines)):
        line = lines[i]
        for j, ch in enumerate(line):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i  # This line has the closing brace
        if depth == 0 and i > open_line_idx:
            # Opening brace must have been on this line or before
            pass
    return None


def wrap_reducer(content, reducer_line_idx):
    """
    Wrap a #[reducer] function body with trace_span.
    Returns (new_content, modified) tuple.
    """
    lines = content.split('\n')
    
    # Find function signature
    fn_name = None
    sig_start = None
    sig_end = None
    
    for i in range(reducer_line_idx, min(reducer_line_idx + 20, len(lines))):
        m = re.search(r'pub(?:\(crate\))?\s+fn\s+(\w+)', lines[i])
        if m:
            fn_name = m.group(1)
            sig_start = i
            break
    
    if not fn_name:
        return content, False
    
    # Find the function body opening {
    body_open_line = None
    body_open_col = None
    
    for i in range(sig_start, min(sig_start + 25, len(lines))):
        line = lines[i]
        if '{' in line:
            body_open_line = i
            body_open_col = line.index('{')
            break
    
    if body_open_line is None:
        return content, False
    
    # Find matching closing brace for the function
    close_line = find_matching_brace(lines, body_open_line)
    if close_line is None:
        return content, False
    
    # Check if trace_span is already present
    for i in range(body_open_line, min(body_open_line + 5, len(lines))):
        if 'trace_span!' in lines[i]:
            return content, False  # Already has trace_span
    
    # Get function signature text for workspace_id detection
    sig_text = '\n'.join(lines[sig_start:body_open_line+1])
    has_ws = has_workspace_param(sig_text)
    
    kind = get_kind(fn_name)
    ws_arg = '&workspace_id' if has_ws else '""'
    
    # Get the indentation
    indent = lines[body_open_line][:body_open_col]
    inner_indent = indent + '    '
    
    # The body content (everything between the braces)
    if body_open_line == close_line:
        # Body is `fn() { ... }` on one line
        line = lines[body_open_line]
        brace_idx = line.index('{')
        last_brace_idx = line.rindex('}')
        existing_body = line[brace_idx+1:last_brace_idx].strip()
        
        if existing_body:
            new_line = (line[:brace_idx] + '{' +
                       '\n' + inner_indent + f'trace_span!(ctx, "{fn_name}", {kind}, {ws_arg}, {{' +
                       '\n' + inner_indent + '    ' + existing_body +
                       '\n' + inner_indent + '    })' +
                       '\n' + indent + '}')
            lines[body_open_line] = new_line
        else:
            lines[body_open_line] = (line[:brace_idx] + '{' +
                                    '\n' + inner_indent + f'trace_span!(ctx, "{fn_name}", {kind}, {ws_arg}, {{}})' +
                                    '\n' + indent + '}')
    else:
        # Multi-line body
        # 1. Replace opening brace line
        old_open = lines[body_open_line]
        new_open = old_open[:old_open.index('{')] + '{'
        lines[body_open_line] = new_open
        
        # 2. Insert trace_span opening after the opening brace
        ts_open = inner_indent + f'trace_span!(ctx, "{fn_name}", {kind}, {ws_arg}, {{'
        lines.insert(body_open_line + 1, ts_open)
        
        # Now close_line is one position further
        close_line += 1
        
        # 3. Add the macro closing before the function closing brace
        ts_close = inner_indent + '    })'
        lines.insert(close_line, ts_close)
        
        # 4. Re-indent the original body lines (they need one more level of indentation)
        for i in range(body_open_line + 2, close_line):
            if lines[i].strip():  # non-empty
                lines[i] = inner_indent + lines[i]
            else:
                lines[i] = inner_indent
    
    return '\n'.join(lines), True


def process_file(fpath):
    """Process a single Rust file, adding trace_span wrappers."""
    basename = os.path.basename(fpath)
    
    with open(fpath, 'r') as f:
        content = f.read()
    
    # Add imports
    content, imports_added = add_imports_if_missing(content)
    
    # Find all #[reducer] positions
    lines = content.split('\n')
    reducer_lines = [i for i, l in enumerate(lines) if l.strip() == '#[reducer]']
    
    if not reducer_lines:
        return 0, False
    
    total_wrapped = 0
    changed = False
    
    # Process in reverse order so line indices don't shift
    for rl in reversed(reducer_lines):
        content, wrapped = wrap_reducer(content, rl)
        if wrapped:
            total_wrapped += 1
            changed = True
    
    if changed:
        with open(fpath, 'w') as f:
            f.write(content)
    
    return total_wrapped, changed


def main():
    files = sorted(os.listdir(SRC))
    
    total_wrapped = 0
    total_files = 0
    
    for fname in files:
        if not fname.endswith('.rs'):
            continue
        if fname in ALREADY_DONE:
            continue
        
        fpath = os.path.join(SRC, fname)
        count, changed = process_file(fpath)
        
        if changed:
            print(f"  {fname:30s} → {count} reducers wrapped")
            total_wrapped += count
            total_files += 1
        elif count > 0:
            # File has reducers but none needed wrapping
            pass
    
    print(f"\nTotal: {total_wrapped} reducers wrapped across {total_files} files")


if __name__ == '__main__':
    main()
