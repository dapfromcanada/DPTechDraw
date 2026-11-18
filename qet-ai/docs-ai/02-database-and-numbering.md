# QElectroTech — Internal Project Database, Auto-Numbering, Search & Replace

Scope: `sources/dataBase/`, `sources/autoNum/`, `sources/NameList/`, `sources/properties/`,
`sources/SearchAndReplace/`, `sources/conductorautonumerotation.cpp`, `sources/conductornumexport.cpp`.
Source root referenced throughout: `/root/qet/qelectrotech-source-mirror`.
All paths are relative to that root.

Audience: an agent building an MCP server against this codebase. Every non-obvious claim is
cited `file:LINE`. Inferences are marked `[inference]`. Open questions are marked `UNVERIFIED:`.

---

## 1. Purpose of the internal database

`projectDataBase` (`sources/dataBase/projectdatabase.h:41`) wraps **one SQLite connection per
open `QETProject`**. It is a *derived, denormalised mirror* of the in-memory object graph
(diagrams → elements → element informations; diagrams → conductors → terminals). It exists so
that nomenclature/BOM/summary features can be expressed as SQL instead of graph walks.

It is **not** the project's storage format. The authoritative storage is the `.qet` XML file.
The database is rebuilt from the object graph and is discarded when the project closes
(`projectDataBase::~projectDataBase` just closes the connection — `sources/dataBase/projectdatabase.cpp:76`).

Consumers in-tree:

| Consumer | File | What it does |
|---|---|---|
| BOM export dialog | `sources/ui/bomexportdialog.cpp:95` | `updateDB()` then `newQuery(queryStr())` |
| Nomenclature table item on a folio | `sources/qetgraphicsitem/ViewItem/projectdbmodel.cpp:341,367` | `ProjectDBModel` runs a stored query string |
| Headless CLI `--export-bom` | `sources/cli_export.cpp:302-318` | `updateDB()` then a fixed SELECT |
| Summary (folio list) widget | `sources/dataBase/ui/summaryquerywidget.cpp:81` | queries `project_summary_view` |
| DB file export (build-flag gated) | `sources/dataBase/projectdatabase.cpp:927` | `sqlite3_backup` to a `.sqlite` file |

The connection name is `"qet_project_db_" + project->uuid().toString()`
(`sources/dataBase/projectdatabase.cpp:384`), so multiple open projects coexist.

### When it is built / rebuilt

* **Built** in the constructor: `createDataBase()` → creates tables/views/indexes,
  `prepareQuery()`, then `updateDB()` (`sources/dataBase/projectdatabase.cpp:47`, `:506-509`).
  `projectDataBase` is a **by-value member** of `QETProject` (`sources/qetproject.h:332`,
  constructed at `sources/qetproject.cpp:63,102,122`), so the schema exists from the moment a
  project object exists — even an empty one.
* **Full repopulate** on project load: signals are blocked during XML parsing, then unblocked and
  `updateDB()` is called once (`sources/qetproject.cpp:1525`, `:1564-1565`).
* **Incremental** on graph mutation: `Diagram::addItem`/`removeItem` call
  `addElement`/`removeElement`/`addConductor`/`removeConductor`
  (`sources/diagram.cpp:1659,1669,1692,1700`).
* **Incremental** on info edit: `Element::…` → `elementInfoChanged()`
  (`sources/qetgraphicsitem/element.cpp:1476`,
  `sources/undocommand/changeelementinformationcommand.cpp:119`);
  `Diagram::…` → `diagramInfoChanged()` (`sources/diagram.cpp:1772`).
* **Incremental** on conductor rename: `Conductor::propertiesChange` → `updateConductor()`
  via a `Qt::UniqueConnection` established in `watchConductor()`
  (`sources/dataBase/projectdatabase.cpp:340-355`).
* **Diagram reorder**: lambda connected to `QETProject::projectDiagramsOrderChanged`
  updates `diagram.pos` and `diagram_info.folio` for every diagram
  (`sources/dataBase/projectdatabase.cpp:54-69`).

There is **no invalidation flag and no dirty tracking**. Anything that mutates the model without
going through the hooks above leaves the DB stale until the next `updateDB()`. This is why every
in-tree consumer calls `updateDB()` immediately before querying.

---

## 2. Full schema

All DDL below is transcribed from `sources/dataBase/projectdatabase.cpp`. Statements built by
string concatenation from `QETInformation` key lists are **expanded to literal column names**
here; the key lists are in `sources/qetinformation.cpp:127` (diagram) and `:141` (element).

### 2.1 `diagram` — `projectdatabase.cpp:398`

```sql
CREATE TABLE diagram (
    uuid VARCHAR(50) PRIMARY KEY NOT NULL,
    pos  INTEGER
);
```

* `uuid` — `Diagram::uuid().toString()`, i.e. Qt braced form `{xxxxxxxx-….}`.
* `pos` — **1-based** folio index: `m_project->folioIndex(diagram)+1`
  (`projectdatabase.cpp:201`, `:633`).

### 2.2 `element` — `projectdatabase.cpp:406`

```sql
CREATE TABLE element (
    uuid         VARCHAR(50) PRIMARY KEY NOT NULL,
    diagram_uuid VARCHAR(50) NOT NULL,
    pos          VARCHAR(6)  NOT NULL,
    type         VARCHAR(50),
    sub_type     VARCHAR(50),
    FOREIGN KEY (diagram_uuid) REFERENCES diagram (uuid)
);
```

* `pos` — grid cell string from `Diagram::convertPosition(scenePos()).toString()`, e.g. `"B3"`.
  `DiagramPosition::toString()` returns `"-"` when out of bounds and subtracts 1 from the column
  number when the QSettings key `border-columns_0` is true (default true)
  (`sources/diagramposition.cpp:61-73`). **The stored string therefore depends on a user setting.**
* `type` — `ElementData::typeToString()`; the literal vocabulary is
  `simple`, `next_report`, `previous_report`, `master`, `slave`, `terminal`, `thumbnail`,
  `conductor_definition` (`sources/properties/elementdata.cpp:663-687`).
* `sub_type` — master sub-kind: `coil`, `protection`, `commutator`, `plc`
  (`sources/properties/elementdata.cpp:723-736`); empty for non-master elements when written by
  `populateElementTable()`. See §7 for the insert-path divergence.

### 2.3 `diagram_info` — `projectdatabase.cpp:420-431`

Built from `QETInformation::diagramInfoKeys()` in order. `date` gets SQL type `DATE`; every other
key gets `VARCHAR(100)` (`projectdatabase.cpp:429`). Expanded:

```sql
CREATE TABLE diagram_info (
    diagram_uuid  VARCHAR(50) PRIMARY KEY NOT NULL,
    title         VARCHAR(100),
    author        VARCHAR(100),
    filename      VARCHAR(100),
    folio         VARCHAR(100),
    plant         VARCHAR(100),
    locmach       VARCHAR(100),
    indexrev      VARCHAR(100),
    date          DATE,
    display_folio VARCHAR(100),
    FOREIGN KEY (diagram_uuid) REFERENCES diagram (uuid)
);
```

Values come from `BorderTitleBlock::titleblockInformation()`
(`projectdatabase.cpp:885`), which is the rendered titleblock `DiagramContext`
(`sources/bordertitleblock.cpp:106`, populated in `updateDiagramContextForTitleBlock`
`sources/bordertitleblock.cpp:897-930`).

* `folio` is `btb_final_folio_` — the **resolved** folio string, with `%autonum`, `%id` and
  `%total` already substituted (`sources/bordertitleblock.cpp:986-995`, `:923`).
