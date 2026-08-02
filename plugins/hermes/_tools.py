"""Tool schemas for SpacetimeDB memory plugin."""

from __future__ import annotations

SEARCH_SCHEMA = {
    "name": "spacetime_search",
    "description": (
        "Search all memories, notes, and knowledge-graph nodes by semantic meaning "
        "and keywords. Returns ranked results across all entity types."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "limit": {
                "type": "integer",
                "description": "Max results (default: 10, max: 50).",
            },
        },
        "required": ["query"],
    },
}

STORE_SCHEMA = {
    "name": "spacetime_store",
    "description": (
        "Store a durable memory, fact, or observation. "
        "Auto-embeds for semantic search. Use for preferences, corrections, decisions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact or memory to store.",
            },
            "summary": {
                "type": "string",
                "description": "Optional short summary.",
            },
            "memory_type": {
                "type": "string",
                "description": "Type: world_fact, experience, mental_model (default: experience).",
                "enum": ["world_fact", "experience", "mental_model"],
            },
        },
        "required": ["content"],
    },
}

NOTE_SEARCH_SCHEMA = {
    "name": "spacetime_notes",
    "description": (
        "Search or list markdown notes. Returns titles, dates, backlink counts. "
        "Use to find notes relevant to the conversation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional keyword to search note titles/content.",
            },
            "limit": {"type": "integer", "description": "Max results (default: 20)."},
        },
        "required": [],
    },
}

KG_SCHEMA = {
    "name": "spacetime_kg",
    "description": (
        "Query the knowledge graph — find nodes, their connections, and communities. "
        "Use for understanding relationships between entities."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Node label or keyword to search for.",
            },
        },
        "required": ["query"],
    },
}

PROFILE_SCHEMA = {
    "name": "spacetime_profile",
    "description": (
        "Get or create a user profile with static facts and dynamic context. "
        "Use for long-term user modeling."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "peer_id": {
                "type": "string",
                "description": "Peer/user identifier.",
            },
            "fact": {
                "type": "string",
                "description": "Optional fact to add to profile.",
            },
        },
        "required": ["peer_id"],
    },
}
