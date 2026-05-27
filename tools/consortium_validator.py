"""
tools/consortium_validator.py – Purpose-built multi-model validator for
high-risk foster care alerts.

Unlike the general ModelConsortium (which does Q&A synthesis), this validator
asks each LLM to return structured JSON with a boolean verdict and a confidence
score. Consensus is reached when the average confidence of the "valid=true"
votes meets the threshold.

Usage:
    validator = ConsortiumValidator()
    result = await validator.validate(child, family, risk_score, notes)
    if result["valid"]:
        # send alert

Environment variables:
    CONSORTIUM_MODELS     comma-separated Groq model IDs
                          default: "gemma2-9b-it,llama-3.1-8b-instant"
    CONSORTIUM_THRESHOLD  minimum average confidence to accept (0.0–1.0)
                          default: 0.7
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog
from langchain_groq import ChatGroq

logger = structlog.get_logger()

_VALIDATION_PROMPT = """\
You are a social work supervisor. Evaluate whether the following high-risk
placement disruption alert is genuine and warrants immediate caseworker review.

Child profile  : {child}
Foster family  : {family}
ML risk score  : {risk_score:.1f}%  (0 = stable, 100 = certain disruption)
Caseworker notes: {notes}

Respond in JSON only – no markdown, no extra text:
{{
  "valid": true or false,
  "confidence": <float 0.0–1.0>,
  "reason": "<one concise sentence>"
}}
"""


class ConsortiumValidator:
    """
    Queries multiple LLMs in parallel and reaches a consensus verdict.

    Args:
        model_names: list of Groq model IDs.
                     Defaults to CONSORTIUM_MODELS env var or
                     ["gemma2-9b-it", "llama-3.1-8b-instant"].
        threshold:   minimum average confidence of "valid=true" votes
                     required to approve the alert.
                     Defaults to CONSORTIUM_THRESHOLD env var or 0.7.
    """

    def __init__(
        self,
        model_names: list[str] | None = None,
        threshold: float | None = None,
    ) -> None:
        raw = os.getenv("CONSORTIUM_MODELS", "gemma2-9b-it,llama-3.1-8b-instant")
        self.model_names: list[str] = model_names or [
            m.strip() for m in raw.split(",") if m.strip()
        ]
        self.threshold: float = threshold if threshold is not None else float(
            os.getenv("CONSORTIUM_THRESHOLD", "0.7")
        )
        self._models: list[ChatGroq] = []
        for name in self.model_names:
            try:
                self._models.append(ChatGroq(model=name, temperature=0.0))
            except Exception as exc:  # noqa: BLE001
                logger.warning("consortium_validator.model_init_error",
                               model=name, error=str(exc))

    async def validate(
        self,
        child: dict[str, Any],
        family: dict[str, Any],
        risk_score: float,
        notes: str,
    ) -> dict[str, Any]:
        """
        Ask all models to evaluate the alert in parallel.

        Returns:
            valid      – True if consensus threshold is met
            confidence – average confidence of the "valid=true" votes (0–1)
            details    – per-model raw results
        """
        if not self._models:
            logger.warning("consortium_validator.no_models_available")
            return {"valid": True, "confidence": 1.0, "details": [],
                    "reason": "no models configured – alert passed through"}

        prompt = _VALIDATION_PROMPT.format(
            child=json.dumps(child, default=str),
            family=json.dumps(family, default=str),
            risk_score=risk_score,
            notes=notes[:300],
        )

        responses = await asyncio.gather(
            *[m.ainvoke(prompt) for m in self._models],
            return_exceptions=True,
        )

        details: list[dict[str, Any]] = []
        for i, resp in enumerate(responses):
            model_name = self.model_names[i] if i < len(self.model_names) else f"model-{i}"
            if isinstance(resp, Exception):
                logger.warning("consortium_validator.model_error",
                               model=model_name, error=str(resp))
                details.append({
                    "model": model_name,
                    "valid": False,
                    "confidence": 0.0,
                    "reason": f"model error: {resp}",
                })
                continue

            # Strip markdown fences if the model wraps its JSON
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            try:
                data = json.loads(raw)
                if "valid" not in data or "confidence" not in data:
                    raise ValueError("missing required fields")
                details.append({
                    "model":      model_name,
                    "valid":      bool(data["valid"]),
                    "confidence": float(data["confidence"]),
                    "reason":     data.get("reason", ""),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("consortium_validator.parse_error",
                               model=model_name, raw=raw[:200], error=str(exc))
                details.append({
                    "model":      model_name,
                    "valid":      False,
                    "confidence": 0.0,
                    "reason":     f"parse error: {exc}",
                })

        # Consensus: average confidence of models that voted "valid=true"
        valid_confs = [d["confidence"] for d in details if d["valid"]]
        avg_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 0.0
        final_valid = avg_conf >= self.threshold

        logger.info(
            "consortium_validator.result",
            valid=final_valid,
            confidence=avg_conf,
            threshold=self.threshold,
            votes=[{"model": d["model"], "valid": d["valid"],
                    "conf": d["confidence"]} for d in details],
        )

        return {
            "valid":      final_valid,
            "confidence": avg_conf,
            "details":    details,
        }
