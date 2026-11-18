# QElectroTech — AI Agent Documentation Index

Purpose: give an AI agent enough verified detail about QElectroTech (QET) to
build an MCP server against it without guessing.

All claims in these documents cite `file.cpp:LINE` against the source tree at
`F:\QelectricoTech\qet-source`. Statements not verified in source are marked
`[inference]` or `UNVERIFIED:`. Trust the citations, not the prose.

- Source commit: `56464629bff97c6a297cba19622a2bf6955683fa` (2026-08-22)
- Declared version: `0.100.1` (`CMakeLists.txt:22`)
- Repo: https://github.com/qelectrotech/qelectrotech-source-mirror

## Read order

| # | Document | Read it when you need |
|---|---|---|
| 01 | `01-core-project-model.md` | The `.qet` XML tree, embedded element collection, `embed://` resolution, info keys |
| 02 | `02-database-and-numbering.md` | QET's internal SQLite schema, nomenclature views, auto-numbering and formulas |
| 03 | `03-cli-and-io.md` | **Start here for MCP work.** Every CLI flag, exact output schemas, headless constraints |
| 04 | `04-element-format-and-editor.md` | Writing valid `.elmt` files from scratch |
| 05 | `05-graphics-items.md` | Conductors, terminals, cross-references, what breaks wiring on a part swap |
| 06 | `06-titleblocks-and-terminalstrips.md` | Title block templates, `--set-titleblock`, revision stamping, terminal strips |
| 07 | `07-ui-layer.md` | Boundary marking — what requires a GUI and must never be called headlessly |
| 08 | `08-infrastructure-and-build.md` | File inventory, undo system, XML helpers, element cache traps, build options |

## Build recipe (verified working on this machine)

Environment used: Qt 6.10.1 (mingw_64), MinGW 13.1, Ninja, CMake 4.2.1.

SQLite3 dev files are not shipped with Qt on Windows. They were built from the
amalgamation into `F:\QelectricoTech\deps\sqlite-amalgamation-3530400\`:

```
gcc -O2 -c sqlite3.c -o sqlite3.o -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_JSON1
ar rcs libsqlite3.a sqlite3.o
```

Configure and build:

```
$env:Path = "C:\Qt\Tools\mingw1310_64\bin;C:\Qt\Tools\Ninja;C:\Qt\6.10.1\mingw_64\bin;" + $env:Path

cmake -S . -B build -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DQT_VERSION_MAJOR=6 `
  -DCMAKE_PREFIX_PATH="C:/Qt/6.10.1/mingw_64" `
  -DPACKAGE_TESTS=OFF `
  -DBUILD_WITH_KF=OFF `
  -DQT_NO_PRIVATE_MODULE_WARNING=ON `
  -DSQLite3_INCLUDE_DIR="F:/QelectricoTech/deps/sqlite-amalgamation-3530400" `
  -DSQLite3_LIBRARY="F:/QelectricoTech/deps/sqlite-amalgamation-3530400/libsqlite3.a"

