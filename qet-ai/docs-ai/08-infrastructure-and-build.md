# 08 — Infrastructure, Undo System, XML Helpers, Caching and Build

Scope: `sources/*.cpp` (root level, 61 files), `sources/undocommand/`,
`sources/QPropertyUndoCommand/`, `sources/diagramcommands.cpp`,
`sources/factory/`, `sources/utils/`, `sources/logging/`, the CMake/qmake build
system, and `tests/`.

Source root for every path below: `/root/qet/qelectrotech-source-mirror`.

Audience: an agent that will build an MCP server that reads and writes QET XML
(`.qet` projects, `.elmt` elements, `.titleblock` templates) **out of process**.
The recurring theme is: QET's in-process model is guarded by an undo stack and
several caches; a file-level writer sits underneath all of that and must
therefore match QET's on-disk conventions exactly and know which caches it can
poison.

---

## 1. Root-level file inventory

`sources/` contains 61 `.cpp` files at the top level plus one header-only unit
(`conductorsegmentprofile.h`, no `.cpp`). Every one is listed here.

### 1.1 Application entry, app object, global services

| File | Purpose |
|---|---|
| `main.cpp` | `main()`. Sets org/app name for QSettings (`main.cpp:95-97`), forces `QT_HASH_SEED=0` for stable XML diffs (`main.cpp:93`), sets `QDomImplementation::setInvalidDataPolicy(ReturnNullNode)` (CVE-2026-15037 mitigation, `main.cpp:102`), intercepts headless CLI export **before** SingleApplication (`main.cpp:120-132`), inits `QetLogger` + crash handler (`main.cpp:145-152`), constructs `SingleApplication` and `QETApp`, starts `EventLoopWatchdog` (`main.cpp:208`). |
| `qetapp.cpp` / `.h` | The `QETApp` singleton (derives from `SingleApplication`/`QApplication`). Owns: collection cache, splash screen, system tray, all directory resolution (`configDir()`, `dataDir()`, `commonElementsDir()`, `customElementsDir()`, `companyElementsDir()`, `documentDir()`, `pictureDir()`, `userMacrosDir()`, `languagesPath()`), symbolic-path ↔ real-path translation (`realPath()` `qetapp.cpp:1029`, `symbolicPath()` `qetapp.cpp:1069`), window registry, and startup checks including crash-dump recovery. |
| `qet.cpp` / `.h` | Free-function/enum grab bag in namespace `QET` plus class `Qet`. Enums: `GraphicsItemState`, `DepthOption`, `OrientedMovement`, `OperationAreas`, `ScalingMethod`, `ConductorSegmentType`, `ItemType`, `Filtering`, `Action`, `DiagramArea`, `TitleBlockColumnLength`, `QetCollection`. Free functions include the XML attribute validators and the canonical XML writers — see §3. |
| `qetarguments.cpp` / `.h` | Parses the command line. Recognises `--help`, `--version`/`-v`, `--license`, and the four path overrides `--common-elements-dir=`, `--common-tbt-dir=`, `--config-dir=`, `--data-dir=`, plus `--lang-dir=` (`qetarguments.cpp:259-302`). Each override is compiled in only when the matching `QET_ALLOW_OVERRIDE_*_OPTION` define is set (see §6.3). |
| `qetversion.cpp` / `.h` | Namespace `QetVersion`. `currentVersion()` returns a hardcoded `QVersionNumber{0,200,1}` (`qetversion.cpp:26`); `displayedVersion()` appends a `-dev`/`-alpha N` suffix per `VERSION_TYPE` (`qetversion.cpp:22`). `toXmlAttribute()`/`fromXmlAttribute()` read/write the `version` attribute on a `QDomElement` (`qetversion.cpp:59-79`). `versionZeroDotSix()` = `{0,60}`, used as a compatibility pivot. |
| `machine_info.cpp` / `.h` | `MachineInfo` singleton. Collects OS, CPU (separate Linux `/proc/cpuinfo`, WinNT registry, macOS sysctl paths at `machine_info.cpp:298/354/408`), screen and compilation info; `send_info_to_debug()` dumps it to the log at startup from a worker thread (`main.cpp:202`). |
| `qeticons.cpp` / `.h` | Namespace `QET::Icons`. Declares ~350 `QIcon` globals and `initIcons()`, called from `QETApp` construction (`qetapp.cpp:121`). Pure resource plumbing; no XML relevance. |
| `qetmessagebox.cpp` / `.h` | Namespace `QET::QetMessageBox`. Thin wrappers over `QMessageBox::critical/information/question/warning` that force window-modal + `Qt::Sheet` on macOS when a parent widget is given. |
| `qetresult.cpp` / `.h` | `QETResult`: a bool + error-message pair returned by fallible operations (notably project open/save). |
| `shortcutmanager.cpp` / `.h` | App-wide registry of rebindable shortcuts, addressed generically through the `shortcut` `Q_PROPERTY` common to `QAction` and `QAbstractButton`. |
| `recentfiles.cpp` / `.h` | Recent-files menu. Keys in QSettings are `<identifier>-recentfiles/fileN`, N starting at 1 (`recentfiles.cpp:127`, `recentfiles.cpp:159`). Paths are stored with native separators (`recentfiles.cpp:137`). |
| `cli_export.cpp` / `.h` | Headless batch export/inspection, handled before the GUI exists. See §7.3 — this is the single most MCP-relevant file in the tree. |

### 1.2 Diagram / project model and views

| File | Purpose |
|---|---|
| `diagram.cpp` / `.h` | `Diagram` — the `QGraphicsScene` subclass representing one folio. Holds `border_and_titleblock`, conductor/element content, XML (de)serialisation, and forwards `undoStack()` to the owning project (`diagram.cpp:2693-2694`). |
| `diagramview.cpp` / `.h` | `QGraphicsView` subclass rendering a `Diagram` interactively (zoom, rubber band, drop handling). |
| `qetproject.cpp` / `.h` | `QETProject` — one `.qet` file. Owns the single `QUndoStack` (`qetproject.cpp:205`), the diagram list, the embedded element collection, the embedded title-block collection, project properties, autonum contexts, terminal strips, and the crash-recovery backup (`KAutoSaveFile m_backup_file`, 20-minute timer `qetproject.cpp:46,208-210`). |
| `projectview.cpp` / `.h` | `QTabWidget`-based view of a project (one tab per folio) plus `WheelEnabledTabBar`. `setDiagramPosition()` is what `MoveDiagramCommand` wraps. |
| `qetdiagrameditor.cpp` / `.h` | The main diagram-editor window: menus, toolbars, docks, and the great majority of user actions that push undo commands. |
| `qetmainwindow.cpp` / `.h` | Common base class for QET's top-level windows (menu/statusbar scaffolding). |
| `diagramcontent.cpp` / `.h` | `DiagramContent` — a typed bag of selected/affected items (elements, conductors, texts, images, shapes, tables, terminal strips) with filter flags. The currency of nearly every undo command. |
| `diagramcontext.cpp` / `.h` | Key/value store of a diagram's or element's data, consumed by title-block templates and by `%{var}` substitution. |
| `diagramposition.cpp` / `.h` | Column/row grid position (e.g. `B2`) of an item on a folio. |
| `diagramcommands.cpp` / `.h` | Undo commands that are specifically about a diagram's contents. See §2.3. |
| `qgimanager.cpp` / `.h` | `QGIManager` — refcounts `QGraphicsItem`s so an item held only by an undone command is not leaked or double-deleted. Undo commands call `manage()`/`release()` (`undocommand/addgraphicsobjectcommand.cpp:41,48`). |
| `elementsmover.cpp` / `.h` | Drives interactive multi-item movement on a diagram and produces the resulting `MoveGraphicsItemCommand`. |
| `elementtextsmover.cpp` / `.h` | Same, for element text items / text groups. |
| `autobreakconductor.cpp` / `.h` | `autoBreakConductors()` — when an element is dropped onto an existing conductor, break the conductor and reconnect through the element's terminals, emitting sub-commands under a caller-supplied parent `QUndoCommand`. |
| `elementprovider.cpp` / `.h` | Queries a diagram/project for elements by kind (`master`, `slave`, `folio report`, `terminal`) and by link status (e.g. "free"); also `fromUuids()`. |
| `lastusedstyle.cpp` / `.h` | Session-scoped "last used" pen/brush/font for newly created shapes and free texts. |

### 1.3 Properties containers (XML-serialisable value types)

