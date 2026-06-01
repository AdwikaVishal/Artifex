"""
PlannerAgent – decomposes a natural-language goal into an ordered task list.

Listens on:
  agent.planner.request  – new goal from the API / LangGraph
  agent.planner.replan   – failure report from Validator / Recovery

Publishes:
  agent.executor.inbox   – for search / direct_answer / execute tasks
  agent.retriever.inbox  – for retrieve tasks (internal document search)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage

from nats_client.subjects import Subjects
from .base import BaseAgent
from tools.vector_memory import SharedVectorMemory
from tools.agent_registry import AgentRegistry as _AgentRegistry

logger = structlog.get_logger()

# ── Build capability string from registry at import time ─────────────────────
# This is a static snapshot used to inform the LLM. The live registry
# (in DispatcherAgent) handles actual runtime routing.
_static_registry = _AgentRegistry()
# Pre-populate with known executor capabilities so the planner prompt is
# accurate even before agents self-register at runtime.
_static_registry._agents = {}   # will be populated by agents at startup
_EXECUTOR_CAPABILITIES_STR = (
    "- executor-a: search, direct_answer  (web search and LLM answers)\n"
    "- executor-b: http, shell, file, execute  (tool execution)"
)

# ── System prompt ─────────────────────────────────────────────────────────────
# Few-shot examples teach the model exactly when to use each task type.

SYSTEM_PROMPT = """You are a task-planning AI for an agent swarm. Given a user goal, produce an
ordered list of atomic tasks. Output ONLY valid JSON – no markdown fences, no extra text.

Sequential plan schema (default):
{{
  "tasks": [
    {{"id": "t1", "type": "<task_type>", "agent": "<agent_name>", "params": {{ ... }}}}
  ]
}}

Parallel plan schema (use when subtasks are fully independent):
{{
  "parallel": true,
  "subtasks": [
    {{"id": "t1", "type": "<task_type>", "agent": "<agent_name>", "params": {{ ... }}}},
    {{"id": "t2", "type": "<task_type>", "agent": "<agent_name>", "params": {{ ... }}}}
  ],
  "aggregator": "concatenate" | "vote" | "summary"
}}

Available executor agents and their capabilities
─────────────────────────────────────────────────
{capabilities}

Task types and when to use them
────────────────────────────────
"search"
  Use when the goal requires up-to-date, real-time, or external information.
  agent: executor-a
  params: {{"query": "<concise search query>", "days": <int, optional>}}

"direct_answer"
  Use for timeless factual questions answerable from general knowledge.
  agent: executor-a
  params: {{"question": "<original question>"}}

"execute"
  Use when the goal requires calling a URL, running a command, or file I/O.
  agent: executor-b
  params: {{"tool": "http|shell|file", ...tool-specific params...}}

"retrieve"
  Use ONLY when the user explicitly mentions a pre-loaded knowledge base.
  params: {{"query": "<search query>"}}

"spawn_specialist"
  Use when the goal requires deep domain expertise (finance, medicine, legal,
  foster_care, data_analysis). Spawns a temporary specialist agent.
  params: {{"domain": "<domain>", "query": "<full question>"}}

Rules
─────
1. Time-sensitive keywords (latest, current, today, now, recent, who won,
   what happened) → ALWAYS use "search" with agent "executor-a".
2. Comparing multiple independent items (e.g., weather in 3 cities, prices
   of 5 stocks) → use parallel plan with aggregator "concatenate" or "summary".
3. Ambiguous questions where multiple answers are plausible → use parallel
   plan with aggregator "vote".
4. Domain-specific deep questions (stock analysis, medical info, legal) →
   use "spawn_specialist".
5. Always include the "agent" field.

Few-shot examples
─────────────────
Goal: "Compare weather in London, Paris, and Berlin"
{{"parallel":true,"subtasks":[{{"id":"t1","type":"search","agent":"executor-a","params":{{"query":"current weather London","days":1}}}},{{"id":"t2","type":"search","agent":"executor-a","params":{{"query":"current weather Paris","days":1}}}},{{"id":"t3","type":"search","agent":"executor-a","params":{{"query":"current weather Berlin","days":1}}}}],"aggregator":"concatenate"}}

