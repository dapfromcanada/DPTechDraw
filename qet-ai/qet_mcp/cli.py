"""Typed wrapper around the DPTechDraw headless CLI.

Every method here shells out to DPTechDraw.exe and parses its output.
Known upstream bugs are guarded against rather than reproduced; each guard
cites the source location that motivates it. See docs-ai/03-cli-and-io.md.
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import QetConfig

# DiagramContext::addValue silently discards keys not matching this pattern
# and returns false; setTitleBlock ignores the return and still reports
# success (sources/diagramcontext.cpp:227-246). We validate up front instead.
INFO_KEY_RE = re.compile(r"^[a-z0-9_-]+$")

# Keys --set-titleblock maps to dedicated title-block fields rather than
# custom DiagramContext entries (sources/cli_export.cpp, --set-titleblock).
TITLEBLOCK_KNOWN_KEYS = frozenset(
    {"title", "author", "date", "plant", "location", "revision", "version", "filename"}
)

# csvField() quotes per RFC 4180 with a ';' delimiter (cli_export.cpp:288-297).
# Only --export-bom and --export-links use it. --export-cables and
# --export-wires stream raw values, so a ';' inside a label corrupts the row.
CSV_DELIMITER = ";"

UNQUOTED_EXPORTS = ("cables", "wires")


class QetError(RuntimeError):
    """A QET CLI invocation failed."""

    def __init__(self, message: str, *, args_used: list[str], returncode: int,
                 stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.args_used = args_used
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class QetProjectOpenError(QetError):
    """Refused to write because DPTechDraw appears to be running."""


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def message(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


class QetCli:
    """Thin, defensive wrapper over the DPTechDraw.exe CLI."""

    def __init__(self, config: QetConfig | None = None) -> None:
        self.config = config or QetConfig.from_env()

    # ---------------------------------------------------------------- internals

    def _run(self, args: list[str]) -> RunResult:
        cmd = [str(self.config.exe), *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.config.build_env(),
                timeout=self.config.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise QetError(
                f"QET CLI timed out after {self.config.timeout}s. A modal dialog may "
                "be blocking: QETProject::readProjectXml can open a QMessageBox on "
                "version mismatch, on the same load path the CLI uses "
                "(sources/qetproject.cpp:1470).",
                args_used=args,
                returncode=-1,
            ) from exc
        return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    def _require(self, args: list[str]) -> RunResult:
        result = self._run(args)
        if not result.ok:
            raise QetError(
                f"DPTechDraw {' '.join(args[:1])} failed (exit {result.returncode}): "
                f"{result.message}",
                args_used=args,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    @staticmethod
    def _check_project(project: str | Path) -> Path:
        path = Path(project)
        if not path.is_file():
            raise FileNotFoundError(f"Project not found: {path}")
        return path

    def _export_to_temp(self, flag: str, project: str | Path, suffix: str) -> tuple[str, RunResult]:
        """Run an export flag into a temp file and return its text content."""
        src = self._check_project(project)
        with tempfile.TemporaryDirectory(prefix="qet-mcp-") as tmp:
            out = Path(tmp) / f"export{suffix}"
            result = self._run([flag, str(src), str(out)])
            text = out.read_text(encoding="utf-8") if out.is_file() else ""
        return text, result

    @staticmethod
    def _parse_csv(text: str, *, headerless: bool = False) -> list[dict[str, str]] | list[str]:
        if not text.strip():
            return []
        reader = csv.reader(io.StringIO(text), delimiter=CSV_DELIMITER)
        rows = [r for r in reader if r]
        if headerless:
            return [r[0] for r in rows if r and r[0].strip()]
        header, *body = rows
        return [dict(zip(header, r)) for r in body]

    # ------------------------------------------------------------- capability

    def probe(self) -> dict[str, Any]:
        """Check whether this binary has the unreleased CLI export features.

        There is no --version flag. A supported build answers --info on a
        missing file with exit 2 and 'Project not found:'; a stable 0.100.1
        build does not recognise the flag at all.
        """
        result = self._run(["--info", "___qet_mcp_probe_nonexistent___.qet"])
        supported = "Project not found" in result.message or result.returncode == 2
        return {
            "exe": str(self.config.exe),
            "cli_supported": supported,
            "returncode": result.returncode,
            "message": result.message,
            "note": (
                "CLI export flags are unreleased (PRs #489/#490/#493). If "
                "cli_supported is false, this binary predates them."
            ),
        }

    # ------------------------------------------------------------ read-only ops

    def info(self, project: str | Path) -> dict[str, Any]:
        """Structural summary: per-page element/conductor counts, free terminals."""
        src = self._check_project(project)
        result = self._require(["--info", str(src)])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise QetError(
                f"--info returned unparseable JSON: {result.stdout[:200]}",
                args_used=["--info", str(src)],
                returncode=result.returncode,
            ) from exc

    def bom(self, project: str | Path) -> list[dict[str, str]]:
        """Bill of materials, one row per element.

        Columns (cli_export.cpp:307-310): label, designation, manufacturer,
        manufacturer_reference, quantity, location, function, title, folio.

        NOTE: element_nomenclature_view exposes no uuid column, so rows cannot
        be mapped back to specific elements. manufacturer_reference is the
        canonical part-number field.
        """
        text, result = self._export_to_temp("--export-bom", project, ".csv")
        if not result.ok and not text:
            raise QetError(
                f"--export-bom failed: {result.message}",
                args_used=["--export-bom"],
                returncode=result.returncode,
            )
        return self._parse_csv(text)  # type: ignore[return-value]

    def nets(self, project: str | Path) -> Any:
        """Electrical nets (connected-terminal groups) as parsed JSON."""
        text, result = self._export_to_temp("--export-nets", project, ".json")
        if not text.strip():
            if result.ok:
                return []
            raise QetError(
                f"--export-nets failed: {result.message}",
                args_used=["--export-nets"],
                returncode=result.returncode,
            )
        return json.loads(text)

    def links(self, project: str | Path) -> list[dict[str, str]]:
        """Element cross-references (coil/contact).

        Columns: element, link_type, linked_to, folio, status. UNRESOLVED is
        flagged only for Master/Slave with zero links — an orphaned folio
        report still reports as linked (cli_export.cpp:604).
        """
        text, result = self._export_to_temp("--export-links", project, ".csv")
        if not result.ok and not text:
            raise QetError(
                f"--export-links failed: {result.message}",
                args_used=["--export-links"],
                returncode=result.returncode,
            )
        return self._parse_csv(text)  # type: ignore[return-value]

    def wires(self, project: str | Path) -> list[str]:
        """Distinct wire numbers.

        Headerless single column. Exits 1 with 'Nothing to export (empty list)'
        when the project has no numbered wires -- that is not an error, so it
        is normalised to an empty list here.

        WARNING: values are streamed unquoted (conductornumexport.cpp:102), so
        a ';' inside a wire number would corrupt the file.
        """
        text, result = self._export_to_temp("--export-wires", project, ".csv")
        if not result.ok:
            if "Nothing to export" in result.message:
                return []
            raise QetError(
                f"--export-wires failed: {result.message}",
                args_used=["--export-wires"],
                returncode=result.returncode,
            )
        return self._parse_csv(text, headerless=True)  # type: ignore[return-value]

    def cables(self, project: str | Path) -> dict[str, Any]:
        """Wiring list, one row per conductor.

        Two upstream caveats, both surfaced in the return value:
        1. Values are streamed unquoted (wiringlistexport.cpp:380-388) -- a
           ';' in any label corrupts the row.
        2. Headers come from tr() and no translator is installed in CLI mode
           (QETApp is never constructed), so they are literally French:
           Page;Composant 1;Borne 1;Composant 2;Borne 2;...
        """
        text, result = self._export_to_temp("--export-cables", project, ".csv")
        if not result.ok and not text:
            raise QetError(
                f"--export-cables failed: {result.message}",
                args_used=["--export-cables"],
                returncode=result.returncode,
            )
        rows = self._parse_csv(text)
        return {
            "rows": rows,
            "headers_are_french": True,
            "quoting": "none - a ';' in a label will corrupt the row",
        }

    # ------------------------------------------------------------ validation

    def check_elements(self, target: str | Path) -> dict[str, Any]:
        """Validate .elmt file(s) against the element schema.

        IMPORTANT LIMITATION (cli_export.cpp:426-493): the validator checks
        only four things -- parseable XML, <definition type="element">,
        non-zero numeric width/height, and a document-wide terminal tag count.
        It uses toDouble(), but the runtime loaders require INTEGER literals
        (element.cpp:437-446). So width="90.0" passes validation and then
        fails to load. check_element_strict() closes that gap.
        """
        path = Path(target)
        if not path.exists():
            raise FileNotFoundError(f"Element path not found: {path}")
        result = self._run(["--check-elements", str(path)])
        return {
            "path": str(path),
            "passed": result.ok,
            "returncode": result.returncode,
            "output": result.message,
            "caveat": (
                "Upstream validator accepts non-integer width/height that the "
                "runtime loader rejects. Use check_element_strict for that."
            ),
        }

    def check_element_strict(self, element_file: str | Path) -> dict[str, Any]:
        """Upstream validation plus the integer-attribute rule it misses."""
        import xml.etree.ElementTree as ET

        path = Path(element_file)
        base = self.check_elements(path)
        problems: list[str] = []

        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            problems.append(f"XML parse error: {exc}")
            return {**base, "strict_passed": False, "problems": problems}

        if root.tag != "definition":
            problems.append(f"root tag is <{root.tag}>, expected <definition>")
        if root.get("type") != "element":
            problems.append(f'definition/@type is {root.get("type")!r}, expected "element"')

        # QET::attributeIsAnInteger -- a float literal makes the element fail
        # to load entirely, silently (element.cpp:437-446).
        for attr in ("width", "height", "hotspot_x", "hotspot_y"):
            raw = root.get(attr)
            if raw is None:
                problems.append(f"definition/@{attr} is missing")
                continue
            if not re.fullmatch(r"-?\d+", raw.strip()):
                problems.append(
                    f'definition/@{attr}="{raw}" is not an integer literal; '
                    "the runtime loader will reject this element silently"
                )

        return {**base, "strict_passed": not problems, "problems": problems}

    # ----------------------------------------------------------- write ops

    @staticmethod
    def is_qet_running() -> bool:
        """True if a DPTechDraw GUI process appears to be running.

        QET holds no lock and watches no .qet file, so an open project's next
        save silently clobbers anything written underneath it.
        """
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq DPTechDraw.exe", "/NH"],
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "dptechdraw.exe" in out.lower()

    def _guard_write(self, force: bool) -> None:
        if not force and self.is_qet_running():
            raise QetProjectOpenError(
                "DPTechDraw appears to be running. Writing now risks the GUI "
                "clobbering the result on its next save (QET holds no lock and "
                "watches no .qet file). Close QET, or pass force=True.",
                args_used=[], returncode=-1,
            )

    def resave(self, project: str | Path, output: str | Path,
               *, force: bool = False) -> dict[str, Any]:
        """Load and rewrite the project XML.

        WARNING: this is NOT idempotent. Verified over four successive passes:
        roughly 150 lines change on every no-op save. <terminal> integer ids
        are renumbered each save and conductors using legacy terminal1/
        terminal2 integer addressing follow. <element> lines stay byte-stable.

        Do not use this as a normaliser, and never diff .qet files textually.
        """
        src = self._check_project(project)
        self._guard_write(force)
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        result = self._require(["--resave", str(src), str(out)])
        return {
            "output": str(out),
            "message": result.message,
            "warning": "resave is not idempotent; terminal ids are renumbered",
        }

    def set_titleblock(self, project: str | Path, output: str | Path,
                       fields: dict[str, str], *, force: bool = False) -> dict[str, Any]:
        """Stamp title-block fields onto every folio, then save.

        Known keys: title, author, date, plant, location, revision, version,
        filename. Anything else becomes a custom DiagramContext field -- and
        those MUST match ^[a-z0-9_-]+$ or addValue drops them while the CLI
        still prints "Stamped N field(s)". We reject bad keys up front rather
        than let the caller believe a silent no-op succeeded.

        Note: 'date' accepts the literal 'today'. CLI dates are ISO
        YYYY-MM-DD; XML stores yyyyMMdd. date=today freezes the machine date
        rather than writing the dynamic date="now" marker.
        """
        src = self._check_project(project)
        if not fields:
            raise ValueError("fields is empty; nothing to stamp")

        rejected = {
            k: "custom title-block keys must match ^[a-z0-9_-]+$ (lowercase); "
               "QET would discard this silently and still report success"
            for k in fields
            if k not in TITLEBLOCK_KNOWN_KEYS and not INFO_KEY_RE.fullmatch(k)
        }
        if rejected:
            raise ValueError(f"Invalid title-block keys: {rejected}")

        for key, value in fields.items():
            if "=" in key:
                raise ValueError(f"'=' is not allowed in a key: {key!r}")
            if not isinstance(value, str):
                raise TypeError(f"field {key!r} must be a string, got {type(value).__name__}")

        self._guard_write(force)
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        pairs = [f"{k}={v}" for k, v in fields.items()]
        result = self._require(["--set-titleblock", str(src), str(out), *pairs])
        return {"output": str(out), "stamped": fields, "message": result.message}

    def export_render(self, project: str | Path, output: str | Path,
                      fmt: str = "pdf") -> dict[str, Any]:
        """Render to pdf (single multi-page file), or png/svg (one per folio)."""
        fmt = fmt.lower()
        if fmt not in ("pdf", "png", "svg"):
            raise ValueError(f"fmt must be pdf, png or svg; got {fmt!r}")
        src = self._check_project(project)
        out = Path(output)
        if fmt == "pdf":
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out.mkdir(parents=True, exist_ok=True)
        result = self._require([f"--export-{fmt}", str(src), str(out)])
        return {"output": str(out), "format": fmt, "message": result.message}