| File | Purpose |
|---|---|
| `borderproperties.cpp` / `.h` | `BorderProperties`: columns/rows counts, widths, header sizes, display flags. Defaults: 17 columns × 60.0, header 20.0; 8 rows × 80.0, header 20.0 (asserted in `tests/catch/src/borderproperties_test.cpp:8-15`). |
| `bordertitleblock.cpp` / `.h` | `BorderTitleBlock`: the drawn frame + title block around a diagram; owns a `TitleBlockTemplateRenderer`. |
| `conductorproperties.cpp` / `.h` | `ConductorProperties` and `SingleLineProperties` — the electrical + visual attributes of a conductor. |
| `conductorprofile.cpp` / `.h` | `ConductorProfile` / `ConductorProfilesGroup` — a conductor's routed shape, per corner orientation. |
| `conductorsegment.cpp` / `.h` | One horizontal/vertical run of a conductor. |
| `conductorsegmentprofile.h` | Header-only value type for a single segment's profile. **The only root-level header with no matching `.cpp`.** |
| `exportproperties.cpp` / `.h` | Options for image/PDF export (area, size, DPI, drawing toggles). |
| `titleblockproperties.cpp` / `.h` | `TitleBlockProperties`: title, author, date, filename, folio, plant, locmach, indexrev, version, template name, custom `DiagramContext` fields. |
| `titleblockcell.cpp` / `.h` | One cell of a title-block template (span, alignment, font, value type). |
| `titleblocktemplate.cpp` / `.h` | Parses a `.titleblock` XML template into a cell grid and renders it against a `DiagramContext`. |
| `titleblocktemplaterenderer.cpp` / `.h` | Caches/produces the rendered output of a `TitleBlockTemplate` for a given context and width. |

### 1.4 Dialogs, panels, widgets

