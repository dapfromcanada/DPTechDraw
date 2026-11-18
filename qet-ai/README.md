# qet-mcp

MCP server wrapping the QElectroTech headless CLI.

## What this is and isn't

It wraps what QET's own CLI already does correctly. It does **not** re-implement
`.qet` XML parsing or BOM scraping — QET builds an internal SQLite database for
that, and duplicating it would drift out of sync.

Scaffolding (generating `.qet` and `.elmt` files) is a separate layer and is
not in this module yet.

## Requirements

The CLI export flags are **not in any stable QET release**. They exist only on
the source-mirror head (PRs #489, #490, #493, under *Unreleased* in
`ChangeLog.MD`). You need the local build at
`<repo>\build\DPTechDraw.exe (found automatically)`.

Run `qet_probe` first — it reports `cli_supported: false` on a stable install.

## Setup

```powershell
cd F:\QelectricoTech\qet-source\qet-ai
uv sync
uv run pytest          # 14 integration tests against the real binary
uv run python -m qet_mcp.server
```

Python 3.12 is pinned in `.python-version`. The system Python 3.14 is too new
for some dependencies; uv installs and manages 3.12 for this project only.

## Configuration

All optional — the defaults match the local build.

| Variable | Default | Purpose |
|---|---|---|
| `QET_EXE` | `<repo>\build\DPTechDraw.exe (found automatically)` | Binary path |
| `QET_QT_BIN` | `C:\Qt\6.10.1\mingw_64\bin` | Added to PATH so Qt DLLs resolve |
| `QET_OFFSCREEN` | `1` | Sets `QT_QPA_PLATFORM=offscreen` |
| `QET_TIMEOUT` | `120` | Subprocess timeout in seconds |

## Registering with a client

```json
{
  "mcpServers": {
    "dptechdraw": {
      "command": "uv",
      "args": ["--directory", "F:\\QelectricoTech\\qet-source\\qet-ai",
               "run", "python", "-m", "qet_mcp.server"]
    }
  }
}
```

## Tools

| Tool | Purpose |
|---|---|
| `qet_probe` | Verify the binary has the unreleased CLI features. Call first. |
| `qet_info` | Structural summary — per-folio element/conductor counts |
| `qet_bom` | Bill of materials, 9 columns, one row per element |
| `qet_nets` | Electrical nets (connected terminal groups) |
| `qet_links` | Cross-references (coil/contact master-slave) |
| `qet_wires` | Distinct wire numbers |
| `qet_cables` | Wiring list, one row per conductor |
| `qet_check_element` | Validate a `.elmt`, strictly (see below) |
| `qet_is_open` | Is a QET GUI running? Check before writing. |
| `qet_set_titleblock` | Stamp title-block fields — the revision-stamping path |
| `qet_resave` | Rewrite project XML. Format migration only. |
| `qet_render` | Export PDF / PNG / SVG |

## Drawing tools (qet_mcp/drawing.py)

| Tool | Purpose |
|---|---|
| `qet_list_parts` | Parts in the company/custom folders ("My Parts") and their pin names |
| `qet_create_drawing` | Parts + wires in, one-page `.qet` out, then loaded by QET to confirm nothing was dropped |
| `qet_stamp_date` | Set today's date on every page (every change does this) |
| `qet_release` | Bump revision 1.2 -> 1.3 and set today's date |

- Title-block author/location and wire defaults are read from QET's own
  "new project" settings (`HKCU\Software\QElectroTech\QElectroTech\diagrameditor`).
- Bare file names save to `QET_DRAWINGS_DIR` (default `F:\QelectricoTech\drawings`).
- Any change to an existing drawing first copies it to `<folder>\_backups\`.
- Date/revision edits touch only the `<diagram>` tag; the rest of the file is
  byte-identical.
- Terminal blocks are laid out as a sideways strip facing the connectors and
  each wire gets its own lane. If QET disagrees with a lane it auto-routes
  that wire instead.
- Pins in My Parts were named by `tools/name_pins.py` (DB9 pins matched to the
  printed numbers). Parts added later with unnamed pins are numbered top to
  bottom, then left to right.
- Headless PNG/PDF renders show text as boxes (no fonts in offscreen mode).
  The file itself is fine; check text in the GUI.

## Upstream bugs this wrapper guards against

Each guard cites the source location that motivates it. See
`docs-ai\` for the full analysis.

1. **`--set-titleblock` reports success on keys it discards.** Custom keys must
   match `^[a-z0-9_-]+$`; `DiagramContext::addValue` drops others and returns
   false, which the CLI ignores. We reject bad keys before invoking.
2. **`--check-elements` passes files that won't load.** It validates
   `width`/`height` with `toDouble()`, but the runtime loaders require integer
   literals. `qet_check_element` adds that check.
3. **`--export-wires` exits 1 on an empty list.** Normalised to `[]`.
4. **`--export-cables` and `--export-wires` emit unquoted CSV**, so a `;` in a
   label corrupts the row. `qet_cables` flags this in its return value.
5. **`--export-cables` headers are French** — no translator is loaded in CLI
   mode. Also flagged in the return value.
6. **`--resave` is not idempotent.** ~150 lines change on every no-op save;
   terminal integer ids are renumbered and conductors follow. There is a test
   that asserts this, so a future upstream fix will be noticed.
7. **QET holds no file lock.** If the GUI is open, its next save silently
   clobbers external writes. All write operations check first and refuse
   unless `force=True`.
8. **Modal dialogs on the CLI load path.** `QETProject::readProjectXml` can open
   a `QMessageBox` on version mismatch. A timeout raises with that as the hint.

## Things to know before extending this

- `element_nomenclature_view` has no uuid column, so BOM rows cannot be mapped
  back to individual elements on the drawing.
- Element UUIDs are stable across saves. Terminal integer ids are **not** —
  never persist one in an external database.
- Element caches key on UUID with no invalidation anywhere in QET. Mint a fresh
  UUID on any `.elmt` content change or you get stale icons forever.
- On-disk element type-ids are `embed://import/dir/foo.elmt`. The `import`
  segment is mandatory. `project0+embed://` is runtime-only — never write it.
