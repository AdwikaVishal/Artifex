"""
scripts/run_agent.py – entrypoint for running a single agent.

Usage:
  python -m scripts.run_agent planner
  python -m scripts.run_agent retriever
  ...
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from dotenv import load_dotenv

load_dotenv()

logger = structlog.get_logger()

AGENT_MAP = {
    "planner":       "agents.planner.PlannerAgent",
    "retriever":     "agents.retriever.RetrieverAgent",
    "executor":      "agents.executor.ExecutorAgent",
    "validator":     "agents.validator.ValidatorAgent",
    "supervisor":    "agents.supervisor.SupervisorAgent",
    "recovery":      "agents.recovery.RecoveryAgent",
    "foster_monitor":"agents.foster_monitor.FosterMonitorAgent",
    "dispatcher":    "agents.dispatcher.DispatcherAgent",
    "swarm_manager": "agents.swarm_manager.SwarmManager",
}


def _import_agent(dotted_path: str):
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def main(agent_name: str) -> None:
    if agent_name not in AGENT_MAP:
        logger.error("unknown_agent", name=agent_name, available=list(AGENT_MAP.keys()))
        sys.exit(1)

    AgentClass = _import_agent(AGENT_MAP[agent_name])
    agent = AgentClass()
    logger.info("starting_agent", name=agent_name)
    await agent.start()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python -m scripts.run_agent <{'|'.join(AGENT_MAP)}>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