| File | Purpose |
|---|---|
| `configdialog.cpp` / `.h` | The application preferences dialog (hosts the `ConfigPage`s in `sources/ui/configpage/`). |
| `elementdialog.cpp` / `.h` | Element/category open & save-as pickers built on `ElementsCollectionModel`. |
| `elementscategoryeditor.cpp` / `.h` | Create/rename an element category (directory) including its `qet_directory` translations. |
| `newelementwizard.cpp` / `.h` | Wizard for creating a new `.elmt` (name, category, size, hotspot). |
| `elementspanel.cpp` / `.h` | Legacy `QTreeWidget` panel listing collections, projects, folios, title blocks. |
| `elementspanelwidget.cpp` / `.h` | Toolbar + `ElementsPanel` composite. |
| `genericpanel.cpp` / `.h` | Base class for the tree panels; builds `QTreeWidgetItem`s for projects/diagrams/templates. |
| `exportdialog.cpp` / `.h` | The GUI "export to image" dialog: preview, per-diagram enable, resize, clipboard, PNG/JPG/SVG/DXF output. |
| `exportpropertieswidget.cpp` / `.h` | The reusable options widget embedded in `exportdialog` and in the print path. |
| `elementtextpattern.cpp` / `.h` | `ExportElementTextPattern` / import counterpart — save and reapply an element's dynamic-text layout as a named pattern. |
| `qfilenameedit.cpp` / `.h` | Line edit restricted to portable file names (`^[0-9a-z_-\.]+$`). |
| `qetregexpvalidator.cpp` / `.h` | `QRegularExpressionValidator` that emits a signal on validation failure (drives `QFileNameEdit`'s feedback). |
| `qtextorientationwidget.cpp` / `.h` | Visual text-orientation picker. |
| `qtextorientationspinboxwidget.cpp` / `.h` | The above plus a `QSpinBox`. |

### 1.5 Export/interchange back-ends

| File | Purpose |
|---|---|
| `createdxf.cpp` / `.h` | `Createdxf` — writes DXF entity records (lines, arcs, circles, polylines, text) directly. |
| `dxfpaintdevice.cpp` / `.h` | `DxfPaintEngine`/`DxfPaintDevice` — a `QPaintEngine` that turns `QGraphicsItem::paint()` calls into `Createdxf` entities, so DXF export reuses the normal painting code. |
| `pdf_links.cpp` / `.h` | Turns cross-references and folio reports into clickable internal PDF hyperlinks via the **private** `QPdfEngine::drawHyperlink`. This is the sole reason the build needs `Qt::GuiPrivate` (see §6.5). |
| `wiringlistexport.cpp` / `.h` | `WiringListExport` — CSV wiring list (one row per conductor). |
| `conductornumexport.cpp` / `.h` | `ConductorNumExport` — CSV of distinct conductor numbers. |
| `qetinformation.cpp` / `.h` | Namespace `QETInformation`: the canonical registry of information keys for elements, conductors, diagrams, title blocks, folio reports and terminals, plus the `key → %{key}` variable form and translated labels. Any generator that writes `<input>`/`<dynamic_text>` variable strings must use these keys. |
| `elementscollectioncache.cpp` / `.h` | The SQLite name/pixmap cache for the elements panel. See §5. |
| `qetxml.cpp` / `.h` | Shared XML read/write helpers, namespace `QETXML`. See §3. |

---

## 2. The undo/command system

### 2.1 Shape of the system

* QET uses stock Qt undo: every mutation is a `QUndoCommand` subclass pushed onto a `QUndoStack`.
* **There is exactly one `QUndoStack` per project, not per folio.** It is created in `QETProject`'s constructor (`qetproject.cpp:205`) and exposed as `QETProject::undoStack()` (`qetproject.h:209`). `Diagram::undoStack()` simply returns `*(project()->undoStack())` (`diagram.cpp:2693-2694`). A command touching folio 3 therefore shares an undo history with a command touching folio 7.
* Dirty tracking is derived from the stack: `QETProject::undoStackChanged(bool a) { if (!a) setModified(true); }` is connected to `QUndoStack::cleanChanged` (`qetproject.h:255`, `qetproject.cpp:206`). `QETProject::projectWasModified()` also consults `!m_undo_stack->isClean()` (`qetproject.cpp:2112`).
  **Consequence: a model change that is not pushed as a command does not mark the project dirty, and QET may exit without offering to save it.**
* Item lifetime across undo is handled by `QGIManager` (`qgimanager.cpp`). Commands `manage()` an item on construction and `release()` it on destruction (`undocommand/addgraphicsobjectcommand.cpp:41,48`), so an item that exists only inside an undone command is owned by the manager, not by the scene.
* Most commands call `m_diagram->showMe()` in both `undo()` and `redo()` so undoing on a background folio raises that folio (`undocommand/addgraphicsobjectcommand.cpp:56,71`).
* There are ~203 `undoStack()...push(...)` call sites across `sources/` — command wrapping is the norm, not the exception.

### 2.2 `sources/undocommand/` (15 command families, 30 files)

| Class(es) | File | What it wraps / notes |
|---|---|---|
| `AddDiagramCommand` | `adddiagramcommand.*` | Insert an already-constructed, not-yet-inserted folio into a project. Takes ownership: the diagram is destroyed only if the command dies while undone. Pushed by `QETProject::addNewDiagram()` (`qetproject.cpp:1398`). |
| `RemoveDiagramCommand` | `removediagramcommand.*` | Detach a folio (and its tab) without destroying it; `undo()` reinserts at the original index. |
| `MoveDiagramCommand` | `movediagramcommand.*` | Reorder folio tabs; wraps `ProjectView::setDiagramPosition()`, which does the tab move *and* the project diagram-list reorder in one step. |
| `AddGraphicsObjectCommand` | `addgraphicsobjectcommand.*` | Add any `QGraphicsObject` (element, conductor, text, image, shape) to a diagram at a position. |
| `DeleteQGraphicsItemCommand` | `deleteqgraphicsitemcommand.*` | Delete a `DiagramContent`. Non-trivial: it remembers per-element link lists, the parent element of each deleted dynamic text, parent text groups, connected terminal pairs, linked tables' scenes, and it re-derives conductor potentials (`setPotentialsOfRemovedElements()`). Also exposes `hasNonDeletableTerminal()`. |
| `MoveGraphicsItemCommand` | `movegraphicsitemcommand.*` | Move one or many items. |
| `RotateSelectionCommand` | `rotateselectioncommand.*` | Rotate the current selection (composes `QPropertyUndoCommand`s internally). |
| `RotateTextsCommand` | `rotatetextscommand.*` | Opens a dialog and rotates selected texts/groups; animatable via `QParallelAnimationGroup`. |
| `AddElementTextCommand`, `AddTextsGroupCommand` | `addelementtextcommand.*` | Add a dynamic element text / a text group to an element. |
| `ChangeElementDataCommand` | `changeelementdatacommand.*` | Replace an element's `ElementData`. |
| `ChangeElementInformationCommand` | `changeelementinformationcommand.*` | Replace an element's information `DiagramContext`. |
| `ChangeTitleBlockCommand` | `changetitleblockcommand.*` | Replace a folio's `TitleBlockProperties`. |
| `LinkElementCommand` | `linkelementcommand.*` | Link/unlink master↔slave and report↔report. Supports `mergeWith`, so several link edits in one editing session collapse to one undo step. |
| `ModelIndexCommand`, `ModelHeaderDataCommand` | `itemmodelcommand.*` | Edit a `QAbstractItemModel` index / header data undoably (used by the graphics tables and terminal-strip editors). |
| `SetAutoNumContextCommand` | `setautonumcontextcommand.*` | Wraps `QETProject::add*AutoNum()`. Its own comment states the failure mode plainly: placing an auto-numbered item advances a project counter as a side effect, and without this command undoing the placement removes the visible number but leaves the counter advanced, silently burning it. **This is the canonical example of model state that lives outside the graphics scene but still needs a command.** |

Two further command directories exist outside this doc's scope but follow the
same pattern: `sources/editor/UndoCommand/` (`AddPartCommand`,
`DeletePartsCommand`, `PastePartsCommand`, `OpenElmtCommand` — the element
editor) and `sources/TerminalStrip/UndoCommand/` (8 commands for terminal
strips).

### 2.3 `sources/diagramcommands.cpp` (6 classes, 522 lines)

| Class | Line | Notes |
|---|---|---|
| `PasteDiagramCommand` | `diagramcommands.h:32` | Pastes a `DiagramContent`. Holds a `first_redo` guard so the constructor-time paste is not re-applied on the first `redo()`. Creates auto-break conductor sub-commands lazily on the first redo (`m_break_cmd`). |
| `CutDiagramCommand` | `diagramcommands.h:64` | Trivial subclass of `DeleteQGraphicsItemCommand` (different text only). |
| `MoveConductorsTextsCommand` | `diagramcommands.h:79` | Moves conductor labels; `first_redo` guard; regenerates text labels on undo. |
| `ChangeDiagramTextCommand` | `diagramcommands.h:113` | before/after `QString` on a `DiagramTextItem`; `first_redo` guard. |
| `ChangeConductorCommand` | `diagramcommands.h:146` | Old/new `ConductorProfile` plus `Qt::Corner` path type plus the text-item displacement; `first_redo` guard. |
| `ResetConductorCommand` | `diagramcommands.h:185` | Restores a `QHash<Conductor*, ConductorProfilesGroup>`. |
| `ChangeBorderCommand` | `diagramcommands.h:213` | Old/new `BorderProperties` for a folio. |

The recurring `bool first_redo` member is a QET idiom: the mutation has already
been applied by the calling code before the command is pushed, and `QUndoStack::push()`
calls `redo()` immediately, so the first `redo()` must be a no-op.

### 2.4 `QPropertyUndoCommand` (`sources/QPropertyUndoCommand/`)

Generic command over a `Q_PROPERTY` of a `QObject`
(`qpropertyundocommand.h:33-62`):

* Two constructors: `(object, property_name, old, new, parent)` and
  `(object, property_name, old, parent)` + later `setNewValue()`.
* **Does not take ownership of `object`.**
* `id()` returns the constant `10000` (`qpropertyundocommand.h:51`), and
  `mergeWith()` merges any two commands with the same id, same object pointer
  and same property-name pointer (`qpropertyundocommand.cpp:115-122`).
  Note the property-name comparison is a raw `const char*` pointer comparison,
  not a string compare — it works because call sites pass string literals.
* Optional `QPropertyAnimation` on undo/redo via `setAnimated(animate, first_time)`;
  `first_time=false` skips animating the initial redo.

This is the workhorse for "one property changed" edits throughout the element
editor, the shape editors and the property dock widgets.

### 2.5 Why this matters for an MCP server

An MCP server that writes `.qet` / `.elmt` XML directly on disk **bypasses the
entire command layer**. Concretely:

1. **No undo entry exists** for the change. If QET has the file open, the user
   cannot undo the MCP server's edit — and cannot see that it happened.
2. **The dirty flag is not set** (§2.1). QET's in-memory copy is still
   considered clean relative to *its own* history.
3. **Last-writer-wins clobbering.** There is no `QFileSystemWatcher` on `.qet`
   project files or on the element collection directories. The only watcher in
   the tree is on the title-block templates directory
   (`titleblock/templatescollection.h:157`, `templatescollection.cpp:386`).
   If a project is open in QET and the MCP server rewrites the file, QET's next
   save silently overwrites the MCP server's work, and vice versa.
   **[inference] The safe protocol is: operate on files QET does not currently
   have open, or require the user to close the project first.**
4. **Derived state is not recomputed.** Writing XML does not run
   `autoBreakConductors()`, does not advance or reconcile the autonum counters
   that `SetAutoNumContextCommand` guards, does not re-derive conductor
   potentials the way `DeleteQGraphicsItemCommand::setPotentialsOfRemovedElements()`
   does, and does not update cross-reference link state the way
   `LinkElementCommand` does. Any of these that the generated XML gets wrong
   will be wrong until the user performs the corresponding GUI action.
5. **In-process caches are not invalidated** — see §5.

Model mutations that assume a command wrapper (i.e. mutating them any other way
leaves the project inconsistent or non-dirty): folio add/remove/reorder;
any scene item add/delete/move/rotate; element data, element information and
element links; folio title-block properties; folio border properties;
conductor profile/reset; text content and text rotation; the project's autonum
counters; and any `QAbstractItemModel` backing a graphics table or terminal strip.

---

## 3. XML helpers a generator must match

Two namespaces share this job. `QET` (in `qet.h`/`qet.cpp`) holds the older,
attribute-oriented validators; `QETXML` (in `qetxml.h`/`qetxml.cpp`) holds the
newer property-element system plus the type ↔ XML converters.

### 3.1 `QET::` validators and file writers — exact rules

| Function | Location | Exact rule |
|---|---|---|
| `QET::attributeIsAnInteger(e, name, int* = nullptr)` | `qet.cpp:213-224` | Returns `false` if `!e.hasAttribute(name)`. Otherwise `e.attribute(name).toInt(&ok)`; returns `false` if `!ok`. On success writes the value through the pointer and returns `true`. **`QString::toInt` with the default base 10: no leading `+`/`-` beyond one sign, no whitespace, no hex, no decimal point, no thousands separators, no trailing garbage. `"3.0"` FAILS. `"0x10"` FAILS. `" 3"` FAILS.** |
| `QET::attributeIsAReal(e, name, qreal* = nullptr)` | `qet.cpp:234-245` | Same shape, but `toDouble(&ok)`. Accepts C-locale decimal point `.` and exponent form (`1e3`). **A comma decimal separator FAILS.** Empty attribute FAILS. |
| `QET::forbiddenCharacters()` | `qet.cpp:464-468` | Exactly: `\` `/` `:` `*` `?` `"` `<` `>` `|`. |
| `QET::stringToFileName(name)` | `qet.cpp:479-495` | 1) lowercases the whole string; 2) replaces every forbidden character above with `-`; 3) replaces every space with `_`. Accented characters are **not** stripped (there is an open `@TODO` at `qet.cpp:481`). Verified by `tests/catch/src/qet_test.cpp:5-15`. |
| `QET::escapeSpaces(s)` | `qet.cpp:502-504` | `\` → `\\`, then ` ` → `\ `. |
| `QET::unescapeSpaces(s)` | `qet.cpp:511-513` | `\\` → `\`, then `\ ` → ` `. |
| `QET::joinWithSpaces(list)` | `qet.cpp:521-529` | Escapes each element then joins with a single unescaped space. |
| `QET::splitWithSpaces(s)` | `qet.cpp:538-548` | Splits on the regex `[^\\]?(?:\\\\)* ` with `SkipEmptyParts`, then unescapes each part. |
| `QET::round(x, epsilon)` | `qet.cpp:603-605` | `int(x * epsilon) / epsilon` — truncation toward zero, **not** rounding. `epsilon=10` gives 1-decimal truncation. |
| `QET::correctAngle(angle, positive=false)` | `qet.cpp:614-621` | Normalises into `(-360, 360)`; with `positive=true`, into `[0, 360)`. |
| `QET::compareCanonicalFilePaths(a, b)` | `qet.cpp:629-647` | Both must resolve to a non-empty `canonicalFilePath()` (i.e. **both must exist on disk**); on `Q_OS_WIN` both are lowercased first. |
| `QET::eachStrIsEqual(list)` | `qet.cpp:703-709` | True if all strings equal. Undefined on an empty list — caller must check first. |
| `QET::writeXmlFile(doc, filepath, err*)` | `qet.cpp:654-693` | **The canonical project/element writer.** Uses `QSaveFile` (atomic replace via `commit()`). Opens `WriteOnly` **without** `QIODevice::Text` so line endings stay LF on every platform. Sets the stream to UTF-8 explicitly (`setCodec` on Qt5, `setEncoding(QStringConverter::Utf8)` on Qt6) and `setGenerateByteOrderMark(false)`. Serialises with `xml_doc.toString(4)`. |
| `QET::writeToFile(doc, QFile*, err*)` | `qet.cpp:786-827` | Same encoding contract but writes into a caller-supplied `QFile` (used for the crash-recovery backup, which writes through a `KAutoSaveFile`). Opens the file only if not already open, seeks to 0, and closes only if it opened it. **Note: it does not truncate — seeking to 0 over a longer previous content leaves a tail. [inference] Callers pass a freshly truncated file.** |
| `QETXML::writeXmlFile(doc, path, err*)` | `qetxml.cpp:257-289` | Same encoding/indent contract but plain `QFile`, no atomic replace. |

**Generator contract, restated:** output must be UTF-8, **no BOM**, LF line
endings, indented with **4 spaces**, matching `QDomDocument::toString(4)`.
Numeric attributes must be plain base-10 integers or C-locale doubles.

### 3.2 `QETXML::` property elements

The newer scheme stores a value as a child `<property>` element rather than as
an attribute on the parent.

* Type tag constants (`qetxml.h:109-114`): `int`, `double`, `bool`, `string`, `uuid`, `color`.
* `createXmlProperty(name, value)` overloads for `QString`, `const char*`, `int`,
  `double`, `bool`, `QUuid`, `QColor` (`qetxml.cpp:639-708`). Each produces
  `<property name="…" type="…" value="…"/>`. Formatting per type:
  * `int` / `double` → `QString::number(value)`
  * `bool` → `QString::number(value)`, i.e. it writes **`"1"` / `"0"`**, not `"true"`/`"false"`
  * `QUuid` → `value.toString()`, i.e. **braced** `{xxxxxxxx-…}`
  * `QColor` → `value.name()`, i.e. `#rrggbb`
