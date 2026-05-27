"""
ExecutorAgent – dispatches tasks to the appropriate tool.

Listens on:  agent.executor.inbox
Publishes:   agent.validator.inbox  (with execution result)

Supported task types / tools:
  search        – real-time web search via Tavily / DuckDuckGo
  direct_answer – LLM answers from its own knowledge (no retrieval)
  http          – HTTP GET/POST via httpx
  shell         – subprocess with timeout
  file          – sandboxed read/write
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage
from prometheus_client import Counter, Histogram

from nats_client.subjects import Subjects
from tools.http_tool import HttpTool
from tools.shell_tool import ShellTool
from tools.file_tool import FileTool
from tools.web_search_tool import web_search_with_answer
from .base import BaseAgent

logger = structlog.get_logger()

# ── Search-specific Prometheus metrics ────────────────────────────────────────
SEARCH_REQUESTS = Counter(
    "artifex_search_requests_total",
    "Total web search requests",
    ["agent"],
)
SEARCH_ERRORS = Counter(
    "artifex_search_errors_total",
    "Total web search errors",
    ["agent"],
)
SEARCH_LATENCY = Histogram(
    "artifex_search_latency_seconds",
    "Web search latency in seconds",
    ["agent"],
)
DIRECT_ANSWER_REQUESTS = Counter(
    "artifex_direct_answer_requests_total",
    "Total direct-answer (LLM-only) requests",
    ["agent"],
)

DIRECT_ANSWER_PROMPT = """Answer the following question concisely and accurately.
Base your answer only on well-established facts you are confident about.
If you are uncertain or the question requires real-time data, say exactly: "I don't know – a web search is needed."

Question: {question}

