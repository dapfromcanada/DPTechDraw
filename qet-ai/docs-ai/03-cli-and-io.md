# 03 — QElectroTech CLI, Export & I/O Subsystems

Scope: `sources/cli_export.{h,cpp}`, `sources/main.cpp`, the file-load/save path the CLI
touches, and the adjacent import/export subsystems (`sources/import/`, `sources/dxf/`,
`sources/print/`, `sources/svg/`, `sources/createdxf.cpp`, `sources/dxfpaintdevice.cpp`).

Source root for every citation: `/root/qet/qelectrotech-source-mirror/`.

---

## 0. RELEASE STATUS — READ FIRST

**The entire CLI described here is unreleased.** It exists only on this mirror's
development head, in the changelog's `## [Unreleased]` section:

- `ChangeLog.MD:35` — PR **#483** "Add headless command-line export (PDF / PNG / SVG /
  cable-list / wire-list)"
- `ChangeLog.MD:33` — PR **#485** "CLI export: don't draw the editor grid in PDF/PNG/SVG output"
- `ChangeLog.MD:29` — PR **#489** "CLI: add verification & data-export tools (info, BOM, nets,
  links, check-elements, resave)"
- `ChangeLog.MD:28` — PR **#490** "CLI: clickable cross-reference hyperlinks in PDF export"
- `ChangeLog.MD:26` — PR **#493** "CLI: add --set-titleblock, and fix headless backup crash"

The declared project version is `0.100.1` (`CMakeLists.txt:22`). **A stock 0.100.1 build has
none of these flags.** An MCP server MUST verify the binary it drives is built from this
source head. There is no `--version`-style feature probe for the CLI; see §3.4 for the
recommended capability check.

There are **no automated tests** covering `cli_export.cpp` — `tests/` contains only
`borderproperties_test.cpp`, `kautosavefile_test.cpp`, `qet_test.cpp` and framework
scaffolding (`tests/catch/src/`). Everything below is read from source, not from test
fixtures.

---

## 1. DISPATCH PATH — how a CLI run is detected

### 1.1 The detection block

`sources/main.cpp:117-132`:

```
	{
		QStringList raw_args;
		for (int i = 0; i < argc; ++i)
			raw_args << QString::fromLocal8Bit(argv[i]);
		if (CLIExport::isExportRequest(raw_args)) {
			QApplication export_app(argc, argv);
			QETProject::setBackupEnabled(false);
			return CLIExport::run(export_app.arguments());
		}
	}
```

Ordering facts an MCP server depends on:

1. Detection runs on the **raw `argv`**, before any Qt object is constructed
   (`main.cpp:121-124`). `argv[0]` (the binary path) is included in the scanned list.
2. `CLIExport::isExportRequest()` (`cli_export.cpp:761-767`) returns true if **any**
   argument is an exact string match for a key of `exportFlags()`. Not a prefix match, not
   `--flag=value` — exact token equality.
3. If true, a plain **`QApplication`** is constructed (`main.cpp:125`) — *not*
   `SingleApplication`, *not* `QETApp`.
4. `QETProject::setBackupEnabled(false)` (`main.cpp:129`) — see §5.1.
5. `CLIExport::run()` is called with `export_app.arguments()`, i.e. the argument list
   **after** Qt has consumed its own platform switches, and the process returns that exit
   code directly. **`app.exec()` is never called — there is no event loop in CLI mode.**

Because detection precedes `SingleApplication` (`main.cpp:154`), a CLI invocation is never
forwarded to an already-running GUI instance. The comment at `main.cpp:118-119` states this
explicitly.

### 1.2 What is NOT initialised in CLI mode

`QETApp` is never constructed, so everything its constructor does is skipped:

| Skipped | Where it would happen | Consequence for CLI output |
|---|---|---|
| Translator install | `qetapp.cpp:230`, `qetapp.cpp:249` | `tr()` returns **source strings**, which are **French** in this codebase. Directly affects the `--export-cables` CSV header (§2.6). |
| `initFonts()` — bundled Liberation Sans / Liberation Serif / osifont TTFs from `:/fonts/` | called at `qetapp.cpp:122`, implemented `qetapp.cpp:2243-2280` | The application fonts are **not** registered. `QETApp::diagramTextsFont()` (`qetapp.cpp:1358-1367`) still asks for family `"Liberation Sans"` by default; on a host without it, Qt substitutes, changing text metrics and layout in PDF/PNG/SVG output. **Install Liberation fonts in any container that renders QET CLI exports.** |
| Logger + crash handler (`QetLogger::init()`, `installCrashHandler()`) | `main.cpp:145-152` | CLI runs do **not** write a session log file; `qInfo`/`qWarning` go to stderr, interleaved with the CLI's own stderr messages. |
| `EventLoopWatchdog`, `MachineInfo`, startup `QtConcurrent` worker | `main.cpp:195-209` | Not relevant. |
| GUI style / palette (`initStyle`, `qetapp.cpp:2287`) | — | Not relevant; rendering uses explicit item pens/brushes. |

Static `QETApp::` helpers *are* safe without an instance — they are lazily-initialising
statics (`qetapp.cpp:446-458`) or pure `QSettings` readers (`qetapp.cpp:1358`), and the
project load path only touches those (`qetproject.cpp:412`, `qetproject.cpp:567-573`).

### 1.3 Headless / no-display implications

`QApplication` (the **widgets** class, `main.cpp:125`) is a full GUI application object. On
X11/Wayland it **requires a working display connection at construction time** or it aborts
with `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`.

Mitigations, in order of preference for an MCP server:

1. `QT_QPA_PLATFORM=offscreen` — supported by Qt's bundled offscreen plugin, gives a real
   raster paint surface. This is the correct choice: PNG/PDF/SVG rendering all go through
   `QPainter` on `QImage`/`QPdfWriter`/`QSvgGenerator`, none of which need a window.
2. `QT_QPA_PLATFORM=minimal` — also viable for the non-rendering flags.
3. `xvfb-run` — works but is heavier.

For the pure-data flags (`--export-bom`, `--export-nets`, `--export-links`, `--info`,
`--check-elements`, `--resave`, `--set-titleblock`, `--export-cables`, `--export-wires`) the
QApplication object is still constructed, so the platform plugin requirement still applies
even though nothing is painted.

**[inference]** `offscreen` is sufficient for every flag; nothing in `cli_export.cpp`
touches `QScreen`, window handles, or the clipboard.
**UNVERIFIED:** whether `minimal` renders text identically to `offscreen`. Test: run
`--export-png` under both and compare pixel hashes.

### 1.4 Argument-stripping subtlety

`main.cpp:125` passes `argc, argv` to `QApplication`, which removes Qt-recognised switches
(`-platform`, `-style`, `-display`, …) from `argv`. `run()` then receives
`export_app.arguments()` (`main.cpp:130`) — the **post-strip** list. So this works:

```
qelectrotech -platform offscreen --export-pdf in.qet out.pdf
```

but detection at `main.cpp:124` used the raw list, so the flag is found either way.

---

## 2. COMPLETE CLI REFERENCE

### 2.0 Flag table (verbatim from `cli_export.cpp:66-79`)

```
{"--export-pdf",     "pdf"},
{"--export-png",     "png"},
{"--export-svg",     "svg"},
{"--export-cables",  "cables"},
{"--export-wires",   "wires"},
{"--export-bom",     "bom"},
{"--export-nets",    "nets"},
{"--export-links",   "links"},
{"--info",           "info"},
{"--check-elements", "check"},
{"--resave",         "resave"},
{"--set-titleblock", "settb"},
```