* `validXmlProperty(e)` (`qetxml.cpp:891-902`): true iff `e` has **all three** of
  `name`, `type`, `value`. No other check — the tag name is not verified.
* `property(e, name)` (`qetxml.cpp:855-866`): scans direct children, skips any
  child failing `validXmlProperty`, returns the first whose `name` attribute matches.
* `attribute(e, name, type, QString* out)` (`qetxml.cpp:877-899`): the
  compatibility shim. If no matching `<property>` child exists it falls back to
  a **legacy plain attribute** `e.attribute(name)` and returns that. If a
  `<property>` child exists but its `type` attribute differs from the requested
  type, it returns `false` (logged via `qDebug`). So: legacy attributes are
  untyped and always accepted; property elements are type-checked strictly.

Validation helpers, with exact rules (`qetxml.cpp:713-853`). Each returns a
`PropertyFlags` value: `Success = 0`, `NotFound = 1`, `NoValidConversion = 2`
(`qetxml.h:116-121`).

| Helper | Rule |
|---|---|
| `propertyInteger(const QString&, int*)` | `value.toInt(&ok)`; `!ok` → `NoValidConversion`. Same strictness as `attributeIsAnInteger`. |
| `propertyInteger(e, name, int*)` | `attribute(e, name, "int", …)` first; failure → `NotFound`. Then the string form. |
| `propertyDouble(const QString&, double*)` | `value.toDouble(&ok)`; `!ok` → `NoValidConversion`. |
| `propertyDouble(e, name, double*)` | `attribute(e, name, "double", …)` then the string form. |
| `propertyBool(const QString&, bool*)` | First tries `value.toInt(&ok)` — **so any integer parses, and any non-zero integer is `true`** (`"2"` → true, `"-1"` → true). If `toInt` fails, accepts exactly the literals `"true"`, `"1"`, `"false"`, `"0"`; anything else → `NoValidConversion`. |
| `propertyBool(e, name, bool*)` | `attribute(e, name, "bool", …)` then the string form. |
| `propertyUuid(const QString&, QUuid*)` | `QUuid(value).isNull()` → `NoValidConversion`. **A syntactically valid but all-zero UUID is therefore rejected**, as is any unparseable string. `QUuid`'s parser accepts both braced and unbraced 36/38-char forms. |
| `propertyUuid(e, name, QUuid*)` | `attribute(e, name, "uuid", …)` then the string form. |
| `propertyColor(const QString&, QColor*)` | `QColor(value).isValid()` → else `NoValidConversion`. Accepts `#rgb`, `#rrggbb`, `#aarrggbb`, `#rrrrggggbbbb` and SVG colour names. |
| `propertyColor(e, name, QColor*)` | `attribute(e, name, "color", …)` then the string form. |
| `propertyString(e, name, QString*)` | `attribute(e, name, "string", …)`; **no further validation** — any string, including empty, is `Success`. |

Separate from the property system, `QETXML::boolFromString(value, default, ok*)`
(`qetxml.cpp:606-625`) is **stricter** than `propertyBool`: it accepts only the
exact literals `"true"`, `"1"`, `"false"`, `"0"`; anything else returns
`default_value` with `*conv_ok = false`. `boolToString()` writes `"true"`/`"false"`
(`qetxml.cpp:594-598`). **Note the asymmetry: `createXmlProperty(name, bool)`
writes `"1"`/`"0"` while `boolToString()` writes `"true"`/`"false"`; both are
readable by `propertyBool` but only the latter pair by `boolFromString`.**

### 3.3 `QETXML::` structured converters

| Function | Location | On-disk form |
|---|---|---|
| `penToXml` / `penFromXml` | `qetxml.cpp:36-90` | `<pen style="…" color="#rrggbb" widthF="…"/>`. Styles: `SolidLine`, `DashLine`, `DotLine`, `DashDotLine`, `DashDotDotLine`, `CustomDashLine`, else `Unknown`. **Reader defaults: unknown/absent tag → a pen with `Qt::DashLine`; absent `style` → `DashLine`; absent `color` → `#000000`; absent `widthF` → `1`. `CustomDashLine` is hardcoded to the dash pattern `{10, 10}`.** |
| `brushToXml` / `brushFromXml` | `qetxml.cpp:100-165` | `<brush style="…" color="#rrggbb"/>`. Styles: `NoBrush`, `SolidPattern`, `Dense1..7Pattern`, `HorPattern`, `VerPattern`, `CrossPattern`, `BDiagPattern`, `FDiagPattern`, `DiagCrossPattern`, else `Unknown` (read back as `NoBrush`). Absent `style` → `NoBrush`; absent `color` → `#000000`. |
| `marginsToXml` / `marginsFromXml` | `qetxml.cpp:387-430` | `<margins>L;T;R;B</margins>` — a **text node**, semicolon-separated, integers. Reader returns a default `QMargins()` if the tag name is not `margins` or the split does not yield exactly 4 parts. |
| `qGraphicsItemPosToXml` / `…FromXml` | `qetxml.cpp:909-945` | `<pos x="…" y="…" z="…"/>`. Writer uses `QString::number(qreal)` for all three. **Reader parses `x`/`y` as double but `z` as `toInt()`** — a fractional z in the file is truncated. Missing attributes default to `"0"`. |
| `orientationToAttribute` / `…FromAttribute` | `qetxml.cpp:960-990` | Attribute `orientation` with value **`"Horizontal"` / `"Vertical"` (capitalised)**. Reader takes a `def_value` (defaults to `Qt::Vertical`). |
| `alignmentToAttribute` / `…FromAttribute` | `qetxml.cpp:991-1046` | Attribute `alignment`. |
| `textToDomElement(doc, tag, value)` | `qetxml.cpp:304-313` | `<tag>value</tag>` via a text node. |
| `directChild(e, tag)` | `qetxml.cpp:322-340` | Direct element children with that tag name. |
| `subChild(e, parent_tag, child_tag)` | `qetxml.cpp:350-380` | Grandchildren `child_tag` under direct children `parent_tag`. |
| `findInDomElement(e, tag)` | `qetxml.cpp:566-585` | Recursive-ish search (mirrors `QET::findInDomElement`). |
| `modelHeaderDataToXml` / `…FromXml` | `qetxml.cpp:439-565` | Serialises selected header roles of a `QAbstractItemModel` (graphics tables). |
| `fileSystemDirToXmlCollectionDir` | `qetxml.cpp:178-207` | Turns a directory into `<category name="…">` plus, if a `qet_directory` file exists whose root tag is `qet-directory`, an embedded `NamesList`. |
| `fileSystemElementToXmlCollectionElement` | `qetxml.cpp:222-244` | Turns an `.elmt` file into `<element name="…">` wrapping the file's document element. Returns a **null** element if the file cannot be opened or `setContent()` fails — i.e. malformed `.elmt` files are dropped silently from the embedded collection. |

---

## 4. Logging and settings — where the files live

### 4.1 Logging (`sources/logging/`, 5 units)

Design notes are in the class comment at `qetlogger.h:28-72`. The subsystem has
four pieces:

* **`QetLogger`** (`qetlogger.cpp`, 431 lines) — the singleton behind the
  `qInstallMessageHandler` hook installed in `main.cpp:145-146`.
* **`LogRing`** (`logring.h`) — lock-free fixed ring, `kCapacityEntries = 4096`
  × `kEntryBytes = 512` = **2 MiB preallocated**, never allocates on append
  (`logring.h:52-54`).
* **`CrashHandler`** (`crashhandler.h`) — installs `sigaction` handlers for
  `SIGSEGV`, `SIGABRT`, `SIGBUS`, `SIGFPE`, `SIGILL` on POSIX (plus a Windows
  SEH path); flushes the ring to a fixed file, then restores the default
  disposition and **re-raises** so a core dump / WER report is still produced.
  Only the first crash writes a dump (atomic test-and-set).
* **`EventLoopWatchdog`** (`eventloopwatchdog.h`) — a precise repeating timer
  measuring actual elapsed wall time per tick via `QElapsedTimer`; emits a
  `qWarning()` only when a tick is late by more than `kStallThresholdMs` (200 ms, `eventloopwatchdog.h:70`).
  Started in `main.cpp:208-209`.
* `logging/ui/diagnosticsreportdialog.*` — the "save a diagnostics report" dialog.

**Paths.** The log directory is `QETApp::dataDir()` (`qetlogger.cpp:95`), created
with `QDir().mkpath()` if missing (`qetlogger.cpp:132`).

| Artefact | Path | Reference |
|---|---|---|
| Current session log | `<dataDir>/YYYYMMDD.log` | `qetlogger.cpp:115-117`; base name resolved **once** at `init()` (`qetlogger.cpp:96`), so a session crossing midnight stays in one file |
| Rotated logs | `<dataDir>/YYYYMMDD.1.log` … `.4.log` | `qetlogger.cpp:152-154`; `kRotationKeep = 4` (`qetlogger.h:77`) |
| Crash dump | `<dataDir>/crash_dump.log` | `qetlogger.cpp:110-112` |