cmake --build build
```

Result: `build\qelectrotech.exe`, 18.8 MB, 378/378 targets, zero errors.

Notes:

- `BUILD_WITH_KF=OFF` skips the KDE Frameworks fetch (which fails on Windows
  because Extra CMake Modules is not found) and uses the bundled fallbacks in
  `sources/ui/nokde/`. Verified working.
- To run the binary, `C:\Qt\6.10.1\mingw_64\bin` must be on PATH for the Qt DLLs.
- On a headless host, set `QT_QPA_PLATFORM=offscreen` — the CLI path constructs
  a full `QApplication` (`main.cpp:125`).

## CLI verification results

Tested against `examples\741.qet` (65 elements, 67 conductors, 1 folio):

| Flag | Result |
|---|---|
| `--info` | exit 0, valid JSON |
| `--export-bom` | exit 0, 65 components |
| `--export-nets` | exit 0, 24 nets |
| `--export-links` | exit 0, 0 linkable elements |
| `--export-cables` | exit 0 |
| `--export-wires` | **exit 1**, "Nothing to export (empty list)" — this project has no numbered wires |
| `--resave` | exit 0 |
| `--export-pdf` | exit 0, 1 page |

**These CLI flags are NOT in the 0.100.1 stable release.** They exist only on
this mirror's head (PRs #489, #490, #493, listed under *Unreleased* in
`ChangeLog.MD`). A locally built binary is required. There is no `--version`
flag; probe with `--info /nonexistent.qet`, which exits 2 with
`Project not found:`.

## VERIFIED FINDING: `--resave` is not idempotent

This was tested directly, not inferred. Four successive `--resave` passes on
`examples\741.qet`:

| Pass | Lines | Changed lines |
|---|---|---|
| original → 1 | 1577 → 1566 | 526 removed / 515 added (includes `version="0.90"` → `"0.200.1"` format migration) |
| 1 → 2 | 1566 → 1559 | 146 / 139 |
| 2 → 3 | 1559 → 1559 | 143 / 143 |
| 3 → 4 | 1559 → 1559 | 153 / 153 |

Line count stabilises after pass 2, but **content never stabilises**. Analysis
of the pass 3 → 4 diff:

- Changed lines are exclusively `<terminal>` (172) and `<conductor>` (134).
- `<element>` lines are **byte-identical** across passes — element UUIDs are stable.
- `<conductor>` lines are **not** identical.

Cause: the integer `id` attribute on `<terminal>` is renumbered on every save,
and conductor endpoints that use the legacy `terminal1`/`terminal2` integer
addressing follow that renumbering. See `05-graphics-items.md` on the two
conductor addressing regimes.

### Consequences for an MCP server

1. **Do not diff `.qet` files to detect meaningful change.** A no-op save
   produces ~150 changed lines. Compare parsed content, not text.
2. **Never persist a terminal integer `id` in your own database.** It is
   invalid after the next save. Element UUIDs are safe; terminal integer ids
   are not.
3. **Do not use `--resave` as a normaliser.** It does not converge.
4. Revision control on `.qet` files will be noisy regardless of what you do.

UNVERIFIED: whether this churn also occurs on projects authored in the current
format (the test file was `version="0.90"`, so pass 1 conflated migration with
churn — but passes 3 and 4 were both already current-format and still churned,
so the instability is real and independent of migration). Worth re-testing on a
project created fresh in this build.

## Standing constraints (collected from all 8 documents)

- Element resolution fails **silently** at five separate gates — a bad scaffold
  produces an empty drawing with only a `qDebug`, not an error.
- On-disk element type-ids are `embed://import/dir/foo.elmt`. The `import`
  segment is mandatory. `project0+embed://…` is a runtime-only form and must
  never be written to a file.
- Info keys must match `^[a-z0-9-_]+$` or `DiagramContext::addValue` silently
  drops them (`sources/diagramcontext.cpp:227-246`). `Client=ACME` is discarded;
  `client=ACME` works — and `--set-titleblock` still reports success.
- `width`/`height`/`hotspot_x`/`hotspot_y` on `<definition>` must be integer
  literals. `width="90.0"` fails to load, and `--check-elements` does not catch it.
- Element caches key on UUID with **no invalidation anywhere in the tree**.
  Editing an `.elmt` in place while keeping its UUID leaves stale name, icon and
  rendering permanently. Mint a fresh UUID on every content change.
- The project database is in-memory only and unreachable from another process.
  Call `updateDB()` before querying. Writes to it never reach the `.qet` file.
- Terminal UUIDs in `.elmt` files are per-author v4 randoms, so two
  independently authored catalogue parts never share them. A naive `type=` swap
  loses every wire even when the symbols are pixel-identical.
- `QETProject::readProjectXml()` can open a modal `QMessageBox` on version
  mismatch — on the same load path the CLI uses (`qetproject.cpp:1470`, `:1497`).
- Test coverage is near zero. `--check-elements`, `--resave` and `--info` are
  the practical validation oracle.

## Open items

- Re-test `--resave` idempotence on a project authored in this build.
- Confirm `--export-wires` succeeds on a project that has numbered wires.
- `<terminal_strips>` XML shape is documented from serialisers only; no sample
  file in the tree contains the node.
- CLI CSV escaping is inconsistent: only `--export-bom` and `--export-links`
  quote properly. `--export-cables` and `--export-wires` stream raw values, so a
  `;` in a label corrupts the file. `--export-cables` headers are French because
  no translator is installed in CLI mode.
