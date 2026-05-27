"""
ValidatorAgent – checks execution results and decides next action.

Listens on:  agent.validator.inbox
Publishes:
  api.result            – if result is valid and no tasks remain
  agent.executor.inbox  – if more tasks remain
  agent.retriever.inbox – if next task is retrieve
  agent.planner.replan  – if result is invalid (triggers replanning)
  validator.failed      – for Recovery agent to diagnose

Validation strategy by task type
──────────────────────────────────
search        → check snippets are non-empty and relevant; LLM relevance check
direct_answer → check confidence; reject "I don't know" answers; LLM plausibility check
execute/http  → generic LLM critic
retrieve      → generic LLM critic
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage
from prometheus_client import Counter

from nats_client.subjects import Subjects
from .base import BaseAgent
from tools.model_consortium import consortium_from_env

logger = structlog.get_logger()

# ── Prometheus ────────────────────────────────────────────────────────────────
HALLUCINATION_REJECTIONS = Counter(
    "artifex_hallucination_rejections_total",
    "Results rejected due to suspected hallucination or low confidence",
    ["agent", "task_type"],
)
SEARCH_VALIDATIONS = Counter(
    "artifex_search_validations_total",
    "Search result validations",
    ["agent", "outcome"],   # outcome: passed | failed
)

# ── Prompts ───────────────────────────────────────────────────────────────────

GENERIC_CRITIC_PROMPT = """You are a result validator. Given a task and its result, decide if the
result is acceptable. Return JSON only:
{"valid": true/false, "reason": "<brief explanation>", "suggestion": "<how to fix if invalid>"}
"""

SEARCH_RELEVANCE_PROMPT = """You are checking whether web search results are relevant to a goal.

Goal: {goal}
Search query: {query}
Top snippet: {snippet}

Is the snippet relevant to the goal? Return JSON only:
{{"relevant": true/false, "reason": "<one sentence>"}}
"""

DIRECT_ANSWER_PLAUSIBILITY_PROMPT = """You are checking whether an LLM-generated answer is
plausible and not hallucinated.

Question: {question}
Answer: {answer}
Confidence declared by LLM: {confidence}

