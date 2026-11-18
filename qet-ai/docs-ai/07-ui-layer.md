# 07 — The QElectroTech GUI Layer

Scope: `sources/ui/` (101 `.cpp`/`.h` files + 32 `.ui` forms), the GUI shell of
`sources/editor/`, `sources/PropertiesEditor/`, `sources/QWidgetAnimation/`,
`sources/richtext/`, and the top-level window/dialog files
(`qetapp`, `qetmainwindow`, `qetdiagrameditor`, `editor/ui/qetelementeditor`,
`diagramview`, `configdialog`, `elementdialog`, `projectview`).

**Purpose of this document.** An MCP server built against QET will almost never
*call* this code. It exists to tell that server's author (a) what is here, so
identical-sounding class names are not confused with model classes, and (b)
exactly which call sites will block on a modal dialog, require a window system,
or dereference a GUI singleton that does not exist headlessly. Section 3 is the
one that matters operationally.

Source root for all citations: `/root/qet/qelectrotech-source-mirror/`.
Paths below are relative to that root.

---

## 0. The one-paragraph summary

QET is a classic Qt widget application with **no service layer**. There is no
headless API object; the "application" *is* `QETApp`, a `QObject` that in its
constructor parses argv, creates config directories, loads fonts, opens a
splash screen, installs a system-tray icon, builds an SQLite element cache and
constructs a `QETDiagramEditor` main window (`sources/qetapp.cpp:110`–`160`).
The only supported headless entry point is the `CLIExport` shim in
`sources/cli_export.cpp`, which is dispatched from `main()` **before** anything
else and never constructs `QETApp` at all (`sources/main.cpp:118`–`131`).
Everything else — including several functions that live in model files — will
open a modal dialog and block forever without a user.

---

## 1. Map of the UI layer

### 1.1 Top-level windows and views (not in `sources/ui/`)

| File | Class | Role |
|---|---|---|
| `sources/qetapp.cpp/.h` | `QETApp` | Application singleton. Owns collections, caches, recent-files, systray, splash, registered projects. See §2 and §4. |
| `sources/qetmainwindow.cpp/.h` | `QETMainWindow` | Base class for every top-level window. Supplies the shared Settings/Help menus, full-screen toggle, "What's this", drag-and-drop of `.qet`/`.elmt`/`.tbt` files (`sources/qetmainwindow.cpp:276`, `:289`). |
| `sources/qetdiagrameditor.cpp/.h` | `QETDiagramEditor` | The project/diagram editor main window. MDI area + 5 docks + ~70 `QAction`s. §2.2. |
| `sources/editor/ui/qetelementeditor.cpp/.h` | `QETElementEditor` | The element (`.elmt`) editor main window. §2.3. |
| `sources/titleblock/qettemplateeditor.cpp` | `QETTitleBlockTemplateEditor` | Third editor window kind (title-block templates). Out of scope here, but `QETApp` tracks it alongside the other two. |
| `sources/projectview.cpp/.h` | `ProjectView` | `QWidget` holding one `QETProject`: a `QTabWidget` of `DiagramView`s, save/saveAs/clean/export entry points. |
| `sources/diagramview.cpp/.h` | `DiagramView` | `QGraphicsView` over one `Diagram`. Mouse/keyboard/gesture handling, zoom, cut/copy/paste, context menu, drag-drop of elements and title blocks. |
| `sources/editor/elementview.cpp` | `ElementView` | `QGraphicsView` over one `ElementScene` (element editor canvas). |
| `sources/configdialog.cpp/.h` | `ConfigDialog` | Generic paged preferences dialog: icon list on the left, `QStackedWidget` of `ConfigPage`s on the right. Reused for *both* app preferences and project properties. |
| `sources/elementdialog.cpp/.h` | `ElementDialog` | Element/category picker over the collections tree. 5 modes (`OpenElement`, `SaveElement`, `OpenCategory`, `SaveCategory`, `SaveTemplate`), reached through the static helpers `getOpenElementLocation()` / `getSaveElementLocation()` / `getSaveTemplateLocation()` (`sources/elementdialog.cpp:315`, `:326`, `:337`). |
| `sources/exportdialog.cpp` | `ExportDialog` | GUI counterpart of `--export-png/svg` — folio picker + preview + `ExportPropertiesWidget`. |
| `sources/print/projectprintwindow.cpp` | `ProjectPrintWindow` | Print/PDF preview window; `launchDialog()` is the only supported entry (`sources/print/projectprintwindow.cpp:62`). |
| `sources/elementspanelwidget.cpp`, `sources/elementspanel.cpp`, `sources/genericpanel.cpp` | `ElementsPanelWidget`, `ElementsPanel`, `GenericPanel` | Legacy "Projects" dock tree (projects → folios → embedded collection). |
| `sources/ElementsCollection/elementscollectionwidget.cpp` | `ElementsCollectionWidget` | Modern "Collections" dock (common/company/custom collections, search field, context menu). |
| `sources/newelementwizard.cpp` | `NewElementWizard` | `QWizard` for creating a new element file. |
| `sources/elementscategoryeditor.cpp` | `ElementsCategoryEditor` | Rename/create a collection category. |

### 1.2 `sources/ui/` — functional clusters

**Cluster A — property *widgets* (embeddable, no `exec()` of their own).**
These derive from `PropertiesEditorWidget` or `AbstractElementPropertiesEditorWidget`
and follow the `apply()` / `reset()` / `associatedUndo()` contract
(`sources/PropertiesEditor/propertieseditorwidget.h:35`–`42`). They are the
reusable leaves that both the selection dock and the modal dialogs embed.

