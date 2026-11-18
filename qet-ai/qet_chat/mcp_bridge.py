"""Runs the qet_mcp server as a child process and talks MCP to it.

The MCP client is async; the window is Qt. A private asyncio loop runs in a
background thread and blocking helpers (list_tools, call_tool) hand work to
it. Any MCP server could be swapped in here: the chat only sees tool names,
descriptions, JSON schemas and JSON results.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, stdio_client

from .settings import SETTINGS_DIR

SERVER_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = SETTINGS_DIR / "mcp-server.log"


class McpBridge:
    def __init__(self, drawings_dir: str) -> None:
        self.drawings_dir = drawings_dir
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._session: ClientSession | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self.tools: list[Any] = []

    # ------------------------------------------------------------ lifecycle

    def start(self, timeout: float = 60) -> None:
        self._ready.clear()
        self._error = None
        self._future = asyncio.run_coroutine_threadsafe(self._run(), self._loop)
        if not self._ready.wait(timeout):
            raise TimeoutError("The drawing tools did not start within a minute")
        if self._error:
            raise RuntimeError(f"The drawing tools failed to start: {self._error}")

    async def _run(self) -> None:
        env = dict(os.environ)
        env["QET_DRAWINGS_DIR"] = self.drawings_dir
        env["PYTHONPATH"] = str(SERVER_DIR)
        params = StdioServerParameters(command=sys.executable, args=["-m", "qet_mcp.server"],
                                       cwd=str(SERVER_DIR), env=env)
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        self._stop = asyncio.Event()
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as errlog:
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self.tools = (await session.list_tools()).tools
                        self._session = session
                        self._ready.set()
                        await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - reported to the window
            self._error = exc
        finally:
            self._session = None
            self._ready.set()

    def stop(self) -> None:
        """Stop the server and wait for it to exit (so a restart can't race it)."""
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        fut = getattr(self, "_future", None)
        if fut is not None:
            try:
                fut.result(timeout=15)
            except Exception:  # noqa: BLE001 - already reported or shutting down
                pass

    def restart(self, drawings_dir: str) -> None:
        self.stop()
        self.drawings_dir = drawings_dir
        self.start()

    # ------------------------------------------------------------ calls

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None,
                  timeout: float = 300) -> dict[str, Any]:
        """Call a tool and return its JSON result as a dict."""
        if self._session is None:
            return {"ok": False, "error": "NotConnected",
                    "message": "The drawing tools are not running. Restart DPTechDraw Chat."}
        fut = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments or {}), self._loop)
        res = fut.result(timeout)
        data = getattr(res, "structured_content", None)
        if isinstance(data, dict):
            # FastMCP wraps non-dict returns as {"result": ...}
            return data
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except ValueError:
            return {"ok": not getattr(res, "is_error", False), "result": text}