* `plant` = `=` designation; `locmach` = `+` designation (see the translations at
  `sources/qetinformation.cpp:240-241`).
* `date` is bound via `QLocale::system().toDate(infos.value("date").toString(), QLocale::ShortFormat)`
  (`projectdatabase.cpp:889-891`). The context stores the date as a **locale short-format string**
  (`sources/bordertitleblock.cpp:915-917`), so this is a locale round-trip. See §7.
* `display_folio` is **always NULL**: nothing ever writes a `display_folio` key into the titleblock
  context. The only other references to the key in the whole tree are its declaration
  (`sources/qetinformation.h:99`) and an explicit skip in the summary UI
  (`sources/dataBase/ui/summaryquerywidget.cpp:128`).

### 2.4 `element_info` — `projectdatabase.cpp:437-449`

Built from `QETInformation::elementInfoKeys()` (56 keys, `sources/qetinformation.cpp:141-200`),
each as `VARCHAR(100)`, in this exact order:

```sql
CREATE TABLE element_info (
    element_uuid                              VARCHAR(50) PRIMARY KEY NOT NULL,
    formula                                   VARCHAR(100),
    label                                     VARCHAR(100),
    plant                                     VARCHAR(100),
    location                                  VARCHAR(100),
    comment                                   VARCHAR(100),
    function                                  VARCHAR(100),
    description                               VARCHAR(100),
    designation                               VARCHAR(100),
    manufacturer                              VARCHAR(100),
    manufacturer_reference                    VARCHAR(100),
    machine_manufacturer_reference            VARCHAR(100),
    supplier                                  VARCHAR(100),
    quantity                                  VARCHAR(100),
    unity                                     VARCHAR(100),
    auxiliary1                                VARCHAR(100),
    description_auxiliary1                    VARCHAR(100),
    designation_auxiliary1                    VARCHAR(100),
    manufacturer_auxiliary1                   VARCHAR(100),
    manufacturer_reference_auxiliary1         VARCHAR(100),
    machine_manufacturer_reference_auxiliary1 VARCHAR(100),
    supplier_auxiliary1                       VARCHAR(100),
    quantity_auxiliary1                       VARCHAR(100),
    unity_auxiliary1                          VARCHAR(100),
    auxiliary2                                VARCHAR(100),
    description_auxiliary2                    VARCHAR(100),
    designation_auxiliary2                    VARCHAR(100),
    manufacturer_auxiliary2                   VARCHAR(100),
    manufacturer_reference_auxiliary2         VARCHAR(100),
    machine_manufacturer_reference_auxiliary2 VARCHAR(100),
    supplier_auxiliary2                       VARCHAR(100),
    quantity_auxiliary2                       VARCHAR(100),
    unity_auxiliary2                          VARCHAR(100),
    auxiliary3                                VARCHAR(100),
    description_auxiliary3                    VARCHAR(100),
    designation_auxiliary3                    VARCHAR(100),
    manufacturer_auxiliary3                   VARCHAR(100),
    manufacturer_reference_auxiliary3         VARCHAR(100),
    machine_manufacturer_reference_auxiliary3 VARCHAR(100),
    supplier_auxiliary3                       VARCHAR(100),
    quantity_auxiliary3                       VARCHAR(100),
    unity_auxiliary3                          VARCHAR(100),
    auxiliary4                                VARCHAR(100),
    description_auxiliary4                    VARCHAR(100),
    designation_auxiliary4                    VARCHAR(100),
    manufacturer_auxiliary4                   VARCHAR(100),
    manufacturer_reference_auxiliary4         VARCHAR(100),
    machine_manufacturer_reference_auxiliary4 VARCHAR(100),
    supplier_auxiliary4                       VARCHAR(100),
    quantity_auxiliary4                       VARCHAR(100),
    unity_auxiliary4                          VARCHAR(100),
    plc_type                                  VARCHAR(100),
    plc_address                               VARCHAR(100),
    plc_function                              VARCHAR(100),
    plc_comment                               VARCHAR(100),
    plc_crossref                              VARCHAR(100),
    exclude_from_bom                          VARCHAR(100),
    FOREIGN KEY (element_uuid) REFERENCES element (uuid)
);
```

Column semantics (translations at `sources/qetinformation.cpp:234-319`):

* `formula` — the *label formula* (e.g. `%prefix%sequ_1`). Not the rendered label.
* `label` — **the rendered label**, not the raw stored property:
  `elementInfoToString()` special-cases `label` to `Element::actualLabel()`
  (`projectdatabase.cpp:868-876`), which evaluates the formula through
  `autonum::AssignVariables::formulaToLabel` (`sources/qetgraphicsitem/element.cpp:1750-1760`).
  Every other key is `elementInformations()[key].toString()`.
* `designation` = article number; `manufacturer_reference` = order number;
  `machine_manufacturer_reference` = internal number.
* `auxiliaryN` + its 8 companions = four repeatable "auxiliary component" blocks (a single
  graphical element may carry up to five orderable parts).
* `plc_*` — PLC slave cross-reference fields.
* `exclude_from_bom` — stored as the **strings `"true"` / `"false"`**
  (`sources/ui/elementinfowidget.cpp:430`, read back at `:380`). Not `0`/`1`, not NULL for new
  elements that were never touched (then it is `""` or NULL).

`terminalElementInfoKeys()` (`sources/qetinformation.cpp:376-386`) is a UI-only subset
(`formula`, `label`, `comment`, `designation`, `manufacturer`, `manufacturer_reference`,
`machine_manufacturer_reference`, `supplier`) — it does **not** change the table shape.

### 2.5 `terminal` — `projectdatabase.cpp:461-468`

```sql
CREATE TABLE terminal (
    uuid         VARCHAR(50) NOT NULL,
    element_uuid VARCHAR(50) NOT NULL,
    name         VARCHAR(50),
    PRIMARY KEY (uuid, element_uuid),
    FOREIGN KEY (element_uuid) REFERENCES element (uuid)
);
```

`uuid` is `Terminal::stableUuid()`, **not** `Terminal::uuid()`. `uuid()` comes from the catalog
`.elmt` definition and is identical across every placed instance of that catalog element (and is
null for pre-uuid definitions). `stableUuid()` returns the definition uuid if present, otherwise a
deterministic **UUID v5** derived from the terminal's local position and orientation in namespace
`{6b1f6d1e-6a1a-5f7e-9a3d-9c0a5b2d7e11}` (`sources/qetgraphicsitem/terminal.cpp:824-870`).
Hence the composite primary key `(uuid, element_uuid)`.

Terminals are inserted only as a side effect of inserting a conductor
(`projectdatabase.cpp:719-721`, `:741-742`), with `INSERT OR IGNORE`
(`projectdatabase.cpp:844`). **Unconnected terminals never appear in this table.**

### 2.6 `conductor` — `projectdatabase.cpp:474-486`

```sql
CREATE TABLE conductor (
    uuid                   VARCHAR(50) PRIMARY KEY NOT NULL,
    diagram_uuid           VARCHAR(50) NOT NULL,
    terminal1_uuid         VARCHAR(50) NOT NULL,
    terminal1_element_uuid VARCHAR(50) NOT NULL,
    terminal2_uuid         VARCHAR(50) NOT NULL,
    terminal2_element_uuid VARCHAR(50) NOT NULL,
    text                   VARCHAR(100),
    FOREIGN KEY (diagram_uuid) REFERENCES diagram (uuid),
    FOREIGN KEY (terminal1_uuid, terminal1_element_uuid) REFERENCES terminal (uuid, element_uuid),
    FOREIGN KEY (terminal2_uuid, terminal2_element_uuid) REFERENCES terminal (uuid, element_uuid)
);
```