| File | Class | Purpose |
|---|---|---|
| `abstractelementpropertieseditorwidget` | `AbstractElementPropertiesEditorWidget` | Base for element-scoped property editors; holds a `QPointer<Element>`. |
| `borderpropertieswidget` | `BorderPropertiesWidget` | Edits `BorderProperties` (rows/columns count & size, header display). |
| `conductorpropertieswidget` | `ConductorPropertiesWidget` | Edits `ConductorProperties` (type, colour, section, formula, autonum combo). |
| `titleblockpropertieswidget` | `TitleBlockPropertiesWidget` | Edits `TitleBlockProperties` + picks a template from a `TitleBlockTemplatesCollection`. |
| `elementinfowidget` | `ElementInfoWidget` | Edits an element's `DiagramContext` (label, comment, manufacturer…). |
| `elementinfopartwidget` | `ElementInfoPartWidget` | One row of the above, bound to a fixed key. |
| `customelementinfopartwidget` | `CustomElementInfoPartWidget` | One user-defined key/value row; key validated by `DiagramContext::isKeyAcceptable()`. |
| `elementpropertieswidget` | `ElementPropertiesWidget` | Tab container: general / texts / master-slave / xref, per element type. |
| `dynamicelementtextitemeditor` | `DynamicElementTextItemEditor` | Tree editor for an element's dynamic texts and text groups. |
| `dynamicelementtextmodel` | `DynamicElementTextModel` | `QStandardItemModel` backing the above (+ `DynamicTextItemDelegate`). |
| `masterpropertieswidget` | `MasterPropertiesWidget` | Links one master element to N slaves. Builds the undo command itself. |
| `linksingleelementwidget` | `LinkSingleElementWidget` | Links a report/slave element to exactly one other element. |
| `plclinkwidget` | `PlcLinkWidget` | Links a PLC-slave to one IO entry of a PLC-master. |
| `reportpropertiewidget` | `ReportPropertieWidget` | Edits folio-report label format. |
| `xrefpropertieswidget` | `XRefPropertiesWidget` | Edits `XRefProperties` (cross-reference display style). |
| `shapegraphicsitempropertieswidget` | `ShapeGraphicsItemPropertiesWidget` | Edits a `QetShapeItem` (pen, brush, geometry). |
| `imagepropertieswidget` | `ImagePropertiesWidget` | Edits a `DiagramImageItem` (size, rotation). |
| `inditextpropertieswidget` | `IndiTextPropertiesWidget` | Edits one or several `IndependentTextItem`s. |
| `diagramcontextwidget` | `DiagramContextWidget` | Generic key/value table over a `DiagramContext`. |
| `configsaveloaderwidget` | `ConfigSaveLoaderWidget` | Named-config save/load group box (combo + load/save/delete). |
| `diagrameditorhandlersizewidget` | `DiagramEditorHandlerSizeWidget` | Combo controlling the `graphics_handler_size` dynamic property of the parent `QETDiagramEditor`. Self-wiring via `QETApp::instance()->diagramEditorAncestorOf(this)` (`sources/ui/diagrameditorhandlersizewidget.cpp:33`). |

**Cluster B — modal dialogs.** All of these call `exec()`; see §3.

| File | Class | Purpose |
|---|---|---|
| `aboutqetdialog` | `AboutQETDialog` | About box (version, authors, license, build info). |
| `diagrampropertiesdialog` | `DiagramPropertiesDialog` | Folio properties. **Calls `exec()` from its own constructor** (`sources/ui/diagrampropertiesdialog.cpp:93`). |
| `projectpropertiesdialog` | `ProjectPropertiesDialog` | Not a `QDialog` — a `QObject` wrapper that assembles a `ConfigDialog` of project pages (`sources/ui/projectpropertiesdialog.cpp:33`–`49`). |
| `conductorpropertiesdialog` | `ConductorPropertiesDialog` | Wraps `ConductorPropertiesWidget`; pushes the undo command on accept (`sources/ui/conductorpropertiesdialog.cpp:89`). |
| `potentialselectordialog` | `PotentialSelectorDialog` | Asks which of two colliding potentials' properties to keep when conductors are joined. |
| `multipastedialog` | `MultiPasteDialog` | Grid/repeat paste; serialises the selection through `Diagram::toXml`/`fromXml` (`sources/ui/multipastedialog.cpp:48`, `:89`). |
| `importelementdialog` | `ImportElementDialog` | "Element already exists in project" → Ignore / Erase / Rename. |
| `importelementtextpatterndialog` | `ImportElementTextPatternDialog` | Pick a saved element-text pattern (a `QInputDialog::getItem` clone + checkbox). |
| `compositetexteditdialog` | `CompositeTextEditDialog` | Edits the composite text of a dynamic element text field. |
| `formulaassistantdialog` | `FormulaAssistantDialog` | Autonumbering formula builder with variable insertion. |
| `alignmenttextdialog` | `AlignmentTextDialog` | Horizontal/vertical alignment picker for text parts. |
| `marginseditdialog` | `MarginsEditDialog` | Trivial `QMargins` editor. |
| `contactgroupselectiondialog` | `ContactGroupSelectionDialog` | Table of a master's slave contact groups; user picks one. |
| `jumptoelementdialog` | `JumpToElementDialog` | Transient "quick open" popup: live-filter elements on a folio by label, Enter selects and scrolls. |
| `terminalnumberingdialog` | `TerminalNumberingDialog` | Configures automatic terminal numbering; returns a `QUndoCommand` via `getUndoCommand(project)`. |
| `bomexportdialog` | `BOMExportDialog` | Bill-of-materials query builder; overrides `exec()` (`sources/ui/bomexportdialog.cpp:60`). |
| `diagramselection` | `diagramselection` (lowercase) | Folio multi-select table used by export/print flows. |
| `backupdialog` | `BackupDialog` | "Create a backup copy?" yes/no, shown on **every** project open. |
| `dialogwaiting` | `DialogWaiting` | Modeless progress dialog, a lazily-created **static singleton** (`instance()`/`hasInstance()`/`dropInstance()`, `sources/ui/dialogwaiting.h:31`–`61`). Pumps the event loop via `qApp->processEvents()` (`sources/ui/dialogwaiting.cpp:52`). |
| `thirdpartybinaryinstalldialog` | `ThirdPartyBinaryInstallDialog` | "Missing external binary" → opens a download URL / the install folder with `QDesktopServices` (`sources/ui/thirdpartybinaryinstalldialog.cpp:38`, `:44`). |

**Cluster C — docks.**

| File | Class | Purpose |
|---|---|---|
| `diagrampropertieseditordockwidget` | `DiagramPropertiesEditorDockWidget` | The right-hand "selection properties" dock. Tracks `Diagram::selectionChanged` and rebuilds its editor through `PropertiesEditorFactory::propertiesEditor()` (`sources/ui/diagrampropertieseditordockwidget.cpp:77`). |
| `PropertiesEditor/propertieseditordockwidget` | `PropertiesEditorDockWidget` | Its base: a `QDockWidget` holding a list of `PropertiesEditorWidget`s with shared apply/reset. |