Twelve flags. There is **no** `--help`, `--version`, or `--list-flags` in the CLI namespace;
`--help`/`--version`/`--license` are GUI-path options handled by `QETArguments`
(`qetarguments.cpp:259-268`) and will start the full GUI application.

### 2.1 Argument-order rules (`cli_export.cpp:769-835`)

`run()` scans the argument list left-to-right for the **first** token that is a known flag
(`cli_export.cpp:773-780`). Everything **after** it becomes `rest`. Everything before it —
including `argv[0]` — is discarded.

Consequences:

- **The flag must come before the file paths.** `qelectrotech project.qet --export-pdf out.pdf`
  makes `rest = ["out.pdf"]`, so `input = "out.pdf"` → `Project not found: out.pdf`, exit 2.
- **Only the first flag is honoured.** A second flag becomes a positional argument. E.g.
  `--info a.qet --export-bom b.csv` → `rest = ["a.qet", "--export-bom", "b.csv"]`, so `--info`
  writes JSON to the file literally named `--export-bom`. **Never batch two flags in one
  invocation.**
- Extra trailing arguments are ignored for every flag except `--set-titleblock`, which
  consumes `rest.mid(2)` as its `key=value` list (`cli_export.cpp:833`).

Canonical form: `qelectrotech <FLAG> <INPUT> [OUTPUT] [extra...]`

### 2.2 Universal preamble (applies to all flags except `--check-elements`)

`cli_export.cpp:793-808`:

1. `input = rest.value(0)`. If empty →
   `Usage: qelectrotech <flag> <project.qet> <output>` on stderr, **exit 2**.
2. `QFileInfo::exists(input)` false → `Project not found: <input>` on stderr, **exit 2**.
3. `QETProject project(input)` — loads and fully parses the `.qet` (`qetproject.cpp:99-112`).
   If `project.state() != QETProject::Ok` →
   `Failed to open project: <input> (state <N>)` on stderr, **exit 1**.

`ProjectState` numeric values (`qetproject.h:83-90`), which appear verbatim in that message:

```
Ok                    = 0
FileOpenFailed        = 1
XmlParsingFailed      = 2
ProjectParsingRunning = 3
ProjectParsingFailed  = 4
FileOpenDiscard       = 5
```

4. `--info` is dispatched here (`cli_export.cpp:811-812`) — **before** the output-argument
   check, which is why its output path is optional.
5. `output = rest.value(1)`; if empty → usage message, **exit 2** (`cli_export.cpp:814-819`).

---

### 2.3 `--export-pdf <project.qet> <output.pdf>`

Implementation: `exportPdf()`, `cli_export.cpp:127-214`.

- Empty project (`project.diagrams().isEmpty()`) → `No diagrams to export.` stderr, **exit 1**
  (`cli_export.cpp:130-133`).
- **One multi-page PDF; exactly one diagram per page, no tiling** (`cli_export.cpp:136-139`).
- `QPdfWriter` with `setCreator("QElectroTech")` and `setResolution(96)` (`cli_export.cpp:141-143`).
- Each page is sized to that diagram's border+title-block rect converted px→pt at
  `72.0/96.0` (`cli_export.cpp:150-152`); margins are zero (`cli_export.cpp:154`).
- If `painter.begin()` fails → `Cannot open '<output>' for writing.` stderr, **exit 1**
  (`cli_export.cpp:157-160`).
- Render source rect = `diagramRect()` (`cli_export.cpp:91-96`): the
  `border_and_titleblock.borderAndTitleBlockRect()` adjusted `(0,0,1,1)` to include the 1px
  border, then `toAlignedRect()`.
- **The editor grid and guides are suppressed** for the render and restored afterwards
  (`renderDiagram()`, `cli_export.cpp:112-125`) — this is PR #485.
- Cross-reference hyperlinks are injected per page (`cli_export.cpp:173-204`) via
  `PdfLinks::injectCrossRefLinks()`, then the whole file is post-processed by
  `PdfLinks::convertUriToGoTo()` (`cli_export.cpp:210`) which rewrites `/S /URI` annotations
  into native `/S /GoTo` internal destinations. See §6.1.
- Success line on **stdout**: `Exported <N> page(s) -> <output>` (`cli_export.cpp:212`).
- **Exit 0**.

Note the PDF path `#include <private/qpdf_p.h>` (`cli_export.cpp:35`) for
`QPdfEngine::drawHyperlink()`. The build therefore requires Qt private GUI headers;
`CMakeLists.txt:81-89` hard-fails if `Qt6::GuiPrivate` is absent.

### 2.4 `--export-png <project.qet> <output_dir>` and `--export-svg <project.qet> <output_dir>`

Implementation: `exportImages()`, `cli_export.cpp:216-258`. Reached as the fall-through at
`cli_export.cpp:834`.

- **The second argument is a DIRECTORY, not a file.** `QDir().mkpath(out_dir)` creates it
  (`cli_export.cpp:224`).
- One file per diagram. Filename stem from `diagramStem()` (`cli_export.cpp:99-109`):
  - `title = diagram->title()` (which is `border_and_titleblock.title()`, `diagram.cpp:2135-2138`)
  - `title.replace(QRegularExpression("[^\\w \\-]"), "_")` then `.simplified()`
  - empty → literal `"diagram"`
  - final stem: `QStringLiteral("%1_%2").arg(index, 2, 10, QChar('0')).arg(title)`
  - so: **`<out_dir>/NN_Title.png`** with `NN` zero-padded to 2 digits, 1-based, and
    **index > 99 is not truncated** — it just widens (`100_Title.png`).
- **Filename collisions are silently overwritten** if two folios share a title.
- SVG: `QSvgGenerator` with `setSize(r.size())`, `setViewBox(QRect(0,0,w,h))`,
  `setTitle(diagram->title())` (`cli_export.cpp:233-241`). No write-failure check — a bad
  path yields no error and still exits 0. **[inference]**
- PNG: `QImage(r.size(), QImage::Format_ARGB32)` filled `Qt::white`, antialiasing on
  (`cli_export.cpp:243-248`). Save failure → `Failed to write '<path>'.` stderr, **exit 1**
  (`cli_export.cpp:249-252`).
- Grid/guides suppressed, same as PDF.
- Per-file stdout line: two leading spaces then the path — `  <path>` (`cli_export.cpp:254`).
- Final stdout line: `Exported <N> diagram(s) -> <out_dir>` (`cli_export.cpp:256`).
- Empty project → `No diagrams to export.` stderr, **exit 1** (`cli_export.cpp:220-223`).
- **Exit 0** otherwise.

### 2.5 `--export-bom <project.qet> <output.csv>`

Implementation: `exportBom()`, `cli_export.cpp:302-340`.

Data source: QET's own in-memory SQLite project database — **the same source the GUI
nomenclature export uses**. `project.dataBase()->updateDB()` is forced first
(`cli_export.cpp:305`); `updateDB()` repopulates diagram/diagram_info/element/element_info/
conductor tables (`dataBase/projectdatabase.cpp:86-94`).

Query (`cli_export.cpp:312-314`):

```
SELECT label, designation, manufacturer, manufacturer_reference, quantity, location, function, title, folio
  FROM element_nomenclature_view
 ORDER BY label
```

**CSV schema — exact header line (`cli_export.cpp:307-310` + `:320`):**

```
label;designation;manufacturer;manufacturer_reference;quantity;location;function;title;folio
```

- Delimiter `;`. Header is the raw column list joined by `;`, **not** quoted, **not** localised.
- Every data cell goes through `csvField()` (§2.11).
- Row terminator `"\n"` (`cli_export.cpp:326`). File opened with `QIODevice::Text`
  (`cli_export.cpp:331`), so on Windows this becomes CRLF.
