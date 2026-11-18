"""MCP server exposing the DPTechDraw headless CLI as tools.

Run with:  uv run python -m qet_mcp.server
Or via the MCP dev inspector:  uv run mcp dev qet_mcp/server.py

Scope note: this server deliberately wraps only what QET's own CLI already
does correctly. It does not re-implement .qet XML parsing or BOM scraping --
QET builds an internal SQLite database for that, and duplicating it would
drift. Scaffolding (writing .qet / .elmt files) is a separate layer and is
not part of this module.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from . import drawing
from .cli import QetCli, QetError, QetProjectOpenError
from .config import QetNotFoundError

# MCP Python SDK 2.x renamed FastMCP to MCPServer; the decorator and run()
# surface are otherwise unchanged.
mcp = MCPServer("dptechdraw")

_cli: QetCli | None = None


def cli() -> QetCli:
    """Lazily resolve the binary so import never fails on a machine without it."""
    global _cli
    if _cli is None:
        _cli = QetCli()
    return _cli


def _fail(exc: Exception) -> dict[str, Any]:
    """Turn an exception into a structured result the model can act on."""
    return {
        "ok": False,
        "error": type(exc).__name__,
        "message": str(exc),
    }


@mcp.tool()
def qet_probe() -> dict[str, Any]:
    """Check that the DPTechDraw binary is present and has the CLI export features.

    Call this first. The export flags are unreleased upstream and only exist in
    a locally built binary; a stable 0.100.1 install will report false.
    """
    try:
        return {"ok": True, **cli().probe()}
    except (QetNotFoundError, QetError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_info(project: str) -> dict[str, Any]:
    """Structural summary of a .qet project.

    Returns per-folio element and conductor counts plus unconnected terminal
    counts. Cheap; use it to sanity-check a project before heavier operations.

    Args:
        project: Absolute path to a .qet file.
    """
    try:
        return {"ok": True, "info": cli().info(project)}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_bom(project: str) -> dict[str, Any]:
    """Bill of materials for a project, one row per element.

    Columns: label, designation, manufacturer, manufacturer_reference,
    quantity, location, function, title, folio.

    manufacturer_reference is the canonical part-number field. Note that rows
    carry no element UUID, so they cannot be mapped back to individual
    elements on the drawing.

    Args:
        project: Absolute path to a .qet file.
    """
    try:
        rows = cli().bom(project)
        return {"ok": True, "count": len(rows), "rows": rows}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_nets(project: str) -> dict[str, Any]:
    """Electrical nets -- groups of terminals connected by conductors.

    Args:
        project: Absolute path to a .qet file.
    """
    try:
        return {"ok": True, "nets": cli().nets(project)}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_links(project: str) -> dict[str, Any]:
    """Element cross-references (coil/contact master-slave links).

    Columns: element, link_type, linked_to, folio, status. Status is
    UNRESOLVED only for Master/Slave elements with zero links; an orphaned
    folio report still reports as linked.

    Args:
        project: Absolute path to a .qet file.
    """
    try:
        rows = cli().links(project)
        return {"ok": True, "count": len(rows), "rows": rows}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_wires(project: str) -> dict[str, Any]:
    """Distinct wire numbers used in the project.

    Returns an empty list when the project has no numbered wires (upstream
    exits 1 in that case; it is not treated as an error here).

    Args:
        project: Absolute path to a .qet file.
    """
    try:
        values = cli().wires(project)
        return {"ok": True, "count": len(values), "wires": values}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_cables(project: str) -> dict[str, Any]:
    """Wiring list, one row per conductor.

    Two upstream caveats are echoed in the result: headers are French (no
    translator is loaded in CLI mode) and values are unquoted, so a ';' in any
    label corrupts that row.

    Args:
        project: Absolute path to a .qet file.
    """
    try:
        return {"ok": True, **cli().cables(project)}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_check_element(element_file: str) -> dict[str, Any]:
    """Validate a .elmt element file, strictly.

    Runs QET's own --check-elements and then adds the check it misses:
    width, height, hotspot_x and hotspot_y must be INTEGER literals. QET's
    validator accepts "90.0" but the runtime loader silently rejects it, so
    the element would validate and then fail to appear on the canvas.

    Args:
        element_file: Absolute path to a .elmt file.
    """
    try:
        return {"ok": True, **cli().check_element_strict(element_file)}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_is_open() -> dict[str, Any]:
    """Check whether a DPTechDraw GUI process is currently running.

    QET holds no file lock and does not watch .qet files, so if it is open,
    its next save will silently overwrite anything written underneath it.
    Always check this before writing.
    """
    try:
        running = cli().is_qet_running()
        return {
            "ok": True,
            "qet_running": running,
            "safe_to_write": not running,
        }
    except Exception as exc:  # noqa: BLE001 - tasklist is best-effort
        return _fail(exc)


@mcp.tool()
def qet_set_titleblock(project: str, output: str, fields: dict[str, str],
                       force: bool = False) -> dict[str, Any]:
    """Stamp title-block fields onto every folio and save to a new file.

    This is the supported way to write a revision or date onto a drawing.

    Known keys: title, author, date, plant, location, revision, version,
    filename. Any other key becomes a custom field and MUST be lowercase
    matching ^[a-z0-9_-]+$ -- QET discards non-conforming keys silently while
    still reporting success, so they are rejected here instead.

    'date' accepts the literal value 'today'.

    Args:
        project: Absolute path to the source .qet file.
        output: Absolute path for the stamped output .qet file.
        fields: Mapping of title-block key to value.
        force: Write even if DPTechDraw is running. Risks being clobbered.
    """
    try:
        return {"ok": True, **cli().set_titleblock(project, output, fields, force=force)}
    except QetProjectOpenError as exc:
        return {**_fail(exc), "hint": "Close DPTechDraw, or call again with force=true."}
    except (QetNotFoundError, QetError, FileNotFoundError, ValueError, TypeError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_resave(project: str, output: str, force: bool = False) -> dict[str, Any]:
    """Load and rewrite a project's XML. Use for format migration only.

    WARNING: this is not idempotent. Roughly 150 lines change on every no-op
    save because terminal integer ids are renumbered and conductors that use
    legacy integer addressing follow them. Do not use it as a normaliser, and
    never diff .qet files textually to detect real change.

    Args:
        project: Absolute path to the source .qet file.
        output: Absolute path for the rewritten .qet file.
        force: Write even if DPTechDraw is running.
    """
    try:
        return {"ok": True, **cli().resave(project, output, force=force)}
    except QetProjectOpenError as exc:
        return {**_fail(exc), "hint": "Close DPTechDraw, or call again with force=true."}
    except (QetNotFoundError, QetError, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_render(project: str, output: str, fmt: str = "pdf") -> dict[str, Any]:
    """Render a project to PDF, PNG or SVG.

    pdf produces one multi-page document at the output path. png and svg
    produce one file per folio inside the output directory.

    Args:
        project: Absolute path to a .qet file.
        output: Output file path for pdf, or output directory for png/svg.
        fmt: One of "pdf", "png", "svg".
    """
    try:
        return {"ok": True, **cli().export_render(project, output, fmt)}
    except (QetNotFoundError, QetError, FileNotFoundError, ValueError) as exc:
        return _fail(exc)


# ----------------------------------------------------------------- drawing
#
# Simple wiring drawings: parts + wires in, a .qet file out. Rules agreed
# with Derek: every change updates the date only; "release" bumps the
# revision 1.2 -> 1.3 and updates the date. A backup is made before any
# existing drawing is changed.


def _prepare_existing(path, force: bool) -> dict[str, Any]:
    """Refuse if QET is open (unless forced), then back the file up."""
    cli()._guard_write(force)
    saved = drawing.backup(path)
    return {"backup": str(saved) if saved else None}


@mcp.tool()
def qet_list_parts() -> dict[str, Any]:
    """List the parts available for drawings, with their pin names.

    These come from DPTechDraw's company and custom part folders (Derek's
    "My Parts"). Use the 'part' value in qet_create_drawing, and the pin
    names in wire ends like "J1:3".
    """
    try:
        parts = drawing.list_parts()
        return {"ok": True, "count": len(parts), "parts": parts}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def qet_create_drawing(title: str, parts: list[dict[str, Any]],
                       wires: list[dict[str, Any]], output: str,
                       revision: str = "1.0", overwrite: bool = False,
                       force: bool = False) -> dict[str, Any]:
    """Create a one-page wiring drawing and check that DPTechDraw loads it.

    Args:
        title: Drawing title for the title block.
        parts: [{"id": "J1", "part": "dsub9_male"}, {"id": "X1", "part": "terminal_block"}]
            "id" is the label shown on the drawing. Optional "x", "y" (page px,
            page is about 1020 x 640) and "rotation" (0/90/180/270) override
            the automatic layout. Leave them out normally: terminal blocks are
            laid out as a strip facing the connectors automatically.
        wires: [{"from": "J1:2", "to": "X1:1", "name": "W1", "colour": "red"}]
            Ends are "<part id>:<pin>"; the pin can be left off for one-pin
            parts like ground. Colours: black, red, blue, white, green,
            yellow, orange, brown, violet, grey, pink, green-yellow, or #rrggbb.
        output: File name (saved in the drawings folder) or a full path.
        revision: Starting revision, normally "1.0".
        overwrite: Replace an existing file (a backup is made first). If
            DPTechDraw is open, the file is NOT replaced: the change is
            saved as a numbered copy (name_2.qet, name_3.qet...) instead, and
            the result says so in "note".
        force: Write even if DPTechDraw is running.

    Title-block author/location and wire defaults come from DPTechDraw's
    own "new project" settings.
    """
    try:
        out = drawing.resolve_output(output)
        result: dict[str, Any] = {}
        if out.exists():
            if not overwrite:
                return {"ok": False, "error": "FileExists",
                        "message": f"{out} already exists. Pick another name or set overwrite=true."}
            if not force and cli().is_qet_running():
                # Never write under an open DPTechDraw: save a numbered copy.
                copy = drawing.next_free_copy(out)
                result["saved_as_copy"] = True
                result["note"] = (f"DPTechDraw is open, so {out.name} was left untouched and "
                                  f"the change was saved as {copy.name}. Close the old one "
                                  "in DPTechDraw when you're happy with the new one.")
                out = copy
            else:
                result.update(_prepare_existing(out, force))
        tree, summary = drawing.build_drawing(title, parts, wires,
                                              revision=revision, filename=out.name)
        drawing.write_tree(tree, out)
        check = drawing.verify(cli(), out, len(parts), len(wires))
        return {"ok": check["loaded_ok"], "file": str(out), **summary, "check": check, **result}
    except QetProjectOpenError as exc:
        return {**_fail(exc), "hint": "Close DPTechDraw, or call again with force=true."}
    except (drawing.DrawingError, QetNotFoundError, QetError, OSError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_stamp_date(project: str, force: bool = False) -> dict[str, Any]:
    """Set today's date on every page of a drawing. Use after any change.

    The revision is not touched. A backup is made first.

    Args:
        project: Full path to the .qet file.
        force: Write even if DPTechDraw is running.
    """
    try:
        path = drawing.resolve_output(project)
        if not path.is_file():
            raise FileNotFoundError(f"Drawing not found: {path}")
        extra = _prepare_existing(path, force)
        return {"ok": True, "file": str(path), **drawing.stamp(path), **extra}
    except QetProjectOpenError as exc:
        return {**_fail(exc), "hint": "Close DPTechDraw, or call again with force=true."}
    except (drawing.DrawingError, QetNotFoundError, QetError, OSError) as exc:
        return _fail(exc)


@mcp.tool()
def qet_release(project: str, force: bool = False) -> dict[str, Any]:
    """Release a drawing: bump the revision (1.2 -> 1.3) and set today's date.

    Only call this when the user asks to release. A backup is made first.

    Args:
        project: Full path to the .qet file.
        force: Write even if DPTechDraw is running.
    """
    try:
        path = drawing.resolve_output(project)
        if not path.is_file():
            raise FileNotFoundError(f"Drawing not found: {path}")
        before = drawing.read_title_block(path)["revision"]
        new_rev = drawing.next_revision(before)
        extra = _prepare_existing(path, force)
        stamped = drawing.stamp(path, revision=new_rev)
        return {"ok": True, "file": str(path), "previous_revision": before, **stamped, **extra}
    except QetProjectOpenError as exc:
        return {**_fail(exc), "hint": "Close DPTechDraw, or call again with force=true."}
    except (drawing.DrawingError, QetNotFoundError, QetError, OSError) as exc:
        return _fail(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