**Cluster D — configuration pages (`sources/ui/configpage/`).**
All derive from `ConfigPage` (`sources/ui/configpage/configpage.h:27`), which
declares `applyConf()`, `title()`, `icon()`. They are added to a `ConfigDialog`.

| Class | File | Purpose |
|---|---|---|
| `GeneralConfigurationPage` | `generalconfigurationpage` | The big preferences page. `applyConf()` writes ~40 `QSettings` keys (`sources/ui/configpage/generalconfigurationpage.cpp:207`–`343`, `:434`). |
| `NewDiagramPage` | `configpages` | Defaults for new folios/projects (border, title block, conductor, guides). Doubles as a project page when constructed with a `QETProject`. |
| `ExportConfigPage`, `PrintConfigPage` | `configpages` | Default export and print properties. |
| `ShortcutsConfigPage` | `shortcutsconfigpage` | Lists every shortcut registered with `ShortcutManager`; persists only on `applyConf()`. |
| `GuidesPropertiesWidget` | `guidespropertieswidget` | Table of default folio guides, embedded in `NewDiagramPage`. |
| `ProjectConfigPage` (abstract), `ProjectMainConfigPage`, `ProjectAutoNumConfigPage` | `projectconfigpages` | Project-scoped pages. `ProjectConfigPage::applyConf()` short-circuits on read-only projects (`sources/ui/configpage/projectconfigpages.cpp:90`). |

**Cluster E — vendored / third-party (`sources/ui/nokde/`).**

| File | Class | Purpose |
|---|---|---|
| `kautosavefile` | `KAutoSaveFile` | KDE's crash-recovery temp file, vendored for `BUILD_WITHOUT_KF` builds. `allStaleFiles()` drives the recovery prompt. |
| `kcolorbutton`, `kcolorcombo` | `KColorButton`, `KColorCombo` | Colour pickers. |

### 1.3 The element-editor GUI shell (`sources/editor/ui/`, `sources/editor/`)

The part/XML classes (`sources/editor/graphicspart/`) are covered elsewhere.
The GUI shell is:

| File | Class | Purpose |
|---|---|---|
| `editor/ui/qetelementeditor` | `QETElementEditor` | Main window. §2.3. |
| `editor/ui/{line,rectangle,ellipse,polygon,terminal,text,dynamictextfield}editor` | `*Editor` | One property panel per primitive kind, all deriving from `ElementItemEditor`. Each pushes `QPropertyUndoCommand`s onto the scene's stack (e.g. `sources/editor/ui/terminaleditor.cpp:218`ff). |
| `editor/ui/elementpropertieseditorwidget` | `ElementPropertiesEditorWidget` | Element-level metadata (type, kind, PLC table, slave contact groups). |
| `editor/elementitemeditor` | `ElementItemEditor` | Base class: gives every panel access to the `ElementScene` and its `QUndoStack`. |
| `editor/elementscene` | `ElementScene` | `QGraphicsScene` for the element. **Model + GUI mixed**: `toXml()`/`fromXml()` are the real serialisation API, but the same class opens dialogs (`sources/editor/elementscene.cpp:912`, `:930`, `:992`). |
| `editor/elementview` | `ElementView` | The canvas view; clipboard paste (`sources/editor/elementview.cpp:215`, `:240`, `:262`). |
| `editor/elementprimitivedecorator` | `ElementPrimitiveDecorator` | The selection handles/rubber-band decorator. |
| `editor/styleeditor`, `editor/arceditor` | — | Style panel; arc-specific panel. |
| `editor/esevent/*` | `ESEventAdd*` | State objects implementing "click to place a line / rect / terminal / text…". Pure GUI event machines. |
| `editor/UndoCommand/*` | `AddPartCommand`, `DeletePartsCommand`, `PastePartsCommand`, `OpenElmtCommand` | Element-editor undo commands — these *are* the model-mutating API. |

### 1.4 Small support libraries

| Directory | Contents |
|---|---|
| `sources/PropertiesEditor/` | `PropertiesEditorWidget` (interface), `PropertiesEditorDialog` (a header-only template that wraps *any* widget exposing `title()`/`apply()`/`reset()` into an Apply/Cancel/Reset dialog, `sources/PropertiesEditor/propertieseditordialog.h:42`), `PropertiesEditorDockWidget`. |
| `sources/QWidgetAnimation/` | `QWidgetAnimation` — a `QPropertyAnimation` that animates a widget's `maximumWidth`/`maximumHeight` for slide-in/out panels. Used for the search-and-replace panel (`sources/qetdiagrameditor.cpp:99`). Three sizing behaviours: `minimumSizeHint`, `availableSpace`, `lastSize`. |
| `sources/richtext/` | Qt Designer's rich-text editor, vendored verbatim under `namespace qdesigner_internal`. Only consumer is `DiagramTextItem::edit()` (`sources/qetgraphicsitem/diagramtextitem.cpp:484`–`493`). |

---

## 2. The main windows

### 2.1 `QETApp` (`sources/qetapp.cpp`)

`QETApp` is **not** a `QApplication` subclass — it is a plain `QObject`
(`sources/qetapp.h:54`) that sits beside the real `SingleApplication`/`QApplication`
created in `main()`. It is a de-facto singleton: the constructor assigns
`m_qetapp = this` (`sources/qetapp.cpp:113`) and `QETApp::instance()` returns it
(`sources/qetapp.cpp:195`).

What it owns (all `static`, all file-scope in `sources/qetapp.cpp:60`–`101`):

- `collections_cache_` — `ElementsCollectionCache*`, the SQLite element name/pixmap cache.
- `m_common_tbt_collection`, `m_company_tbt_collection`, `m_custom_tbt_collection` — title-block template collections, lazily created (`:446`, `:467`, `:488`).
- `registered_projects_` — `QMap<uint, QETProject*>`, the global open-project registry, plus `next_project_id`.
- `m_projects_recent_files`, `m_elements_recent_files` — `RecentFiles*`.
- `default_titleblock_template_` — lazily loaded from `:/titleblocks/default.titleblock` (`:1576`).
- Resolved collection/config/data directory paths (`m_common_element_dir` etc.).
- Non-static GUI state: splash screen, systray icon + menu, ~12 `QAction`s.