* `text` — the wire number (`conductor->properties().text`), `projectdatabase.cpp:374`.
  It is the **only** mutable column; `updateConductor()` rewrites just this
  (`projectdatabase.cpp:853`).
* A conductor whose either endpoint has no parent element is **skipped entirely**
  (`projectdatabase.cpp:267-270`, `:736-739`).
* No conductor properties other than `text` are mirrored — `m_function`,
  `m_tension_protocol`, `m_wire_color`, `m_wire_section`, `m_formula` are **not in the DB**.

### 2.7 Indexes — `projectdatabase.cpp:496-504`

```sql
CREATE INDEX idx_conductor_terminal1_element ON conductor (terminal1_element_uuid);
CREATE INDEX idx_conductor_terminal2_element ON conductor (terminal2_element_uuid);
CREATE INDEX idx_conductor_diagram           ON conductor (diagram_uuid);
```

These are the only explicit indexes. (SQLite additionally creates implicit indexes for the
non-`INTEGER PRIMARY KEY` primary keys on `diagram`, `element`, `diagram_info`, `element_info`,
`terminal`, `conductor`.)

### 2.8 `element_nomenclature_view` — `projectdatabase.cpp:516-586`

61 columns. No `formula`, **no uuid of any kind**.

```sql
CREATE VIEW element_nomenclature_view AS SELECT
  ei.label AS label,
  ei.plant AS plant,
  ei.location AS location,
  ei.comment AS comment,
  ei.function AS function,
  ei.description AS description,
  ei.designation AS designation,
  ei.manufacturer AS manufacturer,
  ei.manufacturer_reference AS manufacturer_reference,
  ei.machine_manufacturer_reference AS machine_manufacturer_reference,
  ei.supplier AS supplier,
  ei.quantity AS quantity,
  ei.unity AS unity,
  ei.auxiliary1 AS auxiliary1,
  ei.description_auxiliary1 AS description_auxiliary1,
  ei.designation_auxiliary1 AS designation_auxiliary1,
  ei.manufacturer_auxiliary1 AS manufacturer_auxiliary1,
  ei.manufacturer_reference_auxiliary1 AS manufacturer_reference_auxiliary1,
  ei.machine_manufacturer_reference_auxiliary1 AS machine_manufacturer_reference_auxiliary1,
  ei.supplier_auxiliary1 AS supplier_auxiliary1,
  ei.quantity_auxiliary1 AS quantity_auxiliary1,
  ei.unity_auxiliary1 AS unity_auxiliary1,
  ei.auxiliary2 AS auxiliary2,
  ei.description_auxiliary2 AS description_auxiliary2,
  ei.designation_auxiliary2 AS designation_auxiliary2,
  ei.manufacturer_auxiliary2 AS manufacturer_auxiliary2,
  ei.manufacturer_reference_auxiliary2 AS manufacturer_reference_auxiliary2,
  ei.machine_manufacturer_reference_auxiliary2 AS machine_manufacturer_reference_auxiliary2,
  ei.supplier_auxiliary2 AS supplier_auxiliary2,
  ei.quantity_auxiliary2 AS quantity_auxiliary2,
  ei.unity_auxiliary2 AS unity_auxiliary2,
  ei.auxiliary3 AS auxiliary3,
  ei.description_auxiliary3 AS description_auxiliary3,
  ei.designation_auxiliary3 AS designation_auxiliary3,
  ei.manufacturer_auxiliary3 AS manufacturer_auxiliary3,
  ei.manufacturer_reference_auxiliary3 AS manufacturer_reference_auxiliary3,
  ei.machine_manufacturer_reference_auxiliary3 AS machine_manufacturer_reference_auxiliary3,
  ei.supplier_auxiliary3 AS supplier_auxiliary3,
  ei.quantity_auxiliary3 AS quantity_auxiliary3,
  ei.unity_auxiliary3 AS unity_auxiliary3,
  ei.auxiliary4 AS auxiliary4,
  ei.description_auxiliary4 AS description_auxiliary4,
  ei.designation_auxiliary4 AS designation_auxiliary4,
  ei.manufacturer_auxiliary4 AS manufacturer_auxiliary4,
  ei.manufacturer_reference_auxiliary4 AS manufacturer_reference_auxiliary4,
  ei.machine_manufacturer_reference_auxiliary4 AS machine_manufacturer_reference_auxiliary4,
  ei.supplier_auxiliary4 AS supplier_auxiliary4,
  ei.quantity_auxiliary4 AS quantity_auxiliary4,
  ei.unity_auxiliary4 AS unity_auxiliary4,
  ei.exclude_from_bom AS exclude_from_bom,
  ei.plc_type AS plc_type,
  ei.plc_address AS plc_address,
  ei.plc_function AS plc_function,
  ei.plc_comment AS plc_comment,
  ei.plc_crossref AS plc_crossref,
  d.pos AS diagram_position,
  e.type AS element_type,
  e.sub_type AS element_sub_type,
  di.title AS title,
  di.folio AS folio,
  e.pos AS position
 FROM element_info ei, diagram_info di, element e, diagram d
 WHERE ei.element_uuid = e.uuid AND e.diagram_uuid = d.uuid AND di.diagram_uuid = d.uuid
   AND (ei.exclude_from_bom IS NOT 'true');
```

* It is a comma (inner) join. An element whose diagram has no `diagram_info` row, or whose
  `element_info` row is missing, silently disappears from the view.
* `diagram_position` = 1-based folio index (INTEGER); `position` = grid cell string;
  `folio` = the resolved folio label; `title` = folio title.
* `IS NOT 'true'` is NULL-safe in SQLite, so untouched elements (NULL / `''` /`"false"`) are kept.

### 2.9 `project_summary_view` — `projectdatabase.cpp:605-617`

```sql
CREATE VIEW project_summary_view AS SELECT
  di.title    AS title,
  di.author   AS author,
  di.folio    AS folio,
  di.plant    AS plant,
  di.locmach  AS locmach,
  di.indexrev AS indexrev,
  di.date     AS date,
  d.pos       AS pos
 FROM diagram_info di, diagram d
 WHERE di.diagram_uuid = d.uuid;
```

### 2.10 `conductor_nomenclature_view` — **does not exist**

Verified by exhaustive grep: the only `CREATE VIEW` statements in the tree are the two above
(`projectdatabase.cpp:518`, `:607`). A stale comment at `projectdatabase.cpp:322-324` and
`:492-495` refers to a `wire_count` correlated subquery in the nomenclature view; **there is no
`wire_count` column anywhere in the source**. The three `idx_conductor_*` indexes it justifies
still exist but are currently unused by any view.

An MCP server that wants a wiring list must either join `conductor`/`terminal`/`element_info`
itself, or use the object-graph path (`ConductorNumExport`, `WiringListExport`, `--export-nets`).

---

## 3. Lifecycle, storage medium, PRAGMAs

### 3.1 `updateDB()`

```cpp
void projectDataBase::updateDB();          // sources/dataBase/projectdatabase.cpp:86
```

Body (`:86-94`), in order:

1. `populateDiagramTable()` — `DELETE FROM diagram`, re-insert all (`:625-638`)
2. `populateDiagramInfoTable()` — `DELETE FROM diagram_info`, re-insert all (`:702-715`)
3. `populateElementTable()` — `DELETE FROM element`, re-insert (`:644-667`)
4. `populateElementInfoTable()` — `DELETE FROM element_info`, re-insert (`:673-700`)
5. `populateConductorTable()` — `DELETE FROM conductor`; `DELETE FROM terminal`; re-insert (`:723-751`)
6. `emit dataBaseUpdated()`