- Column semantics come from `element_nomenclature_view`
  (`dataBase/projectdatabase.cpp:516-586`): `label/designation/manufacturer/
  manufacturer_reference/quantity/location/function` are `element_info` fields; `title` is
  `diagram_info.title`; `folio` is `diagram_info.folio` (the folio *string* from the title
  block, e.g. `"1"`, or a template expression — **not** guaranteed to be an integer).
- **The view filters out elements marked excluded from the BOM**: its WHERE clause ends
  `AND (ei.exclude_from_bom IS NOT 'true')` (`projectdatabase.cpp:586`). BOM counts will not
  match `--info` element counts.
- On query failure → `BOM query failed: <QSqlError text>` stderr, **exit 1**
  (`cli_export.cpp:315-318`).
- Open failure → `Cannot open '<output>' for writing.` stderr, **exit 1**.
- Success stdout: `Exported <rows> component(s) -> <output>` (`cli_export.cpp:338`).
- **Exit 0**.

**One row per element instance**, not per part number — there is no `GROUP BY`. Aggregation
is the caller's job.

### 2.6 `--export-cables <project.qet> <output.csv>`

Implementation: `exportCsv()` with `format == "cables"` (`cli_export.cpp:260-285`), delegating
to `WiringListExport::toCsvString()` (`wiringlistexport.cpp:180-392`).

**Header line is produced by `tr()` calls (`wiringlistexport.cpp:369-377`) with the
disambiguation context `"Wiring list CSV header"`.** Because no translator is installed in
CLI mode (§1.2), the emitted header is the **source (French) text**, verbatim:

```
Page;Composant 1;Borne 1;Composant 2;Borne 2;Tension / Protocole;Couleur du fil;Section du fil;Fonction
```

Data row order (`wiringlistexport.cpp:380-388`), matching `struct ConductorData`
(`wiringlistexport.h:23-36`):

| # | Header | Field | Origin |
|---|---|---|---|
| 1 | `Page` | `folio` | `diagram` element's `folio` attr, else its `title` attr (`wiringlistexport.cpp:24-30`) |
| 2 | `Composant 1` | `element1_label` | `conductor@element1_label`, else `@element1_linked`, else element's `label`/`name` (`:124-127`, `:257-260`) |
| 3 | `Borne 1` | `terminalname1` | `conductor@terminalname1` (`:134`) |
| 4 | `Composant 2` | `element2_label` | as #2 (`:129-132`) |
| 5 | `Borne 2` | `terminalname2` | `conductor@terminalname2` (`:135`) |
| 6 | `Tension / Protocole` | `tension_protocol` | `conductor@tension_protocol` (`:136`) |
| 7 | `Couleur du fil` | `conductor_color` | `conductor@conductor_color` (`:137`) |
| 8 | `Section du fil` | `conductor_section` | `conductor@conductor_section` (`:138`) |
| 9 | `Fonction` | `function` | `conductor@function` (`:139`) |

Behaviour notes:

- Operates on `m_project->toXml()` (`wiringlistexport.cpp:184`) — the serialised project, not
  the live graphics scene.
- Conductors whose `num` attribute is exactly `"Brücke"` are skipped (`:117`).
- Conductors touching a `conductor_definition` element are skipped (`:253-255`).
- Half-wires through placeholder elements are merged into one row; unmatched halves are
  emitted as leftovers (`:279-314`).
- Endpoints are canonically ordered (lower-cased label ascending) (`:316-322`), then rows are
  sorted by folio (numeric-aware, comma-split), then `element1_label`, `element2_label`,
  `terminalname1`, `terminalname2` (`:324-365`).
- **CRITICAL: this path does NOT use `csvField()`.** Values are streamed raw
  (`wiringlistexport.cpp:380-388`). A label or function containing `;`, `"` or a newline
  **will corrupt the CSV**. Contrast with `--export-bom` / `--export-links`, which do quote.
- Empty result (`csv.isEmpty()`) → `Nothing to export (empty list).` stderr, **exit 1**
  (`cli_export.cpp:270-273`). Note the header line is always present when a project loads, so
  emptiness here effectively means `toXml()` returned null.
- Open failure → `Cannot open '<output>' for writing.` stderr, **exit 1**.
- Success stdout: `Exported cables list -> <output>` (`cli_export.cpp:283`).
- **Exit 0**.

### 2.7 `--export-wires <project.qet> <output.csv>`

Implementation: `exportCsv()` with `format == "wires"` (`cli_export.cpp:267-268`), delegating
to `ConductorNumExport::wiresNum()` (`conductornumexport.cpp:93-107`).

**This is not a table. It is a headerless, single-column, deliberately-repeating list.**

- `ConductorNumExport`'s constructor calls `fillHash()` (`conductornumexport.cpp:39`), which
  builds `QHash<QString,int>` of wire number → occurrence count
  (`conductornumexport.cpp:113-143`).
- Counting rule: for each conductor, take `c->textItem()->toPlainText()`; skip if empty or
  matches `^ *$` (`:116`, `:123-125`); then **increment once per endpoint whose parent element
  is not a folio report** (`!(linkType() & Element::AllReport)`, `:129-140`). So a normal
  conductor contributes **2** to its number's count; one end landing on a report contributes 1.
- `wiresNum()` sorts the distinct numbers (`QStringList::sort()`, `:98`) and emits each key
  `count` times, one per line, each terminated `"\n"` (`:99-104`).

**Output shape:**

```
1
1
1
1
2
2
L1
L1
```

No header, no delimiter, no quoting. The header comment in `cli_export.h:61` says "list of
distinct wire numbers" — **that is wrong**: the values repeat. The multiplicity is the
terminal count.

- Empty → `Nothing to export (empty list).` stderr, **exit 1**.
- Success stdout: `Exported wires list -> <output>` (`cli_export.cpp:283`).
- **Exit 0**.

**Note:** unlike the GUI path (`conductornumexport.cpp:76`), the CLI does **not** append a
trailing `endl` — `exportCsv()` writes `csv` as-is (`cli_export.cpp:281`). The last line still
ends in `\n` because `wiresNum()` appends one per entry.

### 2.8 `--export-nets <project.qet> <output.json>`

Implementation: `exportNets()`, `cli_export.cpp:531-600`.

Algorithm: collect every conductor on every folio (`:536-538`); for each unvisited conductor,
call `c->relatedPotentialConductors(true, &t_list)` (`:551`, declared
`qetgraphicsitem/conductor.h:131-133`) which returns the whole potential across all folios and
fills `t_list` with every terminal in it, **following folio reports and terminal blocks**;
mark the group visited; add `terminal1`/`terminal2` of the seed conductor (`:555-556`).
Wire number for the net = the **lexicographically smallest non-empty** conductor text in the
group (`:559-563`, `wire_nos.value(0)` after `sort()`).

**JSON shape — exact keys, `QJsonDocument::Indented` (4-space indent, `\n` line endings,
UTF-8, trailing newline):**

```json
{
    "list": [
        {
            "net": 1,
            "terminals": [
                {
                    "element": "K1",
                    "folio": 1,
                    "terminal": "A1"
                }
            ],
            "wire_no": "L1"
        }
    ],
    "nets": 3,
    "project": "My project"
}
```

Key facts:

- Root keys (`cli_export.cpp:586-589`): `project` (string, `QETProject::title()`,
  `qetproject.cpp:478`), `nets` (int, count), `list` (array).
