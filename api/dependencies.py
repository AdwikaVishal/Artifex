"""
FastAPI dependency providers.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import AsyncGenerator

from temporalio.client import Client
from temporalio.service import TLSConfig
from nats_client.client import NATSManager


@lru_cache(maxsize=1)
def get_settings() -> dict:
    return {
        "temporal_host": os.getenv("TEMPORAL_HOST", "localhost:7233"),
        "temporal_namespace": os.getenv("TEMPORAL_NAMESPACE", "default"),
        "temporal_task_queue": os.getenv("TEMPORAL_TASK_QUEUE", "artifex-queue"),
        "nats_url": os.getenv("NATS_URL", "nats://localhost:4222"),
    }


async def get_temporal_client() -> Client:
    settings = get_settings()
    print("TEMPORAL_HOST =", settings["temporal_host"])
    print("TEMPORAL_NAMESPACE =", settings["temporal_namespace"])
    return await Client.connect(
        settings["temporal_host"],
        namespace=settings["temporal_namespace"],
    )


async def get_nats() -> AsyncGenerator[NATSManager, None]:
    manager = NATSManager()
    if not manager.nc or manager.nc.is_closed:
        await manager.connect()
    yield manager
