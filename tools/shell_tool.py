"""
ShellTool – run shell commands in a subprocess with timeout.

Security notes:
  • Commands are passed as a list (no shell=True) to prevent injection.
  • Working directory is sandboxed to /tmp/artifex_sandbox.
  • A hard timeout (default 30 s) kills runaway processes.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any


SANDBOX_DIR = os.getenv("SHELL_SANDBOX_DIR", "/tmp/artifex_sandbox")


class ShellTool:
    DEFAULT_TIMEOUT = 30

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        params:
          command (str | list) – shell command
          timeout (int)        – seconds, default 30
          cwd     (str)        – working directory (must be inside sandbox)
        """
        raw_cmd = params.get("command", "")
        timeout: int = int(params.get("timeout", self.DEFAULT_TIMEOUT))
        cwd: str = params.get("cwd", SANDBOX_DIR)

        # Ensure sandbox exists
        os.makedirs(SANDBOX_DIR, exist_ok=True)

        # Resolve and validate cwd is inside sandbox
        cwd = os.path.realpath(cwd)
        sandbox = os.path.realpath(SANDBOX_DIR)
        if not cwd.startswith(sandbox):
            raise PermissionError(f"cwd '{cwd}' is outside sandbox '{sandbox}'")

        if isinstance(raw_cmd, str):
            cmd_list = shlex.split(raw_cmd)
        else:
            cmd_list = list(raw_cmd)

        proc = await asyncio.create_subprocess_exec(
            *cmd_list,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"Command timed out after {timeout}s: {raw_cmd}")

        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }
