"""LangGraph/LangChain memory store integration for Spacetime-Memory.

Provides ``StmemStore``, an implementation of LangGraph's ``BaseStore``
backed by Spacetime-Memory.

Usage::

    from langgraph.store.base import Item
    from spacetime_memory.sdks.langchain import StmemStore

    store = StmemStore(config={"host": "localhost", "port": 3001})

    # Store an item
    store.put(("users", "alice"), "preferences", {"likes": "pizza"})

    # Retrieve it
    item = store.get(("users", "alice"), "preferences")
    print(item.value)  # {"likes": "pizza"}

    # Search for items
    results = store.search(("users",), query="food")
    for r in results:
        print(r.value)

    # List namespaces
    namespaces = store.list_namespaces(prefix=("users",))

Also provides a ``StmemMemoryStore`` that implements LangChain's
``BaseStore`` interface for simpler key-value usage::

    from spacetime_memory.sdks.langchain import StmemMemoryStore

    store = StmemMemoryStore(config={"host": "localhost", "port": 3001})
    store.mset([("key1", {"text": "hello"})])
    values = store.mget(["key1"])
"""

from __future__ import annotations

import json
import uuid as _uuid
from collections.abc import Iterator, Sequence
from typing import Any

from ..client import Client


# ---------------------------------------------------------------------------
# LangChain BaseStore interface
# ---------------------------------------------------------------------------


