"""
VectorTool – Qdrant wrapper for semantic search.

Supports:
  • search(embedding, top_k) – nearest-neighbour lookup
  • upsert(id, embedding, payload) – add/update a document
  • create_collection(name, size) – one-time setup
"""

from __future__ import annotations

import os
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)


class VectorTool:
    def __init__(
        self,
        url: str | None = None,
        collection: str | None = None,
    ) -> None:
        self._url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self._collection = collection or os.getenv("QDRANT_COLLECTION", "artifex")
        self._client: AsyncQdrantClient | None = None

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(url=self._url)
        return self._client

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        params:
          action     (str)        – search | upsert | create_collection
          embedding  (list[float])– required for search / upsert
          top_k      (int)        – for search, default 5
          doc_id     (str)        – for upsert
          payload    (dict)       – for upsert
          size       (int)        – for create_collection
        """
        action = params.get("action", "search")
        if action == "search":
            embedding = params["embedding"]
            top_k = int(params.get("top_k", 5))
            return {"documents": await self.search(embedding, top_k)}
        elif action == "upsert":
            await self.upsert(
                doc_id=params["doc_id"],
                embedding=params["embedding"],
                payload=params.get("payload", {}),
            )
            return {"upserted": True}
        elif action == "create_collection":
            await self.create_collection(
                name=params.get("name", self._collection),
                size=int(params["size"]),
            )
            return {"created": True}
        else:
            raise ValueError(f"Unknown vector action: {action}")

    async def search(
        self, embedding: list[float], top_k: int = 5
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        results = await client.search(
            collection_name=self._collection,
            query_vector=embedding,
            limit=top_k,
            with_payload=True,
        )
        return [
            {"id": str(r.id), "score": r.score, "payload": r.payload}
            for r in results
        ]

    async def upsert(
        self, doc_id: str, embedding: list[float], payload: dict[str, Any]
    ) -> None:
        client = await self._get_client()
        await client.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=doc_id, vector=embedding, payload=payload)],
        )

    async def create_collection(self, name: str, size: int = 1536) -> None:
        client = await self._get_client()
        await client.recreate_collection(
            collection_name=name,
            vectors_config=VectorParams(size=size, distance=Distance.COSINE),
        )