- **`QJsonObject` serialises keys in sorted order**, so the physical order in the file is
  `list`, `nets`, `project` at the root, and `net`, `terminals`, `wire_no` per net, and
  `element`, `folio`, `terminal` per terminal. Parse by key, never by position.
- Per-net keys (`:580-582`): `net` = 1-based sequential int; `wire_no` = string, **`""` when
  no conductor in the net carries text**; `terminals` = array.
- Per-terminal keys (`:574-576`): `element` = `elementLabel()` (§2.12) or `""` if the terminal
  has no parent element; `terminal` = `Terminal::name()` (`qetgraphicsitem/terminal.cpp:877`);
  `folio` = 1-based page index of the parent element, **`0` if unknown** (`:576`,
  `folioIndex()` at `:514-526`).
- Duplicate terminals are de-duplicated per net via a `QSet<Terminal*>` (`:567-571`).
- **Nets with zero conductors do not exist**: the walk is conductor-seeded, so an isolated
  element terminal never appears. Use `--info`'s `free_terminals` for that.
- Open failure → `Cannot open '<output>' for writing.` stderr, **exit 1** (`:592-595`).
- Success stdout: `Exported <N> net(s) -> <output>` (`:598`).
- **Exit 0**.

### 2.9 `--export-links <project.qet> <output.csv>`

Implementation: `exportLinks()`, `cli_export.cpp:604-652`.

**CSV header, verbatim (`cli_export.cpp:608`) — hardcoded, not localised:**

```
element;link_type;linked_to;folio;status
```

Row construction (`cli_export.cpp:633-637`):

| # | Column | Value | Quoted by `csvField()`? |
|---|---|---|---|
| 1 | `element` | `elementLabel(e)` | **yes** |
| 2 | `link_type` | `e->linkTypeToString()` | no |
| 3 | `linked_to` | `names.join(", ")` where each name is `"<label>(f<folio>)"` | **yes** |
| 4 | `folio` | `QString::number(folio.value(e, 0))` | no |
| 5 | `status` | `linked` or `UNRESOLVED` | no |

- Elements with `linkType() == Element::Simple` are **skipped entirely** (`:615-616`).
- `link_type` values are exactly those returned by `Element::linkTypeToString()`
  (`qetgraphicsitem/element.cpp:1355-1378`):
  `Simple`, `NextReport`, `PreviousReport`, `Master`, `Slave`, `Terminale`, `Thumbnail`,
  `ConductorDefinition`, `Unknown`. (`Simple` cannot appear, per the skip above.)
  Underlying enum values: `Simple=1, NextReport=2, PreviousReport=4, AllReport=6, Master=8,
  Slave=16, Terminale=32, Thumbnail=64, ConductorDefinition=128` (`element.h:56-63`).
- `status` is `UNRESOLVED` **only** when the link type is `Master` or `Slave` **and**
  `linkedElements()` is empty (`:626-631`). A `NextReport`/`PreviousReport` with no target is
  reported as `linked` with an empty `linked_to` — a false negative for validation purposes.
- The `linked_to` cell uses `", "` as its internal separator; since it is `csvField()`-quoted
  only when it contains `;`/`"`/newline, a normal multi-target cell stays unquoted (commas are
  not the delimiter).
- Folio numbers embedded in `(fN)` are 1-based; `0` means the target element was not found in
  the folio map (`:623`).
- Open failure → `Cannot open '<output>' for writing.` stderr, **exit 1**.
- Success stdout: `Exported <linkable> linkable element(s), <unresolved> unresolved -> <output>`
  (`:649-650`).
- **Exit 0 even when unresolved links exist.** The count is informational only. An MCP
  validate capability must parse the CSV (or the stdout line) rather than trust the exit code.

### 2.10 `--info <project.qet> [output.json]`

Implementation: `exportInfo()`, `cli_export.cpp:356-413`. Dispatched early
(`cli_export.cpp:811-812`), so the output argument is **optional**.

- No output argument → the JSON is written to **stdout** and nothing else is printed
  (`:400-401`). This is the only flag whose stdout is machine-parseable on its own.
- With an output argument → JSON to that file, plus stdout line
  `Wrote project info -> <output>` (`:410`).

**JSON shape (keys sorted on output, as in §2.8):**

```json
{
    "conductors": 42,
    "diagrams": 3,
    "elements": 57,
    "free_terminals": 4,
    "pages": [
        {
            "conductors": 14,
            "elements": 19,
            "folio": "1 of 3",
            "free_terminals": 2,
            "height_px": 594,
            "index": 1,
            "title": "Power",
            "width_px": 841
        }
    ],
    "project": "My project"
}
```

Root keys (`cli_export.cpp:389-395`): `project` (string), `diagrams` (int), `elements` (int,
summed), `conductors` (int, summed), `free_terminals` (int, summed), `pages` (array).

Per-page keys (`cli_export.cpp:373-381`):

- `index` — 1-based int
- `title` — `Diagram::title()`
- `folio` — **string**, formatted `"%1 of %2"` → e.g. `"1 of 3"`. This is a synthesised
  string, *not* the title-block folio field (contrast with the BOM `folio` column, §2.5).
- `width_px`, `height_px` — ints from `diagramRect()`, i.e. the border+title-block rect in
  scene pixels, already `+1` adjusted and aligned.
- `elements` — `diagram->elements().size()`. **No BOM-exclusion filter** — will exceed the
  BOM row count when elements are marked excluded.
- `conductors` — `diagram->conductors().size()`
- `free_terminals` — sum over the page's elements of terminals with
  `conductorsCount() == 0` (`freeTerminals()`, `cli_export.cpp:343-351`;
  `terminal.h:74`)

- Open failure (file mode only) → `Cannot open '<output>' for writing.` stderr, **exit 1**.
- **Exit 0.** An empty project (0 diagrams) still exits 0 with `"diagrams": 0` and
  `"pages": []`.

### 2.11 `--check-elements <element.elmt | directory>`

Implementation: `checkElements()` (`cli_export.cpp:480-511`) + `checkOneElement()`
(`cli_export.cpp:417-477`). **Dispatched before any project handling**
(`cli_export.cpp:784-791`) — it never opens a `.qet`.

Input resolution (`:483-500`):

- Directory → recursive `QDirIterator(path, {"*.elmt"}, QDir::Files, QDirIterator::Subdirectories)`,
  results `sort()`ed.
- File → that single path (extension is **not** checked).
- Neither → `Not found: <path>` stderr, **exit 2**.
- Directory with no matches → `No .elmt files found under: <path>` stderr, **exit 2**.
- Missing argument entirely →
  `Usage: qelectrotech --check-elements <element.elmt | directory>` stderr, **exit 2**
  (`:785-789`).

Per-file checks, in order (all lines go to **stdout**, `cli_export.cpp:417-476`):

| Condition | Line format | Internal code |
|---|---|---|
| cannot open | `FAIL  <path>  (cannot open)` | 2 |
| XML parse error | `FAIL  <path>  (XML error line <N>: <message>)` | 2 |
| root not `<definition type="element">` | `FAIL  <path>  (root is not <definition type="element">)` | 2 |
| `width`/`height` missing, non-numeric, or zero | `FAIL  <path>  (missing/zero bounding box <width>x<height>)` | 2 |
| negative `width` or `height` | `WARN  <path>  (negative bounding box <w>x<h>, <N> terminals)` | 1 |
| zero `<terminal>` elements | `WARN  <path>  (loads, but 0 terminals)` | 1 |
| otherwise | `OK    <path>  (<N> terminals)` | 0 |

Note the **two trailing spaces** before the parenthesised detail and the padding that aligns
`OK` to four characters (`OK` + 4 spaces, `WARN`/`FAIL` + 2 spaces).