It is a **full truncate-and-reload of every table**, not an incremental sync. Cost is
O(diagrams × elements + conductors). No transaction wraps it — each `exec()` is its own implicit
transaction. (`elementInfoChanged(QList<Element*>)` *does* wrap its batch in
`transaction()`/`commit()`, `:188-192`.)

Elements are selected through
`ElementProvider::find(ElementData::Simple | Terminal | Master | Thumbnail)`
(`:652`, `:681`) — so **slave elements, folio reports (`next_report`/`previous_report`) and
conductor definitions are excluded** from `element` and `element_info` after any `updateDB()`.

### 3.2 Invalidation

There is none. `dataBaseUpdated()` is a *notification*, not an invalidation. It is emitted from
`addElement`, `removeElement`, `elementInfoChanged`, `addDiagram`, `removeDiagram`,
`diagramInfoChanged`, `addConductor`, `removeConductor`, and the diagram-reorder lambda —
but **deliberately not** from `updateConductor()` (`:320-327`), because auto-numbering renames
every conductor in one pass and each emission would re-run every `ProjectDBModel` query.

`diagramOrderChanged()` (`projectdatabase.h:59`) is declared and **empty** (`:247-249`); the real
work is in the constructor lambda.

Practical rule for an MCP server: **call `updateDB()` before every read**, exactly as
`bomexportdialog.cpp:95`, `cli_export.cpp:305` and `projectdbmodel.cpp:201` do.

### 3.3 On disk or in memory?

```cpp
m_data_base = QSqlDatabase::addDatabase("QSQLITE",
                "qet_project_db_" + m_project->uuid().toString());
if(!m_data_base.open()) { … }              // projectdatabase.cpp:384-388
```

`setDatabaseName()` is **never called**. For the QSQLITE driver an empty database name is passed
straight to `sqlite3_open_v2("")`, which per SQLite semantics creates a *private temporary
database*. Combined with `PRAGMA temp_store = MEMORY` (issued immediately after open) this is
held in memory and is destroyed on `close()`. `[inference]` — based on documented SQLite
behaviour for an empty filename plus `temp_store`; the in-tree comments call it
`memory_db_handle` (`projectdatabase.cpp:963`).

`UNVERIFIED:` whether a spill file is ever created on disk for a very large project.
Test: open a large `.qet`, then `lsof -p <pid> | grep etilqs` (SQLite's temp-file prefix) while
the project is open.

### 3.4 PRAGMAs — `projectdatabase.cpp:390-392`

```sql
PRAGMA temp_store  = MEMORY;
PRAGMA journal_mode = MEMORY;
PRAGMA synchronous  = OFF;
```

No `foreign_keys = ON` is issued, so the declared `FOREIGN KEY` constraints are **not enforced**
(SQLite defaults to off). Orphan rows are possible and are not an error.

### 3.5 Export to a file — `projectdatabase.cpp:900-975`

Compiled only when `QET_EXPORT_PROJECT_DB` is defined. It is **ON in the qmake build**
(`qelectrotech.pro:64`) and **OFF by default in the CMake build**
(`cmake/start_options.cmake:32`).

```cpp
static sqlite3 *projectDataBase::sqliteHandle(QSqlDatabase *db);
static void projectDataBase::exportDb(projectDataBase *db,
                                      QWidget *parent = nullptr,
                                      const QString &caption = QString(),
                                      const QString &dir = QString());
```

`exportDb` opens a file connection, then `sqlite3_backup_init/step(-1)/finish` from the live
handle. **It opens a `QFileDialog`** (`:948`), so it is unusable headless as-is. GUI entry point:
`sources/qetdiagrameditor.cpp:523`. An MCP server wanting a snapshot file should replicate the
`sqlite3_backup` block without the dialog, or use `VACUUM INTO '<path>'` over `newQuery()`.
`[inference]` on `VACUUM INTO` — depends on the linked SQLite ≥ 3.27; the version is logged at
runtime by `projectdatabase.cpp:593-599`.

---

## 4. How to query it

### 4.1 Public API — `sources/dataBase/projectdatabase.h`

```cpp
projectDataBase(QETProject *project, QObject *parent = nullptr);
void        updateDB();
QETProject *project() const;
QSqlQuery   newQuery(const QString &query = QString());   // :110 in the .cpp

void addElement(Element *);        void removeElement(Element *);
void elementInfoChanged(Element *);  void elementInfoChanged(QList<Element *>);
void addDiagram(Diagram *);        void removeDiagram(Diagram *);
void diagramInfoChanged(Diagram *); void diagramOrderChanged();   // no-op
void addConductor(Conductor *);    void removeConductor(Conductor *);
void updateConductor(Conductor *);

signals: void dataBaseUpdated();
```

Access from a project: `QETProject::dataBase()` returns a **non-owning pointer to a by-value
member** (`sources/qetproject.cpp:183-186`). Never delete it; its lifetime equals the project's.

`newQuery(sql)` is `QSqlQuery(query, m_data_base)` — note that the `QSqlQuery(QString, QSqlDatabase)`
constructor **executes immediately** if the string is non-empty. Callers that then call `exec()`
(e.g. `cli_export.cpp:312-315`, `bomexportdialog.cpp:96-100`) run it twice; harmless for SELECTs.

### 4.2 What an external tool CAN do

* Any read-only SQL against the six tables and two views — arbitrary joins, `GROUP BY`,
  `COUNT(*)`, window functions if the linked SQLite supports them.
* Read the SQLite version: `newQuery("select sqlite_version();")` (pattern at
  `projectdatabase.cpp:593-599`).
* Introspect: `SELECT name, sql FROM sqlite_master` works and is the cheapest way to confirm the
  schema of the running binary rather than trusting this document.
* Reuse the two query-builder widgets' output format. `ElementQueryWidget::queryStr()`
  (`sources/dataBase/ui/elementquerywidget.cpp:284-393`) produces, in order:
  `SELECT <cols>[, <count>] FROM element_nomenclature_view [WHERE (<type filters>)]<filters>[ GROUP BY x] ORDER BY <cols>`.
  Type filters are `element_type = 'terminal'|'thumbnail'|'simple'` and
  `element_sub_type = 'commutator'|'coil'|'protection'|'plc'` (`:340-374`).
  It always appends `AND (exclude_from_bom IS NULL OR exclude_from_bom != '1')` (`:381-383`) —
  which is a no-op given values are `"true"`/`"false"`, and is redundant with the view's own filter.
  `SummaryQueryWidget::queryStr()` (`summaryquerywidget.cpp:55-85`) produces
  `SELECT <cols> FROM project_summary_view ORDER BY <cols>`.
* Read the user's saved queries: `$configDir/nomenclature.json` (element queries,
  `elementquerywidget.cpp:502,638,663`) and `$configDir/summary.json`
  (`summaryquerywidget.cpp:146,299,334`) — JSON objects keyed by user-chosen name.

### 4.3 What an external tool CANNOT do

* **Write to it usefully.** Nothing reads back from the DB into the model. Any `UPDATE`/`INSERT`
  is destroyed by the next `updateDB()`, and never reaches the `.qet` file. To change project
  data you must go through the object graph + undo commands (see §6).
* **Get an element or conductor uuid out of `element_nomenclature_view`.** The view exposes no
  uuid column. Join `element_info`/`element` directly if you need identity:
  ```sql
  SELECT e.uuid, ei.label, ei.designation, d.pos, e.pos
    FROM element e
    JOIN element_info ei ON ei.element_uuid = e.uuid
    JOIN diagram d       ON d.uuid = e.diagram_uuid;
  ```
