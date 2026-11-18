"""DPTechDraw Chat window (PySide6)."""

from __future__ import annotations

import html
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
                               QTextBrowser, QVBoxLayout, QWidget)

from qet_mcp import drawing as qd
from qet_mcp.config import QetConfig

from .agent import Agent
from .mcp_bridge import McpBridge
from .prompt import system_prompt
from .settings import PROVIDERS, Settings, get_api_key, set_api_key

TOOL_LABELS = {
    "qet_create_drawing": "Creating drawing",
    "qet_list_parts": "Checking parts",
    "qet_release": "Releasing",
    "qet_stamp_date": "Updating date",
    "qet_bom": "Reading parts list",
    "qet_cables": "Reading wire list",
    "qet_nets": "Reading connections",
    "qet_info": "Checking drawing",
    "qet_render": "Exporting",
    "qet_is_open": "Checking if DPTechDraw is open",
}


class Bus(QObject):
    """Thread-safe hand-off from worker threads to the window."""
    event = Signal(str, object)
    done = Signal(object)          # None or an error message
    ready = Signal(object)         # None or an error message (tools started)


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget, settings: Settings) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI settings")
        self.settings = settings
        p = settings.provider
        form = QFormLayout(self)
        form.addRow(QLabel(f"<b>{html.escape(p)}</b>"))
        self.url = QLineEdit(settings.base_url(p))
        self.url.setPlaceholderText("Server address, e.g. http://127.0.0.1:1234/v1")
        if settings.kind(p) == "openai":
            form.addRow("Server address", self.url)
        self.key = QLineEdit(get_api_key(p))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Stored in Windows Credential Manager")
        form.addRow("API key", self.key)
        if not settings.needs_key(p):
            form.addRow(QLabel("A key is usually not needed for local AI."))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(480, 0)

    def accept(self) -> None:
        p = self.settings.provider
        set_api_key(p, self.key.text().strip())
        if self.settings.kind(p) == "openai":
            self.settings.base_urls[p] = self.url.text().strip()
        self.settings.save()
        super().accept()


