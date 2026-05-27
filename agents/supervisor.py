"""
SupervisorAgent – monitors agent heartbeats and restarts failed pods.

Listens on:  agent.*.heartbeat  (wildcard)
Logic:
  • Tracks last-seen timestamp per agent.
  • If an agent misses 3 consecutive 30-second windows (90 s total), it is
    considered dead and the Supervisor calls the Kubernetes API to delete
    (and thus restart) the corresponding pod.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from typing import Any

import structlog

from nats_client.subjects import Subjects
from .base import BaseAgent

logger = structlog.get_logger()

HEARTBEAT_INTERVAL = 30          # seconds between expected heartbeats
MAX_MISSED = 3                   # consecutive misses before restart
CHECK_INTERVAL = 15              # how often the watchdog loop runs


class SupervisorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="supervisor", metrics_port=9095)
        self._last_seen: dict[str, float] = defaultdict(lambda: time.time())
        self._miss_count: dict[str, int] = defaultdict(int)
        self._k8s_namespace = os.getenv("K8S_NAMESPACE", "artifex")
        self._in_cluster = os.getenv("IN_CLUSTER", "false").lower() == "true"
        self._k8s_client: Any = None

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.subscribe(Subjects.HEARTBEAT_WILDCARD, self.handle_heartbeat)
        asyncio.create_task(self._watchdog_loop(), name="supervisor-watchdog")
        self._log.info("supervisor.ready")
        while self._running:
            await asyncio.sleep(3600)

    # ── Heartbeat handler ─────────────────────────────────────────────────────

    async def handle_heartbeat(self, msg: dict[str, Any]) -> None:
        agent_name: str = msg.get("agent", "unknown")
        ts: float = msg.get("timestamp", time.time())
        self._last_seen[agent_name] = ts
        self._miss_count[agent_name] = 0
        self._log.debug("supervisor.heartbeat_received", agent=agent_name)

    # ── Watchdog ──────────────────────────────────────────────────────────────

    async def _watchdog_loop(self) -> None:
        """Periodically check for stale heartbeats."""
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)
            now = time.time()
            for agent_name, last_ts in list(self._last_seen.items()):
                elapsed = now - last_ts
                if elapsed > HEARTBEAT_INTERVAL:
                    self._miss_count[agent_name] += 1
                    self._log.warning(
                        "supervisor.missed_heartbeat",
                        agent=agent_name,
                        missed=self._miss_count[agent_name],
                        elapsed_seconds=round(elapsed, 1),
                    )
                    if self._miss_count[agent_name] >= MAX_MISSED:
                        await self._restart_agent(agent_name)
                        self._miss_count[agent_name] = 0

    # ── Kubernetes restart ────────────────────────────────────────────────────

    async def _restart_agent(self, agent_name: str) -> None:
        self._log.error("supervisor.restarting_agent", agent=agent_name)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._k8s_delete_pod, agent_name
            )
        except Exception as exc:  # noqa: BLE001
            self._log.exception("supervisor.restart_failed", agent=agent_name, error=str(exc))

    def _k8s_delete_pod(self, agent_name: str) -> None:
        """Delete the pod so Kubernetes restarts it via the Deployment."""
        try:
            from kubernetes import client as k8s_client, config as k8s_config  # type: ignore

            if self._in_cluster:
                k8s_config.load_incluster_config()
            else:
                k8s_config.load_kube_config()

            v1 = k8s_client.CoreV1Api()
            pods = v1.list_namespaced_pod(
                namespace=self._k8s_namespace,
                label_selector=f"app={agent_name}",
            )
            for pod in pods.items:
                pod_name = pod.metadata.name
                v1.delete_namespaced_pod(name=pod_name, namespace=self._k8s_namespace)
                self._log.info("supervisor.pod_deleted", pod=pod_name, agent=agent_name)
        except ImportError:
            self._log.warning("supervisor.k8s_unavailable", agent=agent_name)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"K8s restart failed for {agent_name}: {exc}") from exc