Startup sequence, in constructor order (`sources/qetapp.cpp:110`–`160`):

1. `m_qetapp = this`.
2. `parseArguments()` (`:115`, body at `:2140`) — reads `qApp->arguments()`, builds a `QETArguments`, applies `--common-elements-dir` / `--config-dir` / `--data-dir` / `--lang-dir` overrides, and sets `non_interactive_execution_` for `--help` / `--version` / `--license`.
3. If non-interactive → `std::exit(EXIT_SUCCESS)` immediately (`:117`).
4. `initConfiguration()` (`:119`, body `:2310`) — `mkpath`s config dir, data dir, custom/company element dirs, custom/company title-block dirs, macros dir; then constructs the two `RecentFiles` objects (which internally build `QMenu`s).
5. `initLanguage()` (`:120`) → `setLanguage(langFromSetting())` — installs `QTranslator`s and may call `switchLayout()`.
6. `QET::Icons::initIcons()` (`:121`) — populates ~350 global `QIcon`s from the Qt resource system; calls `QApplication::isRightToLeft()` (`sources/qeticons.cpp:382`).
7. `initFonts()` (`:122`, body `:2243`) — `QFontDatabase::addApplicationFont()` for 12 Liberation faces + 2 osifont faces.
8. `initStyle()` (`:123`, body `:2287`) — snapshots `qApp->palette()`, then applies `usesystemcolors` from `QSettings`.
9. `initSplashScreen()` (`:124`, body `:2201`) — `new QSplashScreen(...)`, `show()`.
10. `initSystemTray()` (`:125`, body `:2364`) — builds the tray menu and `QSystemTrayIcon::show()`.
11. `qApp->setQuitOnLastWindowClosed(false)` (`:129`) — QET keeps running with no windows, living in the tray.
12. Creates `ElementsCollectionCache` at `dataDir()/elements_cache.sqlite` (`:137`–`140`).
13. Either `new QETDiagramEditor()` (no files given, `:147`) or `openFiles(qet_arguments_)` (`:152`).
14. `buildSystemTrayMenu()` (`:155`), hide splash, `checkBackupFiles()` (`:160`).

### 2.2 `QETDiagramEditor` (`sources/qetdiagrameditor.cpp:72`)

Owns:

- `QMdiArea m_workspace` — one `QMdiSubWindow` per `ProjectView`; tabbed or windowed per the `diagrameditor/viewmode` setting.
- Five docks: "Projets" (`ElementsPanelWidget`, `setUpElementsPanel()` `:159`), "Collections" (`ElementsCollectionWidget`, `:195`), "Annulations" (`QUndoView`, `:220`), selection properties (`DiagramPropertiesEditorDockWidget`, `:246`), autonumbering (`AutoNumberingDockWidget`, `:256`).
- `QUndoGroup undo_group` — the per-window active undo stack; each `QETProject` contributes its own `QUndoStack`.
- `SearchAndReplaceWidget m_search_and_replace_widget`, animated by a `QWidgetAnimation` (`:99`).
- Five `QActionGroup`s and ~70 `QAction`s, every one registered with `ShortcutManager::instance().registerAction(...)`.

Constructor order (`:72`–`149`): splitter + MDI area → window title/icon/status bar
→ the five `setUp*` dock/stack builders → `setUpActions()` / `setUpToolBar()` /
`setUpMenu()` → `setWindowState(Qt::WindowMaximized)` → clipboard connection →
`readSettings()` (`:135`) → `show()` (`:136`) → open any files passed in.

`closeEvent` (`:948`) asks each `ProjectView` to close, then `writeSettings()`
and `setAttribute(Qt::WA_DeleteOnClose)`.

### 2.3 `QETElementEditor` (`sources/editor/ui/qetelementeditor.cpp:64`)

Owns one `ElementScene` (`m_elmt_scene`), one `ElementView`, a list of
`ElementItemEditor` panels (`m_editors`, deleted in the dtor `:91`), and a
`.ui`-generated action set. Constructor: `ui->setupUi(this)` → `initGui()` →
`setupActions()` → `setupConnection()` → build the tear-off "display" menu →
`setWindowState(Qt::WindowMaximized)` → `readSettings()` → `show()` (`:68`–`82`).

Its load/save surface is the boundary described in §5:
`fromFile` (`:209`), `toFile` (`:270`), `fromLocation` (`:292`), `toLocation` (`:337`).

---

## 3. GUI-only dependencies — what must never run headless

> Rule of thumb for an MCP server: **anything that reaches a `QDialog::exec()`,
> a `QMessageBox`, a `QFileDialog`, `QApplication::clipboard()`, a
> `QGraphicsScene::views()` dereference, or `QETApp::instance()` is off-limits.**
> The dangerous part is that several such call sites live in files that look
> like model code.

### 3.1 Hard blocker: `QApplication` itself needs a platform plugin

Even the supported headless path constructs a **`QApplication`**, not a
`QCoreApplication`: `sources/main.cpp:125`. On Linux this aborts with
"could not connect to display" unless `QT_QPA_PLATFORM=offscreen` (or `minimal`)
is exported, or the process runs under Xvfb. Nothing in the tree sets that
variable — grep for `QT_QPA_PLATFORM` across `sources/` returns nothing.
**An MCP server shelling out to `qelectrotech --export-*` must set
`QT_QPA_PLATFORM=offscreen` itself.**

### 3.2 Modal dialogs reached from *model* code (highest risk)

These are the traps. Each is invoked from a class an automation author would
reasonably assume is headless-safe.