Summary line, always printed last (`:508-509`):

```
<N> file(s), <W> warning(s), <F> failure(s)
```

Process exit code (`:510`): **`failures > 0 ? 1 : 0`**. **Warnings do not affect the exit
code.** Terminal count is `root.elementsByTagName("terminal").count()` (`:460`) — a
whole-subtree count, not direct children.

The negative-bounding-box case is deliberately a warning, not a failure: the comment at
`:462-463` says QET's own loader accepts it, so the checker agrees with the loader.

### 2.12 `--resave <project.qet> <output.qet>`

Implementation: `resaveProject()`, `cli_export.cpp:656-669`.

- `project.toXml()` (`qetproject.cpp:999`) then `fout << doc.toString(4)` — 4-space indent.
- **Writes to `<output.qet>`; the input file is never modified.**
- Open failure → `Cannot open '<output>' for writing.` stderr, **exit 1**.
- Success stdout: `Re-saved project -> <output>` (`:667`).
- **Exit 0**.

Purpose per `cli_export.h:69`: round-trip integrity — diff input against output to reveal
markup QET silently normalises.

**Encoding caveat.** This path uses a bare `QTextStream` on a `QIODevice::Text` file
(`:660`, `:664-665`). It does **not** replicate `QET::writeToFile()` (`qet.cpp:786-825`),
which explicitly sets UTF-8 and disables the BOM (`qet.cpp:811`/`:816`, `:818`). On Qt 6
`QTextStream` defaults to UTF-8 so the result matches; **on Qt 5 the default is the locale
codec**, so a non-UTF-8 locale would mangle non-ASCII content. **[inference]** —
**UNVERIFIED:** test by resaving a project with accented labels under a Qt5 build with
`LC_ALL=C` and comparing bytes to a `QETApp` "Save As".

`QIODevice::Text` also means **LF is translated to CRLF on Windows**, so a resave there is
never byte-identical to the input.

Neither `toXml()` nor this writer emits an `<?xml …?>` declaration — `.qet` files have no XML
prolog, consistent with the GUI save path.

### 2.13 `--set-titleblock <project.qet> <output.qet> key=value...`

Implementation: `setTitleBlock()`, `cli_export.cpp:676-755`, invoked with `rest.mid(2)`
(`cli_export.cpp:833`).

Parsing (all assignments validated **before** anything is written, `:684-701`):

- No assignments → `No field assignments given (expected key=value).` stderr, **exit 2**.
- Any token whose first `=` is at index ≤ 0 →
  `Bad assignment '<a>' (expected key=value).` stderr, **exit 2**. (So `=x` and a bare `x`
  both fail; `k=` is legal and sets an empty value.)
- Key `date` (case-insensitive) whose value is neither `today` (case-insensitive) nor a valid
  `Qt::ISODate` date → `Bad date '<v>' (expected YYYY-MM-DD or 'today').` stderr, **exit 2**.
- Value is everything after the **first** `=`, so `title=a=b` sets title to `a=b`.

Key mapping — key is lower-cased before comparison (`:705`), so `TITLE=` works
(`:707-724`, targets are `TitleBlockProperties` fields, `titleblockproperties.h:54-66`):

| CLI key | `TitleBlockProperties` member |
|---|---|
| `title` | `title` |
| `author` | `author` |
| `filename` | `filename` |
| `plant` | `plant` |
| `location` | `locmach` |
| `revision` | `indexrev` |
| `version` | `version` |
| `date` | `date` + forces `useDate = TitleBlockProperties::UseDateValue` (`:720`) |
| *anything else* | `p.context.addValue(<original-case key>, value)` — a custom title-block field (`:723`) |

Note the asymmetry: standard keys are matched case-insensitively, but an unknown key is
stored with its **original case** (`f.first`, not `k`). `Foo=1` and `foo=1` create two
different custom fields.

Also note there is **no CLI key for `folio`** (`titleblockproperties.h:62`) or
`template_name`; `folio=X` becomes a custom field, not the folio field.

Application scope (`:727-741`):

1. The **project default** title block (`defaultTitleBlockProperties()` →
   `setDefaultTitleBlockProperties()`), i.e. the template for new folios.
2. **Every existing folio**, via `border_and_titleblock.exportTitleBlock()` → apply →
   `importTitleBlock()`.

Then `project.toXml()` is written to `<output.qet>` with `doc.toString(4)` (`:743-751`) —
same writer, same encoding caveat as `--resave`. **The input project is not modified.**

- Open failure → `Cannot open '<output>' for writing.` stderr, **exit 1**.
- Success stdout: `Stamped <F> field(s) on <N> folio(s) -> <output>` (`:752-753`), where `<F>`
  is the number of assignments and `<N>` the folio count.
- **Exit 0**.

Example (from `cli_export.h:73`):
`qelectrotech --set-titleblock in.qet out.qet revision=B date=today`

### 2.14 `csvField()` — the quoting helper

`cli_export.cpp:288-297`:

```
QString csvField(const QString &value)
{
	if (value.contains(';') || value.contains('"')
		|| value.contains('\n') || value.contains('\r')) {
		QString v = value;
		v.replace('"', "\"\"");
		return '"' % v % '"';
	}
	return value;
}
```

Rules:

- Delimiter is **`;`** (semicolon), not comma. Matches the European/Excel-FR convention QET
  targets.
- A field is wrapped in `"` only if it contains `;`, `"`, `\n` or `\r`.
- Inside a quoted field, `"` is doubled (RFC 4180).
- **Commas are never special** — a field containing `,` is emitted bare.
- **Leading/trailing whitespace is not preserved by quoting** (it is simply not a trigger).

**Applied by:** `--export-bom` (`:325`) and `--export-links` (`:633`, `:635` — columns 1 and 3
only).
**NOT applied by:** `--export-cables` (`wiringlistexport.cpp:380-388`, raw) or
`--export-wires` (`conductornumexport.cpp:102`, raw). Treat those two as
delimiter-unsafe.

Header lines are never passed through `csvField()`.

### 2.15 `elementLabel()` — how elements are named in nets/links

`cli_export.cpp:85-88`:

```
const QString label = element->elementInformations()["label"].toString();
return label.isEmpty() ? element->name() : label;
```

So the `element` column in `--export-links` and the `element` key in `--export-nets` are the
device tag (`K1`, `Q55`) when set, otherwise the element's display name. The BOM's `label`
column comes from a different route (`element_info.label` in SQLite) but the same underlying
field.

---

## 3. EXIT CODES AND STREAM DISCIPLINE

### 3.1 Exit-code table

| Code | Meaning | Emitted at |
|---|---|---|
| **0** | Success | every `exportX()` tail |
| **1** | Runtime failure: project loaded but the operation failed — no diagrams, cannot open output, image save failed, BOM query failed, empty list. **Also: `--check-elements` found ≥1 FAIL.** | `cli_export.cpp:132, 158, 222, 251, 272, 278, 317, 333, 406, 510, 594, 644, 662, 747, 807` |
| **2** | Usage / input error: flag with no arguments, project file not found, `--check-elements` path not found or empty, bad `key=value`, bad date. | `cli_export.cpp:494, 499, 681, 690, 698, 788, 796, 818` |

Distinguishing rule an MCP server can rely on: **2 = you called it wrong; 1 = it tried and
failed; 0 = it worked.** The one exception is `--check-elements`, which overloads 1 to mean
"validation failures found" (`cli_export.cpp:510`) — semantically a result, not an error.

There is no exit code for "succeeded with warnings". `--export-links` exits 0 even with
`UNRESOLVED` rows; `--check-elements` exits 0 with `WARN` rows.