* **See slaves, folio reports, or conductor definitions** after an `updateDB()` (§3.1).
* **See unconnected terminals** (§2.5), or any conductor property other than `text` (§2.6).
* **Connect to the DB from another process.** It is a private temp database inside the QET
  process; there is no file path to open. Cross-process access requires either the
  `QET_EXPORT_PROJECT_DB` backup path or an in-process bridge.
* **Rely on foreign-key integrity** (§3.4).

---

## 5. The numbering / formula system

Three independent numbering domains, each a `QHash<QString /*name*/, NumerotationContext>` on the
project (`sources/qetproject.h:315-321`):

| Domain | Hash | Current-selection accessor |
|---|---|---|
| Conductor (wire numbers) | `m_conductor_autonum` | `conductorCurrentAutoNum()` / `setCurrentConductorAutoNum()` |
| Element (labels) | `m_element_autonum` | `elementCurrentAutoNum()` / `setCurrrentElementAutonum()` *(sic, 3 r's)* |
| Folio (page numbers) | `m_folio_autonum` | per-diagram `BorderTitleBlock::autoPageNum()` |

API surface: `sources/qetproject.h:150-170`.

### 5.1 `NumerotationContext` — the counter state

`sources/autoNum/numerotationcontext.h:30`. Internally a `QStringList` where each entry is one
**part**, pipe-joined into exactly 6 fields (`numerotationcontext.cpp:141-152`):

```
type | value | increase | initialvalue | modulus | format
```

* `type` — one of `unit unitfolio ten tenfolio hundred hundredfolio wrap alpha string
  idfolio folio plant locmach elementline elementcolumn elementprefix`
  (`numerotationcontext.cpp:206`, validated by `keyIsAcceptable`).
* Numeric types (`keyIsNumber`, `:215`): `unit unitfolio ten tenfolio hundred hundredfolio wrap`.
* `increase` — step per allocation.
* `initialvalue` — only meaningful for the `*folio` types (serialised only for those, `:248-252`).
* `modulus` — only for `wrap`; `0` means "not wrapping" (`:253-255`).
* `format` — zero-padding mask, spreadsheet style: `"00"` → 2 digits, `"0000"` → 4.
  Empty = the type's natural width. Serialised only when non-empty (`:256-258`).
  Absent in every context written before this field existed; `formatOf()` returns `""` then
  (`:314-317`).

XML round-trip: `toXml`/`fromXml` at `numerotationcontext.cpp:240-271`; each part becomes
`<part type= value= increase= [initialvalue=] [modulus=] [format=]/>`.

Padding rules — `NumerotationContext::formatValue` (`:329-343`) is kept **by hand** in sync with
`autonum::setSequentialToList` (`sources/autoNum/assignvariables.cpp:492-523`):

1. `alpha` → used verbatim (not an integer);
2. non-empty mask → `arg(value.toInt(), mask.length(), 10, '0')`;
3. `ten`/`tenfolio` → 2 digits; `hundred`/`hundredfolio` → 3 digits;
4. otherwise → plain `QString::number(int)`.

### 5.2 Context → formula

`autonum::numerotationContextToFormula(const NumerotationContext&)`
(`sources/autoNum/assignvariables.cpp:624-704`) walks the parts and emits, in order:

| Part type | Emitted token |
|---|---|
| `string` | the part's literal `value` |
| `idfolio` | `%id` |
| `folio` | `%F` |
| `plant` | `%M` |
| `locmach` | `%LM` |
| `elementcolumn` | `%c` |
| `elementline` | `%l` |
| `elementprefix` | `%prefix` |
| `unit` (n-th) | `%sequ_<n>` |
| `wrap` (n-th) | `%seqw_<n>` |
| `unitfolio` (n-th) | `%sequf_<n>` |
| `ten` (n-th) | `%seqt_<n>` |
| `tenfolio` (n-th) | `%seqtf_<n>` |
| `hundred` (n-th) | `%seqh_<n>` |
| `hundredfolio` (n-th) | `%seqhf_<n>` |
| `alpha` (n-th) | `%seqa_<n>` |

The `<n>` counters are **per type**, 1-based, in part order.

### 5.3 Formula → rendered string

`autonum::AssignVariables::formulaToLabel(QString formula, sequentialNumbers &seq,
Diagram *diagram, const Element *elmt = nullptr, const Conductor *cndr = nullptr)`
(`assignvariables.h:68`, impl `assignvariables.cpp:216-229`). **Returns `formula` unchanged if
`diagram == nullptr`** (the whole substitution block is inside `if (m_diagram)`, `:358-409`).

Substitution order (`assignvariables.cpp:346-410`):

1. Diagram/folio scalars: `%F` → titleblock folio, `%f` → folio index+1, `%id` → folio index+1,
   `%total` → folio total, `%M` → plant, `%LM` → locmach.
2. If an element is supplied: `%c` → column number (minus 1 when QSettings `border-columns_0`
   is true — `:389-393`), `%l` → row letter, `%prefix` → `Element::getPrefix()`.
3. If a conductor is supplied: `%wf` → function, `%wv` → tension/protocol, `%wc` → wire colour,
   `%ws` → wire section (`:398-404`).
4. `assignTitleBlockVar()` — every titleblock *additional field* key `k` replaces both `%{k}`
   and `%k` (`:412-424`).
5. `assignProjectVar()` — same for every project property key (`:426-438`).
6. `assignSequence()` — `%sequ_N`, `%seqw_N`, `%seqt_N`, `%seqh_N`, `%sequf_N`, `%seqtf_N`,
   `%seqhf_N`, `%seqa_N` from the `sequentialNumbers` struct (`:440-482`).

Separately, `AssignVariables::replaceVariable(const QString &formula, const DiagramContext &dc)`
(`assignvariables.cpp:239-316`) handles the **`%{key}` form** used by dynamic texts: a hard-coded
list covering every element info key, the four conductor keys (`tension_protocol`,
`conductor_section`, `conductor_color`, `function`), the ten `plc_*` keys, and `%{void}` → `""`.
Note this list includes `plc_tc`, `plc_t1`…`plc_t4` (`:309-313`) which are **not** in
`elementInfoKeys()` and therefore have no DB column.

`AssignVariables::genericXref(const Element*)` (`:323-343`) builds `"<folio>-<cell>"`, using the
titleblock folio when QSettings `genericpanel/folio` is true, else the folio index+1.

### 5.4 Where sequential counters actually live

Two distinct places, and they are not the same thing:

* **The allocator state** — `NumerotationContext` in `QETProject::m_*_autonum`. Persisted in the
  `.qet` file under `<conductors_autonums>`, `<folio_autonums>`, `<element_autonums>`
  (write: `sources/qetproject.cpp:1888-1923`; read: `:1760-1789`). Each entry is
  `<conductor_autonum title="…" formula="…"><part …/>…</conductor_autonum>`. The container
  elements carry `current_autonum`, `freeze_new_conductors` / `freeze_new_elements`,
  `auto_break_conductors`.
* **The allocated value on an item** — `autonum::sequentialNumbers`
  (`assignvariables.h:34-58`): eight `QStringList`s (`unit`, `wrap`, `unit_folio`, `ten`,
  `ten_folio`, `hundred`, `hundred_folio`, `alpha`). Serialised per item as
  `<sequentialNumbers><unit>1;7</unit><ten>03</ten>…</sequentialNumbers>`, values `;`-joined
  (`assignvariables.cpp:103-150`, read at `:157-189`). This is what makes a label stable after
  the project counter has moved on.
* **Per-folio maxima** for the `*folio` types live on `Diagram`:
  `m_elmt_unitfolio_max`, `m_elmt_tenfolio_max`, `m_elmt_hundredfolio_max`
  (`QHash<QString /*autonum name*/, QStringList>`), fed by
  `autonum::setFolioSequentialToHash` (`assignvariables.cpp:532-560`) and reloaded by
  `Diagram::loadElmtFolioSeq()` / `loadCndFolioSeq()` (`sources/diagram.cpp:1964-2050+`).

### 5.5 Advancing a counter

`NumerotationContextCommands` (`sources/autoNum/numerotationcontextcommands.h:30`):

```cpp
NumerotationContextCommands(const NumerotationContext &, Diagram * = nullptr);
NumerotationContext next();
NumerotationContext previous();
QString             toRepresentedString();
```

`next()` (`numerotationcontextcommands.cpp:43-62`) applies a per-part `NumStrategy`. Numeric parts
add `increase` (`nextNumber`, `:270-278`); non-incrementing parts are copied (`nextString`, `:257-264`);
`alpha` does a base-26 increment `a…z, aa, ab…` including case-preserving carry
(`incrementAlpha`, `:622-639`); `wrap` takes `(value+increase) % modulus` and triggers
`carry()` into the nearest preceding **numeric** part, cascading through chained wrap parts
(`:98-120`). `previous()` mirrors this with `borrow()` (`:129-148`);
`decrementAlpha` clamps a single `"a"`/`"A"` rather than underflowing (`:653-682`).

`toRepresentedString()` (`:154-167`) renders the *context* directly — `unit` verbatim, `ten`
zero-padded to 2, `hundred` to 3, and the variable types render as their **literal tokens**
(`%id`, `%F`, `%M`, `%LM`, `%l`, `%c`, `%prefix`) rather than resolved values
(`:736-740`, `:771-775`, `:806-810`, `:842-846`, `:878-882`, `:913-917`, `:948-952`).
It falls back to `diagram_->defaultConductorProperties.text` for an empty context (`:165`).
Note this path **ignores the `format` mask** — it uses the type's natural width only.

### 5.6 The two numbering flows

**Element labels** — `Element::setUpFormula(bool code_letter, QUndoCommand *parent_undo)`
(`sources/qetgraphicsitem/element.cpp:1652-1700`):

1. Returns immediately for `Slave` and any `AllReport` element (`:1657`).
2. Stores the *current* project formula into the element's `formula` info key (`:1665`).
3. `autonum::setSequential(formula, m_autoNum_seq, nc, diagram(), autonum_name)` copies the
   current counter values into the element's own `sequentialNumbers` (`:1676`).
4. `ncc.next()` computes the advanced context, wrapped in a `SetAutoNumContextCommand` pushed on
   the undo stack (`:1682-1695`) so undo does not "burn" a number
   (`sources/undocommand/setautonumcontextcommand.h:11-17`).
5. `Element::actualLabel()` (`element.cpp:1750-1760`) evaluates `formula` + the element's own
   `m_autoNum_seq` on every call — the label is *not* cached, which is why
   `element_info.label` is written from `actualLabel()` (§2.4).
6. Freeze: `m_freeze_label` / `QETProject::isFreezeNewElements()` suppress relabelling
   (`element.cpp:1698`, `:1740-1744`).

**Conductor numbers** — `ConductorAutoNumerotation`
(`sources/conductorautonumerotation.cpp`):

* `numerate()` (`:57-63`): if the conductor joins an existing potential (≥1 related conductor)
  → `numeratePotential()`; else if `properties().type == ConductorProperties::Multi`
  → `numerateNewConductor()`. **A single-line conductor with no potential gets no number.**
* `numeratePotential()` (`:176-225`): if all conductors of the potential share properties, copy
  them and copy `sequenceNum()`. If texts+formulas agree, merge equal attributes. Otherwise it
  **opens `PotentialSelectorDialog` modally** (`:219-223`) — a hard blocker for headless use.
* `numerateNewConductor()` (`:231-279`): resolve the diagram's autonum name →
  `project()->conductorAutoNum(name)` → `numerotationContextToFormula()` → store as
  `cp.m_formula` → `setSequential()` → `ncc.next()` → `SetAutoNumContextCommand` →
  `applyText(formulaToLabel(...))`.
* `applyText(const QString&)` (`:71-133`) pushes `QPropertyUndoCommand(conductor, "properties", …)`
  for the conductor **and every conductor in its potential**.

**Folio numbers** — `QETProject::autoFolioNumberingSelectedFolios(int from, int to, const QString &autonum)`
(`sources/qetproject.cpp:973-993`) sets each folio's raw folio string to the sentinel
`"%autonum"`, then `setFolioData(i+1, total, nCC.toRepresentedString(), project_properties)`
substitutes it (`sources/bordertitleblock.cpp:991-995`) and also expands `%id` and `%total`
(`:994-995`). The counter is advanced with `addFolioAutoNum(autonum, nCC.next())` (`:989-990`).
`autoFolioNumberingNewFolios()` merely emits `addAutoNumDiagram()` (`:961-964`).
`QETProject::updateDiagramsFolioData()` (`:2123-2160`) re-resolves `%autonum` for every folio
whose raw folio contains it, and maintains `previous-folio-num` / `next-folio-num`.

### 5.7 If the MCP server wants to be the numbering authority

Safe, in decreasing order of preference:

1. **Read-only mirroring.** Read `m_*_autonum` via `QETProject::conductorAutoNum()` /
   `elementAutoNum()` / `folioAutoNum()` (hash or by-key overloads, `qetproject.h:150-161`),
   convert with `numerotationContextToFormula()`, render with `formulaToLabel()` supplying your
   own `sequentialNumbers`. Nothing mutates.
2. **Own the counter, let QET render.** Compute the next value yourself, then write the whole
   context back with `addConductorAutoNum(key, ctx)` / `addElementAutoNum` / `addFolioAutoNum`
   (`qetproject.h:153-155`). **Wrap it in `SetAutoNumContextCommand`** (the setter is a
   `std::function<void(const QString&, const NumerotationContext&)>` — see
   `conductorautonumerotation.cpp:163-167` for the exact lambda shape) or undo will desynchronise
   the counter from the drawing.
3. **Own the numbers entirely.** Set each item's *literal* value and clear its formula:
   for elements write the `label` info key with an empty `formula` key — `actualLabel()` then
   returns the stored label verbatim (`element.cpp:1750-1753`); for conductors set
   `ConductorProperties::text` with an empty `m_formula`. Do it through
   `ChangeElementInformationCommand` / `QPropertyUndoCommand` so the DB hooks fire.
   Also set `freeze_new_elements` / `freeze_new_conductors`
   (`qetproject.cpp:1764`, `:1784`) so QET does not renumber behind you.

Hard constraints to design around:

* The rendered label of an element with a non-empty `formula` is recomputed on every
  `actualLabel()` call. You cannot pin it by writing `label` alone — you must clear `formula`.
* `numeratePotential()` can open a modal dialog. Never invoke conductor auto-numbering headless
  on a conductor that joins a heterogeneous potential.
* `formulaToLabel()` is a no-op without a `Diagram*`. Never evaluate formulas for detached items.
* Counter values are **project-global per autonum name**, not per folio — except the `*folio`
  types, whose per-folio maxima live on `Diagram` and are re-derived on load.

---

## 6. Search and replace

`SearchAndReplaceWorker` — `sources/SearchAndReplace/searchandreplaceworker.h:51`.
Everything goes through the project undo stack inside a `beginMacro`/`endMacro` pair, so it is
the correct substrate for headless bulk part substitution.

### 6.1 Two modes

**Simple mode** — "set these fields to these values", per target class:

```cpp
void replaceDiagram  (QList<Diagram *>);            // :42   titleblock properties
void replaceElement  (QList<Element *>);            // :104  element informations
void replaceIndiText (QList<IndependentTextItem*>); // :160  free text items
void replaceConductor(QList<Conductor *>);          // :199  conductor properties
```

Merge semantics — `SearchAndReplaceWorker::applyChange(const QString &original, const QString &change)`
(`:451-457`):

| `change` | result |
|---|---|
| empty | keep `original` (i.e. "do not modify") |
| `"XXXXXXXXXXXXXXXXXXX"` (`eraseText()`, `.h:72`) | set to empty |
| anything else | replace with `change` |

Dates use the same trick with `eraseDate() == QDate(1900,1,1)` (`.h:74`, used at `:70-77`).

* `replaceDiagram` covers `title author filename plant locmach indexrev folio date`, plus
  `context.add()` of extra titleblock fields (`:62-79`). Pushes `ChangeTitleBlockCommand`.
* `replaceElement` iterates **all 56 `elementInfoKeys()`** (`:131-135`) and only applies to
  elements whose `linkType()` is `Master`, `Simple`, `Terminale` or `Thumbnail` (`:124-127`).
  Pushes `ChangeElementInformationCommand`. **This is the headless part-substitution hook**:
  set `manufacturer`, `manufacturer_reference`, `designation`, `supplier`, `description`,
  `quantity`, `unity` (and any `_auxiliaryN` variant) on a selected element list.
* `replaceConductor` merges via the `ConductorProperties` overload of `applyChange` (`:414-443`),
  which is field-by-field with per-field "invalid means unchanged" sentinels seeded by
  `invalidConductorProperties()` (`:388-406`): `text_size > 2`, `cond_size >= 0.4`,
  `m_dash_size >= 2`, valid `QColor`, `style != Qt::NoPen`, alignment must be
  Left/Right resp. Top/Bottom, rotations `>= 0`. Note `m_show_text`, `m_bicolor` and
  `singleLineProperties` are copied **unconditionally** (`:423,437,440`) — there is no
  "unchanged" sentinel for them. Changes propagate to the whole potential
  (`relatedPotentialConductors(true)`, `:220-228`).

**Advanced mode** — regex replace on **one named field of one target class**:

```cpp
struct advancedReplaceStruct {   // .h:33
    int     who;      // 0=diagram, 1=element, 2=conductor, 3=independent text
    QString what;     // field key
    QString search;   // QRegularExpression pattern
    QString replace;  // replacement (supports \1 backrefs via QString::replace)
};
void replaceAdvanced(QList<Diagram*>, QList<Element*>,
                     QList<IndependentTextItem*>, QList<Conductor*>);  // :251
```

Valid `what` values per `who` come from the dialog
(`sources/SearchAndReplace/ui/replaceadvanceddialog.cpp:92-112`):

* `who == 0` → `QETInformation::diagramInfoKeys()`; the worker handles
  `title author filename folio plant locmach indexrev` (`:480-486`).
  **`date` and `display_folio` are offered by the UI but silently ignored by the worker.**
* `who == 1` → `elementInfoKeys()`; the worker replaces on any key already present in the
  element's `DiagramContext` (`:504-516`). A key absent from the context is skipped — advanced
  mode cannot *create* a field, only rewrite one.
* `who == 2` → `conductorInfoKeys()` = `formula text function tension_protocol conductor_color
  conductor_section` (`sources/qetinformation.cpp:116-125`). The worker matches
  `formula`, `text`, `function`, `conductor_color`, `conductor_section` — and
  **`"tension/protocol"`, which no key list ever produces** (`:548`). See §7.
* `who == 3` → the independent text's plain text (`:346-362`).

### 6.2 What "search" actually searches — `SearchAndReplaceWidget`

`searchTerms()` builds the haystack per item:

* Diagram (`sources/SearchAndReplace/ui/searchandreplacewidget.cpp:848-866`):
  title, author, filename, plant, locmach, indexrev, folio, `date.toString()`, plus every
  additional titleblock context value.
* Element (`:873-910`): every non-empty value of the 56 `elementInfoKeys()`, **plus** the plain
  text of every `UserText`/`CompositeText` dynamic text item and every text group name.
* Conductor (`:916-930`): `text`, `m_function`, `m_tension_protocol`, `m_wire_color`,
  `m_wire_section`. **Not `m_formula`.**

Matching is either substring (`QStringList::filter`, case flag from a checkbox) or whole-word
via `\b…\b` (`:409-435`). This is a widget, not a worker API — headless code should reimplement
the term extraction and drive `SearchAndReplaceWorker` directly.

### 6.3 Related: `ReplaceElementDialog`

`sources/SearchAndReplace/ui/replaceelementdialog.cpp:71-85` builds one editor row per
`elementInfoKeys()` entry and returns a `DiagramContext` (`:61-69`) suitable for
`SearchAndReplaceWorker::m_element_context`. Placeholder text is "Ne pas modifier" — i.e. an empty
row means "unchanged", matching `applyChange()`.

---

## 7. Gotchas

1. **No `conductor_nomenclature_view`, no `wire_count`.** Comments at
   `projectdatabase.cpp:322-324` and `:492-495` describe both; neither exists in the source.
   The three conductor indexes they justify are currently used by nothing.

2. **The nomenclature view has no uuid column.** You cannot map a BOM row back to an element
   without joining `element`/`element_info` yourself (§4.3).

3. **`updateDB()` and the incremental hooks disagree about which elements belong in the DB.**
   `Diagram::addItem` calls `addElement()` for *every* `Element` regardless of type
   (`sources/diagram.cpp:1656-1662`), while `populateElementTable()` filters to
   `Simple|Terminal|Master|Thumbnail` (`projectdatabase.cpp:652`). A freshly placed folio report
   or slave therefore has a row until the next `updateDB()` deletes it. Row counts are not stable
   across a rebuild.

4. **`sub_type` is written from two different sources.**
   `addElement()` uses `element->kindInformations()["type"]` (`projectdatabase.cpp:129`);
   `populateElementTable()` uses `elmt_data.masterTypeToString()` (`:661`), which returns an
   **empty string for any non-master element** (`elementdata.cpp:716-721`). The same element can
   have different `sub_type` before and after a rebuild.

5. **`diagram_info.display_folio` is always NULL** — nothing writes the key (§2.3).

6. **`diagram_info.date` is a locale round-trip.** The titleblock stores the date as a
   `QLocale::system()` short-format *string* (`bordertitleblock.cpp:915-917`), and the DB binder
   parses that string back with `QLocale::system().toDate(..., ShortFormat)`
   (`projectdatabase.cpp:889-891`). Change the system locale between write and read and the date
   becomes NULL/invalid. Consumers then re-format it for display
   (`projectdbmodel.cpp:377-380`, `bomexportdialog.cpp:136-139`).

7. **`element.pos` depends on a QSettings key.** `border-columns_0` (default true) shifts the
   column number by −1 (`diagramposition.cpp:68-72`). Out-of-bounds elements store `"-"`.
   The same is true of `%c` in formulas (`assignvariables.cpp:389-393`).

8. **`element_info.label` is the *rendered* label, `formula` is the *source*.** They can be
   inconsistent with the raw `label` property stored in the element's `DiagramContext`, because
   `elementInfoToString()` substitutes `actualLabel()` for the `label` key only
   (`projectdatabase.cpp:868-876`).

9. **`exclude_from_bom` is `"true"`/`"false"` strings.** The view filters with
   `IS NOT 'true'` (correct); `ElementQueryWidget` additionally appends
   `exclude_from_bom != '1'` (`elementquerywidget.cpp:381`), which never excludes anything.
   Do not write `1`/`0` — `ElementInfoWidget` reads with `== "true"` (`elementinfowidget.cpp:380`).

10. **Foreign keys are declared but not enforced** — no `PRAGMA foreign_keys = ON` (§3.4).

11. **`newQuery("SELECT …")` executes on construction**; a following `exec()` runs it a second
    time (§4.1).

12. **Advanced replace on a conductor's tension/protocol is dead code.** The worker tests
    `what == "tension/protocol"` (`searchandreplaceworker.cpp:548`) but the only producer of
    `what` is the dialog, which supplies `conductorInfoKeys()` values — including
    `"tension_protocol"` with an underscore (`qetinformation.cpp:120`,
    `replaceadvanceddialog.cpp:108-110`). The branch can never be taken.
    Likewise `who == 0` silently ignores `date` and `display_folio`.

13. **`projectDataBase::diagramOrderChanged()` is an empty function** (`projectdatabase.cpp:247-249`).
    The real reorder handling is the constructor lambda; calling the public method does nothing.

14. **`updateConductor()` deliberately does not emit `dataBaseUpdated()`** (`:320-327`).
    A UI/model that only listens to that signal will show stale wire numbers after a bulk rename.

15. **`exportDb()` is behind a build flag and opens a `QFileDialog`.** ON for the qmake build
    (`qelectrotech.pro:64`), OFF by default for CMake (`cmake/start_options.cmake:32`).

16. **`toRepresentedString()` ignores the `format` mask** and renders variable part types as
    their literal tokens (`%F`, `%id`, …) rather than resolved values (§5.5). Use it only for
    folio numbering (where the tokens are resolved afterwards by `setFolioData`) or previews.

17. **`NumerotationContext` values may not contain `|`** — it is the field separator and is
    stripped on insert (`numerotationcontext.cpp:140`, `:151`). A literal `string` part
    containing a pipe silently loses it.

18. **Legacy contexts have fewer than 6 fields.** `itemAt(i)` returns whatever `split("|")`
    yields; every accessor guards with `strl.size() > 4` / `> 5`
    (`numerotationcontext.cpp:285-286`, `:316`). Reproduce those guards if you parse the XML.

19. **`ConductorNumExport` does not use the database.** It walks the object graph and counts
    *terminal occurrences* per wire number, skipping endpoints on folio-report elements
    (`sources/conductornumexport.cpp:113-142`). `wiresNum()` emits the number once **per
    occurrence** (`:99-106`), so the CSV is intentionally a repeated-line label list, not a
    de-duplicated wire list. `toCsv()` opens a `QFileDialog` (`:57`) — headless callers must use
    `wiresNum()` directly, as `cli_export.cpp:267-268` does.

20. **`NamesList` silently drops invalid language codes.** `addName()` requires exactly 2 chars,
    or 5 with `_` at index 2 (`sources/NameList/nameslist.cpp:46-50`). `name()` resolution order:
    system language → base language (`de_DE` → `de`) → `en` → caller fallback → first entry →
    `""` (`:261-277`). `toXml()` on an empty list emits a single `<name lang="en"> </name>`
    placeholder (`:189-194`).

21. **`ElementData` implements `PropertiesInterface` only partially** — the class comment says
    only `fromXml` is really reimplemented (`sources/properties/elementdata.h:30-34`).
    `ReportProperties` is not even a `PropertiesInterface`; it is a single static returning the
    QSettings value `diagrameditor/defaultreportlabel`, default `"%f-%l%c"`
    (`sources/properties/reportproperties.cpp:27-31`).

22. **`%{plc_tc}`, `%{plc_t1}`…`%{plc_t4}` are substitutable in formulas**
    (`assignvariables.cpp:309-313`) but are **not** in `elementInfoKeys()` and therefore have no
    `element_info` column. Only `plc_type`, `plc_address`, `plc_function`, `plc_comment`,
    `plc_crossref` are persisted to the DB.

23. **`setCurrrentElementAutonum`** is spelled with three `r`s (`sources/qetproject.h:170`).
    Do not "fix" the spelling when binding to it.

24. `UNVERIFIED:` whether `newQuery()` can safely be called from a thread other than the one that
    opened the connection. `QSqlDatabase` is documented as not thread-safe across threads.
    Test: run a query from a worker thread and check for the
    "QSqlDatabasePrivate::database: requested database does not belong to the calling thread"
    warning.

25. `UNVERIFIED:` the exact behaviour of `element_nomenclature_view` when two folios share a
    `diagram_info` row (should be impossible — `diagram_uuid` is the primary key — but the comma
    join would fan out if it ever happened). Test: force a duplicate insert and count view rows.

---

## 8. Quick reference — headless recipes

```cpp
// 1. Fresh BOM rows, with identity. (updateDB first, always.)
project.dataBase()->updateDB();
QSqlQuery q = project.dataBase()->newQuery(
    "SELECT e.uuid, ei.label, ei.designation, ei.manufacturer, "
    "       ei.manufacturer_reference, ei.quantity, ei.unity, "
    "       d.pos AS folio_index, e.pos AS cell, di.folio, di.title "
    "  FROM element e "
    "  JOIN element_info ei ON ei.element_uuid = e.uuid "
    "  JOIN diagram d       ON d.uuid = e.diagram_uuid "
    "  JOIN diagram_info di ON di.diagram_uuid = d.uuid "
    " WHERE ei.exclude_from_bom IS NOT 'true' "
    " ORDER BY d.pos, ei.label");
q.exec();   // (the ctor already ran it once; harmless for SELECT)
```

```cpp
// 2. Wiring list from the DB (there is no view for this).
"SELECT c.text AS wire, "
"       e1.uuid AS elmt1, t1.name AS term1, "
"       e2.uuid AS elmt2, t2.name AS term2, d.pos AS folio "
"  FROM conductor c "
"  JOIN diagram  d  ON d.uuid = c.diagram_uuid "
"  JOIN terminal t1 ON t1.uuid = c.terminal1_uuid AND t1.element_uuid = c.terminal1_element_uuid "
"  JOIN terminal t2 ON t2.uuid = c.terminal2_uuid AND t2.element_uuid = c.terminal2_element_uuid "
"  JOIN element  e1 ON e1.uuid = c.terminal1_element_uuid "
"  JOIN element  e2 ON e2.uuid = c.terminal2_element_uuid "
" ORDER BY c.text"
```

```cpp
// 3. Headless part substitution across a selection.
SearchAndReplaceWorker w;                       // m_element_context is a private member;
                                                // SearchAndReplaceWidget is its friend.
// Build the "change" context: empty value = leave alone,
// SearchAndReplaceWorker::eraseText() = clear the field.
DiagramContext change;
change.addValue("manufacturer",           "Schneider");
change.addValue("manufacturer_reference", "LC1D09BD");
// w.m_element_context = change;   // requires friendship or a small accessor patch
w.replaceElement(element_list);                 // one undo macro, DB hooks fire automatically
```

```cpp
// 4. Render a formula without mutating any counter.
autonum::sequentialNumbers seq;                            // your own allocated values
QString label = autonum::AssignVariables::formulaToLabel(
        "%prefix%sequ_1", seq, diagram, element, nullptr); // diagram MUST be non-null
```

```cpp
// 5. Read the project's numbering configuration.
for (const QString &name : project.elementAutoNum().keys()) {
    NumerotationContext ctx = project.elementAutoNum(name);
    QString formula = autonum::numerotationContextToFormula(ctx);
    for (int i = 0; i < ctx.size(); ++i) {
        const QStringList part = ctx.itemAt(i);   // type|value|increase|init|modulus|format
        qDebug() << name << part.at(0)
                 << NumerotationContext::formatValue(part);
    }
}
```
