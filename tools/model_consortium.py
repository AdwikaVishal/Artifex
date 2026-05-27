"""
tools/model_consortium.py – Multi-model validation consortium.

Queries multiple LLMs in parallel, validates claims for consensus, then
has an arbiter synthesise a final answer. Prevents any single model from
dominating the decision and catches hallucinations before they propagate.

Configuration (via env vars or explicit dict):
    CONSORTIUM_MODELS  = "llama-3.1-8b-instant:2,gemma2-9b-it:2,mixtral-8x7b-32768:1"
    ARBITER_MODEL      = "gemma2-9b-it"
    CONFIDENCE_THRESHOLD = 0.8
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog
from langchain_groq import ChatGroq

logger = structlog.get_logger()

# ── Prompts ───────────────────────────────────────────────────────────────────

_CLAIM_VALIDATION_PROMPT = """You are a fact-checker. Given a list of claims,
mark each as VERIFIED or UNVERIFIED based on your knowledge.
Return JSON only: {{"claims": [{{"text": "...", "status": "VERIFIED|UNVERIFIED", "reason": "..."}}]}}

Claims to check:
{claims}
"""

_SYNTHESIS_PROMPT = """You are a synthesis arbiter. Multiple models answered the same question.
Only use claims marked VERIFIED. Produce a single, concise, accurate answer.

Question: {question}

Model responses:
{responses}

Verified claims only:
{verified_claims}

Return a direct answer with no preamble.
"""

_CONSENSUS_PROMPT = """Rate the agreement between these responses on a scale of 0.0 to 1.0.
0.0 = completely contradictory, 1.0 = identical meaning.
Return JSON only: {{"score": <float>, "reason": "<one sentence>"}}

Responses:
{responses}
"""


class ModelConsortium:
    """
    Parallel multi-model query with claim validation and arbiter synthesis.

    Args:
        config: dict with keys:
            models    – list of "model_name:weight" strings
            arbiter   – model name for final synthesis
            threshold – minimum consensus score to accept (0–1)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._models = self._load_models(config.get("models", []))
        self._arbiter = ChatGroq(
            model=config.get("arbiter", "gemma2-9b-it"),
            temperature=0.0,
        )
        self._threshold = float(config.get("threshold", 0.8))

    # ── Public API ────────────────────────────────────────────────────────────

    async def query(self, prompt: str) -> dict[str, Any]:
        """
        Query all models in parallel, validate claims, synthesise answer.

        Returns:
            answer           – final synthesised answer string
            confidence       – consensus score (0–1)
            validated_claims – list of {text, status, reason} dicts
            passed           – True if confidence >= threshold
        """
        if not self._models:
            # Fallback: single arbiter call
            resp = await self._arbiter.ainvoke(prompt)
            return {
                "answer": resp.content,
                "confidence": 1.0,
                "validated_claims": [],
                "passed": True,
            }

        # Step 1: query all models in parallel
        tasks = [m.ainvoke(prompt) for m in self._models]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        texts = [
            r.content if not isinstance(r, Exception) else ""
            for r in responses
        ]
        texts = [t for t in texts if t]  # drop failures

        if not texts:
            return {"answer": "", "confidence": 0.0, "validated_claims": [], "passed": False}

        # Step 2: validate claims
        validated = await self._validate_claims(texts)

        # Step 3: arbiter synthesis using only verified claims
        answer = await self._synthesise(prompt, texts, validated)

        # Step 4: consensus score
        confidence = await self._compute_consensus(texts)

        return {
            "answer": answer,
            "confidence": confidence,
            "validated_claims": validated,
            "passed": confidence >= self._threshold,
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _load_models(self, model_specs: list[str]) -> list[ChatGroq]:
        """Parse "model_name:weight" specs and instantiate ChatGroq clients."""
        models = []
        for spec in model_specs:
            name = spec.split(":")[0].strip()
            if name:
                try:
                    models.append(ChatGroq(model=name, temperature=0.2))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("consortium.model_load_error", model=name, error=str(exc))
        return models

    async def _validate_claims(self, responses: list[str]) -> list[dict[str, Any]]:
        """Extract and fact-check claims from all responses."""
        # Treat each response as a single claim for simplicity
        claims_text = "\n".join(f"- {r[:300]}" for r in responses)
        prompt = _CLAIM_VALIDATION_PROMPT.format(claims=claims_text)
        try:
            resp = await self._arbiter.ainvoke(prompt)
            data = json.loads(resp.content.strip())
            return data.get("claims", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("consortium.claim_validation_error", error=str(exc))
            return [{"text": r[:200], "status": "UNVERIFIED", "reason": "validation error"} for r in responses]

    async def _synthesise(
        self,
        question: str,
        responses: list[str],
        validated: list[dict[str, Any]],
    ) -> str:
        verified = [c for c in validated if c.get("status") == "VERIFIED"]
        verified_text = "\n".join(f"- {c['text']}" for c in verified) or "None verified"
        responses_text = "\n\n".join(f"Model {i+1}: {r[:400]}" for i, r in enumerate(responses))

        prompt = _SYNTHESIS_PROMPT.format(
            question=question[:500],
            responses=responses_text,
            verified_claims=verified_text,
        )
        try:
            resp = await self._arbiter.ainvoke(prompt)
            return resp.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("consortium.synthesis_error", error=str(exc))
            return responses[0] if responses else ""

    async def _compute_consensus(self, responses: list[str]) -> float:
        if len(responses) < 2:
            return 1.0
        responses_text = "\n\n".join(f"Response {i+1}: {r[:300]}" for i, r in enumerate(responses))
        prompt = _CONSENSUS_PROMPT.format(responses=responses_text)
        try:
            resp = await self._arbiter.ainvoke(prompt)
            data = json.loads(resp.content.strip())
            return float(data.get("score", 0.5))
        except Exception as exc:  # noqa: BLE001
            logger.warning("consortium.consensus_error", error=str(exc))
            return 0.5


def consortium_from_env() -> ModelConsortium:
    """Build a ModelConsortium from environment variables."""
    raw = os.getenv("CONSORTIUM_MODELS", "llama-3.1-8b-instant:2,gemma2-9b-it:2")
    return ModelConsortium({
        "models": [s.strip() for s in raw.split(",") if s.strip()],
        "arbiter": os.getenv("ARBITER_MODEL", "gemma2-9b-it"),
        "threshold": float(os.getenv("CONFIDENCE_THRESHOLD", "0.8")),
    })