Is this answer factually plausible? Return JSON only:
{{"plausible": true/false, "reason": "<one sentence>"}}
"""


class ValidatorAgent(BaseAgent):
    def __init__(self) -> None:
        # Support per-instance model and NATS subject via env vars so that
        # validator-a and validator-b can run as separate containers with
        # different LLMs without any code changes.
        import os as _os
        model_name   = _os.getenv("VALIDATOR_MODEL", "llama-3.1-8b-instant")
        inbox_subject = _os.getenv("VALIDATOR_SUBJECT", Subjects.VALIDATOR_INBOX)
        instance_name = _os.getenv("VALIDATOR_INSTANCE", "validator")

        super().__init__(name=instance_name, metrics_port=9094)
        self._inbox_subject = inbox_subject
        self._llm = ChatGroq(model=model_name, temperature=0.0)
        self._log.info("validator.init", model=model_name, subject=inbox_subject)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe(self._inbox_subject, self.handle_validate, queue="validator")
        # Emergent swarm: bid on announced tasks
        await self.subscribe(Subjects.TASK_ANNOUNCEMENT, self._handle_task_announcement)
        # Emergent swarm: respond to proposal requests from TeamCoordinator
        await self.subscribe(f"agent.{self.name}.propose", self._handle_propose)
        self._log.info("validator.ready", subject=self._inbox_subject)
        while self._running:
            await asyncio.sleep(3600)

    # ── Emergent swarm: bidding ───────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current agent status for bid scoring."""
        return {
            "capabilities": self.capabilities,
            "current_tasks": 0,
            "success_rate":  0.85,
        }

    async def _handle_task_announcement(self, msg: dict) -> None:
        """Evaluate the announced task and submit a bid if capable."""
        from tools.negotiation_protocol import compute_agent_score, Bid  # noqa: PLC0415
        task_id  = msg.get("task_id", "")
        task_req = msg.get("requirements", {})
        score    = compute_agent_score(self.get_status(), task_req)
        bid      = Bid(
            agent_id=self.name,
            task_id=task_id,
            score=score,
            proposed_team=[self.name],
            capabilities=self.capabilities,
        )
        await self.publish(Subjects.TASK_BID, bid.to_dict())
        self._log.debug("validator.bid_submitted", task_id=task_id, score=score)

    async def _handle_propose(self, msg: dict) -> None:
        """
        TeamCoordinator asks this agent to propose a solution.
        Validator proposes by running a generic critique on the task goal.
        """
        task     = msg.get("task", {})
        reply_to = msg.get("_reply") or msg.get("reply_to")
        goal     = task.get("requirements", {}).get("goal", task.get("goal", ""))
        # Produce a lightweight proposal using the LLM
        try:
            from langchain.schema import HumanMessage  # noqa: PLC0415
            import json as _j  # noqa: PLC0415
            prompt = (
                f"You are a validator agent. Given the goal: '{goal}', "
                "propose a concise, accurate answer. "
                'Return JSON: {"result": "<answer>", "confidence": <0.0-1.0>}'
            )
            resp   = await self._llm.ainvoke([HumanMessage(content=prompt)])
            parsed = _j.loads(resp.content.strip())
            proposal = {
                "result":     parsed.get("result", ""),
                "confidence": float(parsed.get("confidence", 0.5)),
            }
        except Exception as exc:  # noqa: BLE001
            proposal = {"result": None, "confidence": 0.0, "error": str(exc)}

        if reply_to:
            await self.reply(reply_to, proposal)

    # ── Handler ───────────────────────────────────────────────────────────────

    async def handle_validate(self, msg: dict[str, Any]) -> None:
        task: dict       = msg.get("task", {})
        result: dict     = msg.get("result", {})
        remaining: list  = msg.get("remaining_tasks", [])
        workflow_id: str = msg.get("workflow_id", "unknown")
        original_goal: str = msg.get("original_goal", "")
        reply_to: str | None = msg.get("_reply") or msg.get("reply_to")

        task_type: str = task.get("type", "execute")
        self._log.info("validator.handle", task_type=task_type, task_id=task.get("id"), workflow_id=workflow_id)

        # ── Hard failure from executor ────────────────────────────────────────
        if result.get("status") == "error":
            await self._handle_failure(task, result, workflow_id, original_goal, reply_to)
            return

        # ── Type-specific validation ──────────────────────────────────────────
        if task_type == "search":
            verdict = await self._validate_search(task, result, original_goal)
        elif task_type == "direct_answer":
            verdict = await self._validate_direct_answer(task, result)
        else:
            verdict = await self._generic_critique(task, result)

        if not verdict.get("valid", True):
            HALLUCINATION_REJECTIONS.labels(agent=self.name, task_type=task_type).inc()
            await self._handle_failure(
                task, result, workflow_id, original_goal, reply_to,
                reason=verdict.get("reason", ""),
                suggestion=verdict.get("suggestion", ""),
            )
            return

        # ── Valid – continue pipeline or finish ───────────────────────────────
        if remaining:
            next_task = remaining[0]
            rest      = remaining[1:]
            subject   = {
                "search":        Subjects.EXECUTOR_INBOX,
                "direct_answer": Subjects.EXECUTOR_INBOX,
                "execute":       Subjects.EXECUTOR_INBOX,
                "retrieve":      Subjects.RETRIEVER_INBOX,
                "validate":      Subjects.VALIDATOR_INBOX,
            }.get(next_task.get("type", "execute"), Subjects.EXECUTOR_INBOX)

            payload = {
                "task":            next_task,
                "remaining_tasks": rest,
                "workflow_id":     workflow_id,
                "original_goal":   original_goal,
                "previous_result": result,
            }
            if reply_to:
                await self.reply(reply_to, {"status": "continue", "next_subject": subject, **payload})
            else:
                await self.publish(subject, payload)
        else:
            # All tasks done – build final answer and publish
            final_answer = self._extract_final_answer(task_type, result)
            final_payload = {
                "workflow_id":  workflow_id,
                "status":       "completed",
                "final_answer": final_answer,
                "task_id":      task.get("id"),
                "task_type":    task_type,
            }
            if reply_to:
                await self.reply(reply_to, final_payload)
            else:
                await self.publish(Subjects.API_RESULT, final_payload)
            # Publish performance score so the agent registry can track quality
            await self._publish_performance(task, workflow_id, score=1.0)
            # Store successful outcome in shared vector memory so the planner
            # can recall it on future similar goals.
            await self._store_memory(task, result, original_goal, final_answer)
            self._log.info("validator.completed", workflow_id=workflow_id, task_type=task_type)


    async def validate_with_consortium(
        self, task: dict, result: dict, goal: str
    ) -> dict:
        """
        Use the multi-model consortium for high-stakes validation.
        Falls back to single-model validation if consortium is unavailable.
        """
        try:
            consortium = consortium_from_env()
            prompt = (
                f"Task type: {task.get('type')}\n"
                f"Goal: {goal}\n"
                f"Result: {str(result)[:500]}\n"
                f"Is this result valid and accurate? Answer yes or no with a brief reason."
            )
            validation = await consortium.query(prompt)
            answer_lower = validation.get("answer", "").lower()
            passed = validation.get("passed", True) and "no" not in answer_lower[:20]
            return {
                "valid":      passed,
                "confidence": validation.get("confidence", 1.0),
                "reason":     validation.get("answer", "")[:200],
                "suggestion": "Retry with a different approach" if not passed else "",
            }
        except Exception as exc:  # noqa: BLE001
            self._log.warning("validator.consortium_error", error=str(exc))
            # Graceful fallback to existing single-model validation
            return await self._generic_critique(task, result)

    # ── Search validation ─────────────────────────────────────────────────────

    async def _validate_search(
        self, task: dict, result: dict, goal: str
    ) -> dict[str, Any]:
        data    = result.get("result", {})
        answer  = data.get("answer", "")
        results = data.get("results", [])

        # 1. Empty results → hard fail
        if not results and not answer:
            SEARCH_VALIDATIONS.labels(agent=self.name, outcome="failed").inc()
            return {
                "valid":      False,
                "reason":     "Search returned no results",
                "suggestion": "Try a broader or differently phrased query",
            }

        # 2. LLM relevance check on top snippet
        top_snippet = results[0]["snippet"] if results else answer
        query       = task.get("params", {}).get("query", goal)

        try:
            prompt = SEARCH_RELEVANCE_PROMPT.format(
                goal=goal or query,
                query=query,
                snippet=top_snippet[:500],
            )
            resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
            check = json.loads(resp.content.strip())
            if not check.get("relevant", True):
                SEARCH_VALIDATIONS.labels(agent=self.name, outcome="failed").inc()
                return {
                    "valid":      False,
                    "reason":     f"Search results not relevant: {check.get('reason', '')}",
                    "suggestion": "Refine the search query",
                }
        except Exception as exc:  # noqa: BLE001
            self._log.warning("validator.search_relevance_error", error=str(exc))
            # Don't fail on LLM error – pass through

        SEARCH_VALIDATIONS.labels(agent=self.name, outcome="passed").inc()
        return {"valid": True, "reason": "Search results are relevant"}

    # ── Direct-answer validation ──────────────────────────────────────────────

    async def _validate_direct_answer(
        self, task: dict, result: dict
    ) -> dict[str, Any]:
        data       = result.get("result", {})
        answer     = data.get("answer", "")
        confidence = data.get("confidence", "medium")

        # 1. Empty answer
        if not answer:
            return {"valid": False, "reason": "Empty answer", "suggestion": "Rephrase the question"}

        # 2. LLM explicitly said it doesn't know → escalate to search
        if "i don't know" in answer.lower() or "web search is needed" in answer.lower():
            return {
                "valid":      False,
                "reason":     "LLM lacks knowledge – web search required",
                "suggestion": "Switch task type to search",
            }

        # 3. Low confidence → reject to prevent hallucination
        if confidence == "low":
            HALLUCINATION_REJECTIONS.labels(agent=self.name, task_type="direct_answer").inc()
            return {
                "valid":      False,
                "reason":     "LLM reported low confidence – potential hallucination",
                "suggestion": "Switch task type to search for grounded answer",
            }

        # 4. LLM plausibility check
        question = task.get("params", {}).get("question", "")
        try:
            prompt = DIRECT_ANSWER_PLAUSIBILITY_PROMPT.format(
                question=question,
                answer=answer[:300],
                confidence=confidence,
            )
            resp  = await self._llm.ainvoke([HumanMessage(content=prompt)])
            check = json.loads(resp.content.strip())
            if not check.get("plausible", True):
                HALLUCINATION_REJECTIONS.labels(agent=self.name, task_type="direct_answer").inc()
                return {
                    "valid":      False,
                    "reason":     f"Answer not plausible: {check.get('reason', '')}",
                    "suggestion": "Use web search for a grounded answer",
                }
        except Exception as exc:  # noqa: BLE001
            self._log.warning("validator.plausibility_error", error=str(exc))

        return {"valid": True, "reason": "Direct answer is plausible"}

    # ── Generic LLM critic (http / shell / file / retrieve) ──────────────────

    async def _generic_critique(self, task: dict, result: dict) -> dict[str, Any]:
        messages = [
            SystemMessage(content=GENERIC_CRITIC_PROMPT),
            HumanMessage(content=f"Task: {json.dumps(task)}\nResult: {json.dumps(result)}"),
        ]
        try:
            response = await self._llm.ainvoke(messages)
            return json.loads(response.content.strip())
        except Exception as exc:  # noqa: BLE001
            self._log.warning("validator.critique_error", error=str(exc))
            return {"valid": True, "reason": "critique unavailable"}

    # ── Final answer extraction ───────────────────────────────────────────────

    def _extract_final_answer(self, task_type: str, result: dict) -> Any:
        """Pull the most useful value out of the result for the API response."""
        data = result.get("result", {})

        if task_type == "search":
            # Prefer Tavily's synthesised answer; fall back to top snippet
            answer  = data.get("answer", "")
            sources = data.get("sources", [])
            results = data.get("results", [])
            if answer:
                return {
                    "answer":  answer,
                    "sources": sources,
                }
            if results:
                return {
                    "answer":  results[0]["snippet"],
                    "sources": [{"title": r["title"], "url": r["url"]} for r in results[:3]],
                }
            return data

        if task_type == "direct_answer":
            return {
                "answer":  data.get("answer", ""),
                "sources": data.get("sources", ["LLM knowledge"]),
            }

        # Generic fallback
        return data or result.get("documents")

    # ── Swarm memory ──────────────────────────────────────────────────────────

    async def _store_memory(
        self,
        task: dict,
        result: dict,
        goal: str,
        final_answer: Any,
    ) -> None:
        """
        Store a successful task outcome in the shared vector memory so the
        planner can recall similar past successes and reuse their approach.
        """
        if not goal:
            return
        try:
            from tools.vector_memory import SharedVectorMemory  # noqa: PLC0415
            memory = SharedVectorMemory()
            if not memory.available:
                return
            embedding = await self._get_embedding(goal)
            memory.add(embedding, {
                "goal":         goal,
                "task_type":    task.get("type", "unknown"),
                "agent":        task.get("agent", ""),
                "plan":         task,
                "final_answer": str(final_answer)[:300] if final_answer else "",
                "outcome":      "success",
            })
            self._log.debug("validator.memory_stored", goal=goal[:60])
        except Exception as exc:  # noqa: BLE001
            self._log.warning("validator.memory_store_error", error=str(exc))

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate a 384-dim embedding. Falls back to zeros if unavailable."""
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            model = getattr(self, "_embed_model", None)
            if model is None:
                self._embed_model = SentenceTransformer("all-MiniLM-L6-v2")
                model = self._embed_model
            return model.encode(text).tolist()
        except Exception:  # noqa: BLE001
            return [0.0] * 384

    # ── Performance feedback ──────────────────────────────────────────────────

    async def _publish_performance(
        self, task: dict, workflow_id: str, score: float
    ) -> None:
        """
        Publish a performance score to agent.performance so the AgentRegistry
        can maintain a moving average and route future tasks to the best agent.
        score: 1.0 = success, 0.0 = failure
        """
        try:
            await self.publish(Subjects.AGENT_PERFORMANCE, {
                "agent":       self.name,
                "task_type":   task.get("type", "unknown"),
                "tool":        task.get("tool", ""),
                "score":       score,
                "workflow_id": workflow_id,
            })
        except Exception as exc:  # noqa: BLE001
            self._log.warning("validator.performance_publish_error", error=str(exc))

    # ── Failure handler ───────────────────────────────────────────────────────

    async def _handle_failure(
        self,
        task: dict,
        result: dict,
        workflow_id: str,
        original_goal: str,
        reply_to: str | None,
        reason: str = "",
        suggestion: str = "",
    ) -> None:
        error_msg = result.get("error") or reason or "validation failed"
        self._log.warning("validator.failure", workflow_id=workflow_id, error=error_msg)

        failure_payload = {
            "workflow_id":   workflow_id,
            "original_goal": original_goal,
            "failed_task":   task,
            "error":         error_msg,
            "suggestion":    suggestion,
        }

        await self.publish(Subjects.VALIDATOR_FAILED, failure_payload)

        if reply_to:
            await self.reply(reply_to, {"status": "failed", **failure_payload})
        else:
            await self.publish(Subjects.PLANNER_REPLAN, {**failure_payload, "reply_to": reply_to})

        # Publish failure score for registry tracking
        await self._publish_performance(task, workflow_id, score=0.0)

        # Store failure in shared vector memory so the planner avoids repeating it
        if original_goal:
            try:
                from tools.vector_memory import SharedVectorMemory  # noqa: PLC0415
                memory = SharedVectorMemory()
                if memory.available:
                    embedding = await self._get_embedding(original_goal)
                    memory.add(embedding, {
                        "goal":      original_goal,
                        "task_type": task.get("type", "unknown"),
                        "agent":     task.get("agent", ""),
                        "plan":      task,
                        "error":     error_msg[:200],
                        "outcome":   "failure",
                    })
                    self._log.debug("validator.failure_memory_stored", goal=original_goal[:60])
            except Exception as _mem_exc:  # noqa: BLE001
                self._log.warning("validator.failure_memory_error", error=str(_mem_exc))
