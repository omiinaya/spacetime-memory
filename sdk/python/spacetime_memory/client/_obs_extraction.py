"""Observation extraction mixin — extract explicit observations from text.

Uses LLM to extract structured observations from messages, memories, or
any text content.  Each observation is a concise, atomic statement about
a fact, preference, or event that can be stored as a memory.

Reference: Honcho/LangMem observation extraction pattern.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default LLM prompt for observation extraction
# ---------------------------------------------------------------------------

OBSERVATION_EXTRACTION_PROMPT = """You are an expert at extracting explicit observations from text.

Given a piece of text, extract all explicit, atomic observations. Each observation
should be a single sentence stating an objective fact, preference, event, or
relationship that is DIRECTLY stated in the text (not inferred).

Rules:
1. Each observation must be a standalone sentence (1 sentence, max 200 chars).
2. Do NOT add interpretations, inferences, or assumptions.
3. Do NOT combine multiple facts into one observation.
4. Extract ONLY what is explicitly stated.
5. Aim for 1-5 observations per text input.
6. Return as a JSON array of strings.

Examples:

Input: "Alice loves hiking in the mountains and she works as a software engineer at Google."
Output: ["Alice loves hiking in the mountains.", "Alice works as a software engineer at Google."]

Input: "The meeting was scheduled for 3pm but got cancelled because Bob was sick."
Output: ["The meeting was scheduled for 3pm.", "The meeting was cancelled.", "Bob was sick."]

Input: "I think the new design is nice but maybe too colorful."
Output: ["The user thinks the new design is nice.", "The user finds the new design too colorful."]

Now extract observations from the following text.
Return ONLY a JSON array of strings, no other text.
"""


class ObservationExtractionMixin:
    """Mixin for extracting explicit observations from text using LLM.

    Provides methods to extract atomic observations from any text content
    and optionally store them as memories.

    Usage::

        client = Client(...)

        # Extract observations from text
        observations = client.extract_observations(
            "Alice said she prefers async communication and works remotely."
        )

        # Extract and store as memories
        result = client.store_observations(
            workspace_id="ws-1",
            content="John manages the infrastructure team and uses Kubernetes.",
        )
    """

    def extract_observations(
        self,
        content: str,
        llm_prompt: str = OBSERVATION_EXTRACTION_PROMPT,
        max_observations: int = 10,
    ) -> list[str]:
        """Extract explicit observations from text using LLM.

        Args:
            content: The text to extract observations from.
            llm_prompt: Custom prompt template (default: OBSERVATION_EXTRACTION_PROMPT).
            max_observations: Maximum number of observations to return.

        Returns:
            A list of observation strings.

        Raises:
            RuntimeError: If the LLM extraction fails.
        """
        if not content or not content.strip():
            return []

        prompt = f"{llm_prompt}\n\nText:\n{content}\n\nObservations (JSON array):"
        raw = self._llm_complete(prompt)

        if not raw:
            logger.warning("extract_observations: LLM returned empty response")
            return []

        observations = self._parse_observation_json(raw)
        return observations[:max_observations]

    def _parse_observation_json(self, raw: str) -> list[str]:
        """Parse the LLM response into a list of observation strings.

        Tries JSON parsing first, then falls back to line-by-line extraction.
        """
        raw = raw.strip()

        # Try to extract JSON array from the response
        # (LLMs sometimes wrap in markdown code blocks)
        if raw.startswith("```"):
            # Find the JSON content within code blocks
            start = raw.find("[")
            end = raw.rfind("]")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]

        # Try JSON parse
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(o).strip() for o in parsed if str(o).strip()]
            return []
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: split by newlines and clean up
        lines = []
        for line in raw.split("\n"):
            line = line.strip().strip("-").strip('"').strip("'").strip()
            if line and not line.startswith("```") and not line.startswith("Text:"):
                # Remove leading numbering
                if line[0].isdigit() and ". " in line[:4]:
                    line = line.split(". ", 1)[1]
                lines.append(line)

        return lines

    def _llm_complete(self, prompt: str) -> str:
        """Call the LLM with a completion prompt.

        Uses the configured LLM backend if available, otherwise logs a warning.
        Override this in subclasses to provide actual LLM integration.
        """
        # Try to use the client's LLM infrastructure
        llm = getattr(self, "_llm", None)
        if llm is not None and hasattr(llm, "complete"):
            try:
                return llm.complete(prompt)
            except Exception as e:
                logger.error("LLM completion failed: %s", e)
                return ""

        # Try using the local_llm module if available
        try:
            from spacetime_memory.local_llm import query_llm

            result = query_llm(prompt, system_prompt="You extract observations from text.")
            if result:
                return result
        except (ImportError, Exception) as e:
            logger.debug("local_llm not available: %s", e)

        logger.warning(
            "No LLM backend configured for observation extraction. "
            "Set up an LLM or override _llm_complete()."
        )
        return ""

    def store_observations(
        self,
        workspace_id: str,
        content: str,
        source_session_id: str = "",
        source_message_id: str = "",
        memory_type: str = "observation",
        confidence: float = 0.8,
        max_observations: int = 10,
    ) -> list[dict[str, Any]]:
        """Extract observations from text and store each as a memory.

        Args:
            workspace_id: Target workspace.
            content: Text to extract observations from.
            source_session_id: Optional source session ID.
            source_message_id: Optional source message ID.
            memory_type: Memory type for stored observations.
            confidence: Confidence score for stored observations.
            max_observations: Maximum observations to extract and store.

        Returns:
            List of stored memory dicts, one per observation.
        """
        observations = self.extract_observations(
            content=content,
            max_observations=max_observations,
        )

        if not observations:
            logger.info(
                "store_observations: no observations extracted from content in workspace %s",
                workspace_id,
            )
            return []

        stored: list[dict[str, Any]] = []
        for obs in observations:
            result = self.store(
                workspace_id=workspace_id,
                content=obs,
                summary=f"Observation: {obs[:80]}",
                memory_type=memory_type,
                confidence=confidence,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
                entities_json=json.dumps({"source": "observation_extraction"}),
            )
            stored.append(result)

        logger.info(
            "store_observations: stored %d observations in workspace %s",
            len(stored),
            workspace_id,
        )
        return stored
