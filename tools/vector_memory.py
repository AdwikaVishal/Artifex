"""
tools/vector_memory.py – Thread-safe singleton shared vector memory.

Uses FAISS for fast similarity search so all agents can read/write a
common store. Lessons learned by the validator are instantly available
to the planner on the next request.

Falls back gracefully if faiss is not installed (returns empty results).

Persistence:
  Call save(path) to write the index + metadata to disk.
  Call load(path) on startup to restore a previous session.
  The worker calls load() automatically if MEMORY_PATH env var is set.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Embedding dimension for sentence-transformers all-MiniLM-L6-v2
_EMBED_DIM = 384


class SharedVectorMemory:
    """
    Process-wide singleton FAISS index.

    Usage:
        memory = SharedVectorMemory()
        memory.add(embedding, {"goal": "...", "plan": {...}, "outcome": "success"})
        results = memory.search(embedding, k=3)
        memory.save("memory/swarm")   # persist to disk
        memory.load("memory/swarm")   # restore on startup
    """

    _instance: SharedVectorMemory | None = None
    _class_lock = threading.Lock()

    def __new__(cls) -> SharedVectorMemory:
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init()
                    cls._instance = inst
        return cls._instance

    def _init(self) -> None:
        self._write_lock = threading.Lock()
        self._memories: list[dict[str, Any]] = []
        self._index = None
        self._available = False

        try:
            import faiss  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415

            self._faiss = faiss
            self._np = np
            self._index = faiss.IndexFlatL2(_EMBED_DIM)
            self._available = True
            logger.info("vector_memory.initialized", dim=_EMBED_DIM)

            # Auto-load from disk if MEMORY_PATH is configured
            memory_path = os.getenv("MEMORY_PATH", "")
            if memory_path:
                try:
                    self.load(memory_path)
                except Exception as exc:  # noqa: BLE001
                    logger.info("vector_memory.no_saved_state",
                                path=memory_path, reason=str(exc))
        except ImportError:
            logger.warning(
                "vector_memory.faiss_unavailable",
                detail="Install faiss-cpu to enable shared vector memory",
            )

    # ── Write ─────────────────────────────────────────────────────────

    def add(self, embedding: list[float], metadata: dict[str, Any]) -> None:
        """Store an embedding + metadata. No-op if FAISS is unavailable."""
        if not self._available:
            return
        vec = self._np.array([embedding], dtype=self._np.float32)
        with self._write_lock:
            self._index.add(vec)
            self._memories.append(metadata)

        # Auto-save after every write if MEMORY_PATH is set
        memory_path = os.getenv("MEMORY_PATH", "")
        if memory_path:
            try:
                self.save(memory_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("vector_memory.auto_save_error", error=str(exc))

    # ── Read ──────────────────────────────────────────────────────────

    def search(
        self, embedding: list[float], k: int = 5
    ) -> list[tuple[float, dict[str, Any]]]:
        """
        Return up to k (distance, metadata) pairs, closest first.
        Returns [] if FAISS is unavailable or the index is empty.
        """
        if not self._available or self._index.ntotal == 0:
            return []

        vec = self._np.array([embedding], dtype=self._np.float32)
        actual_k = min(k, self._index.ntotal)
        distances, indices = self._index.search(vec, actual_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx != -1 and idx < len(self._memories):
                results.append((float(dist), self._memories[idx]))
        return results

    # ── Persistence ───────────────────────────────────────────────────

    def save(self, path: str) -> None:
        """
        Persist the FAISS index and metadata to disk.

        Creates two files:
          <path>.index  – binary FAISS index
          <path>.json   – metadata list
        """
        if not self._available:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            self._faiss.write_index(self._index, str(p) + ".index")
            with open(str(p) + ".json", "w", encoding="utf-8") as f:
                json.dump(self._memories, f, default=str)
        logger.info("vector_memory.saved", path=path, entries=len(self._memories))

    def load(self, path: str) -> None:
        """
        Restore a previously saved FAISS index and metadata from disk.
        Raises FileNotFoundError if the files don't exist yet.
        """
        if not self._available:
            return
        index_path = str(path) + ".index"
        meta_path  = str(path) + ".json"
        if not Path(index_path).exists():
            raise FileNotFoundError(index_path)
        with self._write_lock:
            self._index = self._faiss.read_index(index_path)
            with open(meta_path, encoding="utf-8") as f:
                self._memories = json.load(f)
        logger.info("vector_memory.loaded", path=path, entries=len(self._memories))

    # ── Helpers ───────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._memories)

    @property
    def available(self) -> bool:
        return self._available