class ChatWindow(QMainWindow):
    def __init__(self, agent_factory: Any = None) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.bus = Bus()
        self.bus.event.connect(self._on_event)
        self.bus.done.connect(self._on_done)
        self.bus.ready.connect(self._on_ready)
        self.agent: Agent | None = None
        self.agent_key: tuple = ()
        self.agent_factory = agent_factory          # tests inject a fake AI here
        self.auto_open_qet = agent_factory is None  # tests must not pop up QET
        self.bridge = McpBridge(self.settings.drawings_dir)
        self.busy = False
        self._build_ui()
        self._refresh_paths()
        self._set_busy(True, "Starting drawing tools...")
        threading.Thread(target=self._start_bridge, daemon=True).start()

    # ------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.setWindowTitle("DPTechDraw Chat")
        self.resize(560, 760)
        root = QWidget()
        lay = QVBoxLayout(root)

        row = QHBoxLayout()
        row.addWidget(QLabel("AI:"))
        self.provider = QComboBox()
        self.provider.addItems(list(PROVIDERS))
        self.provider.setCurrentText(self.settings.provider)
        self.provider.currentTextChanged.connect(self._provider_changed)
        row.addWidget(self.provider)
        row.addWidget(QLabel("Model:"))
        self.model = QLineEdit(self.settings.model())
        self.model.editingFinished.connect(self._model_changed)
        row.addWidget(self.model, 1)
        btn = QPushButton("Settings...")
        btn.clicked.connect(self._open_settings)
        row.addWidget(btn)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Save folder:"))
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        row.addWidget(self.folder, 1)
        btn = QPushButton("Browse...")
        btn.clicked.connect(self._pick_folder)
        row.addWidget(btn)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Drawing:"))
        self.current = QLineEdit()
        self.current.setReadOnly(True)
        row.addWidget(self.current, 1)
        btn = QPushButton("Open...")
        btn.clicked.connect(self._pick_drawing)
        row.addWidget(btn)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.btn_qet = QPushButton("Open in DPTechDraw")
        self.btn_qet.clicked.connect(self._open_in_qet)
        row.addWidget(self.btn_qet)
        self.btn_release = QPushButton("Release new revision")
        self.btn_release.clicked.connect(self._release)
        row.addWidget(self.btn_release)
        row.addStretch(1)
        btn = QPushButton("New chat")
        btn.clicked.connect(self._new_chat)
        row.addWidget(btn)
        lay.addLayout(row)

        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(False)
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Describe the drawing... (Ctrl+Enter to send)")
        self.input.setFixedHeight(90)
        row.addWidget(self.input, 1)
        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        lay.addLayout(row)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._send)

        self.setCentralWidget(root)
        self._say("info", "Tell me what to draw, e.g. <i>DB9 male, pins 2, 3 and 5 to "
                          "terminals X1 to X3, red, white, black, and a ground on X3.</i>")

    # ------------------------------------------------------------ helpers

    def _say(self, who: str, text: str, raw_html: bool = True) -> None:
        body = text if raw_html else html.escape(text).replace("\n", "<br>")
        style = {
            "you": "<p><b>You:</b> {}</p>",
            "ai": "<p><b>AI:</b> {}</p>",
            "tool": "<p style='color:#777; font-size:small'>&#9881; {}</p>",
            "info": "<p style='color:#557'>{}</p>",
            "error": "<p style='color:#b00'><b>Problem:</b> {}</p>",
        }[who]
        self.log.append(style.format(body))

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.busy = busy
        self.btn_send.setEnabled(not busy)
        self.btn_release.setEnabled(not busy)
        self.statusBar().showMessage(status)

    def _refresh_paths(self) -> None:
        self.folder.setText(self.settings.drawings_dir)
        self.current.setText(self.settings.current_drawing)
        has = bool(self.settings.current_drawing) and Path(self.settings.current_drawing).is_file()
        self.btn_qet.setEnabled(has)
        self.btn_release.setEnabled(has and not self.busy)

    def _start_bridge(self) -> None:
        try:
            self.bridge.start()
            self.bus.ready.emit(None)
        except Exception as exc:  # noqa: BLE001
            self.bus.ready.emit(str(exc))

    def _on_ready(self, error: str | None) -> None:
        if error:
            self._set_busy(True, "Drawing tools not running")
            self._say("error", html.escape(error) + "<br>Details: %APPDATA%\\QetChat\\mcp-server.log")
        else:
            self._set_busy(False, f"Ready - {len(self.bridge.tools)} tools")
            self._refresh_paths()

    # ------------------------------------------------------------ settings

    def _provider_changed(self, name: str) -> None:
        self.settings.provider = name
        self.model.setText(self.settings.model(name))
        self.settings.save()

    def _model_changed(self) -> None:
        self.settings.models[self.settings.provider] = self.model.text().strip()
        self.settings.save()

    def _open_settings(self) -> None:
        SettingsDialog(self, self.settings).exec()

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder for new drawings",
                                             self.settings.drawings_dir)
        if not d:
            return
        self.settings.drawings_dir = str(Path(d))
        self.settings.save()
        self._refresh_paths()
        self._set_busy(True, "Restarting drawing tools...")

        def restart() -> None:
            try:
                self.bridge.restart(self.settings.drawings_dir)
                self.bus.ready.emit(None)
            except Exception as exc:  # noqa: BLE001
                self.bus.ready.emit(str(exc))
        threading.Thread(target=restart, daemon=True).start()

    def _pick_drawing(self) -> None:
        start = self.settings.current_drawing or self.settings.drawings_dir
        f, _ = QFileDialog.getOpenFileName(self, "Open drawing", start,
                                           "DPTechDraw drawings (*.qet)")
        if f:
            self._set_current(f)
            self._say("info", f"Working on <b>{html.escape(Path(f).name)}</b>")

    def _set_current(self, path: str) -> None:
        self.settings.current_drawing = str(Path(path))
        self.settings.save()
        self._refresh_paths()

    # ------------------------------------------------------------ buttons

    def _open_in_qet(self, path: str | None = None) -> None:
        """Open a drawing in DPTechDraw. If it is already running, QET's
        single-instance handling passes the file to the open window, where it
        appears as another project (sources/main.cpp:154-190)."""
        path = path if isinstance(path, str) and path else self.settings.current_drawing
        try:
            cfg = QetConfig.from_env()
            env = cfg.build_env()
            env.pop("QT_QPA_PLATFORM", None)        # the GUI must be visible
            subprocess.Popen([str(cfg.exe), path], env=env, cwd=str(cfg.exe.parent))
            self.statusBar().showMessage(f"Opening {Path(path).name} in DPTechDraw...")
        except Exception as exc:  # noqa: BLE001
            self._say("error", html.escape(str(exc)))

    def _release(self) -> None:
        path = Path(self.settings.current_drawing)
        try:
            cur = qd.read_title_block(path)["revision"]
            new = qd.next_revision(cur)
        except Exception as exc:  # noqa: BLE001
            self._say("error", html.escape(str(exc)))
            return
        ok = QMessageBox.question(
            self, "Release new revision",
            f"Release {path.name}?\n\nRevision {cur or '(none)'}  ->  {new}\n"
            "Today's date will be stamped. A backup is made first.")
        if ok != QMessageBox.Yes:
            return
        res = self.bridge.call_tool("qet_release", {"project": str(path)})
        if res.get("ok"):
            self._say("info", f"Released <b>{html.escape(path.name)}</b> as revision "
                              f"<b>{html.escape(str(res.get('revision')))}</b>.")
        else:
            msg = res.get("message", "Release failed")
            if res.get("error") == "QetProjectOpenError":
                msg = "DPTechDraw is open. Save and close it, then press Release again."
            self._say("error", html.escape(msg))

    def _new_chat(self) -> None:
        if self.agent:
            self.agent.reset()
        self.log.clear()
        self._say("info", "New chat started.")

    # ------------------------------------------------------------ chat

    def _get_agent(self) -> Agent:
        s = self.settings
        key = get_api_key(s.provider)
        sig = (s.provider, s.model(), s.base_url(), key)
        if self.agent is None or sig != self.agent_key:
            if self.agent_factory:
                self.agent = self.agent_factory(self.bridge)
            else:
                if s.needs_key() and not key:
                    raise RuntimeError(f"No API key set for {s.provider}. Press Settings... to add it.")
                self.agent = Agent(s.kind(), s.model(), self.bridge.tools, self.bridge.call_tool,
                                   api_key=key, base_url=s.base_url())
            self.agent_key = sig
        return self.agent

    def _parts_summary(self) -> str:
        res = self.bridge.call_tool("qet_list_parts", {})
        lines = [f"- {p['part']} ({p['name']}): pins {', '.join(p['pins'])}"
                 for p in res.get("parts", [])]
        return "\n".join(lines) or "(no parts found)"

    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or self.busy:
            return
        self._model_changed()
        try:
            agent = self._get_agent()
        except Exception as exc:  # noqa: BLE001
            self._say("error", html.escape(str(exc)))
            if "API key" in str(exc):
                self._open_settings()
            return
        self.input.clear()
        self._say("you", text, raw_html=False)
        self._set_busy(True, "Thinking...")

        def work() -> None:
            try:
                system = system_prompt(self.settings.drawings_dir,
                                       self.settings.current_drawing, self._parts_summary())
                agent.send(text, system, lambda k, p: self.bus.event.emit(k, p))
                self.bus.done.emit(None)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.bus.done.emit(f"{type(exc).__name__}: {exc}")
        threading.Thread(target=work, daemon=True).start()

    def _on_event(self, kind: str, payload: Any) -> None:
        if kind == "text":
            self._say("ai", payload, raw_html=False)
        elif kind == "tool":
            label = TOOL_LABELS.get(payload["name"], payload["name"])
            self._say("tool", html.escape(label) + "...")
            self.statusBar().showMessage(label + "...")
        elif kind == "tool_result":
            res = payload["result"] or {}
            if payload["name"] in ("qet_create_drawing", "qet_release", "qet_stamp_date") \
                    and res.get("ok") and res.get("file"):
                self._set_current(res["file"])
                if payload["name"] == "qet_create_drawing" and self.auto_open_qet:
                    self._open_in_qet(res["file"])
            if res.get("note"):
                self._say("tool", html.escape(str(res["note"])))
            if res.get("ok") is False:
                self._say("tool", "tool reported: " + html.escape(str(res.get("message", "")))[:300])

    def _on_done(self, error: str | None) -> None:
        if error:
            self._say("error", html.escape(error))
        self._set_busy(False, "Ready")
        self._refresh_paths()
        self.input.setFocus()

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt name
        self.bridge.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("DPTechDraw Chat")
    win = ChatWindow()
    win.show()
    sys.exit(app.exec())