`<dataDir>` = `QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)`
with trailing slashes chopped (`qetapp.cpp:960-973`), unless overridden by
`--data-dir=` (guarded by `QET_ALLOW_OVERRIDE_DD_OPTION`). With
org `QElectroTech` / app `QElectroTech` (`main.cpp:95-97`) that resolves to:

* **Linux/BSD:** `~/.local/share/QElectroTech/QElectroTech`
* **Windows:** `C:/Users/<USER>/AppData/Roaming/QElectroTech/QElectroTech`
* **macOS:** `~/Library/Application Support/QElectroTech/QElectroTech`

  (The doc comment at `qetapp.cpp:949-958` states the Windows path as
  `AppData/Roaming/<APPNAME>`. **[inference]** Qt's `AppDataLocation` appends
  both organisation and application name, so the real path has two path
  components; treat the doc comment as approximate.)

**Rotation and retention.** Each file is capped at `kMaxFileBytes = 2 MiB`
(`qetlogger.h:76`), rotating `.log → .1.log → … → .4.log` and dropping the old
`.4.log` (`qetlogger.cpp:159-175`). Individual messages are truncated to
`kMaxMessageBytes = 4096` (`qetlogger.h:78`). Control characters are escaped
before writing (`qetlogger.cpp:212-244`) specifically because much of what QET
logs is externally controlled — file paths, element names, font strings read out
of a `.qet` — and an unescaped `\n` would let a crafted string forge log lines.
`pruneOldLogFiles(days)` is called with `days = 7` from a worker thread at
startup (`main.cpp:201`) and deletes matching files whose `lastModified()` date
is more than `days` old (`qetlogger.cpp:331-356`) — deliberately `lastModified()`,
not `lastRead()`, so reading a log does not reset its retention clock.

**Escape hatch:** `QET_LOG_DISABLE=1` in the environment at `init()` time
disables ring, file and rotation, leaving only a minimal stderr passthrough
(`qetlogger.cpp:90`). `QET_WATCHDOG_DISABLE=1` similarly neuters the watchdog.

**Redaction:** `QetLogger::redact()` replaces the user's home directory with `~`
and is applied to both the crash dump and `buildDiagnosticsReport()` before they
reach the user, because both are destined for a public bug tracker
(`qetlogger.h:125-129`).

### 4.2 Settings

QET uses **default-format `QSettings`** throughout — there is no
`setDefaultFormat(IniFormat)` and no explicit `QSettings(path, IniFormat)`
anywhere in `sources/` (verified by grep). With
`setOrganizationName("QElectroTech")` and `setApplicationName("QElectroTech")`
(`main.cpp:95-97`) the backing store is therefore:

* **Linux/BSD:** `~/.config/QElectroTech/QElectroTech.conf` (INI text)
* **Windows:** the registry, `HKEY_CURRENT_USER\Software\QElectroTech\QElectroTech` — **not a file**
* **macOS:** `~/Library/Preferences/org.qelectrotech.QElectroTech.plist`
  (derived from `setOrganizationDomain("qelectrotech.org")`, `main.cpp:96`)

  **[inference]** These are the standard `QSettings` locations for the
  organisation/application/domain triple QET sets; the code never names them.

`QETApp::configDir()` (`qetapp.cpp:933-945`) is a *different* thing: it is
`QStandardPaths::writableLocation(AppConfigLocation)` (Linux `~/.config/QElectroTech/QElectroTech`,
Windows `C:/Users/<USER>/AppData/Local/QElectroTech/QElectroTech`), overridable
by `--config-dir=`. Both `configDir()` and `dataDir()` cache their result in a
C++11 function-local static specifically so they are safe to call from
`QtConcurrent` worker threads, since `QStandardPaths` is not thread-safe
(`qetapp.cpp:938-943`, `qetapp.cpp:965-972`).

`sources/utils/qetsettings.*` is a deliberately thin namespace over `QSettings`
"for values used in several parts of the code" (`qetsettings.h:23-28`). It
currently holds only the HiDPI rounding policy, key
`hdpi_scale_factor_rounding_policy`, values `Round | Ceil | Floor |
RoundPreferFloor | PassThrough`, defaulting to `PassThrough`
(`qetsettings.cpp:35-49`); it is read before the `QApplication` exists
(`main.cpp:114`).

Settings keys of interest to an MCP server (all read via a bare `QSettings settings;`):

* `elements-collections/common-collection-path` (`qetapp.cpp:604`)
* `elements-collections/custom-collection-path` (`qetapp.cpp:663`)
* `elements-collections/company-collection-path` (`qetapp.cpp:700`)
* `elements-collections/custom-tbt-path`, `.../company-tbt-path`, `.../macros-path`
* `lang`, `diagrameditor/*`, `elementeditor/*`, `<id>-recentfiles/fileN`

Each collection path uses the sentinel string `"default"` to mean "not
overridden"; a non-default value is used only if the directory actually exists
(`qetapp.cpp:608-616`).

### 4.3 Directory resolution summary

| Accessor | Default | Override |
|---|---|---|
| `commonElementsDir()` `qetapp.cpp:592` | Setting, else `--common-elements-dir=`, else compile-time `QET_COMMON_COLLECTION_PATH`, else `<applicationDirPath>/elements` | `QET_ALLOW_OVERRIDE_CED_OPTION` |
| `customElementsDir()` `qetapp.cpp:656` | Setting, else `<dataDir>/elements/` | — |
| `companyElementsDir()` `qetapp.cpp:693` | Setting, else `<dataDir>/elements-company/` | — |
| `userMacrosDir()` `qetapp.cpp:885` | Setting, else `<dataDir>/macros/` | — |
| `configDir()` `qetapp.cpp:933` | `AppConfigLocation` | `--config-dir=` |
| `dataDir()` `qetapp.cpp:960` | `AppDataLocation` | `--data-dir=` |
| Elements cache DB | `<dataDir>/elements_cache.sqlite` | `qetapp.cpp:137` |
| Crash-recovery autosave (no-KF build) | `<AppDataLocation>/autosave/` | `ui/nokde/kautosavefile.cpp:32-44` |

`*DirN()` variants return the same path without the trailing `/`
(`qetapp.cpp:730`, `:742`, `:754`). `resetCollectionsPath()` (`qetapp.cpp:760+`)
clears the memoised values when a setting changes.

---

## 5. Element cache — the stale-shadow trap

There are **two** independent element caches, and neither is invalidated by
file content changing.

### 5.1 `ElementsCollectionCache` — persistent, on disk

* Class doc: a SQLite cache "for data related to elements collections, mainly
  **names and pixmaps**", avoiding the cost of parsing XML and building full
  `CustomElement` objects when reloading the elements panel
  (`elementscollectioncache.h:25-29`).
* File: `<dataDir>/elements_cache.sqlite`, created once in `QETApp`'s
  constructor (`qetapp.cpp:136-140`). **It survives across runs.**
* PRAGMAs set at open: `temp_store=MEMORY`, `journal_mode=MEMORY`,
  `page_size=4096`, `cache_size=16384`, `locking_mode=EXCLUSIVE`,
  `synchronous=OFF` (`elementscollectioncache.cpp:48-53`).
* Schema (`elementscollectioncache.cpp:59-73`):
  * `names(path VARCHAR(512), locale VARCHAR(2), uuid VARCHAR(512), name VARCHAR(128), PRIMARY KEY(path, locale))`
  * `pixmaps(path VARCHAR(512) UNIQUE, uuid VARCHAR(512), pixmap BLOB, PRIMARY KEY(path), FOREIGN KEY(path) REFERENCES names(path) ON DELETE CASCADE)`
* Prepared statements (`elementscollectioncache.cpp:80-83`):
  * `SELECT name FROM names WHERE path = :path AND locale = :locale AND uuid = :uuid`
  * `SELECT pixmap FROM pixmaps WHERE path = :path AND uuid = :uuid`
  * `REPLACE INTO names …` / `REPLACE INTO pixmaps …`
* `fetchElement()` (`elementscollectioncache.cpp:147-174`): the cache is used
  only when the DB is open **and** the location is not inside a project
  (`!location.isProject()`) — embedded project elements are always re-parsed.
  On a hit for both name and pixmap it returns immediately; otherwise it calls
  `fetchData()` (which builds a real `Element` through `ElementFactory`) and
  `REPLACE`s both rows.
* Pixmaps are stored as `PNG` by default (`elementscollectioncache.cpp:36`),
  configurable via `setPixmapStorageFormat()`.

**The key is `(path, uuid)` — there is no mtime, no size, no content hash.**
`ElementsLocation::uuid()` reads the `<uuid uuid="…">` child of the `.elmt`
document element and returns a null `QUuid` if absent
(`ElementsCollection/elementslocation.cpp:835-846`).

Consequences for a scaffold workflow that writes `.elmt` files by hand:

1. **Editing an `.elmt` in place while keeping its `<uuid>` unchanged leaves the
   cached name and icon stale — permanently, across restarts.** The `SELECT`
   still matches on `(path, uuid, locale)`, returns the old row, and the file is
   never re-read. There is no `DELETE FROM names` or `DELETE FROM pixmaps`
   anywhere in the codebase (verified by grep) — nothing ever evicts an entry.
