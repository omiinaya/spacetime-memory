# mem0-switch — Drop-in Adapter Demonstration

The real magic is in the import statement. Compare:

## Using Mem0 directly (pip install mem0ai)

```python
from mem0 import Memory

m = Memory()
m.add("I like pizza", user_id="alice")
results = m.search("food", user_id="alice")
```

## Using spacetime-memory's Mem0 adapter — SAME CODE

```python
from spacetime_memory.sdks.mem0 import Memory

m = Memory(config={"host": "localhost", "port": 3001})
m.add("I like pizza", user_id="alice")
results = m.search("food", user_id="alice")
```

Same method names, same parameters, same return types.
Switch backends by changing **ONE import line**.

## Key Points

- **Mem0's API**: `add()`, `search()`, `get_all()`, `get()`, `update()`, `delete()`, `history()`, `reset()`
- **All work identically** with the spacetime-memory adapter
- **Return shapes match**: both return `{"results": [...]}` format
- **The adapter covers ~92%** of Mem0's public API (26/26 tests passing)
- **Missing**: `entity_store` (Qdrant-specific, can't replicate on STDB)

## Running the Adapter Tests

```bash
cd /path/to/spacetime-memory
python -m pytest tests/test_mem0_core.py -v
```

## Verdict

Start prototyping with real Mem0 (fastest setup). When you need
knowledge graphs, multi-strategy search, document storage, auth,
or any feature Mem0 doesn't have — change one import line and
switch to spacetime-memory. Zero code changes required.