| Call site | Trigger | Consequence headless |
|---|---|---|
| `sources/qetproject.cpp:1218`–`1219` — `ImportElementDialog ied; ied.exec()` | `QETProject::importElement()` when an element of the same path but a different UUID already exists in the embedded collection. | Blocks forever. |
| `sources/qetproject.cpp:1231`–`1240` — `QMessageBox::warning(nullptr, ...)` | Same function, `QET::Erase` branch, when the new element defines slave contact groups. | Blocks forever. |
| `sources/qetproject.cpp:1470` — `QET::QetMessageBox::warning(nullptr, ...)` | `QETProject::readProjectXml()` when the file's `version` attribute is **newer** than the running build. | **Blocks during plain project loading**, including the `--export-*` CLI path (`sources/cli_export.cpp:803` constructs `QETProject project(input)`). |
| `sources/qetproject.cpp:1497` — `QET::QetMessageBox::warning(nullptr, ...)` | Same function, when the project was written by QET ≤ 0.6. | Same: blocks during CLI load of an old project. |
| `sources/conductorautonumerotation.cpp:219`–`223` — `PotentialSelectorDialog psd(...); psd.exec()` | `ConductorAutoNumerotation::applyText()` when the conductors of a potential do not all carry the same text/formula. | Blocks. Reached from ordinary conductor creation. |
| `sources/undocommand/linkelementcommand.cpp:341`–`342` — `PotentialSelectorDialog psd(...); psd.exec()` | `LinkElementCommand::redo()` on the first redo, when the linked potentials disagree. | Blocks — **inside an undo command's `redo()`**. |
| `sources/qetgraphicsitem/element.cpp:182`–`197` — `PropertiesEditorDialog dialog(epw, QApplication::activeWindow()); dialog.exec()` | `Element::editProperty()`. | Blocks; also `QApplication::activeWindow()` is null headless. |
| `sources/qetgraphicsitem/qetshapeitem.cpp:977`–`982` — `PropertiesEditorDialog ped(..., diagram()->views().at(0)); ped.exec()` | `QetShapeItem::editProperty()`. | **Crashes before blocking**: `views().at(0)` on an empty list is UB/assert when no `DiagramView` exists. |
| `sources/qetgraphicsitem/diagramimageitem.cpp:92` — `dialog.exec()` | `DiagramImageItem::editProperty()`. | Blocks. |
| `sources/qetgraphicsitem/diagramtextitem.cpp:484`–`493` — `qdesigner_internal::RichTextEditorDialog editor(parent); editor.exec()` | `DiagramTextItem::edit()`. | Blocks. |
| `sources/qetgraphicsitem/ViewItem/qetgraphicstableitem.cpp:122` — `QMessageBox::information(...)` | Table row-limit warning. | Blocks. |
| `sources/diagramevent/diagrameventaddimage.cpp:160`, `:167` — `QFileDialog::getOpenFileName`, `QMessageBox::critical` | Placing an image on a folio. | Blocks. |
| `sources/dataBase/projectdatabase.cpp:948` — `QFileDialog::getSaveFileName(parent, ...)` | Exporting the internal project SQLite DB. | Blocks. |
| `sources/conductornumexport.cpp:57`, `:66` — `QFileDialog::getSaveFileName`, `QMessageBox::critical` | Conductor-number CSV export. | Blocks. |
| `sources/wiringlistexport.cpp:161`–`177` — `QFileDialog` + three `QMessageBox`es | Wiring-list export. | Blocks. Note `CLIExport` deliberately reimplements this rather than calling it. |
| `sources/createdxf.cpp:54`, `:245`, `:280`, `:328`, `:653`, `:709`, `:762`, `:843` — `errorFileOpen.exec()` | Any file-open failure inside DXF creation. | Blocks on the *error path*, which is the worst case for automation. |
| `sources/dxf/dxftoelmt.cpp:61`, `:113` — `msgBox.exec()`, `dialog_.exec()` | DXF → element import. | Blocks. |
| `sources/factory/qetgraphicstablefactory.cpp:50`, `:69` — `d->exec()` | Creating a nomenclature/summary table item. | Blocks. |
| `sources/elementtextpattern.cpp:64`, `:144` — `QMessageBox::question`, `::information` | Saving/loading an element text pattern. | Blocks. |
| `sources/undocommand/rotatetextscommand.cpp:132` — `ori_text_dialog.exec()` | Rotating texts to a chosen angle. | Blocks — again inside an undo command. |

### 3.3 Dialogs that are unavoidable on the *normal GUI* project-open path

`QETDiagramEditor::openAndAddProject()` (`sources/qetdiagrameditor.cpp:1128`) is
saturated with them and can never be reused headlessly:

- `QET::QetMessageBox::critical` if the file is missing (`:1161`) or unreadable (`:1177`).
- `QET::QetMessageBox::warning` if the file is not writable (`:1192`).
- `DialogWaiting::instance(this)` (`:1203`) — creates the modeless progress dialog **and pumps the event loop** during the load (see the comment at `:1206`–`1209`).
- `QET::QetMessageBox::warning` on parse failure (`:1218`).
- `QET::QetMessageBox::information` if any font description had to be salvaged (`:1265`).
- `BackupDialog backup_dialog(this); backup_dialog.exec()` (`:1274`–`1275`) — **shown on every successful open**.

`QETApp::checkBackupFiles()` (`sources/qetapp.cpp:2554`) runs at the end of the
`QETApp` constructor and pops `QET::QetMessageBox::question` whenever a stale
`KAutoSaveFile` exists (`:2604`); if none exists it calls `checkCrashDump()`
(`:2643`), which `exec()`s a `DiagnosticsReportDialog` (`:2658`).

Mitigating detail: `QETProject` guards its own progress reporting with
`DialogWaiting::hasInstance()` (`sources/qetproject.cpp:287`, `:1595`), so the
model itself does **not** create the dialog — only the editor does. That is why
`CLIExport` can load projects at all.

### 3.4 Constructors that block

Two classes call `exec()` from inside their own constructor, so merely
constructing them hangs:

- `DiagramPropertiesDialog::DiagramPropertiesDialog` — `if (this->exec() == QDialog::Accepted ...)` at `sources/ui/diagrampropertiesdialog.cpp:93`. The static helper `diagramPropertiesDialog()` (`:130`) does nothing but construct one.
- `ElementDialog::execConfiguredDialog` (`sources/elementdialog.cpp:344`–`352`) is a static that news, `exec()`s and deletes — the three `get*Location()` helpers all funnel through it.

### 3.5 `QETApp::instance()` dereferences (null without a GUI)

`QETApp::instance()` returns `m_qetapp`, which is only assigned in the
constructor. Under `CLIExport` it is **null**. Call sites that dereference it
without a check:

