"""Graphiti communities mixin — community detection and saga summarization."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from ...llm import LLMClient
from ._models import (
    CommunityEdge,
    CommunityNode,
    SagaNode,
)
from ._utils import _esc

logger = logging.getLogger("spacetime_memory.sdks.graphiti")


class GraphitiCommunities:
    """Mixin providing build_communities and related methods."""

    def build_communities(self, group_ids: list[str] | None = None) -> list[CommunityNode]:
        """Run community detection on the knowledge graph.

        Delegates to SpacetimeDB's ``detect_communities`` reducer.

        Args:
            group_ids: List of workspace names.  Uses first if multiple.

        Returns:
            List of CommunityNode objects.
        """
        gid = group_ids[0] if group_ids else "default"
        ws_id = self._resolve_workspace(gid)
        try:
            self._client.detect_communities(ws_id)
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data
        try:
            self._client.seed_communities(ws_id)
        except RuntimeError:
            pass  # non-fatal — operation may fail under concurrent load or missing data

        community_nodes = self._client._query(
            "kg_node", workspace_id=ws_id, filter_dict={"node_type": "community"}
        )

        communities: list[CommunityNode] = []
        community_edges: list[CommunityEdge] = []
        for row in community_nodes:
            community = CommunityNode(
                uuid=row.get("id", ""),
                name=row.get("label", ""),
                group_id=gid,
                summary=row.get("summary", ""),
            )
            # Fetch community edges (member relationships)
            try:
                edge_rows = self._client._query(
                    "kg_edge",
                    workspace_id=ws_id,
                    filter_dict={"source_node_id": community.uuid},
                )
                for erow in edge_rows:
                    community_edges.append(
                        CommunityEdge(
                            uuid=erow.get("id", ""),
                            source_node_uuid=erow.get("source_node_id", ""),
                            target_node_uuid=erow.get("target_node_id", ""),
                            group_id=gid,
                        )
                    )
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data
            # Generate LLM name and summary if not already set
            if (
                not community.summary
                or not community.name
                or community.name.startswith("community_")
            ):
                try:
                    llm = LLMClient()
                    if llm.available:
                        # Fetch member nodes and edges for this community
                        member_rows = self._sql_query(
                            "SELECT n.* FROM community_edge ce "
                            "JOIN kg_node n ON ce.target_node_uuid = n.id "
                            f"WHERE ce.source_node_uuid = '{_esc(community.uuid)}'"
                        )
                        edge_rows = self._sql_query(
                            "SELECT e.* FROM community_edge ce "
                            "JOIN kg_edge e ON ce.target_node_uuid = e.id "
                            f"WHERE ce.source_node_uuid = '{_esc(community.uuid)}'"
                        )
                        nodes_for_llm = [
                            {
                                "name": r.get("label", r.get("id", "")[:12]),
                                "summary": r.get("summary", ""),
                            }
                            for r in member_rows
                        ]
                        edges_for_llm = [
                            {
                                "source_node": r.get("source_node_id", "")[:12],
                                "target_node": r.get("target_node_id", "")[:12],
                                "relation": r.get("relation", ""),
                                "fact": r.get("fact", ""),
                            }
                            for r in edge_rows
                        ]

                        # Generate name + summary via LLM
                        entity_names = [n.get("name", "?") for n in nodes_for_llm]
                        name_prompt = (
                            f"Based on these entity names: {entity_names}, "
                            "generate a short community name (2-5 words) and a 1-sentence description "
                            "of what this community represents. "
                            'Return JSON: {"name": "...", "summary": "..."}'
                        )
                        name_result = llm.chat(
                            [
                                {
                                    "role": "system",
                                    "content": "You are a concise knowledge graph analyst. Return ONLY valid JSON, no markdown, no explanation.",
                                },
                                {"role": "user", "content": name_prompt},
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.3,
                        )
                        if name_result:
                            try:
                                parsed = json.loads(name_result)
                                llm_name = parsed.get("name", "").strip()
                                llm_summary = parsed.get("summary", "").strip()
                                if llm_name and (
                                    not community.name or community.name.startswith("community_")
                                ):
                                    community.name = llm_name
                                if llm_summary:
                                    community.summary = llm_summary
                            except (json.JSONDecodeError, TypeError):
                                pass  # corrupt attribute data — skip this entry gracefully

                        # Fall back to summarize_community if summary still empty
                        if not community.summary:
                            summary_text = llm.summarize_community(
                                community.name or community.uuid[:12],
                                nodes_for_llm,
                                edges_for_llm,
                            )
                            if summary_text:
                                community.summary = summary_text

                        # Persist updated name/summary
                        if community.summary or community.name:
                            try:
                                self._client._call(
                                    "update_node",
                                    [
                                        community.uuid,
                                        community.name,
                                        "community",
                                        community.summary,
                                        "{}",
                                    ],
                                )
                            except RuntimeError:
                                pass  # non-fatal — operation may fail under concurrent load or missing data
                except RuntimeError as exc:
                    logger.warning("build_communities() failed to process community: %s", exc)
            communities.append(community)

        return communities

    # -------------------------------------------------------------------
    # Saga operations
    # -------------------------------------------------------------------


    def summarize_saga(self, saga_id: str) -> SagaNode:
        """Generate or update an incremental summary for an episode saga.

        Queries all episodes linked to *saga_id* (via ``source_session_id``),
        uses the LLM to produce an incremental summary, and persists the
        result as a :class:`SagaNode` in the knowledge graph
        (``node_type="saga"``).

        Args:
            saga_id: The saga / session identifier.  Maps to
                ``source_session_id`` on the memory table.

        Returns:
            A :class:`SagaNode` with the current summary and episode range.

        Graceful degradation: returns a SagaNode with minimal metadata
        when no LLM is available.
        """
        now = datetime.now(UTC)

        # Query episodes linked to this saga
        episodes = self._client._query(
            "memory",
            filter_dict={"source_session_id": saga_id},
            columns=["id", "content", "created_at", "peer_id", "workspace_id"],
        )

        if not episodes:
            # No episodes yet — return a stub
            return SagaNode(
                uuid=saga_id,
                name=saga_id[:64],
                group_id="default",
                created_at=now,
                summary="",
            )

        # Sort by created_at ascending
        episodes.sort(key=lambda e: e.get("created_at", 0))

        first_ep = episodes[0]
        last_ep = episodes[-1]
        group_id = first_ep.get("workspace_id", "default")
        saga_name = first_ep.get("peer_id", saga_id)[:64] or saga_id[:64]

        first_ep_uuid = first_ep.get("id", "")
        last_ep_uuid = last_ep.get("id", "")

        # Build episode content for LLM summarization
        episode_texts = []
        for ep in episodes:
            content = ep.get("content", "")
            ep_id = ep.get("id", "")[:12]
            if content:
                episode_texts.append(f"[{ep_id}] {content[:500]}")
            else:
                episode_texts.append(f"[{ep_id}] (no content)")

        combined = "\n".join(episode_texts)

        # Try LLM summarization
        summary = ""
        last_summarized_at: datetime | None = None
        try:
            llm = LLMClient()
            if llm.available:
                prompt = (
                    f"You are summarizing an episode saga with {len(episodes)} episodes. "
                    "Write a concise 3-5 sentence summary of the key events, entities, "
                    "and narrative arc across all episodes.\n\n"
                    f"### Episodes\n{combined}"
                )
                result = llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "You are a precise summarization assistant. Summarize the following episode log concisely while preserving key facts, entities, and narrative arc.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=512,
                )
                if result:
                    summary = result.strip()
                    last_summarized_at = now
        except RuntimeError:
            logger.warning("summarize_saga() LLM call failed for saga %s", saga_id)

        # Build SagaNode
        saga = SagaNode(
            uuid=saga_id,
            name=saga_name,
            group_id=group_id,
            created_at=now,
            summary=summary,
            first_episode_uuid=first_ep_uuid,
            last_episode_uuid=last_ep_uuid,
            last_summarized_at=last_summarized_at,
            last_summarized_episode_valid_at=(
                datetime.fromtimestamp(last_ep.get("created_at", 0) / 1_000_000, tz=UTC)
                if last_ep.get("created_at", 0) and last_ep.get("created_at", 0) > 1e12
                else datetime.fromtimestamp(last_ep.get("created_at", 0), tz=UTC)
                if last_ep.get("created_at", 0)
                else now
            ),
        )

        # Persist as a kg_node with node_type="saga"
        ws_id = self._resolve_workspace(group_id)
        try:
            self._client.create_node(
                workspace_id=ws_id,
                label=saga_name,
                node_type="saga",
                summary=summary,
                metadata_json=json.dumps(
                    {
                        "saga_id": saga_id,
                        "first_episode_uuid": first_ep_uuid,
                        "last_episode_uuid": last_ep_uuid,
                        "episode_count": len(episodes),
                    }
                ),
            )
        except RuntimeError:
            # Node may already exist — try updating
            try:
                self._client._call(
                    "update_node",
                    [
                        saga_id,
                        saga_name,
                        "saga",
                        summary,
                        json.dumps(
                            {
                                "saga_id": saga_id,
                                "first_episode_uuid": first_ep_uuid,
                                "last_episode_uuid": last_ep_uuid,
                                "episode_count": len(episodes),
                            }
                        ),
                    ],
                )
            except RuntimeError:
                pass  # non-fatal — operation may fail under concurrent load or missing data

        return saga

    # -------------------------------------------------------------------
    # Episode removal
    # -------------------------------------------------------------------