class StmemMemoryStore:
    """LangChain ``BaseStore``-compatible key-value store.

    Wraps Spacetime-Memory's memory table behind a simple
    ``BaseStore``-like interface:

    - ``mget(keys)`` — retrieve memories by ID
    - ``mset(key_value_pairs)`` — store memories
    - ``mdelete(keys)`` — deactivate memories
    - ``yield_keys(prefix)`` — list active memory IDs

    Each key-value pair maps to a SpacetimeDB ``memory`` record,
    with the value stored as JSON content.

    .. note::
       This is a **synchronous** implementation.  LangChain's
       ``BaseStore`` defines async methods (``amget``, ``amset``,
       etc.) that are not implemented here.  Use the sync versions
       in non-async contexts.

    Example::

        store = StmemMemoryStore(
            config={"host": "localhost", "port": 3001}
        )
        store.mset([("m1", {"role": "user", "content": "Hello!"})])
        values = store.mget(["m1"])
        for key in store.yield_keys():
            print(key)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        client: Client | None = None,
    ):
        config = config or {}
        if client is not None:
            self._client = client
        else:
            self._client = Client(
                host=config.get("host"),
                port=config.get("port"),
                database=config.get("db", config.get("database")),
                embedder_url=config.get("embedder_url"),
                token=config.get("token"),
            )
        self._workspace_id: str = config.get("workspace_id", "")

    def _ws(self) -> str:
        """Resolve workspace, creating a unique one scoped to the current identity."""
        if self._workspace_id:
            return self._workspace_id
        # Always create a fully unique workspace name per instance
        # to avoid stale workspace conflicts from other identities.
        caller_tag = _caller_tag(self._client)
        import uuid as _uid
        unique = _uid.uuid4().hex[:8]
        ws_name = f"lcmem-{caller_tag}-{unique}"
        try:
            self._client.create_workspace(ws_name)
        except RuntimeError:
            pass
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []
        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == ws_name:
                    self._workspace_id = ws["id"]
                    return ws["id"]
        self._workspace_id = "default"
        return "default"

    def mget(self, keys: Sequence[str]) -> list[Any | None]:
        """Get values for the given memory keys.

        Keys are looked up by ``source_session_id`` (not memory UUID),
        matching how ``mset`` stores them.

        Args:
            keys: Sequence of memory keys to retrieve.

        Returns:
            List of value dicts (or ``None`` for missing keys).
        """
        results: list[Any | None] = []
        ws_id = self._ws()
        for key in keys:
            try:
                rows = self._client._sql(
                    f"SELECT id, content, summary, memory_type, "
                    f"entities_json, created_at, updated_at "
                    f"FROM memory WHERE source_session_id = '{_esc(key)}' "
                    f"AND workspace_id = '{_esc(ws_id)}' "
                    f"AND is_active = true "
                )
            except RuntimeError:
                rows = []
            if rows:
                row = rows[0]
                results.append({
                    "id": row.get("id", ""),
                    "content": row.get("content", ""),
                    "summary": row.get("summary", ""),
                    "memory_type": row.get("memory_type", ""),
                    "metadata": _json_parse(row.get("entities_json", "{}")),
                    "created_at": row.get("created_at", 0),
                    "updated_at": row.get("updated_at", 0),
                })
            else:
                results.append(None)
        return results

    def mset(self, key_value_pairs: Sequence[tuple[str, Any]]) -> None:
        """Set values for the given memory keys.

        Args:
            key_value_pairs: Sequence of ``(key, value)`` pairs.
                Value is a dict that may contain ``content``, ``summary``,
                ``memory_type``, ``metadata`` keys.
        """
        ws_id = self._ws()
        for key, value in key_value_pairs:
            if isinstance(value, dict):
                content = str(value.get("content", value.get("text", str(value))))
                memory_type = value.get("memory_type", "memory")
                metadata = value.get("metadata", {})
            else:
                content = str(value)
                memory_type = "memory"
                metadata = {}

            try:
                self._client.store(
                    workspace_id=ws_id,
                    content=content,
                    memory_type=memory_type,
                    entities_json=json.dumps(metadata) if isinstance(metadata, dict) else json.dumps(metadata),
                    source_session_id=key,
                )
            except RuntimeError:
                pass

    def mdelete(self, keys: Sequence[str]) -> None:
        """Delete (deactivate) memories by key.

        Args:
            keys: Sequence of memory IDs to delete.
        """
        for key in keys:
            try:
                self._client.delete_memory(key)
            except RuntimeError:
                pass

    def yield_keys(self, *, prefix: str | None = None) -> Iterator[str]:
        """Yield memory IDs in the workspace, optionally filtered by prefix.

        Args:
            prefix: Optional content prefix filter.  Since SpacetimeDB
                doesn't support LIKE, filtering is done client-side.

        Yields:
            Memory ID strings.
        """
        ws_id = self._ws()
        try:
            rows = self._client._sql(
                "SELECT id, content FROM memory WHERE "
                f"workspace_id = '{_esc(ws_id)}' AND is_active = true"
            )
        except RuntimeError:
            return

        for row in rows:
            key = row.get("id", "")
            if key:
                if prefix:
                    content = row.get("content", "")
                    if not content.startswith(prefix):
                        continue
                yield key


# ---------------------------------------------------------------------------
# LangGraph BaseStore interface
# ---------------------------------------------------------------------------


class StmemStore:
    """LangGraph ``BaseStore`` implementation backed by Spacetime-Memory.

    Maps::

        namespace  → workspace_name (joined by "/")
        key        → memory_id or generated UUID
        value      → JSON-serialized dict (stored as memory content)
        index      → fields to make searchable (via ``memory_type``)

    The store uses a flat namespace → workspace mapping.  Nested
    namespaces like ``("users", "alice", "sessions")`` are mapped to
    workspace name ``"users/alice/sessions"``.

    Usage::

        from spacetime_memory.sdks.langchain import StmemStore

        store = StmemStore(config={"host": "localhost", "port": 3001})

        # Store
        store.put(("users", "alice"), "prefs", {"theme": "dark"})
        store.put(("users", "bob"), "prefs", {"theme": "light"})

        # Get
        item = store.get(("users", "alice"), "prefs")
        print(item.value["theme"])  # "dark"

        # Search (semantic)
        results = store.search(("users",), query="theme preferences")
        for item in results:
            print(item.namespace, item.key, item.value)

        # List namespaces
        namespaces = store.list_namespaces()
        # [("users",), ("users", "alice"), ("users", "bob")]

    **Note:** All methods are synchronous wrappers.  ``LangGraph``
    ``BaseStore`` defines async variants (``aget``, ``aput``, etc.)
    which are not implemented here for simplicity.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        client: Client | None = None,
    ):
        """
        Args:
            config: Dict with ``host``, ``port``, ``database``,
                ``token``, ``embedder_url`` keys.  Ignored if
                ``client`` is provided.
            client: An existing ``Client`` instance.
        """
        if client is not None:
            self._client = client
        else:
            config = config or {}
            try:
                self._client = Client(
                    host=config.get("host"),
                    port=config.get("port"),
                    database=config.get("db", config.get("database")),
                    embedder_url=config.get("embedder_url"),
                    token=config.get("token"),
                )
            except TypeError:
                # Fallback for older Client API
                self._client = Client(
                    host=config.get("host"),
                    port=config.get("port"),
                    database=config.get("db", config.get("database")),
                    embedder_url=config.get("embedder_url"),
                )
        # Cache: namespace_path -> workspace_id
        self._ns_cache: dict[str, str] = {}

    # -------------------------------------------------------------------
    # Namespace resolution
    # -------------------------------------------------------------------

    def _ns_to_ws(self, namespace: tuple[str, ...]) -> str:
        """Convert a namespace tuple to a workspace name (slash-joined)."""
        if not namespace:
            return f"langgraph-{_caller_tag(self._client)}"
        return "/".join(namespace)

    def _resolve_workspace(self, name: str) -> str:
        """Get or create a workspace by name.  Caches the UUID."""
        if name in self._ns_cache:
            return self._ns_cache[name]
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []
        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == name:
                    self._ns_cache[name] = ws["id"]
                    return ws["id"]
        # Create
        try:
            self._client.create_workspace(name)
        except RuntimeError:
            pass
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []
        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == name:
                    self._ns_cache[name] = ws["id"]
                    return ws["id"]
        self._ns_cache[name] = name
        return name

    def _sql(self, query: str) -> list[dict[str, Any]]:
        try:
            return self._client._sql(query)
        except RuntimeError:
            return []

    # -------------------------------------------------------------------
    # LangGraph BaseStore API (sync only)
    # -------------------------------------------------------------------

    def get(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> Item | None:
        """Retrieve a single item by namespace and key.

        Args:
            namespace: Namespace tuple (e.g. ``("users", "alice")``).
            key: Item key (maps to memory ID).
            refresh_ttl: Not supported (ignored).

        Returns:
            An ``Item`` if found, else ``None``.
        """
        ws_name = self._ns_to_ws(namespace)
        ws_id = self._resolve_workspace(ws_name)

        rows = self._sql(
            "SELECT * FROM memory WHERE "
            f"source_session_id = '{_esc(key)}' AND "
            f"workspace_id = '{_esc(ws_id)}' "
        )
        if not rows:
            return None

        row = rows[0]
        value = _memory_to_dict(row)
        return Item(
            value=value,
            key=key,
            namespace=namespace,
            created_at=row.get("created_at", 0),
            updated_at=row.get("updated_at", 0),
        )

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: bool | list[str] | None = None,
        *,
        ttl: float | None = None,
    ) -> None:
        """Store or update an item.

        Args:
            namespace: Namespace tuple.
            key: Item key (becomes ``source_session_id`` if provided,
                otherwise a UUID is generated).
            value: Dict with the item data.  ``content`` or ``text``
                key is used as the memory content; everything else is
                stored as JSON metadata.
            index: When ``True`` or a list of field names, the content
                is indexed for semantic search via the embedder.
            ttl: Not supported (ignored).
        """
        ws_name = self._ns_to_ws(namespace)
        ws_id = self._resolve_workspace(ws_name)

        # Extract content for embedding
        content = value.pop("content", value.pop("text", None))
        if content is None:
            content = json.dumps(value) if value else ""
        content_str = str(content)

        # Remaining value fields become metadata
        metadata_str = json.dumps(value) if value else "{}"
        memory_type = "searchable" if (index is True or isinstance(index, list)) else "memory"

        try:
            self._client.store(
                workspace_id=ws_id,
                content=content_str,
                summary=content_str[:200],
                memory_type=memory_type,
                source_session_id=key,
                entities_json=metadata_str,
            )
        except RuntimeError:
            pass

    def delete(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> None:
        """Delete an item by namespace and key.

        Args:
            namespace: Namespace tuple.
            key: Item key (memory ID).
        """
        ws_name = self._ns_to_ws(namespace)
        ws_id = self._resolve_workspace(ws_name)
        rows = self._sql(
            f"SELECT id FROM memory WHERE source_session_id = '{_esc(key)}' "
            f"AND workspace_id = '{_esc(ws_id)}'"
        )
        if rows:
            try:
                self._client.delete_memory(key)
            except RuntimeError:
                pass

    def search(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[SearchItem]:
        """Search for items within a namespace prefix.

        Uses Spacetime-Memory's hybrid search (semantic + keyword)
        when *query* is provided.  Falls back to keyword filtering
        for filter-only searches.

        Args:
            namespace_prefix: Namespace prefix to search within
                (e.g. ``("users",)`` to search all users).
            query: Semantic search query string.
            filter: Dict of metadata fields to filter on.
            limit: Max results to return (default 10).
            offset: Result offset for pagination (default 0).
            refresh_ttl: Not supported (ignored).

        Returns:
            List of ``SearchItem`` namedtuples with ``namespace``,
            ``key``, ``value``, ``score`` fields.
        """
        ws_name = self._ns_to_ws(namespace_prefix)
        ws_id = self._resolve_workspace(ws_name)

        all_rows: list[dict[str, Any]] = []

        if query:
            try:
                results = self._client.search(
                    workspace_id=ws_id,
                    query=query,
                    limit=limit + offset,
                    semantic=True,
                )
                for r in results:
                    eid = r.get("entity_id", "")
                    if eid:
                        mems = self._sql(
                            f"SELECT * FROM memory WHERE id = '{_esc(eid)}'"
                        )
                        if mems:
                            all_rows.append(mems[0])
            except RuntimeError:
                pass

        # If no semantic results or no query, fall back to listing
        if not all_rows:
            try:
                rows = self._sql(
                    "SELECT * FROM memory WHERE "
                    f"workspace_id = '{_esc(ws_id)}' "
                    "AND is_active = true"
                )
            except RuntimeError:
                rows = []

            # Client-side keyword filter
            if query:
                q = query.lower()
                rows = [
                    r for r in rows
                    if q in r.get("content", "").lower()
                    or q in r.get("summary", "").lower()
                ]
            if filter:
                rows = _apply_filter(rows, filter)
            all_rows = rows

        # Apply offset and limit
        all_rows = all_rows[offset:offset + limit]
        return [
            SearchItem(
                namespace=namespace_prefix,
                key=row.get("id", ""),
                value=_memory_to_dict(row),
                created_at=_to_dt(row.get("created_at", 0)),
                updated_at=_to_dt(row.get("updated_at", 0)),
                score=row.get("score", 0.0 if query else None),
            )
            for row in all_rows
        ]

    def list_namespaces(
        self,
        *,
        prefix: tuple[str, ...] | None = None,
        suffix: tuple[str, ...] | None = None,
        max_depth: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        """List namespaces that have stored items.

        Since Spacetime-Memory uses workspace names as namespaces,
        this lists all workspaces that contain active memories and
        extracts the namespace structure.

        Args:
            prefix: Filter namespaces starting with this prefix.
            suffix: Filter namespaces ending with this suffix.
            max_depth: Maximum namespace depth.
            limit: Max results (default 100).
            offset: Result offset (default 0).

        Returns:
            List of namespace tuples.
        """
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []

        namespaces: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()

        for ws in workspaces:
            name = ws.get("name", "")
            if not name:
                continue

            parts = tuple(name.split("/"))

            # Apply prefix filter
            if prefix and not name.startswith("/".join(prefix) + "/") and name != "/".join(prefix):
                continue
            # Apply suffix filter
            if suffix and not name.endswith("/".join(suffix)):
                continue
            # Apply max_depth
            if max_depth is not None and len(parts) > max_depth:
                parts = parts[:max_depth]

            # Generate all ancestor namespaces
            for i in range(1, len(parts) + 1):
                ns = parts[:i]
                if ns not in seen:
                    seen.add(ns)
                    namespaces.append(ns)

        namespaces.sort(key=lambda x: ("/".join(x),))
        return namespaces[offset:offset + limit]

    # -------------------------------------------------------------------
    # Batch operations (matching LangGraph BaseStore)
    # -------------------------------------------------------------------

    def batch(self, ops: Sequence[Any]) -> list[Any]:
        """Execute multiple operations in a single batch.

        Args:
            ops: Sequence of operations, each with a ``type`` field
                (``"get"``, ``"put"``, ``"delete"``, ``"search"``).

        Returns:
            List of results, one per operation.
        """
        results: list[Any] = []
        for op in ops:
            op_type = getattr(op, "type", None) if hasattr(op, "type") else None
            if not op_type and isinstance(op, dict):
                op_type = op.get("type")
            if op_type == "get":
                ns = getattr(op, "namespace", ())
                key = getattr(op, "key", "")
                results.append(self.get(tuple(ns), key))
            elif op_type == "put":
                ns = getattr(op, "namespace", ())
                key = getattr(op, "key", "")
                value = getattr(op, "value", {})
                self.put(tuple(ns), key, value)
                results.append(None)
            elif op_type == "delete":
                ns = getattr(op, "namespace", ())
                key = getattr(op, "key", "")
                self.delete(tuple(ns), key)
                results.append(None)
            elif op_type == "search":
                ns = getattr(op, "namespace_prefix", ())
                kw = getattr(op, "kwargs", {})
                results.append(self.search(tuple(ns), **kw))
            else:
                results.append(None)
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a SpacetimeDB memory row to a value dict."""
    value: dict[str, Any] = {
        "content": row.get("content", ""),
        "summary": row.get("summary", ""),
        "memory_type": row.get("memory_type", ""),
    }
    # Merge metadata
    meta = _json_parse(row.get("entities_json", "{}"))
    if meta and isinstance(meta, dict):
        value["metadata"] = meta
    return value


def _apply_filter(
    rows: list[dict[str, Any]], filter: dict[str, Any]
) -> list[dict[str, Any]]:
    """Client-side metadata filter."""
    if not filter:
        return rows
    filtered = []
    for row in rows:
        meta = _json_parse(row.get("entities_json", "{}"))
        if not isinstance(meta, dict):
            meta = {}
        match = True
        for k, v in filter.items():
            if meta.get(k) != v:
                match = False
                break
        if match:
            filtered.append(row)
    return filtered


def _caller_tag(client: Client) -> str:
    """Get a short tag derived from the JWT identity for workspace naming.

    Uses the token hash if available, otherwise 'anon'.
    """
    if hasattr(client, "token") and client.token:
        return _hash_hex(client.token)[:12]
    return "anon"


def _hash_hex(val: str) -> str:
    """SHA-256 hex digest."""
    import hashlib
    return hashlib.sha256(val.encode()).hexdigest()


def _to_dt(micros: int) -> str:
    """Convert SpacetimeDB micros to ISO datetime string."""
    if not micros:
        return ""
    try:
        ts = micros / 1_000_000
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return ""


def _json_parse(val: Any) -> Any:
    """Safely parse a JSON value."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val and val != "{}":
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _esc(val: str) -> str:
    """Basic SQL string escaping."""
    return val.replace("'", "''")


# ---------------------------------------------------------------------------
# BaseChatMessageHistory interface
# ---------------------------------------------------------------------------


class StmemChatMessageHistory:
    """LangChain ``BaseChatMessageHistory`` implementation backed by Spacetime-Memory.

    Stores chat messages as SpacetimeDB memory records with
    ``memory_type='chat_message'``.  Each conversation is identified by a
    ``session_id``, and messages are persisted in creation order.

    Usage::

        from langchain_core.messages import HumanMessage, AIMessage
        from spacetime_memory.sdks.langchain import StmemChatMessageHistory

        history = StmemChatMessageHistory(
            session_id="conversation-1",
            config={"host": "localhost", "port": 3001},
        )

        # Add messages
        history.add_messages([
            HumanMessage(content="Hello!"),
            AIMessage(content="Hi there!"),
        ])

        # Retrieve all messages
        for msg in history.messages:
            print(f"{msg.type}: {msg.content}")

        # Clear the history
        history.clear()

    .. note::
       LangChain's ``BaseChatMessageHistory`` defines async methods
       (``async_add_messages``, ``aclear``) that are not implemented
       here.  Use the sync versions in non-async contexts.
    """

    def __init__(
        self,
        session_id: str,
        config: dict[str, Any] | None = None,
        client: Client | None = None,
    ):
        """Initialise a new chat-message history.

        Args:
            session_id: Identifier for the conversation.  All messages
                for this session will be stored with
                ``source_session_id = session_id``.
            config: Dict with ``host``, ``port``, ``database``,
                ``token``, ``embedder_url`` keys.  Ignored if
                ``client`` is provided.  May also contain
                ``workspace_id`` to specify the target workspace.
            client: An existing ``Client`` instance.
        """
        self.session_id = session_id
        config = config or {}
        if client is not None:
            self._client = client
        else:
            self._client = Client(
                host=config.get("host"),
                port=config.get("port"),
                database=config.get("db", config.get("database")),
                embedder_url=config.get("embedder_url"),
                token=config.get("token"),
            )
        self._workspace_id: str = config.get("workspace_id", "")

    # -------------------------------------------------------------------
    # Workspace resolution
    # -------------------------------------------------------------------

    def _resolve_workspace(self) -> str:
        """Return a workspace ID for storing chat messages.

        If ``workspace_id`` was provided in ``config`` it is returned
        directly.  Otherwise a workspace named ``"chat_history"`` is
        created (or looked up) and cached.
        """
        if self._workspace_id:
            return self._workspace_id
        name = "chat_history"
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []
        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == name:
                    self._workspace_id = ws["id"]
                    return ws["id"]
        # Create the workspace
        try:
            self._client.create_workspace(name)
        except RuntimeError:
            pass
        try:
            workspaces = self._client.list_workspaces()
        except RuntimeError:
            workspaces = []
        if isinstance(workspaces, list):
            for ws in workspaces:
                if ws.get("name") == name:
                    self._workspace_id = ws["id"]
                    return ws["id"]
        self._workspace_id = "default"
        return "default"

    # -------------------------------------------------------------------
    # BaseChatMessageHistory API
    # -------------------------------------------------------------------

    @property
    def messages(self) -> list:
        """Return all messages for this session ordered by creation time.

        Returns:
            List of LangChain ``BaseMessage`` subclass instances
            (``HumanMessage``, ``AIMessage``, ``SystemMessage``,
            ``ToolMessage``, etc.) in the order they were stored.
        """
        ws_id = self._resolve_workspace()
        from langchain_core.messages import messages_from_dict

        try:
            rows = self._client._sql(
                "SELECT id, content, memory_type, entities_json, created_at "
                "FROM memory WHERE "
                f"source_session_id = '{_esc(self.session_id)}' "
                f"AND workspace_id = '{_esc(ws_id)}' "
                "AND memory_type = 'chat_message' "
                "AND is_active = true "
                "ORDER BY created_at ASC"
            )
        except RuntimeError:
            return []

        if not rows:
            return []

        message_dicts = []
        for row in rows:
            try:
                msg_data = json.loads(row.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            # The stored dict should have at least "type" and "content"
            # keys (serialised by ``message_to_dict``).  Fold in any
            # extra metadata stored in entities_json.
            if not isinstance(msg_data, dict):
                continue
            meta = _json_parse(row.get("entities_json", "{}"))
            if isinstance(meta, dict):
                # Merge metadata into additional_kwargs if present
                kwargs = msg_data.setdefault("additional_kwargs", {})
                kwargs.setdefault("memory_id", row.get("id", ""))
            message_dicts.append(msg_data)

        if not message_dicts:
            return []

        try:
            return messages_from_dict(message_dicts)
        except Exception:
            # Fallback: return raw dicts if deserialisation fails
            return message_dicts

    def add_messages(self, messages: Sequence) -> None:
        """Store a sequence of chat messages.

        Each message is serialised with ``message_to_dict`` and stored
        as a SpacetimeDB memory record with ``memory_type='chat_message'``.

        Args:
            messages: Sequence of ``BaseMessage`` instances to persist.
        """
        ws_id = self._resolve_workspace()
        from langchain_core.messages import message_to_dict

        for msg in messages:
            try:
                msg_dict = message_to_dict(msg)
            except Exception:
                # Fallback: manual serialisation
                msg_dict = {
                    "type": getattr(msg, "type", "human"),
                    "content": getattr(msg, "content", ""),
                    "additional_kwargs": getattr(msg, "additional_kwargs", {}),
                }

            content_str = json.dumps(msg_dict, ensure_ascii=False)

            # Store tool_calls metadata if present
            meta = {}
            tool_calls = getattr(msg, "tool_calls", [])
            if tool_calls:
                meta["tool_calls"] = tool_calls
            invalid_tool_calls = getattr(msg, "invalid_tool_calls", [])
            if invalid_tool_calls:
                meta["invalid_tool_calls"] = invalid_tool_calls

            try:
                self._client.store(
                    workspace_id=ws_id,
                    content=content_str,
                    summary=f"chat: {content_str[:200]}",
                    memory_type="chat_message",
                    source_session_id=self.session_id,
                    entities_json=json.dumps(meta) if meta else "{}",
                )
            except RuntimeError:
                pass

    def clear(self) -> None:
        """Remove all chat messages for this session.

        Messages are soft-deleted (``is_active`` set to ``false``)
        in SpacetimeDB.
        """
        ws_id = self._resolve_workspace()
        try:
            rows = self._client._sql(
                f"SELECT id FROM memory WHERE "
                f"source_session_id = '{_esc(self.session_id)}' "
                f"AND workspace_id = '{_esc(ws_id)}' "
                "AND memory_type = 'chat_message' "
                "AND is_active = true"
            )
        except RuntimeError:
            rows = []

        for row in rows:
            mem_id = row.get("id", "")
            if mem_id:
                try:
                    self._client.delete_memory(mem_id)
                except RuntimeError:
                    pass

    # -------------------------------------------------------------------
    # Convenience
    # -------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"StmemChatMessageHistory(session_id={self.session_id!r}, "
            f"message_count={len(self._try_count())})"
        )

    def _try_count(self) -> list:
        """Quick count of stored messages (best-effort, no deserialisation)."""
        ws_id = self._resolve_workspace()
        try:
            rows = self._client._sql(
                "SELECT COUNT(*) as cnt FROM memory WHERE "
                f"source_session_id = '{_esc(self.session_id)}' "
                f"AND workspace_id = '{_esc(ws_id)}' "
                "AND memory_type = 'chat_message' "
                "AND is_active = true"
            )
            if rows:
                return [rows[0].get("cnt", 0)]
        except RuntimeError:
            pass
        return []


# ---------------------------------------------------------------------------
# Type stubs for LangGraph types
# ---------------------------------------------------------------------------

try:
    from langgraph.store.base import Item, SearchItem
except ImportError:
    # Minimal type stubs when langgraph isn't installed
    from collections import namedtuple  # type: ignore[no-redef]

    class Item(namedtuple("Item", ["value", "key", "namespace", "created_at", "updated_at"])):  # type: ignore[no-redef]
        """Minimal stub for ``langgraph.store.base.Item``."""

    class SearchItem(namedtuple("SearchItem", [  # type: ignore[no-redef]
        "namespace", "key", "value", "created_at", "updated_at", "score"
    ])):
        """Minimal stub for ``langgraph.store.base.SearchItem``."""
        __slots__ = ()  # type: ignore[assignment]
        # Provide a default of None for score
        def __new__(cls, namespace, key, value, created_at, updated_at, score=None):
            return super().__new__(cls, namespace, key, value, created_at, updated_at, score)