`sources/editor/ui/qetelementeditor.cpp:880`, `:1346`, `:1591`;
`sources/titleblock/qettemplateeditor.cpp:828`, `:858`;
`sources/ui/elementpropertieswidget.cpp:251`;
`sources/ui/diagrameditorhandlersizewidget.cpp:33`, `:53`;
`sources/ui/titleblockpropertieswidget.cpp:410`, `:415`;
`sources/ui/configpage/generalconfigurationpage.cpp:209`;
`sources/elementspanelwidget.cpp:127`, `:418`, `:431`;
`sources/ElementsCollection/elementscollectionwidget.cpp:423`, `:607`;
`sources/utils/qetutils.cpp:76`; `sources/qetmainwindow.cpp:58`, `:143`, `:293`.

All are GUI files — no model file dereferences `instance()`. **[inference]** This
is why `CLIExport` works: the model reaches `QETApp` only through its *static*
accessors.

### 3.6 The one static that is null-unsafe headlessly

`ElementsLocation::icon()` (`sources/ElementsCollection/elementslocation.cpp:855`–`861`)
does:

```cpp
ElementsCollectionCache *cache = QETApp::collectionCache();
ElementsLocation loc(*this);
if (cache->fetchElement(loc))   // <-- no null check
```

`QETApp::collectionCache()` (`sources/qetapp.cpp:436`) simply returns the static
pointer, which is only assigned inside the `QETApp` constructor
(`sources/qetapp.cpp:137`–`140`). **Calling `ElementsLocation::icon()` without a
constructed `QETApp` is a null dereference.** This is the single most likely
crash for an author who assumes `ElementsLocation` is a pure model type. (It is
otherwise: `xml()`, `name()`, `uuid()`, `setXml()`, `exist()` are all safe.)

### 3.7 `QSettings`-backed state read by model code

`QSettings` itself works headlessly (it is `QtCore`), but the *values* come from
the user's config file, so behaviour differs between a desktop session and a
service account. Model classes that read it:

| Site | Keys |
|---|---|
| `sources/diagram.cpp:77`–`79` | `diagrameditor/grid_display_startup`, `diagrameditor/guides_display_startup` — these change what `Diagram::drawBackground()` paints, and therefore what a PDF/PNG export looks like. `CLIExport::renderDiagram()` explicitly toggles them off around the render (`sources/cli_export.cpp:115`–`121`). |
| `sources/diagram.cpp:140`, `:216`, `:436`, `:479`, `:2366` | grid sizes, autonumbering, misc. |
| `sources/qetproject.cpp:71`–`85` | `diagrameditor/auto_break_conductor`, `diagrameditor/defaultguides` array. |
| `sources/qetproject.cpp:213`–`225` | `diagrameditor/autosave-interval` — a non-zero value starts a `QTimer` that calls `QETProject::write()` on its own. |
| `sources/qetapp.cpp:1358`, `:1392`, `:1426`, `:1450` | `diagramitemfont`, `diagramitemsize`, `diagramitemweight`, `diagramitemstyle`, `diagrameditor/dynamic_text_font`, `diagrameditor/independent_text_font`. Every text item's default font (`sources/qetgraphicsitem/diagramtextitem.cpp:54`, `sources/editor/graphicspart/parttext.cpp:40`, `sources/properties/terminaldata.cpp:42`). |
| `sources/qetapp.cpp:602`–`606` and siblings | `elements-collections/common-collection-path`, `.../company-collection-path`, `.../custom-collection-path`, `.../company-tbt-path`, `.../custom-tbt-path`, `.../macros-path`. **These override where collections are found**, and are cached in a `static bool …_is_set` after the first call (`sources/qetapp.cpp:594`) — so they cannot be changed at runtime except through `resetCollectionsPath()` (`:767`). |
| `sources/borderproperties.cpp:174`, `sources/conductorproperties.cpp:753`, `sources/titleblockproperties.cpp:187`, `sources/exportproperties.cpp:131`, `:145` | `defaultProperties()` / `defaultExportProperties()` for new folios and exports. |
| `sources/diagramcommands.cpp:79` | `diagramcommands/erase-label-on-copy`. |

Window geometry/state keys are pure GUI: `diagrameditor/geometry`,
`diagrameditor/state`, `diagrameditor/viewmode`
(`sources/qetdiagrameditor.cpp:2197`–`2227`), and the equivalents in
`QETElementEditor::readSettings/writeSettings`.

### 3.8 Other window-system dependencies

- **Clipboard** — `QApplication::clipboard()` in `sources/diagram.cpp:2454` (`Diagram::clipboardMayContainDiagram()`), `sources/editor/elementscene.cpp:668`, `:713`, `sources/editor/elementview.cpp:215`/`240`/`262`, `sources/qetdiagrameditor.cpp:133`, `sources/editor/ui/qetelementeditor.cpp:1137`, `:1249`, `sources/ui/masterpropertieswidget.cpp:730`. Works with `offscreen` but is per-process and empty.
- **Screens** — `MachineInfo` calls `qApp->screens()` (`sources/machine_info.cpp:263`) and `QGuiApplication::primaryScreen()->availableSize()` (`:452`, `:460`). `main()` pre-constructs `MachineInfo::instance()` on the GUI thread precisely because this is not thread-safe (`sources/main.cpp:193`–`195`). `ConfigDialog` sizes itself from these values (`sources/configdialog.cpp:43`, `:80`).
- **System tray** — `QSystemTrayIcon::show()` unconditionally in `initSystemTray()` (`sources/qetapp.cpp:2423`); combined with `setQuitOnLastWindowClosed(false)` (`:129`), a headless `QETApp` would never exit.
- **Splash screen** — `QSplashScreen` + `qApp->processEvents()` in `setSplashScreenStep()` (`sources/qetapp.cpp:2226`).
- **Printing** — `QPrintDialog` in `ProjectPrintWindow::launchDialog()` (`sources/print/projectprintwindow.cpp:77`–`87`) and a second `d.exec()` at `:836`. `CLIExport::exportPdf()` bypasses all of it with a raw `QPdfWriter` (`sources/cli_export.cpp:127`).
- **`QDesktopServices::openUrl`** — launches a browser/file manager: `sources/editor/ui/qetelementeditor.cpp:1595`, `:1600`, `:1605`; `sources/ui/thirdpartybinaryinstalldialog.cpp:38`, `:44`; `sources/elementspanelwidget.cpp:168`; `sources/ElementsCollection/elementscollectionwidget.cpp:394`–`403`.
- **`SingleApplication`** — `main()` creates a `SingleApplication` with a shared-memory/local-socket lock (`sources/main.cpp:154`); a second instance forwards its argv and exits (`:161`–`171`). Two concurrent GUI invocations therefore do **not** produce two processes. The CLI-export branch is placed before this deliberately (comment at `sources/main.cpp:117`–`119`).
- **Event-loop watchdog** — `EventLoopWatchdog watchdog; watchdog.start();` (`sources/main.cpp:207`–`208`) measures ticks against `app.exec()`.