### 3.2 stdout vs stderr

Two file-scope streams (`cli_export.cpp:60-61`):

```
QTextStream out(stdout);
QTextStream err(stderr);
```

- **stderr** carries every error message listed above.
- **stdout** carries the success/summary lines, the per-file `  <path>` lines of
  `--export-png`/`--export-svg`, all `OK`/`WARN`/`FAIL` lines of `--check-elements`, and — for
  `--info` with no output file — the entire JSON document.
- Qt's own diagnostics (e.g. `Project "x.qet" (12 KiB) opened in 0.4 seconds`,
  `qetproject.cpp:263-268`, and `SQLite version: …`, `projectdatabase.cpp:599`) go to
  **stderr** via the default message handler, since `qInstallMessageHandler` is not reached
  in CLI mode (`main.cpp:146` is after the early return).

**Practical rule for `--info` without an output path: capture stdout only and discard stderr,
or the JSON will be clean but the log noise will not pollute it.** All other flags: parse the
output file, not stdout.

**[inference]** These `QTextStream`s are never explicitly flushed, but they are file-scope
statics destroyed at exit, and `return` from `main` runs static destructors, so output is
flushed. No evidence of a truncation bug.

### 3.3 Locale sensitivity

`QTextStream` formats integers with the stream's locale, which defaults to `QLocale::C` for
`QTextStream` — so counts in stdout lines are plain ASCII digits with no group separators.
The **JSON** paths use `QJsonDocument`, which is locale-independent. The **`--set-titleblock`
date** parse uses `Qt::ISODate` explicitly (`:696`, `:717`), so it is locale-independent.
The `--export-bom` `quantity` column is whatever SQLite stored, converted with
`QVariant::toString()` (`:325`) — **[inference]** locale-independent for integers.

### 3.4 Capability probe (recommended)

There is no version flag for the CLI. The cheapest reliable probe:

```
qelectrotech --info /nonexistent.qet ; echo $?
```

- Exit **2** with stderr `Project not found: /nonexistent.qet` → CLI is present.
- Anything else (GUI starts, exit 0/1, X11 error) → CLI is absent; the binary is a stock
  0.100.1 build and `--info` was treated as an unknown option by `QETArguments`
  (`qetarguments.cpp:258-310`).

Do the probe with `QT_QPA_PLATFORM=offscreen` set, or a display-less host will fail the probe
for the wrong reason.

---

## 4. FILE LOADING / SAVING ON THE CLI PATH

### 4.1 Load

`QETProject project(input)` → `openFile(&file)` (`qetproject.cpp:99-112`, `:234-277`):

1. `file->open(QIODevice::ReadOnly | QIODevice::Text)`; failure → `FileOpenFailed` (1).
2. `setFilePath(fi.absoluteFilePath())`.
3. `QDomDocument::setContent(file)`; failure → `XmlParsingFailed` (2).
4. `readProjectXml(xml_project)` — full model construction.
5. If the file is not writable, the project is flagged read-only (`:270-272`). **This does not
   block the CLI**, since `--resave`/`--set-titleblock` write via raw `QFile`, not
   `QETProject::write()`.

`.qet` is **plain, uncompressed XML** — there is no decompression step.

`QDomImplementation::setInvalidDataPolicy(QDomImplementation::ReturnNullNode)` is set at
`main.cpp:102-103`, **before** the CLI branch, so it applies to CLI runs: malformed data is
refused rather than serialised (CVE-2026-15037 mitigation).

`qputenv("QT_HASH_SEED", "0")` at `main.cpp:93` also applies — it makes `QHash` iteration
order deterministic so XML diffs are clean. This directly benefits `--resave` reproducibility.

### 4.2 Save

Nothing on the CLI path calls `QETProject::write()` (`qetproject.cpp:1087`). Both writers
(`--resave` `:659-666`, `--set-titleblock` `:744-751`) do:

```
QFile file(output);
file.open(QIODevice::WriteOnly | QIODevice::Text);
QTextStream fout(&file);
fout << doc.toString(4);
file.close();
```

Differences from the GUI save (`QET::writeToFile`, `qet.cpp:786-825`): no explicit UTF-8
codec, no `setGenerateByteOrderMark(false)`, no error message plumbing. Same 4-space indent.

### 4.3 The input file is never written

Every writing flag takes a distinct `<output>`. There is no in-place mode. **[inference]**
This makes the CLI safe to run against a source-controlled `.qet` without a lock.

---

## 5. KNOWN LIMITATIONS AND CODE-FLAGGED HAZARDS

### 5.1 Crash-recovery backups disabled in CLI mode (PR #493)

`main.cpp:126-129`, verbatim comment:

> `// No crash-recovery backups in one-shot CLI mode: the backup write`
> `// runs on a background thread referencing the project and races the`
> `// process exit (intermittent segfault in QET::writeToFile).`

Mechanism: `QETProject::init()` (`qetproject.cpp:200-227`) starts a 20-minute backup timer
(`BACKUP_INTERVAL = 1200000`, `qetproject.cpp:46`) **and calls `writeBackup()` immediately**
(`qetproject.cpp:211`). `writeBackup()` (`qetproject.cpp:1996-2012`) copies the document and
runs `QET::writeToFile` on a `QtConcurrent` thread. In a one-shot CLI run the process returns
from `main` while that thread is still touching `m_backup_file` → intermittent segfault.

The fix is the static guard: `QETProject::m_backup_enabled` (`qetproject.cpp:48`), checked
first thing in `writeBackup()` (`qetproject.cpp:1998-1999`).

**Implication:** a CLI run leaves **no** `KAutoSaveFile` stale-backup artifacts, and a
subsequent GUI launch will not offer to recover from a CLI run. Good for CI hygiene.

The 20-minute timer and the optional autosave timer (`qetproject.cpp:214-225`) are started but
**never fire**, because `app.exec()` is not called in CLI mode.

### 5.2 The grid-suppression round-trip