Respond with JSON only:
{{"answer": "<your answer>", "confidence": "high|medium|low", "sources": ["LLM knowledge"]}}"""


class ExecutorAgent(BaseAgent):
    def __init__(self) -> None:
        import os as _os
        # Support per-instance configuration via env vars so that executor-a
        # (search-capable) and executor-b (tools-capable) can run as separate
        # containers without code changes.
        instance_name  = _os.getenv("EXECUTOR_INSTANCE", "executor")
        inbox_subject  = _os.getenv("EXECUTOR_SUBJECT", Subjects.EXECUTOR_INBOX)
        capabilities   = _os.getenv("EXECUTOR_CAPABILITIES", "search,direct_answer,http,shell,file")

        super().__init__(name=instance_name, metrics_port=9093)
        self._inbox_subject  = inbox_subject
        self._capabilities   = {c.strip() for c in capabilities.split(",") if c.strip()}
        self._tools: dict[str, Any] = {
            "http":  HttpTool(),
            "shell": ShellTool(),
            "file":  FileTool(),
        }
        # Support per-instance model override for agent-voting executors
        model_name = _os.getenv("EXECUTOR_MODEL", "llama-3.1-8b-instant")
        self._llm = ChatGroq(
            model=model_name,
            temperature=0.0,
        )
        self._log.info("executor.init",
                       subject=inbox_subject, capabilities=sorted(self._capabilities),
                       model=model_name)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        # Subscribe to the instance-specific inbox AND the general inbox
        # (load-balanced queue group) so any executor handles overflow.
        await self.subscribe(self._inbox_subject, self.handle_execute, queue="executor")
        if self._inbox_subject != Subjects.EXECUTOR_INBOX:
            await self.subscribe(Subjects.EXECUTOR_INBOX, self.handle_execute, queue="executor")
        # Emergent swarm: bid on announced tasks
        await self.subscribe(Subjects.TASK_ANNOUNCEMENT, self._handle_task_announcement)
        # Emergent swarm: respond to proposal requests from TeamCoordinator
        await self.subscribe(f"agent.{self.name}.propose", self._handle_propose)
        self._log.info("executor.ready", subject=self._inbox_subject)
        while self._running:
            await asyncio.sleep(3600)

    # ── Emergent swarm: bidding ───────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current agent status for bid scoring."""
        return {
            "capabilities": self.capabilities,
            "current_tasks": 0,   # TODO: track in-flight tasks
            "success_rate":  0.8,
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
        self._log.debug("executor.bid_submitted", task_id=task_id, score=score)

    async def _handle_propose(self, msg: dict) -> None:
        """
        TeamCoordinator asks this agent to propose a solution.
        We run the task and return the result with a confidence score.
        """
        task      = msg.get("task", {})
        reply_to  = msg.get("_reply") or msg.get("reply_to")
        task_type = task.get("task_type", task.get("type", "direct_answer"))
        params    = task.get("requirements", task.get("params", {}))

        # Build a minimal task dict compatible with handle_execute
        inner_task = {"type": task_type, "params": params, "id": task.get("task_id", "")}
        try:
            await self.handle_execute({
                "task": inner_task,
                "remaining_tasks": [],
                "workflow_id": task.get("task_id", "emergent"),
                "_reply": reply_to,
            })
        except Exception as exc:  # noqa: BLE001
            if reply_to:
                await self.reply(reply_to, {"confidence": 0.0, "result": None, "error": str(exc)})

    @property
    def capabilities(self) -> list[str]:
        """Advertise this executor's supported task types and tools."""
        return sorted(self._capabilities)

    # ── Handler ───────────────────────────────────────────────────────────────

    async def handle_execute(self, msg: dict[str, Any]) -> None:
        task: dict      = msg.get("task", {})
        remaining: list = msg.get("remaining_tasks", [])
        workflow_id: str = msg.get("workflow_id", "unknown")
        reply_to: str | None = msg.get("_reply") or msg.get("reply_to")

        task_type: str = task.get("type", "execute")
        tool_name: str = task.get("tool", "")
        params: dict   = task.get("params", {})

        self._log.info("executor.handle", task_type=task_type, tool=tool_name, workflow_id=workflow_id)

        # ── Route by task type first, then by tool name ───────────────────────
        if task_type == "search" or tool_name == "web_search":
            result = await self._run_web_search(task, params)

        elif task_type == "direct_answer" or tool_name == "direct_answer":
            result = await self._run_direct_answer(task, params)

        else:
            # Legacy tool dispatch (http / shell / file)
            tool = self._tools.get(tool_name)
            if tool is None:
                result = {
                    "status": "error",
                    "error": f"Unknown tool: {tool_name!r}",
                    "task_id": task.get("id"),
                }
            else:
                try:
                    output = await tool.run(params)
                    result = {"status": "ok", "result": output, "task_id": task.get("id")}
                except Exception as exc:  # noqa: BLE001
                    self._log.exception("executor.tool_error", tool=tool_name, error=str(exc))
                    result = {"status": "error", "error": str(exc), "task_id": task.get("id")}

        payload = {
            "task":            task,
            "result":          result,
            "remaining_tasks": remaining,
            "workflow_id":     workflow_id,
        }

        if reply_to:
            await self.reply(reply_to, payload)
        else:
            await self.publish(Subjects.VALIDATOR_INBOX, payload)

    # ── Web search ────────────────────────────────────────────────────────────

    async def _run_web_search(self, task: dict, params: dict) -> dict[str, Any]:
        query: str = params.get("query", "")
        if not query:
            return {
                "status": "error",
                "error": "Missing 'query' in search task params",
                "task_id": task.get("id"),
            }

        SEARCH_REQUESTS.labels(agent=self.name).inc()
        import time
        t0 = time.perf_counter()

        try:
            # Pass days=7 for time-sensitive queries
            days = params.get("days")
            search_data = await web_search_with_answer(
                query,
                num_results=params.get("num_results", 5),
                days=days,
            )
            elapsed = time.perf_counter() - t0
            SEARCH_LATENCY.labels(agent=self.name).observe(elapsed)

            self._log.info(
                "executor.search_done",
                query=query,
                results=len(search_data.get("results", [])),
                latency=round(elapsed, 2),
            )
            return {
                "status":  "ok",
                "result":  search_data,
                "task_id": task.get("id"),
            }
        except Exception as exc:  # noqa: BLE001
            SEARCH_ERRORS.labels(agent=self.name).inc()
            self._log.exception("executor.search_error", query=query, error=str(exc))
            return {"status": "error", "error": str(exc), "task_id": task.get("id")}

    # ── Direct answer (LLM knowledge only) ───────────────────────────────────

    async def _run_direct_answer(self, task: dict, params: dict) -> dict[str, Any]:
        question: str = params.get("question", params.get("query", ""))
        if not question:
            return {
                "status": "error",
                "error": "Missing 'question' in direct_answer task params",
                "task_id": task.get("id"),
            }

        DIRECT_ANSWER_REQUESTS.labels(agent=self.name).inc()

        try:
            prompt = DIRECT_ANSWER_PROMPT.format(question=question)
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content.strip()

            import json
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # LLM didn't return JSON – wrap the raw text
                parsed = {"answer": raw, "confidence": "medium", "sources": ["LLM knowledge"]}

            self._log.info(
                "executor.direct_answer",
                question=question[:80],
                confidence=parsed.get("confidence"),
            )
            return {
                "status":  "ok",
                "result":  parsed,
                "task_id": task.get("id"),
            }
        except Exception as exc:  # noqa: BLE001
            self._log.exception("executor.direct_answer_error", error=str(exc))
            return {"status": "error", "error": str(exc), "task_id": task.get("id")}