### 3.9 What *is* safe headlessly

Verified by the fact that `CLIExport::run()` (`sources/cli_export.cpp:769`–`836`)
uses them with only a `QApplication` and no `QETApp`:

- `QETProject(path)` construction and `state()` — **except** for the two version
  message boxes in §3.2.
- `QETProject::toXml()`, and file writing via `QDomDocument::toString()`.
- `Diagram::border_and_titleblock`, `Diagram::title()`, `Diagram::displayGrid()/setDisplayGrid()`.
- `QGraphicsScene::render()` into a `QPdfWriter` / `QImage` / `QSvgGenerator`.
- `Element::elementInformations()`, `Element::name()`, `Terminal`, `Conductor` traversal.
- `projectDataBase` SQL queries.
- `QETApp`'s **static** path accessors (`configDir()`, `dataDir()`, `commonElementsDir()`, …) and `diagramTextsFont()` — all pure `QSettings`/`QStandardPaths`.
- `QETProject::setBackupEnabled(false)` (`sources/qetproject.cpp:50`) — CLI mode disables the background backup writer because it races process exit (comment at `sources/main.cpp:126`–`128`).

---

## 4. What `QETApp` initialises — and what CLI mode therefore lacks

There is no `QETApp::init()` method; initialisation is the constructor plus five
`init*()` helpers. Because `CLIExport` returns from `main()` before
`QETApp qetapp;` (`sources/main.cpp:130` vs `:176`), **none of the following
exists in CLI mode**:

| Initialised by `QETApp` | Where | Missing in CLI mode → consequence |
|---|---|---|
| Application fonts (Liberation ×12, osifont ×2) | `initFonts()`, `sources/qetapp.cpp:2243`–`2286` | `QETApp::diagramTextsFont()` still returns a `QFont("Liberation Sans")`, but the family is not registered with the font database, so Qt substitutes whatever the system has. **Text metrics and therefore folio layout can differ between GUI and CLI exports.** [inference — the substitution behaviour is Qt's, not QET's] |
| ~350 `QIcon`s | `QET::Icons::initIcons()`, `sources/qeticons.cpp:380` | Global `QIcon` objects stay null. Harmless unless something paints them. |
| Palette / `usesystemcolors` | `initStyle()`, `:2287` | `initial_palette_` unset; `useSystemPalette()` never called. Irrelevant to rendering, which uses explicit pens/brushes. |
| Config, data, custom-elements, company-elements, custom-tbt, company-tbt and macros directories **created on disk** | `initConfiguration()`, `:2310`–`2350` | Directories are not `mkpath`'d. `QETApp::customElementsDir()` etc. still *return* paths, but they may not exist. |
| `RecentFiles` for projects and elements | `sources/qetapp.cpp:2353`–`2357` | `QETApp::projectsRecentFiles()` returns null (`:1670` returns the raw static). |
| **`ElementsCollectionCache`** (`dataDir()/elements_cache.sqlite`) | ctor `:137`–`140` | `QETApp::collectionCache()` returns `nullptr` → `ElementsLocation::icon()` crashes (§3.6). Element *pixmaps* are unavailable; element *XML* is unaffected. |
| Title-block template collections | lazy, `:446`/`:467`/`:488` | Actually **still work** in CLI mode: they are lazy statics with no dependency on the instance. Same for `defaultTitleBlockTemplate()` (`:1576`), though it passes `QETApp::instance()` (null) as the `QObject` parent — legal, just unparented. |
| `registered_projects_` | `registerProject()` from `QETDiagramEditor::addProject` (`sources/qetdiagrameditor.cpp:1295`) | Empty. `QETApp::availableTitleBlockTemplatesCollections()` (`:508`) therefore omits per-project embedded collections, and `titleBlockTemplatesCollection("<projectId>")` resolves nothing. A project loaded by `CLIExport` is **never registered**. |
| Translators | `initLanguage()`, `:2234` | All UI strings stay in the source language (French for most `tr()` literals). Affects any string QET puts *into* the document, e.g. default folio titles. |
| Splash, systray, `setQuitOnLastWindowClosed(false)` | `:124`, `:125`, `:132` | Absent — which is what allows the CLI process to exit. |

---

## 5. Where GUI actions cross into the model

These are the real mutation APIs. An MCP server should target the right-hand
column and ignore the left.

### 5.1 Project level

| GUI action | Crossing point | Model API actually used |
|---|---|---|
| File ▸ Save / Save As | `ProjectView::doSave()`, `sources/projectview.cpp:712`–`726` | `QETProject::write()`, then `project()->undoStack()->clear()`. |
| File ▸ Open | `QETDiagramEditor::openAndAddProject()`, `sources/qetdiagrameditor.cpp:1212` | `new QETProject(filepath)` → `QETProject::readProjectXml()`; then `QETApp::registerProject(project)` (`:1294`). |
| Project ▸ Properties ▸ OK | `ConfigDialog::applyConf()` (`sources/configdialog.cpp:124`) → each page's `applyConf()` → `ProjectConfigPage::applyProjectConf()` | `QETProject::setTitle()`, `setProjectProperties(DiagramContext)`, `projectPropertiesHandler().usageTracker().setEnabled()`, `setModified(true)` — `sources/ui/configpage/projectconfigpages.cpp:150`–`175`. |
| Project ▸ Clean | `ProjectView::cleanProject()`, `sources/projectview.cpp:778`–`789` | `embeddedTitleBlockTemplatesCollection()->deleteUnusedTitleBlocKTemplates()`, `embeddedElementCollection()->cleanUnusedElement()`, `->cleanUnusedDirectory()`. |
| Drop an element from the panel onto a folio | `DiagramView::handleElementDrop()`, `sources/diagramview.cpp:202` | `QETProject::importElement(ElementsLocation&)` (`sources/qetproject.cpp:1189`) → `XmlElementCollection::copy()`. **This is the path that can open `ImportElementDialog`.** |
| Autosave timer | `QETProject` ctor lambda, `sources/qetproject.cpp:219`–`223` | `QETProject::write()`. |
| Crash backup timer | `QETProject::writeBackup()`, `sources/qetproject.cpp:1996`–`2010` | `QETProject::toXml()` + `QET::writeToFile()` on a `QtConcurrent` thread. Disabled by `setBackupEnabled(false)`. |

