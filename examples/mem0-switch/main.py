#!/usr/bin/env python3
"""mem0-switch demo — Drop-in adapter for Mem0 API."""
import os
from spacetime_memory.sdks.mem0 import Memory
m = Memory(config={"host": os.environ.get("STMEM_HOST", "localhost"),
                   "port": int(os.environ.get("STMEM_PORT", "3001"))})
try: m._client._call("register", [f"demo_{os.urandom(4).hex()}", "Demo", "demopass"])
except RuntimeError: pass
print("=== Mem0-Switch Demo ===")
print("Adapter: spacetime_memory.sdks.mem0.Memory")
print("API: mem0.Memory.add / search / get_all / update")
print("Ready! Use: m.add('I like pizza', user_id='alice')")
m.add("I like pizza and pasta", user_id="alice")
print(f"Stored. Searching...")
results = m.search("food", user_id="alice")
for r in results.get("results", []):
    print(f"  Found: {r.get('memory', r.get('id', ''))[:60]}")
print("Done.\n")