2. **Changing the `<uuid>` does invalidate it.** The `SELECT` misses, `fetchData()`
   re-parses the file, and `REPLACE INTO` overwrites the row (both tables are
   keyed on `path`, so no duplicate accumulates). **[inference] Therefore: a
   generator should mint a fresh UUID on every meaningful content change of an
   `.elmt`, which both fixes the cache and is semantically correct.**
3. An element with **no** `<uuid>` element caches under the string form of a
   null `QUuid` and is equally stale-prone.
4. Deleting `<dataDir>/elements_cache.sqlite` while QET is closed is a safe
   manual reset. **[inference]** — the file is recreated on next start; the
   `CREATE TABLE` calls are unconditional and their failure on an existing DB is
   an acknowledged open `@TODO` (`elementscollectioncache.cpp:55-58`).

### 5.2 `ElementPictureFactory` — in-process, keyed on UUID **only**

`sources/factory/elementpicturefactory.*` is a process-lifetime singleton
holding four hashes, all keyed on `QUuid` with **no path component**
(`elementpicturefactory.h:105-109`):

```
QHash<QUuid, QPicture>   m_pictures_H;
QHash<QUuid, QPicture>   m_low_pictures_H;
QHash<QUuid, QPixmap>    m_pixmap_H;
QHash<QUuid, primitives> m_primitives_H;
```

`getPictures()` (`elementpicturefactory.cpp:47-72`), `pixmap()`
(`:80-121`) and `getPrimitives()` (`:128-137`) all look up by
`location.uuid()` before touching the file.

**Two distinct `.elmt` files that share a UUID render as the same drawing.**
This is a real hazard for a generator that scaffolds new elements by copying a
template file: unless the `<uuid>` is regenerated, every copy shows the
template's geometry. `getPictures()` has a special case — if the uuid is null it
skips the cache entirely and builds fresh each time (`elementpicturefactory.cpp:53-57`)
— so a *missing* uuid is safer than a *duplicated* one for rendering, but worse
for the SQLite cache in §5.1.

The factory is dropped only in `QETApp`'s destructor
(`qetapp.cpp:183-186`, alongside `ElementFactory::dropInstance()`), i.e. at
process exit.

### 5.3 The panel "reload" action does not clear either cache

`ElementsCollectionWidget::reload()` (`ElementsCollection/elementscollectionwidget.cpp:802+`,
bound to a toolbar/context-menu action at `:160,251,376`) rebuilds a fresh
`ElementsCollectionModel` and re-walks the directories, but calls neither
`ElementPictureFactory::dropInstance()` nor any SQLite eviction.

**Net result for the MCP scaffold workflow:** after writing a new or edited
`.elmt` on disk, the reliable way to see it correctly in a running QET is to
(a) give it a fresh `<uuid>`, and, if the file previously existed with the same
uuid, (b) restart QET and, if the icon is still wrong, delete
`<dataDir>/elements_cache.sqlite`. **[inference]** — this sequence follows from
§5.1/§5.2; the codebase documents no supported invalidation path.

---

## 6. Build system reference

Two parallel build systems are maintained: **CMake** (primary, what CI uses) and
**qmake** (`qelectrotech.pro`, still functional, what `INSTALL` documents).

### 6.1 CMake top level (`CMakeLists.txt`, 333 lines)

* `cmake_minimum_required(VERSION 3.5...4.2)` (`CMakeLists.txt:19`).
* `project(qelectrotech VERSION 0.100.1 …  LANGUAGES C CXX)` (`CMakeLists.txt:21-25`).
  **Note the mismatch:** `QetVersion::currentVersion()` returns `0.200.1`
  (`qetversion.cpp:26`) while the CMake project version says `0.100.1`. The
  runtime/XML `version` attribute comes from `QetVersion`, not from CMake.
* C++ standard: **17**, required (`CMakeLists.txt:64-65`). `AUTOMOC`, `AUTORCC`,
  `AUTOUIC` all ON (`:61-63`); `CMAKE_AUTOUIC_SEARCH_PATHS` = `sources/ui` (`:104`).
* Include order (`CMakeLists.txt:17,27,51-58,111,121`):
  `hoto_update_cmake_message` → `copyright_message` → `paths_compilation_installation`
  → `start_options` → `developer_options` → `git_update_submodules` →
  `git_last_commit_sha` → `fetch_singleapplication` → `fetch_pugixml` →
  `qet_compilation_vars` → `fetch_kdeaddons` → (`tests`) → `define_definitions`.
* On Windows the executable is `add_executable(... WIN32 ...)` to get
  `/SUBSYSTEM:WINDOWS` and suppress the console window (`CMakeLists.txt:126-134`).

### 6.2 Every CMake option

| Option | Default | Defined at | Effect |
|---|---|---|---|
| `QT_VERSION_MAJOR` | **5** | `CMakeLists.txt:38-40` | Chooses the Qt major version. Not an `option()` — a plain cache-less variable, set with `-DQT_VERSION_MAJOR=6`. Must be set before `add_subdirectory(tests)` and the `fetch_*` includes so every subproject agrees. Also forces `QT_DEFAULT_MAJOR_VERSION` into the cache (`:49`) because FetchContent'd projects like SingleApplication follow *that* convention and would otherwise silently pick Qt5, breaking AUTOMOC with an `INTERFACE_QT_MAJOR_VERSION` mismatch. |
| `PACKAGE_TESTS` | **ON** | `CMakeLists.txt:114` | Adds `add_subdirectory(tests)`. CI turns this **OFF** for both Windows jobs. |
| `BUILD_WITH_KF` | **ON** | `cmake/developer_options.cmake:38` | Build against KDE Frameworks (`KCoreAddons`, `KWidgetsAddons`). When **OFF**: `define_definitions.cmake:68` adds `-DBUILD_WITHOUT_KF`; `CMakeLists.txt:305-311` adds `sources/ui/nokde` to the include path; `qet_compilation_vars.cmake:806-815` appends the bundled fallbacks `kautosavefile.{cpp,h}`, `kcolorbutton.{cpp,h}`, `kcolorcombo.{cpp,h}`. The `BUILD_WITHOUT_KF` macro is consumed at 16 sites across `sources/editor/ui/*`, `qetproject.h:32`, `qetapp.cpp:53`, `qetdiagrameditor.cpp:60`. |
| `BUILD_KF` | **YES** | `cmake/fetch_kdeaddons.cmake:23` | Only meaningful when `BUILD_WITH_KF=ON`. YES → FetchContent-clone `extra-cmake-modules`, `kcoreaddons`, `kwidgetsaddons` from invent.kde.org at tag `KF_GIT_TAG`. NO → `find_package(KF<N>CoreAddons/WidgetsAddons REQUIRED)` against system packages. **CI passes `-DBUILD_KF=OFF` on Windows** (system MSYS2 packages). |
| `KF_GIT_TAG` | `v5.77.0` (KF5) / `v6.10.0` (KF6) | `cmake/fetch_kdeaddons.cmake:30,35` | Tag used for the three KDE clones. `KF_MAJOR_VERSION` is derived from `QT_VERSION_MAJOR` (`CMakeLists.txt:106-110`) — 6 for Qt6, else 5 — with no independent choice. |
| `BUILD_PUGIXML` | **YES** | `cmake/fetch_pugixml.cmake:21` | YES → FetchContent pugixml **v1.15** from github.com/zeux/pugixml. NO → `find_package(pugixml REQUIRED)`. |
| `QET_ENABLE_PCH` | **OFF** | `cmake/developer_options.cmake:52` | Precompiled headers for `QtCore`/`QtGui`/`QtWidgets`/`QtXml`. Needs CMake ≥ 3.16 (warns and continues otherwise, `CMakeLists.txt:242-245`). The rationale block at `developer_options.cmake:40-51` measures ~4.1 s → ~1.2 s per TU. Deliberately off by default because a PCH satisfies `#include`s a file forgot to make itself, so code written with it on can fail to compile for everyone else. The generator expressions guarding it are load-bearing: the same target compiles 18 C files (`sources/import/edz/lzma/*.c`) and an unguarded PCH list would feed Qt headers to the C compiler. |
| `QET_EXPORT_PROJECT_DB` | **OFF** | `cmake/start_options.cmake:32` | Adds `-DQET_EXPORT_PROJECT_DB`, enabling project-database export. CI passes `=ON` on Windows. (qmake enables it unconditionally, `qelectrotech.pro:68`.) |

Non-option `add_definitions` set unconditionally:

