"""Background processing pipelines — Honcho/LangMem parity.

Provides a native (no Celery/RabbitMQ) background job system using
SpacetimeDB tables for persistence.  Includes:

- BackgroundDeriver: extracts explicit observations from messages/memories
- BackgroundSummarizer: auto-generates session summaries at thresholds
- Dreamer: deduction + induction pipeline (higher-order reasoning)
- ReflectionExecutor: priority queue, debouncing, deduplication

All state is stored in STDB tables — no external dependencies needed.

Reference: https://langmem.ai/background-processing
           https://honcho.dev/docs/background
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ._base import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes debounce cooldown
DEFAULT_MAX_BATCH = 10
DEFAULT_DERIVE_PRIORITY = 10
DEFAULT_SUMMARIZE_PRIORITY = 5
DEFAULT_DREAM_PRIORITY = 3

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BackgroundJob:
    """A background processing job, mirroring the STDB table."""

    id: str
    workspace_id: str
    job_type: str  # "derive" | "summarize" | "dream"
    status: str  # "queued" | "running" | "completed" | "failed"
    payload_json: str
    priority: int
    debounce_key: str
    created_at: int
    started_at: int
    completed_at: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BackgroundJob:
        return cls(
            id=d.get("id", ""),
            workspace_id=d.get("workspace_id", ""),
            job_type=d.get("job_type", ""),
            status=d.get("status", "queued"),
            payload_json=d.get("payload_json", "{}"),
            priority=d.get("priority", 0),
            debounce_key=d.get("debounce_key", ""),
            created_at=d.get("created_at", 0),
            started_at=d.get("started_at", 0),
            completed_at=d.get("completed_at", 0),
        )


# ---------------------------------------------------------------------------
# BackgroundProcessingMixin
# ---------------------------------------------------------------------------


class BackgroundProcessingMixin:
    """Spacetime-Memory background processing mixin.

    Provides native background job management with derivers, summarizers,
    dreamers, and a reflection executor that processes jobs via STDB tables.

    Usage::

        client = Client(...)

        # Enqueue jobs
        client.enqueue_derivation(
            workspace_id="ws-1",
            message_id="msg-123",
            content="Alice likes hiking in the mountains.",
        )
        client.enqueue_summarization(workspace_id="ws-1", session_id="sess-abc")
        client.enqueue_dream(workspace_id="ws-1", strategy="connect")

        # Process pending jobs
        results = client.process_background_jobs(workspace_id="ws-1", max_count=5)

        # Check job status
        status = client.get_background_job_status(workspace_id="ws-1")
    """

    # ------------------------------------------------------------------
    # 1. Enqueue methods
    # ------------------------------------------------------------------

    def enqueue_derivation(
        self,
        workspace_id: str,
        message_id: str,
        content: str = "",
        priority: int = DEFAULT_DERIVE_PRIORITY,
    ) -> dict[str, Any]:
        """Enqueue a derivation job for a message.

        Extracts explicit observations from the message content using LLM
        and stores them as memories.

        Args:
            workspace_id: Target workspace.
            message_id: Source message ID to derive observations from.
            content: Message content (if not provided, fetched from DB).
            priority: Job priority (higher = processed first).

        Returns:
            Reducer result with job_id.
        """
        debounce_key = f"derive:{message_id}"
        payload = json.dumps({
            "message_id": message_id,
            "content": content,
        })
        return self._call("enqueue_background_job", [
            workspace_id,
            "derive",
            payload,
            priority,
            debounce_key,
        ])

    def enqueue_summarization(
        self,
        workspace_id: str,
        session_id: str,
        priority: int = DEFAULT_SUMMARIZE_PRIORITY,
    ) -> dict[str, Any]:
        """Enqueue a summarization job for a session.

        Auto-generates a session summary by analyzing session messages
        and existing memories.

        Args:
            workspace_id: Target workspace.
            session_id: Session to summarize.
            priority: Job priority (higher = processed first).

        Returns:
            Reducer result with job_id.
        """
        debounce_key = f"summarize:{session_id}"
        payload = json.dumps({
            "session_id": session_id,
        })
        return self._call("enqueue_background_job", [
            workspace_id,
            "summarize",
            payload,
            priority,
            debounce_key,
        ])

    def enqueue_dream(
        self,
        workspace_id: str,
        strategy: str = "connect",
        max_new: int = 5,
        priority: int = DEFAULT_DREAM_PRIORITY,
    ) -> dict[str, Any]:
        """Enqueue a dream/synthesis job.

        Generates synthetic memories using the specified strategy
        (connect, generalize, fill_gaps, contrast, or all).

        Args:
            workspace_id: Target workspace.
            strategy: Dreaming strategy.
            max_new: Maximum synthetic memories to generate.
            priority: Job priority (higher = processed first).

        Returns:
            Reducer result with job_id.
        """
        debounce_key = f"dream:{workspace_id}:{strategy}"
        payload = json.dumps({
            "strategy": strategy,
            "max_new": max_new,
        })
        return self._call("enqueue_background_job", [
            workspace_id,
            "dream",
            payload,
            priority,
            debounce_key,
        ])

    # ------------------------------------------------------------------
    # 2. Processing — the ReflectionExecutor
    # ------------------------------------------------------------------

    def process_background_jobs(
        self,
        workspace_id: str,
        max_count: int = DEFAULT_MAX_BATCH,
    ) -> list[dict[str, Any]]:
        """Process pending background jobs for a workspace.

        Dequeues up to ``max_count`` jobs, dispatches each to the
        appropriate handler (deriver/summarizer/dreamer), and updates
        status on completion or failure.

        This is the main entry point for the ReflectionExecutor.

        Args:
            workspace_id: Target workspace.
            max_count: Maximum number of jobs to process in this batch.

        Returns:
            List of result dicts for each processed job.
        """
        # Step 1: Dequeue jobs
        dequeue_result = self._call("dequeue_background_jobs", [
            workspace_id,
            max_count,
        ])
        if not dequeue_result:
            logger.info("process_background_jobs: no jobs to dequeue")
            return []

        # Step 2: Query for running jobs
        running_jobs = self._query_background_jobs(
            workspace_id=workspace_id,
            status="running",
            limit=max_count,
        )

        results: list[dict[str, Any]] = []
        for job in running_jobs:
            result = self._execute_background_job(workspace_id, job)
            results.append(result)

        return results

    def _execute_background_job(
        self,
        workspace_id: str,
        job: BackgroundJob,
    ) -> dict[str, Any]:
        """Execute a single background job and update its status."""
        job_id = job.id
        job_type = job.job_type

        try:
            if job_type == "derive":
                output = self._execute_derivation(workspace_id, job)
            elif job_type == "summarize":
                output = self._execute_summarization(workspace_id, job)
            elif job_type == "dream":
                output = self._execute_dream(workspace_id, job)
            else:
                raise ValueError(f"Unknown job type: {job_type}")

            # Mark as completed
            self._call("update_background_job_status", [
                workspace_id,
                job_id,
                "completed",
            ])

            return {
                "job_id": job_id,
                "job_type": job_type,
                "status": "completed",
                "output": output,
            }

        except Exception as e:
            logger.error(
                "Background job %s (%s) failed: %s",
                job_id,
                job_type,
                str(e),
            )
            # Mark as failed
            try:
                self._call("update_background_job_status", [
                    workspace_id,
                    job_id,
                    "failed",
                ])
            except Exception:
                pass

            return {
                "job_id": job_id,
                "job_type": job_type,
                "status": "failed",
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # 3. BackgroundDeriver
    # ------------------------------------------------------------------

    def _execute_derivation(
        self,
        workspace_id: str,
        job: BackgroundJob,
    ) -> list[dict[str, Any]]:
        """Execute a derivation job — extract observations from a message.

        Uses ObservationExtractionMixin.extract_observations if available,
        or the LLM directly to extract and store observations.
        """
        payload = json.loads(job.payload_json)
        message_id = payload.get("message_id", "")
        content = payload.get("content", "")

        # Fetch message content if not provided
        if not content and message_id:
            messages = self._query(
                "message",
                filter_dict={"id": message_id},
            )
            if messages:
                content = messages[0].get("content", "")

        if not content:
            return []

        # Use observation extraction if available (mixin)
        if hasattr(self, "extract_observations"):
            observations = self.extract_observations(content=content)
        else:
            # Fallback: use the LLM directly
            from ._obs_extraction import OBSERVATION_EXTRACTION_PROMPT, ObservationExtractionMixin
            prompt = f"{OBSERVATION_EXTRACTION_PROMPT}\n\nText:\n{content}\n\nObservations (JSON array):"
            raw = self._llm_complete(prompt)
            obs_mixin = ObservationExtractionMixin()
            observations = obs_mixin._parse_observation_json(raw)

        if not observations:
            return []

        stored: list[dict[str, Any]] = []
        for obs in observations:
            result = self.store(
                workspace_id=workspace_id,
                content=obs,
                summary=f"Extracted observation: {obs[:80]}",
                memory_type="observation",
                confidence=0.85,
                source_message_id=message_id,
                entities_json=json.dumps({"source": "background_derivation"}),
            )
            stored.append(result)

        logger.info(
            "BackgroundDeriver: extracted %d observations from message %s",
            len(stored),
            message_id,
        )
        return stored

    # ------------------------------------------------------------------
    # 4. BackgroundSummarizer
    # ------------------------------------------------------------------

    def _execute_summarization(
        self,
        workspace_id: str,
        job: BackgroundJob,
    ) -> dict[str, Any]:
        """Execute a summarization job — generate a session summary.

        Analyzes session messages and existing memories to generate
        a concise structured summary, then stores it in the session.
        """
        payload = json.loads(job.payload_json)
        session_id = payload.get("session_id", "")

        if not session_id:
            raise ValueError("No session_id in summarization payload")

        # Fetch session messages
        messages = self._query(
            "message",
            filter_dict={"session_id": session_id},
        )

        # Fetch session memories
        memories = self._query(
            "memory",
            filter_dict={"source_session_id": session_id},
        )

        if not messages and not memories:
            logger.info(
                "BackgroundSummarizer: no content for session %s",
                session_id,
            )
            return {"session_id": session_id, "summary": "", "message_count": 0}

        # Build summary from messages
        message_texts = [
            m.get("content", "") for m in messages if m.get("content")
        ]
        memory_texts = [
            m.get("content", "") for m in memories if m.get("content")
        ]

        combined = "\n".join(message_texts + memory_texts)
        if len(combined) > 8000:
            combined = combined[:8000] + "..."

        # Generate summary via LLM
        summary = self._generate_summary(combined, session_id)

        # Update session summary via reducer
        if summary:
            try:
                self._call("update_session_summary", [session_id, summary])
            except Exception as e:
                logger.warning(
                    "Failed to update session summary for %s: %s",
                    session_id,
                    e,
                )

        return {
            "session_id": session_id,
            "summary": summary,
            "message_count": len(messages),
            "memory_count": len(memories),
        }

    def _generate_summary(
        self,
        content: str,
        session_id: str,
    ) -> str:
        """Generate a structured summary from session content using LLM."""
        prompt = (
            "Summarize the following conversation/session content into 2-3 "
            "concise sentences. Capture the key topics, decisions, and outcomes.\n\n"
            f"Session ID: {session_id}\n\n"
            f"Content:\n{content}\n\n"
            "Summary:"
        )

        raw = self._llm_complete(prompt)
        if raw:
            return raw.strip()
        return ""

    # ------------------------------------------------------------------
    # 5. Dreamer — deduction + induction pipeline
    # ------------------------------------------------------------------

    def _execute_dream(
        self,
        workspace_id: str,
        job: BackgroundJob,
    ) -> list[dict[str, Any]]:
        """Execute a dream job — generate synthetic memories.

        Uses the existing synthesize_memories infrastructure if available,
        or performs basic connection/generalization analysis.
        """
        payload = json.loads(job.payload_json)
        strategy = payload.get("strategy", "connect")
        max_new = payload.get("max_new", 5)

        # Use the DreamMixin if available (mixin chain)
        if hasattr(self, "synthesize_memories") and callable(self.synthesize_memories):
            synthetic = self.synthesize_memories(
                workspace_id=workspace_id,
                strategy=strategy,
                max_new=max_new,
            )
        else:
            # Fallback: basic dedup-aware connection synthesis
            synthetic = self._basic_dream(
                workspace_id=workspace_id,
                strategy=strategy,
                max_new=max_new,
            )

        logger.info(
            "Dreamer: generated %d synthetic memories (strategy=%s)",
            len(synthetic),
            strategy,
        )
        return synthetic

    def _basic_dream(
        self,
        workspace_id: str,
        strategy: str = "connect",
        max_new: int = 5,
    ) -> list[dict[str, Any]]:
        """Fallback dream implementation when DreamMixin is not available."""
        from ._dreaming import (
            SYNTHETIC_MEMORY_TYPE,
        )

        memories = self._query(
            "memory",
            workspace_id=workspace_id,
            filter_dict={"workspace_id": workspace_id},
        )

        if not memories:
            return []

        synthetic: list[dict[str, Any]] = []
        if strategy in ("connect", "all"):
            synthetic.extend(self._dream_connect(
                workspace_id, memories, max_new, SYNTHETIC_MEMORY_TYPE,
            ))

        return synthetic[:max_new]

    def _dream_connect(
        self,
        workspace_id: str,
        memories: list[dict[str, Any]],
        max_new: int,
        synthetic_type: str,
    ) -> list[dict[str, Any]]:
        """Connect-related memories via token overlap analysis."""
        from ._dreaming import _extract_tokens, _jaccard_similarity

        if len(memories) < 2:
            return []

        results: list[dict[str, Any]] = []
        for i in range(len(memories)):
            if len(results) >= max_new:
                break
            for j in range(i + 1, len(memories)):
                if len(results) >= max_new:
                    break

                m1, m2 = memories[i], memories[j]
                c1, c2 = m1.get("content", ""), m2.get("content", "")
                if not c1 or not c2:
                    continue

                tokens1, tokens2 = _extract_tokens(c1), _extract_tokens(c2)
                jaccard = _jaccard_similarity(tokens1, tokens2)

                if 0.15 <= jaccard <= 0.85:
                    connection = (
                        f"Connection: '{c1[:120]}...' is related to "
                        f"'{c2[:120]}...' (relevance={jaccard:.2f})"
                    )

                    result = self.store(
                        workspace_id=workspace_id,
                        content=connection,
                        summary=f"Synthetic connection (relevance={jaccard:.2f})",
                        memory_type=synthetic_type,
                        confidence=min(0.9, 0.4 + jaccard * 0.5),
                        entities_json=json.dumps({
                            "source_memories": [m1.get("id", ""), m2.get("id", "")],
                        }),
                    )

                    results.append({
                        "id": result.get("id", ""),
                        "content": connection,
                        "strategy": "connect",
                        "relevance": round(jaccard, 4),
                    })

        return results

    # ------------------------------------------------------------------
    # 6. Job querying and status
    # ------------------------------------------------------------------

    def _query_background_jobs(
        self,
        workspace_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[BackgroundJob]:
        """Query background jobs from STDB."""
        filter_dict: dict[str, Any] = {"workspace_id": workspace_id}
        if status:
            filter_dict["status"] = status

        rows = self._query("background_job", filter_dict=filter_dict)
        rows.sort(key=lambda r: (-r.get("priority", 0), r.get("created_at", 0)))

        # Convert to BackgroundJob objects
        jobs = [BackgroundJob.from_dict(r) for r in rows]
        return jobs[:limit]

    def get_background_job_status(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Get background job status counts for a workspace.

        Returns a dict with counts of jobs in each status category.
        """
        all_jobs = self._query_background_jobs(workspace_id=workspace_id, limit=1000)

        counts: dict[str, int] = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "total": len(all_jobs),
        }

        for job in all_jobs:
            s = job.status
            if s in counts:
                counts[s] += 1

        # Get recent jobs
        recent = [
            {
                "id": j.id,
                "job_type": j.job_type,
                "status": j.status,
                "priority": j.priority,
                "created_at": j.created_at,
            }
            for j in all_jobs[:20]
        ]

        return {
            "workspace_id": workspace_id,
            "counts": counts,
            "recent_jobs": recent,
        }

    def list_background_jobs(
        self,
        workspace_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List background jobs, optionally filtered by status."""
        jobs = self._query_background_jobs(
            workspace_id=workspace_id,
            status=status,
            limit=limit,
        )
        return [
            {
                "id": j.id,
                "workspace_id": j.workspace_id,
                "job_type": j.job_type,
                "status": j.status,
                "priority": j.priority,
                "debounce_key": j.debounce_key,
                "created_at": j.created_at,
                "started_at": j.started_at,
                "completed_at": j.completed_at,
            }
            for j in jobs
        ]

    def _llm_complete(self, prompt: str) -> str:
        """Call the LLM with a completion prompt.

        Uses the configured LLM backend if available, otherwise logs a warning.
        Override this in subclasses to provide actual LLM integration.
        """
        llm = getattr(self, "_llm", None)
        if llm is not None and hasattr(llm, "complete"):
            try:
                return llm.complete(prompt)
            except Exception as e:
                logger.error("LLM completion failed: %s", e)
                return ""

        try:
            from spacetime_memory.local_llm import query_llm

            result = query_llm(prompt, system_prompt="You are a helpful assistant.")
            if result:
                return result
        except (ImportError, Exception) as e:
            logger.debug("local_llm not available: %s", e)

        logger.warning(
            "No LLM backend configured for background processing. "
            "Set up an LLM or override _llm_complete()."
        )
        return ""
