"""
web_search_tool.py – Real-time web search for the Artifex swarm.

Primary:  Tavily (free tier, LLM-optimised, returns clean summaries + sources)
Fallback: duckduckgo-search (no API key required)

Usage:
    results = await web_search("current weather London")
    answer  = await web_search_with_answer("who won the latest F1 race")
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

logger = structlog.get_logger()

TAVILY_API_KEY: str | None = os.getenv("TAVILY_API_KEY")

# ── Tavily client (lazy-initialised) ─────────────────────────────────────────

_tavily_client: Any = None


def _get_tavily():
    global _tavily_client
    if _tavily_client is None:
        from tavily import TavilyClient  # type: ignore
        _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily_client


# ── Public API ────────────────────────────────────────────────────────────────

async def web_search(
    query: str,
    num_results: int = 5,
    days: int | None = None,
) -> list[dict[str, Any]]:
    """
    Search the web and return a list of result dicts:
      [{"title": str, "url": str, "snippet": str, "score": float}, ...]

    Falls back to DuckDuckGo if TAVILY_API_KEY is not set.
    """
    if TAVILY_API_KEY:
        return await _tavily_search(query, num_results, days)
    return await _ddg_search(query, num_results)


async def web_search_with_answer(
    query: str,
    num_results: int = 5,
    days: int | None = None,
) -> dict[str, Any]:
    """
    Search and synthesise a direct answer (Tavily feature).
    Returns:
      {
        "answer":  str,                          # Tavily-generated summary
        "sources": [{"title": str, "url": str}],
        "results": [{"title", "snippet", "url", "score"}],
      }
    Falls back gracefully to snippet-only if Tavily unavailable.
    """
    if TAVILY_API_KEY:
        return await _tavily_search_with_answer(query, num_results, days)

    # DuckDuckGo fallback – no synthesised answer, just results
    results = await _ddg_search(query, num_results)
    return {
        "answer": results[0]["snippet"] if results else "",
        "sources": [{"title": r["title"], "url": r["url"]} for r in results],
        "results": results,
    }


# ── Tavily implementation ─────────────────────────────────────────────────────

async def _tavily_search(
    query: str, num_results: int, days: int | None
) -> list[dict[str, Any]]:
    loop = asyncio.get_event_loop()

    def _sync():
        client = _get_tavily()
        kwargs: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "max_results": num_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        if days:
            kwargs["days"] = days
        resp = client.search(**kwargs)
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", ""),
                "score":   r.get("score", 0.0),
            }
            for r in resp.get("results", [])
        ]

    return await loop.run_in_executor(None, _sync)


async def _tavily_search_with_answer(
    query: str, num_results: int, days: int | None
) -> dict[str, Any]:
    loop = asyncio.get_event_loop()

    def _sync():
        client = _get_tavily()
        kwargs: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "max_results": num_results,
            "include_answer": True,
            "include_raw_content": False,
        }
        if days:
            kwargs["days"] = days
        resp = client.search(**kwargs)
        results = [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("content", ""),
                "score":   r.get("score", 0.0),
            }
            for r in resp.get("results", [])
        ]
        return {
            "answer":  resp.get("answer", ""),
            "sources": [{"title": r["title"], "url": r["url"]} for r in results],
            "results": results,
        }

    return await loop.run_in_executor(None, _sync)


# ── DuckDuckGo fallback ───────────────────────────────────────────────────────

async def _ddg_search(query: str, num_results: int) -> list[dict[str, Any]]:
    loop = asyncio.get_event_loop()

    def _sync():
        from duckduckgo_search import DDGS  # type: ignore
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "score":   1.0,
                })
        return results

    try:
        return await loop.run_in_executor(None, _sync)
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_search.ddg_error", error=str(exc))
        return []