`renderDiagram()` (`cli_export.cpp:112-125`) mutates the diagram (`setDisplayGrid(false)`,
`setDisplayGuides(false)`), renders, then restores. This is state mutation on a shared object
during export. Harmless in the one-shot CLI (no concurrency, and the project is discarded),
but it means `--export-png` is **not** a const operation on the model. It is also why the
grid does not appear in output (PR #485).

### 5.3 `--export-cables` / `--export-wires` produce unescaped CSV

See §2.6 and §2.7. A `;` in an element label silently shifts columns. This is a real defect,
not a documentation gap: `csvField()` exists in the same file and is simply not used by those
two paths.

### 5.4 French headers leak into `--export-cables`

`wiringlistexport.cpp:369-377` uses `tr()`; no translator is installed (§1.2). The GUI
produces localised headers for the same data; the CLI always produces the French source
strings. **A downstream consumer must key on the French literals**, or the schema will break
if a translator is ever installed on the CLI path.

### 5.5 `--export-svg` swallows write failures

`cli_export.cpp:233-241` never checks whether `QSvgGenerator` actually wrote anything, unlike
the PNG branch (`:249-252`). An unwritable directory produces exit 0. **[inference]**
**UNVERIFIED:** run `--export-svg` into a read-only directory and check the exit code.

### 5.6 `--export-nets` misses isolated potentials

Nets are seeded from conductors (`cli_export.cpp:543`). An element terminal with no conductor
attached produces no net entry. Cross-check with `--info`'s `free_terminals`.

### 5.7 `--export-links` does not flag orphan folio reports

Only `Master`/`Slave` with empty `linkedElements()` are marked `UNRESOLVED`
(`cli_export.cpp:626-631`). `NextReport`/`PreviousReport` with no partner are reported
`linked` with an empty `linked_to`. A validation capability must additionally treat
`link_type ∈ {NextReport, PreviousReport}` with empty `linked_to` as a finding.

### 5.8 BOM vs. `--info` element counts diverge by design

`element_nomenclature_view` filters `exclude_from_bom` (`projectdatabase.cpp:586`, feature
from PR #472); `--info` counts every element (`cli_export.cpp:365`). Do not use one to
validate the other.

### 5.9 `cli_export.h` documentation is stale in one place

`cli_export.h:61` describes `--export-wires` as "list of distinct wire numbers as CSV". The
implementation repeats each number once per non-report terminal (§2.7). Trust the source.

### 5.10 Deterministic-output caveats

- `QT_HASH_SEED=0` (`main.cpp:93`) stabilises hash iteration, so `--resave` output is
  reproducible.
- `--export-nets` net numbering depends on `project.diagrams()` order (insertion order,
  `qetproject.cpp:318-321`) and within a folio on `Diagram::conductors()` order — stable for
  a given input file, but **net numbers are not a durable identifier across edits**. Key on
  `wire_no` + terminal sets instead.
- `--export-bom` is `ORDER BY label` (`cli_export.cpp:314`) with no tie-break; rows with equal
  labels have unspecified relative order.

---

## 6. IMPORT / EXPORT SUBSYSTEMS

### 6.1 PDF hyperlinks — `sources/pdf_links.{h,cpp}`

Shared by the GUI print path and the CLI (`pdf_links.h:31-37`). The caller supplies a
`PdfLinks::PageGeometry` (`pdf_links.h:45-56`) — `sceneToDevice` transform, `target` rect,
`pageBounds`, a `devToPdf` point mapper, and a `sourceRectOf(Diagram*)` callback — because the
device-pixel↔point conversions differ between `QPrinter` and `QPdfWriter`. The CLI builds its
geometry inline at `cli_export.cpp:174-202`.

`injectCrossRefLinks()` (`pdf_links.cpp:40-168`) walks `diagram->items()` and emits a link for:

- every entry of a `CrossRefItem::hoveredContactsMap()` (`pdf_links.cpp:108-118`)
- a `DynamicElementTextItem` on a report element that shows `label` or a composite containing
  `%{label}`, targeting `linkedElements().first()` (`pdf_links.cpp:121-141`)
- a `Slave` element's `slaveXrefItem()` → its master (`pdf_links.cpp:144-151`)
- an `ElementTextItemGroup` on a `Slave` → master (`pdf_links.cpp:156-166`)

Each is written as a URI annotation `file://<output>#page=<N>&fitr=<L>_<T>_<R>_<B>`
(`pdf_links.cpp:93-102`), with the target framed with 25 units of padding and a 160-unit
minimum side (`pdf_links.cpp:69-77`). `convertUriToGoTo()` (`pdf_links.cpp:170`) then rewrites
those into native `/S /GoTo` actions and rebuilds the xref table, so the links work in any
viewer. There is also `convertComponentInfoAnnotations()` (`pdf_links.h:86-87`) for the GUI's
component-info popups — **not used by the CLI**.

Build requirement: `#include <private/qpdf_p.h>` (`cli_export.cpp:35`) for
`QPdfEngine::drawHyperlink()`; `CMakeLists.txt:81-89` fails configuration without
`Qt6::GuiPrivate`, and `qelectrotech.pro:267` adds the private headers for qmake builds.

### 6.2 `sources/print/` — GUI print/PDF, not reachable from the CLI

`ProjectPrintWindow` (`print/projectprintwindow.h:43`, `.cpp:63` `launchDialog`) is a
`QMainWindow` with a `QPrintPreviewWidget`. It exposes options the CLI has no equivalent for
(`projectprintwindow.h:55-62`): draw border, draw title block, keep conductor colour, draw
terminals, draw terminal names, component info, fit-in-page, use-full-page — plus per-printer
page-setup persistence (`:606`, `:681`) and a per-folio checkbox list (`:568`).

**CLI PDF is fixed-configuration:** always border+title block, always the diagram's own
geometry, one folio per page, no tiling, no page selection. Anything else requires the GUI or
post-processing.

### 6.3 `sources/svg/` — SVG *helpers*, not the SVG exporter

`QETSVG` (`svg/qetsvg.h:33-49`) is a set of DOM attribute read/write helpers
(`rectToElmt`/`rectFromElmt`, `yToAttribute`, `heightToAttribute`, `rToAttribute`,
`pointsToAttribute`/`pointsFromAttribute`) used by the element editor's shape serialisation.
**It has nothing to do with `--export-svg`**, which uses `QSvgGenerator` directly
(`cli_export.cpp:233-241`).

### 6.4 DXF export — `createdxf.cpp`, `dxfpaintdevice.cpp`

Two layers:

- `Createdxf` (`createdxf.h:28-120+`) — a static, file-append DXF writer targeting the
  **AC1006** dialect: `dxfBegin`/`dxfEnd` bracket a file, and `drawCircle`, `drawArc`,
  `drawDonut`, `drawArcEllipse`, `drawEllipse`, `drawRectangle`, `drawPolygon`, `drawLine`,
  `drawText`, `drawPolyline` append entities. Scaling is via the static
  `Createdxf::xScale`/`yScale` set from sheet size (`exportdialog.cpp:451-452`).
- `DxfPaintEngine` / `DxfPaintDevice` (`dxfpaintdevice.h:65-115`) — a `QPaintEngine` that
  translates the QPainter calls QET's own `paint()` implementations make into DXF entities, so
  existing item-painting code can be reused. Mapping, per the header comment
  (`dxfpaintdevice.h:44-57`): `drawLines→LINE`, `drawRects→LWPOLYLINE` (outline only — no
  filled-rect primitive in AC1006), `drawEllipse→drawArcEllipse`/`CIRCLE`,
  `drawPath→` arc chords or flattened polylines, `drawPolygon→LWPOLYLINE`,
  `drawTextItem→TEXT`, `fillPath→` outline only (no HATCH). Anything else
  (images, gradients) **asserts in debug builds** rather than silently dropping content
  (`dxfpaintdevice.h:59-63`).

**DXF export is reachable only from the GUI** — the sole call sites are
`exportdialog.cpp:454` (`Createdxf::dxfBegin`) and `exportdialog.cpp:740`
(`DxfPaintDevice`), dispatched at `exportdialog.cpp:881-887` when the chosen format acronym is
`"DXF"`. **There is no `--export-dxf` flag.**

### 6.5 DXF import — `sources/dxf/dxftoelmt.{h,cpp}`

`dxfToElmt(file_path)` (`dxf/dxftoelmt.cpp:35-70`) shells out to an **external third-party
binary** `dxf2elmt` with arguments `{file_path, "-v"}` and returns its stdout as the `.elmt`
bytes. The binary is expected at `QETApp::dataDir() + "/binary/dxf2elmt"` (`.exe` on Windows,
`/./dxf2elmt` on macOS) (`dxf/dxftoelmt.cpp:72-90`). If missing, `dxf2ElmtIsPresent(true)`
pops a `ThirdPartyBinaryInstallDialog` pointing at
`https://github.com/Vadoola/dxf2elmt/releases` (`dxf/dxftoelmt.cpp:101-116`).

**Not CLI-reachable**, and it is GUI-coupled: on stderr output it raises a `QMessageBox`
(`dxf/dxftoelmt.cpp:54-62`), which would block a headless run. An MCP server that wants DXF→
elmt should invoke `dxf2elmt` **directly**, bypassing QET entirely.

`sources/qet_elementscaler/qet_elementscaler.cpp` follows the same third-party-binary +
`QInputDialog` pattern (`:36-58`) — also GUI-only.

### 6.6 EPLAN `.edz` import — `sources/import/edz/`

48 files, of which 40 are the vendored decode-only LZMA SDK under
`sources/import/edz/lzma/` (public domain, `lzma/LZMA-SDK-LICENSE.txt`).

Pipeline, per `import/edz/README.md`:

| File | Role |
|---|---|
| `edzarchive.*` | extract `.edz` to a temp dir, locate `part.xml` |
| `edzsevenzip.*` | 7-Zip extraction via the bundled LZMA SDK (no external 7-Zip) |
| `edzpart.*` | parse `part.xml` into a portable model |
| `edzelementbuilder.*` | build the `.elmt` from the model |
| `edzimporter.*` | orchestrate and write into a collection folder |

`EdzImporter::importToDirectory(edz_path, dest_dir)` with `writtenPath()` / `errorString()`
(`import/edz/edzimporter.h:34-38`) is **deliberately UI-decoupled so it stays unit-testable
headless** (`edzimporter.h:28-29`) — but **nothing exposes it on the CLI**. It is invoked from
the elements-panel context menu ("Import an EPLAN part (.edz)…").

What is imported: terminals from `<functiontemplate>` entries with a physical connection
designation; manufacturer / order number / designation / comment into the element-information
fields used by the BOM; localised `<name lang="xx">` entries. **The EPLAN `.ema` macro
geometry is NOT reproduced** — a generic symbol (body rectangle, one west-facing terminal per
pin) is generated instead. Only 7-Zip-format `.edz` is handled; zip-format packages are
detected and reported but unsupported.

Legal note carried in the README: the EPLAN Data Portal Terms of Use (§5.4) restrict
downloaded data to EPLAN products; QET parses only portable factual part data and disclaims
endorsement. **An MCP server should surface this rather than automate bulk `.edz` ingestion.**

---

## 7. RECOMMENDED MCP SERVER USAGE

Assume every invocation is:

```
QT_QPA_PLATFORM=offscreen /path/to/qelectrotech <FLAG> <INPUT> [OUTPUT] [extra...]
```

one flag per process, flag first, absolute paths, `LC_ALL=C.UTF-8`, and Liberation fonts
installed.

| MCP capability | CLI coverage | How |
|---|---|---|
| **Scaffold a new project** | **NOT covered.** No `--new`, no `--add-folio`, no element placement. | Write `.qet` XML directly (plain uncompressed XML, no prolog, 4-space indent to match `--resave`). Then run `--resave` and `--info` to prove QET accepts it. |
| **BOM extract** | **Covered** — `--export-bom <in.qet> <out.csv>` | Parse with `;` delimiter and RFC-4180 quoting (§2.14). Header verbatim §2.5. Remember the `exclude_from_bom` filter and that rows are per-instance, not aggregated. |
| **Wiring list / cable schedule** | **Covered** — `--export-cables <in.qet> <out.csv>` | French header (§2.6). **Unescaped** — validate that no label contains `;` before trusting it, or re-derive from `--export-nets`. |
| **Wire-number census** | **Covered** — `--export-wires <in.qet> <out.csv>` | Headerless, repeating single column (§2.7). Count occurrences to get per-number terminal counts. |
| **Net list / connectivity** | **Covered** — `--export-nets <in.qet> <out.json>` | Best structured output in the CLI. Ground truth for connectivity (walks the potential graph across folios and reports). Nets with no conductor do not appear. |
| **Cross-reference / link audit** | **Covered** — `--export-links <in.qet> <out.csv>` | Exit code is always 0; parse `status == UNRESOLVED` yourself, and add the `NextReport`/`PreviousReport`-with-empty-`linked_to` rule (§5.7). |
| **Structural summary / diff-able fingerprint** | **Covered** — `--info <in.qet>` (JSON on stdout) | The only flag with clean machine-readable stdout. Ideal for a fast "describe this project" tool. Capture stdout only. |
| **Revision stamp** | **Covered** — `--set-titleblock <in.qet> <out.qet> revision=B date=today author="…"` | Writes a NEW file; move it over the original yourself if in-place is wanted. Keys in §2.13. Unknown keys silently become custom fields — validate keys against the table before shelling out, since a typo exits 0. |
| **Validate a project** | **Partially covered.** | Compose: `--info` (does it load? state code, free terminals) + `--export-links` (unresolved xrefs) + `--resave` + textual diff (does QET normalise/lose markup?). No single validate flag exists, and none of them exits non-zero on a "logically invalid but loadable" project. |
| **Validate elements (.elmt)** | **Covered** — `--check-elements <file-or-dir>` | Recursive over a directory. Exit 1 = at least one FAIL; warnings do not change the exit code. Parse the `OK`/`WARN`/`FAIL` stdout lines (§2.11) for detail. |
| **Round-trip integrity** | **Covered** — `--resave <in.qet> <out.qet>` then diff | Watch the Qt5 encoding and Windows CRLF caveats (§2.12). |
| **Render PDF** | **Covered** — `--export-pdf <in.qet> <out.pdf>` | One folio per page, internal cross-reference hyperlinks included. No page-selection, no scaling options — those are GUI-only (§6.2). |
| **Render PNG / SVG previews** | **Covered** — `--export-png` / `--export-svg <in.qet> <out_dir>` | Second arg is a DIRECTORY. Files land as `NN_Title.ext`; enumerate the directory afterwards rather than predicting names (title sanitisation, §2.4). SVG failures are silent (§5.5). |
| **DXF export** | **NOT covered.** GUI-only (§6.4). | Either add a CLI flag upstream, or render SVG and convert externally. |
| **DXF import** | **NOT covered**, and the in-app path is GUI-coupled (§6.5). | Call the `dxf2elmt` binary directly. |
| **EPLAN `.edz` import** | **NOT covered** (§6.6). | `EdzImporter` is headless-clean C++ but has no CLI entry point; exposing it would need an upstream flag. |
| **Batch / multi-op** | **NOT covered.** One flag per process (§2.1). | Sequence separate invocations. Each reloads and reparses the project — budget accordingly on large projects (load time is logged to stderr, `qetproject.cpp:263-268`). |
| **Modify diagram content (add/move/delete elements, conductors)** | **NOT covered at all.** | Custom XML work against the `.qet` schema, then `--resave` + `--info` + `--export-links` as an acceptance gate. |

### 7.1 Suggested MCP tool decomposition

1. `qet_info(project)` → run `--info`, return parsed stdout JSON. Cheapest health check.
2. `qet_bom(project)` → `--export-bom` to a temp file, parse `;`-CSV, return rows.
3. `qet_nets(project)` → `--export-nets`, return parsed JSON.
4. `qet_links(project)` → `--export-links`, return rows **plus** a derived
   `unresolved: [...]` list applying both the `UNRESOLVED` status and the report rule (§5.7).
5. `qet_render(project, format, dest)` → `--export-pdf` | `--export-png` | `--export-svg`,
   returning the list of files actually produced (enumerate the directory).
6. `qet_stamp(project, dest, fields)` → `--set-titleblock`, **validating field keys
   client-side** against §2.13 before shelling out.
7. `qet_check_elements(path)` → `--check-elements`, parse the `OK`/`WARN`/`FAIL` lines and the
   summary; report exit 1 as "validation failures", not "tool error".
8. `qet_roundtrip(project)` → `--resave` + diff, returning the normalisation delta.

Every one of these should first run the §3.4 capability probe once per binary and cache the
result.
