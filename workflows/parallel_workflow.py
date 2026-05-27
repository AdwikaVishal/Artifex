"""
workflows/parallel_workflow.py – Parallel subtask swarm workflow.

Splits a complex goal into independent subtasks and executes them
concurrently as child workflows. Results are aggregated using one of
three strategies:

  concatenate – join all results as a formatted string
  vote        – majority-vote on the most common answer
  summary     – LLM-synthesised summary via summarize_activity

This workflow is triggered by ArtifexSwarmWorkflow when the planner
returns a plan with "parallel": true.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

_retry = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
)

TASK_QUEUE = "artifex-queue"


@workflow.defn(name="ParallelSubtaskWorkflow")
class ParallelSubtaskWorkflow:
    """
    Executes a list of independent subtasks in parallel as child workflows,
    then aggregates their results.

    Args:
        subtasks:   list of task dicts (same schema as sequential tasks)
        aggregator: "concatenate" | "vote" | "summary"
        goal:       original user goal (used by summarize_activity)
    """

    @workflow.run
    async def run(
        self,
        subtasks: list[dict[str, Any]],
        aggregator: str,
        goal: str = "",
    ) -> dict[str, Any]:
        parent_id = workflow.info().workflow_id
        workflow.logger.info(
            f"parallel_workflow.started subtasks={len(subtasks)} "
            f"aggregator={aggregator} parent={parent_id}"
        )

        if not subtasks:
            return {"final_answer": "", "subtask_count": 0, "aggregator": aggregator}

        # ── Launch all subtasks as child workflows in parallel ────────────────
        # Each child runs a TaskWorkerWorkflow (already registered in the worker).
        child_handles = []
        for subtask in subtasks:
            child_id = f"{parent_id}-{subtask.get('id', 'sub')}"
            handle = await workflow.start_child_workflow(
                "TaskWorkerWorkflow",
                args=[subtask],
                id=child_id,
                task_queue=TASK_QUEUE,
                retry_policy=_retry,
                execution_timeout=timedelta(seconds=180),
            )
            child_handles.append((subtask.get("id", "?"), handle))

        # ── Collect results (wait for all) ────────────────────────────────────
        results: list[dict[str, Any]] = []
        for sub_id, handle in child_handles:
            try:
                result = await handle
                results.append({"subtask_id": sub_id, "result": result, "ok": True})
            except Exception as exc:  # noqa: BLE001
                workflow.logger.warning(
                    f"parallel_workflow.subtask_failed subtask_id={sub_id} error={exc}"
                )
                results.append({"subtask_id": sub_id, "result": {}, "ok": False,
                                 "error": str(exc)})

        workflow.logger.info(
            f"parallel_workflow.all_done total={len(results)} "
            f"ok={sum(1 for r in results if r['ok'])}"
        )

        # ── Aggregate ─────────────────────────────────────────────────────────
        if aggregator == "vote":
            final = _vote(results)
        elif aggregator == "summary":
            # Delegate to summarize_activity (LLM synthesis)
            from workflows.temporal_worker import summarize_activity  # noqa: PLC0415
            final = await workflow.execute_activity(
                summarize_activity,
                args=[results, goal],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_retry,
            )
        else:
            # Default: concatenate
            final = _concatenate(results)

        return {
            "final_answer":  final,
            "subtask_count": len(subtasks),
            "aggregator":    aggregator,
            "results":       results,
        }


# ── Aggregation helpers (pure functions, safe inside sandbox) ─────────────────

def _concatenate(results: list[dict[str, Any]]) -> str:
    """Join each subtask's answer with a separator."""
    parts = []
    for r in results:
        if not r.get("ok"):
            continue
        res = r.get("result", {})
        # Unwrap nested result dicts from executor/retriever
        answer = (
            res.get("result", {}).get("answer")
            or res.get("answer")
            or res.get("documents")
            or str(res)
        )
        parts.append(f"[{r['subtask_id']}] {answer}")
    return "\n\n".join(parts) if parts else "No results returned."


def _vote(results: list[dict[str, Any]]) -> str:
    """
    Majority vote: return the most common answer string.
    Falls back to concatenation if all answers are unique.
    """
    answers: list[str] = []
    for r in results:
        if not r.get("ok"):
            continue
        res = r.get("result", {})
        answer = (
            res.get("result", {}).get("answer")
            or res.get("answer")
            or str(res)
        )
        answers.append(str(answer)[:500])   # cap length for comparison

    if not answers:
        return "No valid results to vote on."

    # Count occurrences
    from collections import Counter  # noqa: PLC0415
    counts = Counter(answers)
    winner, count = counts.most_common(1)[0]

    if count > 1:
        return f"{winner}  (agreed by {count}/{len(answers)} agents)"
    # All unique — fall back to first answer with a note
    return f"{answers[0]}  (no majority; showing first result of {len(answers)})"