### 5.2 Folio (diagram) level

| GUI action | Crossing point | Model API |
|---|---|---|
| Folio ▸ Properties ▸ OK | `DiagramPropertiesDialog` ctor, `sources/ui/diagrampropertiesdialog.cpp:99`–`122` | `diagram->undoStack().push(new ChangeTitleBlockCommand(...))`, `... new ChangeBorderCommand(...)`; plus direct writes `diagram->defaultConductorProperties = ...` (`:114`, flagged TODO — **not undoable**) and `diagram->setConductorsAutonumName(...)` (`:119`). |
| Add/remove/reorder folios | `QETDiagramEditor::addDiagramToProject*` / `removeDiagram*` / `moveDiagram*` → `ProjectView::setDiagramPosition()` (`sources/projectview.cpp:1117`) | `QETProject::addNewDiagram()`, `removeDiagram()`, diagram-order commands. |
| Any canvas edit | `sources/diagramevent/*` state machines and `sources/dvevent/*` | `Diagram::undoStack().push(new …Command)` from `sources/diagramcommands.h` and `sources/undocommand/`. |
| Multi-paste | `MultiPasteDialog`, `sources/ui/multipastedialog.cpp:48`, `:89`, `:118` | `Diagram::toXml(false)` → `Diagram::fromXml(doc, pos, false, &dc)` → `PasteDiagramCommand`. |
| Conductor colour (F2) | `DiagramView` shortcut lambda, `sources/diagramview.cpp:132`–`145` | `QPropertyUndoCommand(conductor, "properties", old, new)` pushed on `Diagram::undoStack()`. |
| Terminal numbering | `QETDiagramEditor::slot_terminalNumbering()`, `sources/qetdiagrameditor.cpp:2797`–`2810` | `TerminalNumberingDialog::getUndoCommand(project)` → `undo_group.activeStack()->push(macro)`. |
| Selection-properties dock ▸ Apply | `PropertiesEditorDockWidget::apply()` → each widget's `apply()` | Each widget builds a `QUndoCommand` and pushes it, e.g. `sources/ui/elementinfowidget.cpp:98`, `sources/ui/masterpropertieswidget.cpp:190`, `sources/ui/shapegraphicsitempropertieswidget.cpp:138`, `sources/ui/inditextpropertieswidget.cpp:141`, `sources/ui/imagepropertieswidget.cpp:84`, `sources/ui/plclinkwidget.cpp:125`, `:359`, `sources/ui/linksingleelementwidget.cpp:176`, `sources/ui/dynamicelementtextitemeditor.cpp:124`–`248`. |
| Save selection as macro/template | `DiagramView::createTemplateFromSelection()`, `sources/diagramview.cpp:1259`–`1350` | Builds a `QDomDocument` by hand and writes it to `QETApp::userMacrosDir()`. |

### 5.3 Element level

| GUI action | Crossing point | Model API |
|---|---|---|
| Element editor ▸ Save (to file) | `QETElementEditor::toFile()`, `sources/editor/ui/qetelementeditor.cpp:270`–`286` | `ElementScene::toXml()` → `QET::writeXmlFile(doc, filepath)`. |
| Element editor ▸ Save (to collection) | `QETElementEditor::toLocation()`, `:337`–`350` | `ElementScene::toXml()` → `ElementsLocation::setXml(doc)`. |
| Element editor ▸ Open | `fromFile()` `:242` / `fromLocation()` `:313` | `ElementScene::fromXml(QDomDocument)`. |
| Any primitive edit | `sources/editor/ui/*editor.cpp` panels | `ElementItemEditor::undoStack().push(new QPropertyUndoCommand(...))` — e.g. `sources/editor/ui/terminaleditor.cpp:218`ff. |
| Add a primitive | `sources/editor/esevent/eseventadd*.cpp` | `AddPartCommand` (`sources/editor/UndoCommand/addpartcommand.h`). |
| Element metadata (names, author) | `ElementScene::editNames()` / author dialog, `sources/editor/elementscene.cpp:912`, `:992` | `ElementScene::setElementData(ElementData)` — see `QETElementEditor::setNames()` `:140`–`144`. |

### 5.4 The dependable invariant

**Every GUI mutation of a folio or an element goes through a `QUndoCommand`
pushed on `Diagram::undoStack()` / `ElementScene::undoStack()`, and every
persistence goes through exactly four calls:**

- `QETProject::write()` / `QETProject::toXml()`
- `Diagram::toXml()` / `Diagram::fromXml()`
- `ElementScene::toXml()` / `ElementScene::fromXml()`
- `ElementsLocation::setXml()` / `QET::writeXmlFile()`

An MCP server that wants to change a project should construct the same
`QUndoCommand`s (they live in `sources/diagramcommands.h`,
`sources/undocommand/`, `sources/editor/UndoCommand/`, `sources/QPropertyUndoCommand/`)
and then call `QETProject::write()`. It should not attempt to reuse anything in
`sources/ui/`.

---

## 6. Open questions

- **UNVERIFIED:** whether `QApplication` under `QT_QPA_PLATFORM=offscreen`
  renders text identically to a real X11 session for the PDF path; the font
  substitution described in §4 has not been measured.
- **UNVERIFIED:** whether `--export-*` on a project written by a *newer* QET
  version reliably hits `sources/qetproject.cpp:1470`. It depends on
  `QetVersion::fromXmlAttribute()` returning non-null, which requires the
  `version` attribute to be present and parseable; a project without it skips
  the whole block (`:1466`–`:1468`).
- **UNVERIFIED:** whether any of `sources/TerminalStrip/ui/`,
  `sources/SearchAndReplace/ui/`, `sources/autoNum/ui/`, `sources/NameList/ui/`,
  `sources/logging/ui/`, `sources/ElementsCollection/ui/` and
  `sources/qetgraphicsitem/ViewItem/ui/` contain further model-reachable
  `exec()` sites beyond the ones already listed in §3.2; they were surveyed by
  grep but not read in full.
