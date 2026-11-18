"""The chat loop: send the conversation to an AI, run the tools it asks for,
feed the results back, repeat until it answers in plain text.

Two provider styles cover everything Derek asked for:
- "anthropic": Claude via the Anthropic API.
- "openai":    anything OpenAI-compatible - LM Studio, Ollama, DeepSeek.
Each keeps its conversation in its own native format.
"""

from __future__ import annotations

import json
from typing import Any, Callable

MAX_TOOL_ROUNDS = 20
MAX_RESULT_CHARS = 20000

Event = Callable[[str, Any], None]   # on_event(kind, payload)
ToolRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


def _result_text(result: dict[str, Any]) -> str:
    text = json.dumps(result, indent=1, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n...[truncated]"
    return text


class Agent:
    def __init__(self, kind: str, model: str, tools: list[Any], run_tool: ToolRunner,
                 api_key: str = "", base_url: str = "", client: Any = None) -> None:
        if not model:
            raise ValueError("No model name set. Pick one in Settings.")
        self.kind = kind
        self.model = model
        self.run_tool = run_tool
        self.history: list[dict[str, Any]] = []
        if kind == "anthropic":
            if client is None:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key or None)
            self.tools = [{"name": t.name, "description": t.description or "",
                           "input_schema": t.input_schema} for t in tools]
        else:
            if client is None:
                import openai
                client = openai.OpenAI(base_url=base_url or None,
                                       api_key=api_key or "not-needed")
            self.tools = [{"type": "function",
                           "function": {"name": t.name, "description": t.description or "",
                                        "parameters": t.input_schema}} for t in tools]
        self.client = client

    def reset(self) -> None:
        self.history.clear()

    def send(self, text: str, system: str, on_event: Event) -> None:
        """Run one user turn. On failure the turn is removed from the history,
        so a network error never leaves the conversation half-written."""
        start = len(self.history)
        try:
            if self.kind == "anthropic":
                self._send_anthropic(text, system, on_event)
            else:
                self._send_openai(text, system, on_event)
        except Exception:
            del self.history[start:]
            raise

    # ------------------------------------------------------------ tools

    def _do_tool(self, name: str, args: dict[str, Any], on_event: Event) -> str:
        on_event("tool", {"name": name, "args": args})
        try:
            result = self.run_tool(name, args)
        except Exception as exc:  # noqa: BLE001 - give the AI the error
            result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        on_event("tool_result", {"name": name, "result": result})
        return _result_text(result)

    # ------------------------------------------------------------ Claude

    def _send_anthropic(self, text: str, system: str, on_event: Event) -> None:
        self.history.append({"role": "user", "content": text})
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.client.messages.create(
                model=self.model, max_tokens=4096, system=system,
                messages=self.history, tools=self.tools)
            blocks: list[dict[str, Any]] = []
            calls = []
            for b in resp.content:
                if b.type == "text":
                    blocks.append({"type": "text", "text": b.text})
                    if b.text.strip():
                        on_event("text", b.text)
                elif b.type == "tool_use":
                    blocks.append({"type": "tool_use", "id": b.id, "name": b.name,
                                   "input": b.input})
                    calls.append(b)
            self.history.append({"role": "assistant", "content": blocks or
                                 [{"type": "text", "text": "(no reply)"}]})
            if not calls:
                return
            results = [{"type": "tool_result", "tool_use_id": c.id,
                        "content": self._do_tool(c.name, dict(c.input or {}), on_event)}
                       for c in calls]
            self.history.append({"role": "user", "content": results})
        on_event("text", f"(Stopped after {MAX_TOOL_ROUNDS} tool rounds.)")

    # ------------------------------------------------------------ OpenAI-style

    def _send_openai(self, text: str, system: str, on_event: Event) -> None:
        self.history.append({"role": "user", "content": text})
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *self.history],
                tools=self.tools)
            msg = resp.choices[0].message
            calls = list(msg.tool_calls or [])
            entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if calls:
                entry["tool_calls"] = [{"id": c.id, "type": "function",
                                        "function": {"name": c.function.name,
                                                     "arguments": c.function.arguments or "{}"}}
                                       for c in calls]
            self.history.append(entry)
            if msg.content and msg.content.strip():
                on_event("text", msg.content)
            if not calls:
                return
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                    out = self._do_tool(c.function.name, args, on_event)
                except ValueError as exc:
                    out = _result_text({"ok": False, "error": "BadArguments",
                                        "message": f"Arguments were not valid JSON: {exc}"})
                self.history.append({"role": "tool", "tool_call_id": c.id, "content": out})
        on_event("text", f"(Stopped after {MAX_TOOL_ROUNDS} tool rounds.)")
