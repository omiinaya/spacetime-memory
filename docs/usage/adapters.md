# SDK Adapters

All adapters live in `sdk/python/spacetime_memory/sdks/` and are importable as drop-in replacements for their respective memory library APIs.

---

## Mem0 Adapter

**Import:** `from spacetime_memory.sdks import Mem0Memory`

Replaces `mem0.Memory`. Stores memories via SpacetimeDB instead of the default Mem0 backend.

```python
from spacetime_memory.sdks import Mem0Memory

m = Mem0Memory()
m.add("I like pizza", user_id="alice")
m.add("My favorite color is blue", user_id="alice")

# Search
results = m.search("food preferences", user_id="alice")

# Get specific memory
mem = m.get(memory_id="...")

# List all
all_mems = m.get_all(user_id="alice")

# Update
m.update(memory_id="...", data="I love pizza!")

# History
history = m.history(memory_id="...")

# Delete
m.delete(memory_id="...")
m.delete_all(user_id="alice")
```

**API Surface:** `add()`, `search()`, `get()`, `get_all()`, `update()`, `delete()`, `delete_all()`, `history()`

---

## Graphiti Adapter

**Import:** `from spacetime_memory.sdks import Graphiti`

Replaces `graphiti.Graphiti`. Provides a knowledge-graph interface backed by SpacetimeDB's graph infrastructure.

```python
from spacetime_memory.sdks import Graphiti

g = Graphiti()

# Add a triplet (subject, relation, object)
g.add_triplet("Alice", "likes", "pizza")

# Add an episodic memory
g.add_episode("Alice ordered pizza for dinner")

# Search the graph
results = g.search("What does Alice like?")

# Alternative search
results = g.search_("Alice")

# Get entity edge summary
summary = g.get_entity_edge_summary("Alice")

# Remove an episode
g.remove_episode(episode_id="...")

# Build communities (label propagation clustering)
g.build_communities()
```

**API Surface:** `add_triplet()`, `add_episode()`, `search()`, `search_()`, `get_entity_edge_summary()`, `remove_episode()`, `build_communities()`

---

## LangChain / LangGraph Adapter

**Import:** `from spacetime_memory.sdks import StmemStore, StmemMemoryStore`

Provides both `LangGraph BaseStore` and `LangChain BaseStore` interfaces.

```python
from spacetime_memory.sdks import StmemStore, StmemMemoryStore

# LangGraph BaseStore interface
store = StmemStore()
store.put(("namespaces", "path"), "key", {"data": "value"})
item = store.get(("namespaces", "path"), "key")
results = store.search(("namespaces", "path"))
store.delete(("namespaces", "path"), "key")
store.list_namespaces()

# Batched operations
store.batch([...])

# LangChain BaseStore interface
mstore = StmemMemoryStore()
mstore.mset({"key1": "value1", "key2": "value2"})
values = mstore.mget(["key1", "key2"])
mstore.mdelete(["key1"])
for key in mstore.yield_keys():
    print(key)
```

**API Surface (LangGraph):** `get/put/delete/search/list_namespaces/batch`
**API Surface (LangChain):** `mget/mset/mdelete/yield_keys`

---

## Zep Adapter

**Import:** `from spacetime_memory.sdks import ZepClient, Memory, MemorySearchResult, Session`

Replaces `zep.Zep`. Provides memory storage, session management, and fact extraction.

```python
from spacetime_memory.sdks import ZepClient

zep = ZepClient()

# Add a memory
zep.add(session_id="session-1", content="Alice likes pizza")

# Get a memory
memory = zep.get(memory_id="...")

# Delete a memory
zep.delete(memory_id="...")

# Session CRUD
session = zep.add_session(user_id="alice")
sessions = zep.list_sessions(user_id="alice")

# Search across sessions
results = zep.search(text="pizza", session_id="session-1")

# Messages
zep.add_message(session_id="session-1", role="user", content="Hello")

# Facts
zep.extract_facts(session_id="session-1")
```

**API Surface:** `add()`, `get()`, `delete()`, sessions CRUD, search, messages, facts

---

## Hindsight Adapter

**Import:** `from spacetime_memory.sdks import Hindsight`

Replaces `hindsight.Hindsight`. Inspired by the [Hindsight](https://github.com/vectorize-io/hindsight) project's mental-model approach.

```python
from spacetime_memory.sdks import Hindsight

h = Hindsight()

# Retain a memory
h.retain("I like pizza", source="chat")
h.retain("My favorite color is blue", source="profile")

# Recall memories matching a query
results = h.recall("What food do I like?")
for r in results:
    print(r["content"])

# Reflect — generate insights over stored memories
insights = h.reflect()
for i in insights:
    print(i["insight"])

# Forget a specific memory
h.forget(memory_id="...")
```

**API Surface:** `retain()`, `recall()`, `reflect()`, `forget()`

---

## Honcho Adapter

**Import:** `from spacetime_memory.sdks import Honcho`

Replaces `honcho.Honcho`. Provides user and session management with memory storage.

```python
from spacetime_memory.sdks import Honcho

honcho = Honcho()

# Create a user
user = honcho.create_user(name="alice")
print(user["id"])

# Create a session
session = honcho.create_session(user_id=user["id"])
print(session["id"])

# Add a memory
honcho.add("I like pizza", session_id=session["id"])

# Search memories
results = honcho.search("food", session_id=session["id"])

# Get all user memories
all_mems = honcho.get_user_memories(user_id=user["id"])
```

**API Surface:** `create_user()`, `create_session()`, `add()`, `search()`, `get_user_memories()`
