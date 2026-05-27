"""
FileTool – sandboxed file read/write/list operations.

All paths are resolved relative to SANDBOX_DIR and must stay inside it.
"""

from __future__ import annotations

import os
from typing import Any

SANDBOX_DIR = os.getenv("FILE_SANDBOX_DIR", "/tmp/artifex_files")


class FileTool:
    def __init__(self, sandbox: str = SANDBOX_DIR) -> None:
        self._sandbox = os.path.realpath(sandbox)
        os.makedirs(self._sandbox, exist_ok=True)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        params:
          action  (str) – read | write | list | delete
          path    (str) – relative path inside sandbox
          content (str) – required for write
        """
        action: str = params.get("action", "read")
        rel_path: str = params.get("path", "")
        content: str = params.get("content", "")

        full_path = self._safe_path(rel_path)

        if action == "read":
            return await self._read(full_path)
        elif action == "write":
            return await self._write(full_path, content)
        elif action == "list":
            return await self._list(full_path)
        elif action == "delete":
            return await self._delete(full_path)
        else:
            raise ValueError(f"Unknown file action: {action}")

    # ── Operations ────────────────────────────────────────────────────────────

    async def _read(self, path: str) -> dict[str, Any]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(path, encoding="utf-8") as fh:
            return {"content": fh.read(), "path": path}

    async def _write(self, path: str, content: str) -> dict[str, Any]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {"written": True, "path": path, "bytes": len(content.encode())}

    async def _list(self, path: str) -> dict[str, Any]:
        if not os.path.isdir(path):
            raise NotADirectoryError(f"Not a directory: {path}")
        entries = os.listdir(path)
        return {"entries": entries, "path": path}

    async def _delete(self, path: str) -> dict[str, Any]:
        if os.path.isfile(path):
            os.remove(path)
            return {"deleted": True, "path": path}
        raise FileNotFoundError(f"File not found: {path}")

    # ── Safety ────────────────────────────────────────────────────────────────

    def _safe_path(self, rel_path: str) -> str:
        full = os.path.realpath(os.path.join(self._sandbox, rel_path))
        if not full.startswith(self._sandbox):
            raise PermissionError(f"Path '{rel_path}' escapes sandbox")
        return full