| Define | Where | Meaning |
|---|---|---|
| `QET_ALLOW_OVERRIDE_CED_OPTION` | `start_options.cmake:20` | enables `--common-elements-dir` |
| `QET_ALLOW_OVERRIDE_CTBTD_OPTION` | `start_options.cmake:23` | enables `--common-tbt-dir` |
| `QET_ALLOW_OVERRIDE_CD_OPTION` | `start_options.cmake:26` | enables `--config-dir` |
| `QET_ALLOW_OVERRIDE_DD_OPTION` | `start_options.cmake:29` | enables `--data-dir` |
| `QT_DEPRECATED_WARNINGS` | `developer_options.cmake:20` | warn on deprecated Qt API |
| `QT_MESSAGELOGCONTEXT` | `developer_options.cmake:28` | keep function names/line numbers in release builds (needed by `QetLogger`'s formatter) |
| `GIT_COMMIT_SHA="…"` | `git_last_commit_sha.cmake:41` | HEAD sha; embedded in the About box and the diagnostics report header (`qetlogger.cpp:~390`). Empty when not a git checkout. Note `git_last_commit_sha.cmake:31-37` makes a **failed** `git rev-parse` a `FATAL_ERROR`. |
| `QET_COMMON_COLLECTION_PATH`, `QET_COMMON_TBT_PATH`, `QET_LANG_PATH`, `QET_EXAMPLES_PATH` | `define_definitions.cmake:29,33,40,45` | Compile-time install paths, prefixed with `INSTALL_PREFIX`. `QET_EXAMPLES_PATH` is skipped under MINGW (`:42-47`). |
| `BUILD_WITHOUT_KF` | `define_definitions.cmake:68` | only when `BUILD_WITH_KF=OFF` |
| `QAPPLICATION_CLASS=QApplication` | `fetch_singleapplication.cmake:22` (as a CMake var consumed by SingleApplication) | SingleApplication base class |

### 6.3 Install path variables (`cmake/paths_compilation_installation.cmake`)

| Variable | UNIX (not Apple) | Windows | macOS |
|---|---|---|---|
| `INSTALL_PREFIX` | `${CMAKE_INSTALL_PREFIX}/` | `./` | `/usr/local/` |
| `QET_BINARY_PATH` | `bin/` | `./` | `bin/` |
| `QET_COMMON_COLLECTION_PATH` | `share/qelectrotech/elements/` | `elements/` | `../Resources/elements/` |
| `QET_COMMON_TBT_PATH` | `share/qelectrotech/titleblocks/` | `titleblocks/` | `../Resources/titleblocks/` |
| `QET_LANG_PATH` | `share/qelectrotech/lang/` | `lang/` | `../Resources/lang/` |
| `QET_EXAMPLES_PATH` | `share/qelectrotech/examples/` | — | `share/qelectrotech/examples/` |
| `QET_ICONS_PATH` | `share/icons/hicolor/` | — | `share/icons/hicolor/` |
| `QET_MIME_PACKAGE_PATH` | `share/mime/packages/` | — | — |
| `QET_APPDATA_PATH` | `share/appdata` | — | — |

The Windows `lang/` choice is deliberate and documented at
`paths_compilation_installation.cmake:61-64`: `lang/`, not `l10n/`, because that
is what the WiX packaging (`build-aux/windows/QElectroTech.wxs`) and the shortcuts'
`--lang-dir` argument use.

`install()` rules (`CMakeLists.txt:313-333`): the target always; under
**non-MINGW** additionally the breeze icon sets (16/22/32/48/64/128/256), the
`elements/`, `examples/` and `titleblocks/` trees, the licence/doc files, the
`.qm` translations, and under UNIX-not-Apple the `.desktop`, mime and appdata files.

### 6.4 Sources and translations (`cmake/qet_compilation_vars.cmake`, 850 lines)

* `QET_COMPONENTS` (`:26-34`): `LinguistTools PrintSupport Xml Svg Sql Network Widgets Concurrent`.
  **`GuiPrivate` is deliberately absent** — Qt6 only creates the target when the
  component is explicitly requested, while Qt5 has no such package at all, so
  requesting it here would break the entire Qt5 configure. It is requested
  separately under a `QT_VERSION_MAJOR >= 6` guard at `CMakeLists.txt:80-82`.
* `QET_PRIVATE_LIBRARIES` (`:36-46`): `Qt::PrintSupport Qt::Gui Qt::GuiPrivate
  Qt::Xml Qt::Svg Qt::Sql Qt::Network Qt::Widgets Qt::Concurrent`.
* `QET_RES_FILES` (`:48-115`): ~67 `.ui` files, listed explicitly.
* `QET_SRC_FILES` (`:116-804`): every `.cpp`/`.h` in the project, listed
  explicitly (unlike qmake, which globs). **A new source file must be added
  here by hand or it will not be compiled by the CMake build.**
* `TS_FILES` (`:817-850`): 32 translations —
  `ar ca cs da de el en es fi fr hr hu it ja mn nb nl nl_BE no pl pt pt_BR ro rs ru sk sl sr sv tr uk zh`.
* Translation handling is branched three ways for Qt6 (< 6.2, 6.2–6.6, ≥ 6.7)
  plus a Qt5 path (`CMakeLists.txt:155-227`). The default build only runs
  **lrelease**; refreshing `.ts` from sources is behind an explicit
  `update_translations` target, because running lupdate on every build rewrote
  tracked files and raced lrelease under parallelism ("Premature end of document",
  `CMakeLists.txt:145-150`).

### 6.5 Dependencies

| Dependency | How obtained | Version / notes |
|---|---|---|
| Qt 5 or Qt 6 | `find_package` | Components in §6.4. Qt6 additionally needs the **private GuiGui headers** (`Qt6::GuiPrivate`) for `QPdfEngine::drawHyperlink` used by `pdf_links.cpp`. `CMakeLists.txt:84-90` hard-fails with a message naming `qt6-base-private-dev` if the target is absent. `INSTALL:1-14` documents the same for Debian/Ubuntu (`qt6-base-private-dev`) and Fedora (`qt6-qtbase-private-devel`), noting the failure otherwise is a confusing generate-time "Imported target Qt6::GuiPrivate includes non-existent path". |
| SQLite3 | `find_package(SQLite3 REQUIRED)` (`CMakeLists.txt:92`) | An `ALIAS SQLite3::SQLite3 → SQLite::SQLite3` is added for CMake < 4.3 (`:100-102`). |
| pugixml | FetchContent **v1.15**, or system | `cmake/fetch_pugixml.cmake:28` |
| SingleApplication | FetchContent **v3.2.0**, or the in-tree `SingleApplication/` submodule when present (for offline distro builds with `FETCHCONTENT_FULLY_DISCONNECTED=ON`) | `cmake/fetch_singleapplication.cmake:26-37` |
| KF5/KF6 CoreAddons + WidgetsAddons | FetchContent at `KF_GIT_TAG`, or system, or replaced by `sources/ui/nokde/` | `cmake/fetch_kdeaddons.cmake` |
| Bundled LZMA (C) | in-tree `sources/import/edz/lzma/*.c` (18 files) | For the EPLAN `.edz` importer |
| CUPS (`cupsys-bsd`) | runtime, for printing on UNIX | `INSTALL:29` |

When FetchContent'ing KDE, `qet_make_kf_available()` sets
`KDE_SKIP_TEST_SETTINGS=ON`, `BUILD_TESTING=OFF` (to stop kcoreaddons' autotests
failing the configure), plus `BUILD_DESIGNERPLUGIN=OFF`, `KCOREADDONS_USE_QML=OFF`,
`BUILD_QCH=OFF`, `BUILD_SHARED_LIBS=OFF` — QET is plain QtWidgets with no QML and
would otherwise drag in `Qt6Qml` (`fetch_kdeaddons.cmake:40-79`).

`git_update_submodules.cmake` runs `git submodule update --init --recursive` at
configure time when `.git` exists, and makes a non-zero exit a `FATAL_ERROR`.

### 6.6 Known-good Windows / Qt6 / MinGW invocation

Taken verbatim from the shipped CI (`.github/workflows/windows-build.yml:457-472`),
running under MSYS2 UCRT64:

```
# Toolchain (pacman, from windows-build.yml:389-404):
#   mingw-w64-ucrt-x86_64-{gcc,cmake,ninja,ccache,pkg-config,nsis}
#   mingw-w64-ucrt-x86_64-{qt6-base,qt6-svg,qt6-tools,qt6-translations,qt6-pdf}
#   mingw-w64-ucrt-x86_64-{sqlite3,kwidgetsaddons,kcoreaddons,extra-cmake-modules,angleproject}

mkdir build && cd build
cmake -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/ucrt64 \
  -DQt6_DIR=/ucrt64/lib/cmake/Qt6 \
  -DQT_VERSION_MAJOR=6 \
  -DBUILD_WITH_KF=ON \
  -DBUILD_KF=OFF \
  -DPACKAGE_TESTS=OFF \
  -DCMAKE_POLICY_DEFAULT_CMP0077=NEW \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DQET_EXPORT_PROJECT_DB=ON \
  -DCMAKE_C_COMPILER_LAUNCHER=/ucrt64/bin/ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=/ucrt64/bin/ccache \
  -DSQLite3_INCLUDE_DIR=/ucrt64/include \
  -DSQLite3_LIBRARY=/ucrt64/lib/libsqlite3.dll.a \
  ..
ninja -j"$(nproc)"
```

Points worth carrying over:

* `-DBUILD_KF=OFF` with `-DBUILD_WITH_KF=ON` means "use the MSYS2 KF6 packages,
  don't clone KDE". If KF6 is unavailable, use `-DBUILD_WITH_KF=OFF` instead,
  which switches to the bundled `sources/ui/nokde/` fallbacks (§6.2) — this is
  the documented easiest route on Windows/MinGW (`qelectrotech.pro:249-253`).
* `-DPACKAGE_TESTS=OFF` avoids FetchContent'ing Catch2 and googletest.
* `CMAKE_POLICY_VERSION_MINIMUM=3.5` and `CMP0077=NEW` are needed because the
  FetchContent'd projects declare very old minimum CMake versions.
* SQLite is pointed at explicitly because `FindSQLite3` does not reliably find
  the MSYS2 import library.
* The Qt5 job (`windows-build.yml:110-125`) is the same shape with
  `-DQT_VERSION_MAJOR=5`, `-DQt5_DIR=/ucrt64/lib/cmake/Qt5` and
  `-DCMAKE_DISABLE_FIND_PACKAGE_Qt6=ON`, and additionally deletes
  `/ucrt64/lib/cmake/Qt6` to force the Qt5 path (`:92-97`).

### 6.7 The qmake build (`qelectrotech.pro`, 381 lines)

* Same four `QET_ALLOW_OVERRIDE_*` defines (`:54-64`), plus
  `QET_EXPORT_PROJECT_DB` **unconditionally** (`:68`) and
  `QAPPLICATION_CLASS=QApplication`, `QT_MESSAGELOGCONTEXT`, and a shelled-out
  `GIT_COMMIT_SHA` (`:81-83`).
* `.pri` includes: `PropertiesEditor`, `QetGraphicsItemModeler`,
  **`QPropertyUndoCommand`**, `SingleApplication`, `QWidgetAnimation` (`:75-79`).
* Uses `$$files(...)` globs for `HEADERS`/`SOURCES`/`FORMS` (`:132-247`) — no
  per-file list to maintain, in contrast to CMake.
* `QT += xml svg network sql widgets printsupport concurrent gui-private` (`:245`).
* `CONFIG += c++17 debug_and_release warn_on link_pkgconfig` (`:287`);
  `PKGCONFIG += sqlite3` (`:293`).
* **KF opt-out uses a different spelling than CMake:**
  `qmake CONFIG+=no_kf5` sets `DEFINES += BUILD_WITHOUT_KF5` (`:246-256`).
  **The C++ code only tests `BUILD_WITHOUT_KF` (16 sites, no `_5`), so the qmake
  no-KF path defines a macro nothing reads.** The include path and the extra
  `sources/ui/nokde/*` sources are still added, so it may still link, but any
  `#ifdef BUILD_WITHOUT_KF` block is compiled the *wrong* way. **UNVERIFIED:
  whether `CONFIG+=no_kf5` actually produces a working binary today; treat the
  qmake no-KF path as suspect and prefer CMake with `-DBUILD_WITH_KF=OFF`.**
* `INSTALL` (the file) still documents only the qmake Qt5 flow
  (`qmake && make && make install`) in 15 languages, with a Qt6/CMake preamble
  bolted on at the top (`INSTALL:1-14`).

---

## 7. Tests — what is covered and what is not

### 7.1 Layout

`tests/CMakeLists.txt` declares `project(unittests)` and adds four
subdirectories unconditionally (`tests/CMakeLists.txt:26-33`):

| Subdir | Target | Framework | Fetched from |
|---|---|---|---|
| `catch/` | `C_unittests` | Catch2 | github.com/catchorg/Catch2 **v2.13.10** (`tests/catch/CMakeLists.txt:71-76`) |
| `googletest/` | `G_unittests` | GoogleTest | github.com/google/googletest **v1.17.0** (`tests/googletest/CMakeLists.txt:64-69`) |
| `googlemock/` | `G_unitmocktests` | GoogleMock | same clone |
| `qttest/` | (project name) | QtTest | Qt's own `Test` component |

Each subdirectory re-includes `cmake/qet_compilation_vars.cmake`,
`fetch_kdeaddons.cmake`, `fetch_singleapplication.cmake` and `fetch_pugixml.cmake`
when invoked standalone.

### 7.2 What is actually tested

Only **three** test files contain real assertions, and one of them is not built.

| File | Content |
|---|---|
| `tests/catch/src/borderproperties_test.cpp` | 33 lines. Asserts the default-constructed `BorderProperties` field values (17 columns × 60.0, header 20.0; 8 rows × 80.0, header 20.0; both display flags true), that two default instances compare equal, and that `defaultProperties()` returns the same. |
| `tests/catch/src/kautosavefile_test.cpp` | The substantive test in the tree. Only compiled **when `BUILD_WITH_KF=OFF`** (`tests/catch/CMakeLists.txt:93-105`). Unix-only (`#ifndef Q_OS_UNIX → SUCCEED()`). Forks a child that opens a `KAutoSaveFile` for a managed file, writes a payload, then is killed, and verifies the parent finds the stale file and recovers the payload — i.e. it tests the crash-recovery autosave path of the no-KDE fallback. |
| `tests/catch/src/qet_test.cpp` | 15 lines testing `QET::stringToFileName` (`"test"`, `"t_est"`, `"t-est"`, `"te.st"` pass through; `"tesMt"`, `"te<st"`, `"té<st"` are transformed). **This file is NOT listed in `tests/catch/CMakeLists.txt`'s `add_executable` (lines 84-91) and appears nowhere else in `tests/` — it is dead code that is never compiled or run.** |

Everything else is scaffolding left by the Qt Creator wizards:

* `tests/catch/tst_My_test.cpp` — `TEST_CASE("My first test with Catch2"){ REQUIRE(0 == 0); }`
* `tests/googletest/tst_My_test.cpp` — `TEST(googletest, sample_test){ EXPECT_EQ(1,1); }`
* `tests/googlemock/tst_My_test.cpp` — `TEST(googlemocktest, sample_mock){ EXPECT_EQ(1,1); }`
* `tests/qttest/tst_mytest.cpp` — a `QObject` with empty `initTestCase`, `cleanupTestCase`, `test_case1`.

`enable_testing()` is called in all four subdirectories, but **`add_test()` is
called exactly once in the whole tree** — `tests/qttest/CMakeLists.txt:71`, for
the empty QtTest stub. So `ctest` runs one test, and that test asserts nothing;
the Catch2 and GoogleTest binaries must be executed by hand.

### 7.3 What is *not* tested — the risk surface for an MCP server

There is **no automated coverage at all** of:

* `qetxml.cpp` — none of the `property*` validators, `createXmlProperty`,
  `attribute()`, `validXmlProperty`, `penFromXml`/`brushFromXml`,
  `marginsFromXml`, `qGraphicsItemPos*Xml`, `boolFromString`.
* `qet.cpp` beyond `stringToFileName` (and even that test is not compiled):
  `attributeIsAnInteger`, `attributeIsAReal`, `writeXmlFile`, `writeToFile`,
  `escapeSpaces`/`splitWithSpaces`, `correctAngle`, `round`.
* Project/diagram/element XML round-tripping: `QETProject`, `Diagram`,
  `ElementScene`, `TitleBlockTemplate` — nothing.
* The undo system: not one `QUndoCommand` subclass is exercised.
* `ElementsCollectionCache`, `ElementPictureFactory`, `ElementFactory`.
* `QetLogger`, `LogRing`, `CrashHandler`, `EventLoopWatchdog`.
* `CLIExport` and every export back-end (DXF, PDF, CSV, JSON).

**Practical consequence:** an MCP server cannot lean on QET's test suite to
detect an XML regression. The closest thing to a validation oracle QET ships is
its own CLI (§7.4) — in particular `--check-elements` and `--resave`.

### 7.4 `CLIExport` as the validation oracle

`sources/cli_export.h:38-73` documents the full headless surface; the option
table is at `cli_export.cpp:67-78`. It is dispatched from `main()` **before**
`SingleApplication` is constructed (`main.cpp:120-132`), so it never talks to a
running instance, and it disables crash-recovery backups for the run
(`main.cpp:129`, because the async backup races process exit).

```
qelectrotech --export-pdf     <project.qet> <output.pdf>
qelectrotech --export-png     <project.qet> <output_dir>
qelectrotech --export-svg     <project.qet> <output_dir>
qelectrotech --export-cables  <project.qet> <output.csv>
qelectrotech --export-wires   <project.qet> <output.csv>
qelectrotech --export-bom     <project.qet> <output.csv>
qelectrotech --export-nets    <project.qet> <output.json>
qelectrotech --export-links   <project.qet> <output.csv>
qelectrotech --info           <project.qet> [output.json]
qelectrotech --check-elements <element.elmt | directory>
qelectrotech --resave         <project.qet> <output.qet>
qelectrotech --set-titleblock <project.qet> <output.qet> key=value...
```

The three most useful to an MCP server:

* **`--check-elements`** — validates one `.elmt` (or a whole directory) against
  the element schema. This is the direct answer to "did my generated element
  parse". Use it as a post-write gate.
* **`--resave`** — loads and rewrites the project XML, i.e. a round-trip
  integrity check. If `--resave` produces a file that differs semantically from
  the input, the generator wrote something QET does not fully understand.
  Combined with `QT_HASH_SEED=0` (set unconditionally at `main.cpp:93`
  specifically to make XML diffs stable) this is a usable regression harness.
* **`--info`** — structural JSON summary: per-page element/conductor counts and
  unconnected terminals. A cheap sanity check that a generated project has the
  topology intended.

`--set-titleblock` accepts the keys `title`, `author`, `date` (or `date=today`),
`plant`, `location`, `revision`, `version`, `filename`; any other key becomes a
custom title-block field.

**[inference] Recommended MCP write pipeline:** write XML → run
`--check-elements` (elements) or `--resave` + diff (projects) → only then hand
the file to the user. This substitutes for the test coverage that does not exist.