Goal: "What is the best programming language?"
{{"parallel":true,"subtasks":[{{"id":"t1","type":"direct_answer","agent":"executor-a","params":{{"question":"What is the best programming language for web development?"}}}},{{"id":"t2","type":"direct_answer","agent":"executor-a","params":{{"question":"What is the best programming language for data science?"}}}},{{"id":"t3","type":"search","agent":"executor-a","params":{{"query":"most popular programming languages 2025","days":30}}}}],"aggregator":"vote"}}

Goal: "What is the stock price of Apple?"
{{"tasks":[{{"id":"t1","type":"spawn_specialist","params":{{"domain":"finance","query":"What is the current stock price and recent performance of Apple (AAPL)?"}}}}]}}

Goal: "Who won the latest Formula 1 race?"
{{"tasks":[{{"id":"t1","type":"search","agent":"executor-a","params":{{"query":"latest Formula 1 race winner 2025","days":7}}}}]}}

Goal: "What is the capital of France?"
{{"tasks":[{{"id":"t1","type":"direct_answer","agent":"executor-a","params":{{"question":"What is the capital of France?"}}}}]}}
"""


class PlannerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="planner", metrics_port=9091)
        self._llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.0,
        )
        # Format the system prompt once with the static capability string.
        # At runtime the live registry (in DispatcherAgent) handles actual routing.
        self._system_prompt = SYSTEM_PROMPT.format(
            capabilities=_EXECUTOR_CAPABILITIES_STR
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe(Subjects.PLANNER_REQUEST, self.handle_request, queue="planner")
        await self.subscribe(Subjects.PLANNER_REPLAN,  self.handle_replan,  queue="planner")
        await self.subscribe("events.child_referral",  self.handle_new_child, queue="planner")
        self._log.info("planner.subscribed_child_referral")
        self._log.info("planner.ready")
        while self._running:
            await asyncio.sleep(3600)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def handle_request(self, msg: dict[str, Any]) -> None:
        goal: str        = msg.get("goal", "")
        reply_to: str | None = msg.get("_reply") or msg.get("reply_to")
        workflow_id: str = msg.get("workflow_id", "unknown")

        self._log.info("planner.handle_request", goal=goal[:80], workflow_id=workflow_id)

        # ── Emergent mode decision ────────────────────────────────────────────
        if await self._should_use_emergent(goal):
            self._log.info("planner.emergent_mode_selected", goal=goal[:80])
            await self.log_event(
                f"Complex goal detected – routing to emergent swarm: {goal[:60]}", "info"
            )
            emergent_workflow_id = f"emergent-{workflow_id}"
            try:
                import os as _os  # noqa: PLC0415
                from temporalio.client import Client as _TemporalClient  # noqa: PLC0415
                from temporalio.exceptions import WorkflowAlreadyStartedError as _WASError  # noqa: PLC0415
                temporal_host = _os.getenv("TEMPORAL_HOST", "temporal:7233")
                temporal_ns   = _os.getenv("TEMPORAL_NAMESPACE", "default")
                task_queue    = _os.getenv("TEMPORAL_TASK_QUEUE", "artifex-queue")
                client = await _TemporalClient.connect(temporal_host, namespace=temporal_ns)
                await client.start_workflow(
                    "EmergentSwarmWorkflow",
                    goal,
                    id=emergent_workflow_id,
                    task_queue=task_queue,
                )
                self._log.info("planner.emergent_workflow_started",
                               workflow_id=emergent_workflow_id)
            except _WASError:  # idempotent – workflow already running
                self._log.info("planner.emergent_workflow_already_running",
                               workflow_id=emergent_workflow_id)
            except Exception as exc:  # noqa: BLE001
                self._log.exception("planner.emergent_start_error", error=str(exc))
                # Fall through to deterministic planning on error
                plan = await self._generate_plan(goal)
                await self.log_event(f"Planning (fallback): {goal[:60]}", "warning")
                if reply_to:
                    await self.reply(reply_to, {"plan": plan, "workflow_id": workflow_id})
                else:
                    await self._dispatch_first_task(plan, workflow_id)
                return

            if reply_to:
                await self.reply(reply_to, {
                    "status":      "emergent_started",
                    "workflow_id": emergent_workflow_id,
                    "plan":        {"tasks": []},   # empty plan – swarm self-organises
                })
            return

        # ── Deterministic planning ────────────────────────────────────────────
        plan = await self._generate_plan(goal)
        await self.log_event(f"Planning: {goal[:60]}", "info")

        if reply_to:
            await self.reply(reply_to, {"plan": plan, "workflow_id": workflow_id})
        else:
            await self._dispatch_first_task(plan, workflow_id)

    # ── Complexity detection ──────────────────────────────────────────────────

    async def _should_use_emergent(self, goal: str) -> bool:
        """
        Decide whether this goal warrants emergent team formation instead of
        the deterministic planner → executor → validator chain.

        Heuristics (fast, no LLM call needed):
          1. Contains complexity keywords (team, negotiate, multiple, complex, …)
          2. Contains more than one question mark (multiple sub-questions)
          3. Contains more than two " and " conjunctions (compound goal)
        """
        goal_lower = goal.lower()

        COMPLEX_KEYWORDS = (
            "team", "negotiate", "multiple", "complex", "debate",
            "compare", "analyse", "analyze", "evaluate", "assess",
            "multi", "stakeholder", "consensus", "collaborate",
            "trade-off", "tradeoff", "pros and cons", "weigh",
        )
        if any(kw in goal_lower for kw in COMPLEX_KEYWORDS):
            self._log.debug("planner.emergent_trigger", reason="keyword_match",
                            goal=goal[:60])
            return True

        if goal_lower.count("?") > 1:
            self._log.debug("planner.emergent_trigger", reason="multiple_questions",
                            goal=goal[:60])
            return True

        if goal_lower.count(" and ") > 2:
            self._log.debug("planner.emergent_trigger", reason="compound_goal",
                            goal=goal[:60])
            return True

        return False

    async def handle_replan(self, msg: dict[str, Any]) -> None:
        goal: str        = msg.get("original_goal", "")
        error: str       = msg.get("error", "unknown error")
        workflow_id: str = msg.get("workflow_id", "unknown")
        reply_to: str | None = msg.get("_reply") or msg.get("reply_to")

        self._log.info("planner.handle_replan", goal=goal[:80], error=error, workflow_id=workflow_id)

        augmented_goal = (
            f"{goal}\n\n"
            f"Previous attempt failed with: {error}. "
            "Produce a revised plan that avoids this failure. "
            "If the previous plan used direct_answer and failed, switch to search."
        )
        plan = await self._generate_plan(augmented_goal)

        if reply_to:
            await self.reply(reply_to, {"plan": plan, "workflow_id": workflow_id})
        else:
            await self._dispatch_first_task(plan, workflow_id)

    # ── Helpers ───────────────────────────────────────────────────────────────


    async def handle_new_child(self, msg: dict) -> None:
        """Start a FosterPlacementWorkflow for a new child referral."""
        import os
        from temporalio.client import Client as TemporalClient

        child_id = msg.get("child_id")
        if not child_id:
            self._log.warning("planner.handle_new_child.missing_child_id", msg=msg)
            return

        workflow_id   = f"foster-{child_id}"
        temporal_host = os.getenv("TEMPORAL_HOST", "temporal:7233")
        temporal_ns   = os.getenv("TEMPORAL_NAMESPACE", "default")
        task_queue    = os.getenv("TEMPORAL_TASK_QUEUE", "artifex-queue")

        self._log.info("planner.handle_new_child.connecting",
                       temporal_host=temporal_host, workflow_id=workflow_id)
        try:
            client = await TemporalClient.connect(temporal_host, namespace=temporal_ns)
            await client.start_workflow(
                "FosterPlacementWorkflow",
                msg,
                id=workflow_id,
                task_queue=task_queue,
            )
            self._log.info("planner.started_placement_workflow",
                           workflow_id=workflow_id, child_id=child_id)
        except Exception as exc:
            from temporalio.exceptions import WorkflowAlreadyStartedError as _WASError  # noqa: PLC0415
            if isinstance(exc, _WASError):
                self._log.info("planner.placement_workflow_already_running",
                               workflow_id=workflow_id)
            else:
                self._log.error("planner.handle_new_child.error",
                                workflow_id=workflow_id, child_id=child_id,
                                error=str(exc))

    async def _generate_plan(self, goal: str) -> dict[str, Any]:
        """Call Groq LLM to produce a structured task plan."""
        # ── Query shared memory for similar past plans ────────────────
        memory_context = ""
        try:
            memory = SharedVectorMemory()
            if memory.available and memory.size > 0:
                embedding = await self._get_embedding(goal)
                similar = memory.search(embedding, k=5)

                successes = [
                    mem for dist, mem in similar
                    if dist < 0.5 and mem.get("outcome") == "success"
                ]
                failures = [
                    mem for dist, mem in similar
                    if dist < 0.5 and mem.get("outcome") != "success"
                ]

                lines = []
                if successes:
                    lines.append("Previously successful approaches (reuse these patterns):")
                    for m in successes[:2]:
                        lines.append(
                            f"  - Goal: {m.get('goal', '')[:60]} "
                            f"→ type={m.get('task_type','')} agent={m.get('agent','')}"
                        )
                if failures:
                    lines.append("Previous failures to avoid:")
                    for m in failures[:2]:
                        lines.append(
                            f"  - {m.get('goal', '')[:60]} failed: {m.get('error', '')[:60]}"
                        )
                if lines:
                    memory_context = "\n\nSwarm memory context:\n" + "\n".join(lines)
                    self._log.info("planner.memory_context_injected",
                                   successes=len(successes), failures=len(failures))
        except Exception as _mem_exc:  # noqa: BLE001
            pass  # memory is best-effort; never block planning

        messages = [
            SystemMessage(content=self._system_prompt + memory_context),
            HumanMessage(content=f"Goal: {goal}"),
        ]
        response = await self._llm.ainvoke(messages)
        raw = response.content.strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            self._log.warning("planner.json_parse_error", raw=raw[:200])
            plan = {
                "tasks": [
                    {
                        "id":    "t1",
                        "type":  "search",
                        "agent": "executor-a",
                        "params": {"query": goal},
                    }
                ]
            }

        # Safety: force search for time-sensitive keywords
        TIME_SENSITIVE = ("latest", "current", "today", "now", "recent",
                          "this week", "this year", "who won", "what happened",
                          "breaking", "just", "score", "weather", "price", "stock")
        goal_lower = goal.lower()
        tasks = plan.get("tasks", [])
        if tasks and tasks[0].get("type") == "direct_answer":
            if any(kw in goal_lower for kw in TIME_SENSITIVE):
                self._log.info("planner.forcing_search", reason="time_sensitive_keyword")
                tasks[0] = {
                    "id":     tasks[0].get("id", "t1"),
                    "type":   "search",
                    "agent":  "executor-a",
                    "params": {"query": goal, "days": 7},
                }

        # Safety: ensure every task has an agent field so the dispatcher
        # can route correctly even if the LLM omitted it.
        _type_to_agent = {
            "search":        "executor-a",
            "direct_answer": "executor-a",
            "execute":       "executor-b",
            "retrieve":      "retriever",
        }
        for t in tasks:
            if not t.get("agent"):
                t["agent"] = _type_to_agent.get(t.get("type", "execute"), "executor-a")

        self._log.info(
            "planner.plan_generated",
            task_count=len(tasks),
            first_type=tasks[0].get("type") if tasks else "none",
            first_agent=tasks[0].get("agent") if tasks else "none",
        )
        return plan


    async def _get_embedding(self, text: str) -> list[float]:
        """
        Generate a 384-dim embedding for shared memory queries.
        Uses sentence-transformers if available, falls back to zeros.
        """
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            model = getattr(self, "_embed_model", None)
            if model is None:
                self._embed_model = SentenceTransformer("all-MiniLM-L6-v2")
                model = self._embed_model
            return model.encode(text).tolist()
        except Exception:  # noqa: BLE001
            return [0.0] * 384

    async def _dispatch_first_task(self, plan: dict[str, Any], workflow_id: str) -> None:
        tasks = plan.get("tasks", [])
        if not tasks:
            self._log.warning("planner.empty_plan")
            return

        first     = tasks[0]
        task_type = first.get("type", "execute")
        agent     = first.get("agent", "")

        if task_type == "retrieve":
            # Retriever has its own dedicated subject; bypass the dispatcher
            subject = Subjects.RETRIEVER_INBOX
        elif agent:
            # Route through the dispatcher so it can apply live registry selection
            subject = "agent.executor.request"
        else:
            subject = Subjects.EXECUTOR_INBOX

        await self.publish(subject, {
            "task":            first,
            "remaining_tasks": tasks[1:],
            "workflow_id":     workflow_id,
        })
        self._log.info(
            "planner.dispatched",
            subject=subject,
            task_id=first.get("id"),
            task_type=task_type,
            agent=agent,
        )
