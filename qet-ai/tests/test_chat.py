"""End-to-end tests for DPTechDraw Chat with scripted stand-ins for the AI.

The real MCP server is started over stdio and real drawings are written to
pytest's temp folder; only the AI's replies are scripted. This proves the
Claude-format and OpenAI-format tool loops both drive the tools correctly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from qet_chat.agent import Agent
from qet_chat.mcp_bridge import McpBridge
from qet_mcp import drawing as qd

DRAW_ARGS = {
    "title": "Chat test",
    "parts": [{"id": "X1", "part": "terminal_block"}, {"id": "J1", "part": "dsub9_male"}],
    "wires": [{"from": "J1:2", "to": "X1:1", "name": "W1", "colour": "red"}],
    "output": "chat_test",
}


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    folder = tmp_path_factory.mktemp("drawings")
    b = McpBridge(str(folder))
    b.start()
    yield b
    b.stop()


def test_bridge_lists_drawing_tools(bridge) -> None:
    names = {t.name for t in bridge.tools}
    assert {"qet_create_drawing", "qet_release", "qet_list_parts"} <= names


# ---------------------------------------------------------------- Claude format

class FakeAnthropic:
    """Replies: 1) list parts, 2) create drawing, 3) plain text."""

    def __init__(self) -> None:
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        if n == 1:
            return NS(content=[NS(type="text", text="Checking parts."),
                               NS(type="tool_use", id="t1", name="qet_list_parts", input={})])
        if n == 2:
            return NS(content=[NS(type="tool_use", id="t2", name="qet_create_drawing",
                                  input=DRAW_ARGS)])
        return NS(content=[NS(type="text", text="Done: chat_test.qet")])


def test_claude_loop_creates_a_real_drawing(bridge) -> None:
    fake = FakeAnthropic()
    agent = Agent("anthropic", "test-model", bridge.tools, bridge.call_tool, client=fake)
    events = []
    agent.send("draw it", "system", lambda k, p: events.append((k, p)))

    results = [p["result"] for k, p in events if k == "tool_result"]
    created = results[-1]
    assert created["ok"], created
    assert created["check"]["wires_loaded"] == 1
    assert Path(created["file"]).is_file()
    # tool results went back to the model as tool_result blocks
    tool_turns = [m for m in agent.history if m["role"] == "user"
                  and isinstance(m["content"], list) and m["content"][0]["type"] == "tool_result"]
    assert len(tool_turns) == 2
    assert ("text", "Done: chat_test.qet") in events
    # tools were sent in Anthropic shape
    assert "input_schema" in fake.calls[0]["tools"][0]


# ---------------------------------------------------------------- OpenAI format

class FakeOpenAI:
    def __init__(self) -> None:
        self.calls = []
        self.chat = NS(completions=self)

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            args = dict(DRAW_ARGS, output="chat_test_openai")
            call = NS(id="c1", function=NS(name="qet_create_drawing", arguments=json.dumps(args)))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[call]))])
        return NS(choices=[NS(message=NS(content="Saved.", tool_calls=None))])


def test_openai_loop_creates_a_real_drawing(bridge) -> None:
    fake = FakeOpenAI()
    agent = Agent("openai", "local-model", bridge.tools, bridge.call_tool, client=fake)
    events = []
    agent.send("draw it", "system", lambda k, p: events.append((k, p)))
    created = [p["result"] for k, p in events if k == "tool_result"][0]
    assert created["ok"], created
    assert fake.calls[1]["messages"][-1]["role"] == "tool"
    assert fake.calls[0]["tools"][0]["type"] == "function"


def test_failed_turn_is_rolled_back(bridge) -> None:
    class Boom:
        messages = None

        def create(self, **kw):
            raise ConnectionError("network down")
    boom = Boom()
    boom.messages = boom
    agent = Agent("anthropic", "m", bridge.tools, bridge.call_tool, client=boom)
    with pytest.raises(ConnectionError):
        agent.send("hi", "s", lambda k, p: None)
    assert agent.history == []


# ---------------------------------------------------------------- the window

def test_window_end_to_end(tmp_path, monkeypatch) -> None:
    """Open the real window off-screen, send a message, check the result."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    import qet_chat.mcp_bridge as mb
    import qet_chat.settings as st
    monkeypatch.setattr(st, "SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "cfg" / "settings.json")
    monkeypatch.setattr(mb, "SETTINGS_DIR", tmp_path / "cfg")
    monkeypatch.setattr(mb, "LOG_FILE", tmp_path / "cfg" / "server.log")
    st.Settings(drawings_dir=str(tmp_path / "drawings")).save()

    from PySide6.QtWidgets import QApplication
    from qet_chat.app import ChatWindow
    app = QApplication.instance() or QApplication([])

    def factory(bridge):
        return Agent("anthropic", "m", bridge.tools, bridge.call_tool, client=FakeAnthropic())

    win = ChatWindow(agent_factory=factory)

    def pump(until, secs=60):
        end = time.time() + secs
        while time.time() < end and not until():
            app.processEvents()
            time.sleep(0.05)
        return until()

    try:
        assert pump(lambda: not win.busy), "tools never started"
        win.input.setPlainText("DB9 pin 2 to X1, red")
        win._send()
        assert pump(lambda: not win.busy and "Done" in win.log.toPlainText()), win.log.toPlainText()
        cur = Path(win.settings.current_drawing)
        assert cur.is_file() and cur.parent == tmp_path / "drawings"
        assert win.btn_release.isEnabled()
        assert qd.read_title_block(cur)["revision"] == "1.0"
        # Release through the same path the button uses (dialog skipped)
        res = win.bridge.call_tool("qet_release", {"project": str(cur)})
        from qet_mcp.cli import QetCli
        if QetCli.is_qet_running():
            # the safety guard must refuse and leave the file alone
            assert res["error"] == "QetProjectOpenError", res
            assert qd.read_title_block(cur)["revision"] == "1.0"
        else:
            assert res["ok"] and res["revision"] == "1.1", res
    finally:
        win.close()
