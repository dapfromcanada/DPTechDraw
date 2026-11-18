# 06 — Title blocks, folio properties, and terminal strips

Scope: `sources/titleblock/`, `sources/bordertitleblock.*`, `sources/borderproperties.*`,
`sources/titleblocktemplate*.{cpp,h}`, `sources/titleblockproperties.*`, `sources/titleblockcell.*`,
`sources/TerminalStrip/`, `sources/xml/terminalstripitemxml.cpp`, the repo-root `titleblocks/`
directory, and the `--set-titleblock` path in `sources/cli_export.cpp`.

All paths are relative to the source root (`/root/qet/qelectrotech-source-mirror`).
Line numbers are from the checked-out mirror at documentation time.

---

## 0. Two different things called "title block"

QET separates them and an MCP server must too:

| Concept | C++ type | Where it lives | XML |
|---|---|---|---|
| **Template** — the *layout*: a grid of cells, logos, `%variable` placeholders | `TitleBlockTemplate` (`sources/titleblocktemplate.h`) | a `.titleblock` file on disk, **or** embedded in a `.qet` | `<titleblocktemplate>` |
| **Properties** — the *values*: title, author, date, custom fields, and which template to use | `TitleBlockProperties` (`sources/titleblockproperties.h`) | attributes of each `<diagram>`, and of `<newdiagrams>/<inset>` | attributes + `<properties>/<property>` |
| **Border** — page grid: columns/rows count and size | `BorderProperties` (`sources/borderproperties.h`) | attributes of each `<diagram>`, and `<newdiagrams>/<border>` | attributes |

`BorderTitleBlock` (`sources/bordertitleblock.h:37`) is the runtime object that owns both the
border geometry and the title-block values for one folio, and drives a
`TitleBlockTemplateRenderer` to paint the template. `Diagram` holds one as a public member
`border_and_titleblock` (used e.g. `sources/cli_export.cpp:93`).

---

## 1. Title block template XML format

### 1.1 Root

`sources/titleblocktemplate.cpp:123-138` (`loadFromXmlElement`):

- Root tag **must** be `titleblocktemplate`; anything else → load fails and returns false.
- Attribute `name` is **required** (`:128`); its value becomes the template's identity
  (`name_`, `:131`).
- Three children are then read, in this order: `information`, `logos`, `grid`
  (`:133-135`).

Save side is symmetric — `saveToXmlElement` (`:167-178`) refuses to save a template whose
name is empty, sets `name`, then writes `<information>`, `<logos>`, `<grid>`.

A standalone template file is written by `saveToXmlFile` (`:147-158`), which creates a
throwaway `<root>` element and lets `saveToXmlElement` rename it via `setTagName`, so the
file's document element ends up being `<titleblocktemplate>`.

Skeleton (matches `titleblocks/default.titleblock` exactly):

```xml
<titleblocktemplate name="default">
    <information></information>
    <logos/>
    <grid cols="t22%;r100%;t22%;" rows="25;25;">
        <field valign="center" row="0" hadjust="true" col="0" name="author"
               displaylabel="true" align="left">
            <value>
                <translation lang="en">%author</translation>
            </value>
            <label>
                <translation lang="fr">Auteur</translation>
                <translation lang="en">Author</translation>
                <!-- ... one <translation> per language ... -->
            </label>
        </field>
    </grid>
</titleblocktemplate>
```

### 1.2 `<information>`

Free text, read as `.text()` of the first matching child (`sources/titleblocktemplate.cpp:264-272`),
written back as a text node (`:507-516`). No attributes. Purely descriptive (author/licence
notes shown in the template editor).

### 1.3 `<logos>` / `<logo>` (image *definitions*)

Parsed by `loadLogos` / `loadLogo` (`sources/titleblocktemplate.cpp:282-352`):

- Only `<logo>` elements that are **direct children of `<logos>`** are read (`:296-309`).
- `name` — **required**, else the logo is skipped (`:323-325`). This is the key other cells
  reference.
- `type` — defaults to `"png"` if absent (`:327`). Real templates use `svg`, `png`, `jpeg`.
- `storage` — defaults to `"base64"` (`:328`). Only two values are accepted:
  - `storage="xml"` — the logo is an inline `<svg>` element; the **first** `<svg>` descendant
    is serialised back to bytes (`:333-340`). Missing `<svg>` → logo skipped.
  - `storage="base64"` — the element's text content is base64-decoded (`:341-342`).
  - Any other value → `return false`, logo silently dropped (`:343-345`).

Save side (`:543-566`) writes `name`, `type`, `storage`, and then either the imported `<svg>`
subtree (only when `storage=="xml"` **and** `type=="svg"`, `:552`) or a base64 text node.

**[inference]** `storage="xml"` with `type != "svg"` loads (the reader only checks storage) but
will not round-trip: `saveLogo` would emit an element with neither `<svg>` child nor base64 text.

### 1.4 `<grid>`

`loadGrid` (`sources/titleblocktemplate.cpp:359-383`) takes the **first** `<grid>` child.
Both `rows` and `cols` attributes are **mandatory**; if either is missing the whole grid load
returns false and the template has no cells (`:371-374`).

Order of operations: `parseRows` → `parseColumns` → `initCells` → `loadCells` →
`applyRowColNums` → `applyCellSpans` (`:376-381`).

#### `rows` attribute

`parseRows` (`:391-414`). Semicolon-separated list; each item must match
`^([0-9]+)(?:px)?$` case-insensitively. Items that do not match are **silently dropped**
(no error, the row simply does not exist). Rows are therefore always absolute pixel heights.
Trailing `;` is fine (`Qt::SkipEmptyParts`, `:400`).

Examples from real templates: `rows="25;25;"`, `rows="10;10;10;10;10;10;"`,
`rows="15;15;15;15;"`.

#### `cols` attribute

`parseColumns` (`:422-464`). Semicolon-separated; each item matches one of:

| Pattern | Regex | Meaning (`QET::TitleBlockColumnLength`, `sources/qet.h:141-146`) |
|---|---|---|
| `120` or `120px` | `^([0-9]+)(?:px)?$` | `Absolute` — fixed pixels |
| `t22%` | `^([rt])([0-9]+)%$` | `RelativeToTotalLength` — 22% of the whole title block width |
| `r100%` | same | `RelativeToRemainingLength` — 100% of what is left after absolute + `t` columns |

Non-matching items are silently dropped. Serialisation is `TitleBlockDimension::toShortString()`
(`sources/titleblock/dimension.cpp:50-60`): prefix `t`/`r` for relative types, then the value,
then `px` for absolute or `%` for relative, then `;`.

Width resolution at render time — `columnsWidth(total_width)` (`sources/titleblocktemplate.cpp:838-903`):
1. Absolute columns keep their value; `t` columns become `round(total_width * v / 100)`.
   Both are summed into `abs_widths_sum` (`:847-858`).
2. `remaining_width = total_width - abs_widths_sum` (`:861`).
3. `r` columns become `round(remaining_width * v / 100)` (`:864-872`).
4. Rounding drift up to `0.5px * (number of relative columns)` is redistributed over the
   relative columns (`:875-901`); larger drift is left alone.

Template height is simply the sum of row heights — `height()` (`:1090-1097`). This is what
`BorderTitleBlock::titleBlockRect()` uses as the strip thickness (`sources/bordertitleblock.cpp:88-100`).

### 1.5 Cells: `<field>` and `<logo resource=...>`

`loadCells` (`sources/titleblocktemplate.cpp:473-487`) walks the **direct children of `<grid>`**
and only handles tag names `field` and `logo`. Anything else (including `<empty>`, `<cell>`) is
ignored.

`checkCell` (`:658-711`) validates placement before any content is read:

- `row` and `col` must both be present and parse as integers, and must satisfy
  `0 <= row < rows_count` and `0 <= col < cols_count` (`:672-681`). Out of range → the cell is
  **silently discarded**.
- The target slot must still be empty and not covered by another cell's span (`:687-691`);
  a second cell claiming the same slot is discarded.
- `rowspan` / `colspan` are optional integers, stored as-is if `> 0` (`:697-705`); the actual
  clamping happens later in `applyCellSpans()` / `checkCellSpan()` (`:2054-2131`).

`TitleBlockCell::loadContentFromXml` (`sources/titleblockcell.cpp:163-223`) then reads content:

Common:
- `name` — the cell's internal identifier (`value_name`), only set if present and non-empty
  (`:165-167`). Note: real templates frequently ship `name=""`; that is legal.

`<logo resource="...">` (cell that *places* a logo):
- Requires a non-empty `resource` attribute; only then does the cell become a `LogoCell`
  (`:170-174`). `resource` must match a `<logo name="...">` in `<logos>`.
- Example: `<logo rowspan="1" row="0" col="0" name="" resource="qelectrotech.svg"/>`
  (`titleblocks/single-logo.titleblock`).

`<field>` (text cell):
- `<value>` → a `NamesList` of `<translation lang="xx">…</translation>` children
  (`sources/titleblockcell.cpp:178-186`); this is the string containing the `%variables`.
- `<label>` → same structure; the translated caption printed before the value.
- `displaylabel` — only the literal case-insensitive `"false"` turns the label off (`:195-199`);
  any other value (or absence) leaves it true.
- `fontsize` — integer; absent/invalid → `-1` meaning "use the default" (`:200-205`).
- `align` — `"left"` (default) / `"center"` / `"right"` (`:210-213`).
- `valign` — `"center"` (default) / `"top"` / `"bottom"` (`:215-218`).
- `hadjust` — `true` unless the attribute is present and not exactly the string `"true"`
  (`:221`). It shrinks text horizontally to fit.

Save side (`sources/titleblockcell.cpp:229-272` + `sources/titleblocktemplate.cpp:620-644`):
`saveCell` first creates an element literally named `cell`, sets `row`/`col` and any
`rowspan`/`colspan`, then `saveContentToXml` **renames** the tag to `empty`, `logo`, or `field`.
`saveCells` (`:599-609`) skips empty cells entirely, so a saved template never contains
`<empty>` — confirmed: `grep -c "<empty" titleblocks/*.titleblock` is 0 for all ten files.

The `<translation>` tag/attribute names are not hard-coded in `NamesList`; the cell passes
`TagName="translation"`, `ParentTagName="value"`/`"label"` (`sources/titleblockcell.cpp:178-190`),
and the language attribute defaults to `lang`
(`sources/NameList/nameslist.cpp:215-228`). Language pick order at render time
(`nameslist.cpp:261-277`): exact UI locale → base language (`de` from `de_DE`) → `en` →
supplied fallback → first entry.

---

## 2. Variables (placeholders)

### 2.1 Syntax

`TitleBlockTemplate::interpreteVariables` (`sources/titleblocktemplate.cpp:1810-1823`):

```cpp
foreach (QString key, diagram_context.keys(DiagramContext::DecreasingLength)) {
    interpreted_string.replace("%{" % key % "}", diagram_context[key].toString());
    interpreted_string.replace("%"  % key,       diagram_context[key].toString());
}
```

Consequences an MCP server must know:

- **Both `%{name}` and `%name` are supported.** They are plain string replacements, not a parser.
- Keys are iterated **longest first** (`DecreasingLength`). That is the only reason `%folio`
  does not eat the front of `%folio-total`. If you invent a custom variable that is a prefix of
  another and rely on the bare `%` form, ordering still saves you — but a custom key that is a
  prefix of a *literal* piece of text will corrupt it (e.g. key `rev` turns the literal text
  `%revision` into `<value>ision`). **Prefer `%{name}` in new templates.**
- A variable that is not in the context is left in the output verbatim.
- `listOfVariables()` (`:1830-1854`) — used by the UI to auto-populate the "Custom" tab — only
  recognises the braced form (`%\{([^}]+)\}`, `:1836`). Custom variables written as `%name`
  will **not** be offered in the folio properties dialog.

Label/value assembly is `finalTextForCell` (`:1783-1799`): when `display_label` is true and the
label is non-empty, the rendered string is `" <label> : <value>"`; otherwise `" <value>"`
(note the leading space in both cases).

### 2.2 The context: `DiagramContext`

`sources/diagramcontext.h` / `.cpp`. A key→QVariant map plus a per-key `show` flag.

**Key validation** (`sources/diagramcontext.cpp:234-256`):

```cpp
QString DiagramContext::validKeyRegExp() { return("^[a-z0-9-_]+$"); }
```

`addValue()` returns `false` and **stores nothing** if the key does not match
(`:94-101`). There is no warning. Lowercase letters, digits, `-`, `_` only — no uppercase,
no spaces, no dots, no accents.

**XML form** (`:151-168` / `:174-180`):

```xml
<properties>
    <property show="1" name="71-nextpg">2</property>
</properties>
```

- Tag name defaults to `property` but is a parameter; title-block properties use the default.
- `name` attribute is required on read (`:176`); an element without it is skipped.
- `show` defaults to `"1"` when absent (`:178`).
- Values are text nodes, `trimmed()` on write (`:164`).
- Real examples: `examples/industrial.qet` (`71-nextpg`), `examples/photovoltaique.qet`
  (`date`, `title`, `filename`, `folio`, `author` with empty text).

### 2.3 Built-in variables

Injected per folio by `BorderTitleBlock::updateDiagramContextForTitleBlock`
(`sources/bordertitleblock.cpp:897-931`). These are added **last** and therefore
**override** any project-level or folio-level custom field of the same name (`:910-928`):

| Variable | Source | Notes |
|---|---|---|
| `author` | `<diagram author>` | |
| `date` | `<diagram date>` | Rendered via `QLocale::system().toString(date, QLocale::ShortFormat)` (`:914-916`) — **locale-dependent output** |
| `title` | `<diagram title>` | |
| `filename` | `<diagram filename>` | Free text, *not* the real file name |
| `plant` | `<diagram plant>` | installation, the `=` designation |
| `locmach` | `<diagram locmach>` | location, the `+` designation |
| `indexrev` | `<diagram indexrev>` | revision index |
| `version` | — | Always `QetVersion::displayedVersion()` (see §4 gotcha), not the XML attribute |
| `folio` | computed `btb_final_folio_` | after `%id`/`%total`/`%autonum` substitution |
| `folio-id` | int | 1-based folio index in the project |
| `folio-total` | int | number of folios |
| `auto_page_num` | `<diagram auto_page_num>` | name of the folio auto-numbering scheme |
| `previous-folio-num` | computed | final folio string of folio *n-1* (`:1005-1011`) |
| `next-folio-num` | computed | final folio string of folio *n+1* (`:1017-1022`) |

Project-wide variables, merged in *before* the above by
`QETProject::updateDiagramsFolioData` (`sources/qetproject.cpp:2124-2131`):

| Variable | Source |
|---|---|
| `projecttitle` | `<project title>` |
| `projectpath` | absolute path of the `.qet` |
| `projectfilename` | base name of the `.qet` |

Plus, refreshed on every save by `QETProject::write()` (`sources/qetproject.cpp:1118-1123`):

| Variable | Format |
|---|---|
| `saveddate` | locale short date |
| `saveddate-us` | `yyyy-MM-dd` |
| `saveddate-eu` | `dd-MM-yyyy` |
| `savedtime` | `HH:mm` |
| `savedfilename` | base name |
| `savedfilepath` | full path |

These `saved*` values are stored in the project's `<properties>` node, i.e. they are **written
to the file one save behind** — `write()` updates them *after* `toXml()` has already run
(`:1107` then `:1118`). So the `saveddate` inside a `.qet` is the date of the *previous* save.

The canonical name list is duplicated in two places worth cross-checking:
`sources/qetinformation.h:97-124` (constants) and
`sources/titleblock/templatecellwidget.cpp:443-472` (the user-facing help text).
The "reserved" set used to keep standard fields out of the Custom tab is
`sources/ui/titleblockpropertieswidget.cpp:495-504`.

### 2.4 Custom variables in practice

Shipped templates use them heavily and all obey the lowercase key rule, e.g.
`titleblocks/Societe-pour-Alstom2.titleblock`: `%{05-descr-constructeur}`, `%{08-rev-finale}`,
`%{22-rev-construct}` … ; `titleblocks/page_de garde.titleblock`: `%{nom-client}`,
`%{adresse-projet}`, `%{a-modif}`, `%{a-date}`, `%{a-verifie}`.

---

## 3. Storing templates inside a project

### 3.1 `<titleblocktemplates>`

Written by `QETProject::toXml` (`sources/qetproject.cpp:1015-1022`), only when the project's
embedded collection is non-empty. It is the **first** child of `<project>`, before
`<properties>`:

```xml
<project title="…" version="0.80">
    <titleblocktemplates>
        <titleblocktemplate name="Page de garde">
            <information/>
            <logos>…</logos>
            <grid …>…</grid>
        </titleblocktemplate>
        <titleblocktemplate name="DIN A4 ISO">…</titleblocktemplate>
    </titleblocktemplates>
    …
</project>
```

Read by `TitleBlockTemplatesProjectCollection::fromXml`
(`sources/titleblock/templatescollection.cpp:340-353`):

- Uses `QET::findInDomElement(root, "titleblocktemplates", "titleblocktemplate")` —
  **children of `<titleblocktemplates>` children of the root only**; no deep search
  (`sources/qet.cpp:370-394`).
- A `<titleblocktemplate>` without `name` is skipped (`:343`).
- **Duplicate names: the first one wins**, later ones are ignored (`:347`).
- The XML is stored verbatim and *not parsed* until a folio actually asks for that template
  (`:349-351`).

Confirmed present in `examples/Projet_vierge.qet`, `examples/industrial.qet`,
`examples/affuteuse_250h.qet`, `examples/iso_sfc_example.qet`, `examples/m_000.qet`,
`examples/tableau_domestique.qet`.

`deleteUnusedTitleBlocKTemplates()` (`:358-367`) prunes embedded templates not referenced by
any folio; it is invoked from the UI, not on every save.

### 3.2 Filesystem collections

- Extension: `.titleblock` (`sources/titleblock/templatescollection.h:20`,
  `TITLEBLOCKS_FILE_EXTENSION`). File name == template name + extension
  (`templatescollection.cpp:558-560`).
- Three file collections, each with a URL protocol
  (`sources/qetapp.h:35-37`, wired at `sources/qetapp.cpp:456,477,497`):
  - `commontbt` — shipped templates, default directory
    `<applicationDirPath>/titleblocks/` (`sources/qetapp.cpp:790-799`), overridable at
    compile time; this is the repo-root `titleblocks/` directory.
  - `companytbt` — `elements-collections/company-tbt-path` setting (`:820-`).
  - `customtbt` — `elements-collections/custom-tbt-path` setting (`:853-`).
- Embedded project collection protocol is `project<id>+embedtbt`
  (`templatescollection.cpp:177`).
- A location string is `protocol://name` (`templatelocation.cpp:135-137`), parsed back at
  `:107-130`.
- The hard-wired fallback template is the Qt resource `:/titleblocks/default.titleblock`
  (`sources/qetapp.cpp:1576-1585`), registered in `qelectrotech.qrc:189`. When a folio's
  template name is unknown/removed, `BorderTitleBlock` falls back to it
  (`sources/bordertitleblock.cpp:431-441`).

### 3.3 The ten shipped templates

| File | `rows` | `cols` | fields | logo defs |
|---|---|---|---|---|
| `default.titleblock` | `25;25;` | `t22%;r100%;t22%;` | 5 | 0 |
| `A4_1.titleblock` | `10;` ×6 | 14 `t*%` columns | 36 | 1 |
| `DIN_A4.titleblock` | `10;` ×4 | 13 `t*%` + `r100%` | 36 | 1 |
| `ISO7200_A4_V1.titleblock` | `15;` ×4 | `r100%;50px;70px;165px;215px;35px;100px;35px;35px;` | 17 | 3 |
| `Societe-pour-Alstom2.titleblock` | `10;` ×11 | `25px;r100%;30px;…` | 57 | 4 |
| `Societe-pour-SNCF2.titleblock` | `10;` ×11 | `25px;r100%;30px;…` | 56 | 4 |
| `double-logo.titleblock` | `25;25;` | `50px;r25%;r50%;r25%;50px;` | 5 | 1 |
| `single-logo.titleblock` | `25;25;` | `50px;r25%;r50%;r25%;` | 5 | 1 |
| `page_de garde.titleblock` | 24 rows | 14 columns | 51 | 6 |
| `see-technical.titleblock` | `11;` ×6 | `130px;100px;25px;50px;100px;25px;t22%;r100%;50px;` | 32 | 4 |

Note `default.titleblock` and the two logo templates use the **bare** `%author` / `%date` /
`%title` / `%filename` form, while the newer ones use `%{…}`.

---

## 4. `--set-titleblock` — exact behaviour

CLI surface (`sources/cli_export.h:56`, `:70-73`; flag registered at
`sources/cli_export.cpp:78`; dispatched at `:832-833`):

```
qelectrotech --set-titleblock <project.qet> <output.qet> key=value [key=value ...]
```

Implementation: `setTitleBlock()` at `sources/cli_export.cpp:676-755`.

### 4.1 Parsing (fail-fast, before anything is written)

`:686-701`

- Each argument must contain `=` at index `> 0` (`:687-691`); otherwise
  `"Bad assignment '…' (expected key=value)."` and exit code **2**.
- Value is everything after the **first** `=` (`:693`), so `title=a=b` sets title to `a=b`.
- If the key is `date` (case-insensitive) the value must be either `today`
  (case-insensitive) or a valid `Qt::ISODate` string, i.e. `YYYY-MM-DD` (`:694-699`);
  otherwise `"Bad date '…' (expected YYYY-MM-DD or 'today')."`, exit **2**.
- Arguments are kept in order and applied in order, so a later assignment to the same key wins.

### 4.2 Application (`apply` lambda, `:703-725`)

The key is lowercased for matching (`:705`) — `--set-titleblock Title=x` works.

| CLI key (case-insensitive) | `TitleBlockProperties` field | XML attribute written on `<diagram>` and `<inset>` |
|---|---|---|
| `title` | `title` | `title` |
| `author` | `author` | `author` |
| `filename` | `filename` | `filename` |
| `plant` | `plant` | `plant` |
| `location` | `locmach` | `locmach` |
| `revision` | `indexrev` | `indexrev` |
| `version` | `version` | `version` (see gotcha below) |
| `date` | `date` + `useDate = UseDateValue` | `date` as `yyyyMMdd` |

**Note the two renames**: CLI `location` → XML `locmach`; CLI `revision` → XML `indexrev`.
There is no CLI key for `folio` or `auto_page_num`.

### 4.3 "Any other key becomes a custom field" — concretely

`:722-723`:

```cpp
else // unknown key -> custom title-block field
    p.context.addValue(f.first, v);
```

- The **original-case** key (`f.first`, not the lowercased `k`) is passed to
  `DiagramContext::addValue`.
- `addValue` enforces `^[a-z0-9-_]+$` (`sources/diagramcontext.cpp:94-101, 234-256`) and
  **returns false without storing anything** for a non-matching key.
- `setTitleBlock` ignores that return value, and still reports
  `"Stamped N field(s) on M folio(s)"` (`:752-753`).

So: **`--set-titleblock in.qet out.qet Client=ACME` silently does nothing**, while
`client=ACME` works. Valid custom keys: lowercase ASCII letters, digits, `-`, `_`.
Examples that work: `client`, `71-nextpg`, `rev_note`, `08-rev-finale`.
Examples that are silently dropped: `Client`, `rev note`, `client.name`, `révision`, `réf`.

A stored custom field appears as a `<property>` under a `<properties>` child of the folio's
`<diagram>` element (and of `<newdiagrams>/<inset>`), written by
`TitleBlockProperties::toXml` (`sources/titleblockproperties.cpp:96-100`):

```xml
<diagram … title="Mains Power Supply" indexrev="B" date="20260822" …>
    <properties>
        <property show="1" name="client">ACME</property>
    </properties>
    …
</diagram>
```

The `<properties>` node is only emitted when the context is non-empty (`:96`).

### 4.4 `date=today`

`:714-721`:

```cpp
p.date = (v.compare("today", Qt::CaseInsensitive) == 0)
         ? QDate::currentDate()
         : QDate::fromString(v, Qt::ISODate);
p.useDate = TitleBlockProperties::UseDateValue;
```

`today` is resolved to the **machine date at the moment the CLI runs** and then frozen as a
literal date. It does **not** write the dynamic `date="now"` marker. The serialisation is
`TitleBlockProperties::exportDate()` (`sources/titleblockproperties.cpp:214-224`):

| `useDate` / `date` | attribute value |
|---|---|
| `UseDateValue`, null date | `"null"` |
| `UseDateValue`, real date | `yyyyMMdd`, e.g. `20260822` |
| `CurrentDate` | `"now"` |

Read side `setDateFromString` (`:231-242`): `"now"` → today + `CurrentDate`;
`""` or `"null"` → null date + `UseDateValue`; anything else → `QDate::fromString(s,"yyyyMMdd")`.
An unparseable date string yields a **null QDate**, which then re-serialises as `"null"` —
so a bad hand-written `date` attribute silently erases the date on the next save.

**Format asymmetry to remember: the CLI takes ISO `YYYY-MM-DD`; the XML stores `yyyyMMdd`.**

### 4.5 What gets touched

`:727-741`

1. `project.defaultTitleBlockProperties()` → `apply()` → `setDefaultTitleBlockProperties()`.
   This is the `<newdiagrams>/<inset>` node — the template for *future* folios.
2. Every existing folio: `exportTitleBlock()` → `apply()` → `importTitleBlock()`
   (`sources/bordertitleblock.cpp:288-340`).

Then `project.toXml()` is serialised with `doc.toString(4)` to the output path
(`:743-751`) — 4-space indent, and, unlike `QET::writeXmlFile`
(`sources/qet.cpp:654-694`), it goes through a plain `QFile` opened with `QIODevice::Text`,
so **line endings are platform-native (CRLF on Windows)** whereas a normal GUI save
deliberately avoids `QIODevice::Text` to force LF (`sources/qet.cpp:658`).

Exit codes: `0` success, `1` cannot open output, `2` usage/parse error.

### 4.6 Gotchas specific to `--set-titleblock`

1. **`version=` is a no-op on folios.** `BorderTitleBlock::importTitleBlock` ignores
   `ip.version` and hard-sets `btb_version_ = QetVersion::displayedVersion()`
   (`sources/bordertitleblock.cpp:322`). So each `<diagram version="…">` becomes the QET build
   string (e.g. `0.200.1-dev`, `sources/qetversion.cpp:24-50`), not your value. The
   `<newdiagrams>/<inset version="…">` node *does* keep what you set, because that path never
   goes through `BorderTitleBlock`.
2. **`date="now"` is destroyed by any CLI write.** `exportTitleBlock()` constructs a fresh
   `TitleBlockProperties` (`sources/bordertitleblock.cpp:290`) whose `useDate` defaults to
   `UseDateValue` (`sources/titleblockproperties.cpp:26-31`) and never copies the flag back
   — `BorderTitleBlock` does not store `useDate` at all (see its member list,
   `bordertitleblock.h:245-262`). A folio saved with `date="now"` therefore comes back as a
   frozen `yyyyMMdd`. This applies to `--resave` and to a GUI save too.
3. **`titleblocktemplateCollection` is always rewritten to `embedded` for folios**, because
   `exportTitleBlock()` hard-codes `ip.collection = QET::QetCollection::Embedded`
   (`sources/bordertitleblock.cpp:305`).
4. **`setDefaultTitleBlockProperties` can pull a template in from disk.** If the default
   properties carry a non-empty `template_name` whose collection is *not* `Embedded`, it calls
   `integrateTitleBlockTemplate()` (`sources/qetproject.cpp:558-582`), copying that
   `.titleblock` file into the project's `<titleblocktemplates>`. Since
   `qetCollectionFromString` falls back to `Common` for any unrecognised/absent string
   (`sources/qet.cpp:739-751`), a hand-written `<inset titleblocktemplate="X">` **without**
   `titleblocktemplateCollection` will make the CLI look for `X.titleblock` in the installed
   common collection.
5. The project's own `<properties>` (project-wide variables) is **not** touched by
   `--set-titleblock`; only folio-level and new-folio-default contexts are.

---

## 5. Folio (diagram) properties

### 5.1 The `<diagram>` element

`Diagram::toXml` creates `<diagram>` (`sources/diagram.cpp:819`) and immediately calls
`titleBlockToXml` then `borderToXml` (`:823-825`), both of which set **attributes** on it.
`QETProject::toXml` then adds `order` (1-based position) after appending
(`sources/qetproject.cpp:1053`).

Attributes written by `TitleBlockProperties::toXml`
(`sources/titleblockproperties.cpp:77-101`) — always all of them:

| Attribute | Type | Notes |
|---|---|---|
| `author` | string | |
| `title` | string | also `Diagram::title()` (`sources/diagram.cpp:2135-2138`) |
| `filename` | string | |
| `plant` | string | |
| `locmach` | string | |
| `indexrev` | string | |
| `version` | string | overwritten with the app version, see §4.6 |
| `folio` | string | may contain `%id`, `%total`, `%autonum` |
| `auto_page_num` | string | folio auto-numbering scheme name |
| `date` | `yyyyMMdd` \| `now` \| `null` | |
| `displayAt` | `bottom` \| `right` | anything other than `bottom` reads back as `right` (`:119`) |
| `titleblocktemplate` | string | **only if non-empty** (`:90-94`) |
| `titleblocktemplateCollection` | `common`\|`company`\|`custom`\|`embedded` | only alongside the previous one |

The default template writes **neither** template attribute, because
`BorderTitleBlock::titleBlockTemplateName()` maps the name `"default"` to `""`
(`sources/bordertitleblock.cpp:403-407`).

Attributes written by `BorderTitleBlock::borderToXml` (`sources/bordertitleblock.cpp:232-243`):

| Attribute | Meaning | Default |
|---|---|---|
| `cols` | number of columns | 17 |
| `colsize` | column width in px | 60.0 |
| `displaycols` | `"true"`/`"false"` — show column headers | true |
| `rows` | number of rows | 8 |
| `rowsize` | row height in px | 80.0 |
| `displayrows` | `"true"`/`"false"` | true |
| `height` | `rows*rowsize + columns_header_height`, legacy 0.1-era attribute | derived |

Defaults come from `BorderProperties::BorderProperties()`
(`sources/borderproperties.cpp:35-45`): 17 columns × 60 px wide, 20 px column-header height;
8 rows × 80 px high, 20 px row-header width.

Real example (`examples/industrial.qet`):

```xml
<diagram freezeNewElement="false" titleblocktemplate="DIN A4 ISO" cols="18"
         folio="%id" version="0.80c+87c957a06d79751d3" indexrev="1.0"
         date="20180901" author="IM" height="740" freezeNewConductor="false"
         titleblocktemplateCollection="embedded" title="Mains Power Supply"
         auto_page_num="Name of the new numbering" displaycols="true" filename=""
         colsize="60" order="4" displayrows="true" locmach="-IGC"
         conductorAutonum="Wire" rows="9" plant="" rowsize="80"
         displayAt="bottom">
```

### 5.2 Border geometry and clamping

`sources/bordertitleblock.cpp:34-37`:

```
MIN_COLUMN_COUNT 3
MIN_ROW_COUNT    3
MIN_COLUMN_WIDTH 5.0
MIN_ROW_HEIGHT   5.0
```

- `setColumnsCount` / `setRowsCount`: `qMax(MIN_*, value)` (`:751`, `:804`).
- `setColumnsWidth` / `setRowsHeight`: `qMax(MIN_*, value)` (`:770`, `:823`).
- `setColumnsHeaderHeight` / `setRowsHeaderWidth`: `qBound(5.0, value, 50.0)`
  (`:785`, `:838`).

**`columns_header_height` and `rows_header_width` are never serialised.**
`BorderProperties::toXml` (`sources/borderproperties.cpp:99-107`) and `fromXml` (`:118-125`)
only handle `cols/colsize/rows/rowsize/displaycols/displayrows`; `borderToXml` likewise. They
always come from the application `QSettings` defaults (20 px each). This means header sizes
cannot be set per-project through XML.

Backward compatibility in `borderFromXml` (`:262-274`): if `rows` **and** `rowsize` are both
present they are used; otherwise the legacy `height` attribute is converted via
`setDiagramHeight()` (`:851-855`), which rounds up to a whole number of rows.
`displaycols`/`displayrows` are true unless the attribute is exactly the string `"false"`
(`:277-278`) — note this differs from `BorderProperties::fromXml`, which treats anything
other than `"true"` as false (`sources/borderproperties.cpp:123-124`). Same file, two
different truthiness rules.

Derived geometry (`sources/bordertitleblock.h:56-99`):

```
diagramWidth  = cols * colsize + rows_header_width
diagramHeight = rows * rowsize + columns_header_height
titleBlockRect: bottom edge → (diagram width) × (template height)
                right  edge → (template height) × (diagram height), painter rotated -90°
```

`convertPosition()` (`sources/bordertitleblock.cpp:864-878`) maps a scene point to a grid
label such as `B7`, with letters incremented `A…Z, AA…` (`incrementLetters`, `:942-959`).

### 5.3 The folio string

`setFolioData(index, total, autonum, project_properties)` (`sources/bordertitleblock.cpp:975-999`):

1. `btb_final_folio_ = btb_folio_`.
2. `%autonum` → the auto-numbering value, and this **rewrites `btb_folio_` itself**
   (`:991-994`), so the substitution is destructive and persists to the saved XML.
3. `%id` → 1-based index, `%total` → folio count (`:995-996`).
4. Calls `updateDiagramContextForTitleBlock(project_properties)`.

Default `folio` value from settings is `"%id/%total"`
(`sources/titleblockproperties.cpp:172`).

### 5.4 Project-level nodes

`QETProject::toXml` (`sources/qetproject.cpp:999-1070`), children of `<project>` in order:

```xml
<project title="…" version="…">          <!-- version via QetVersion::toXmlAttribute, :1004 -->
  <titleblocktemplates>…</titleblocktemplates>   <!-- only if non-empty, :1015 -->
  <properties>…</properties>                     <!-- project-wide DiagramContext, :1025 -->
  <usage …/>                                     <!-- local time tracking, :1030 -->
  <newdiagrams>                                  <!-- :1033 -->
    <border cols=… colsize=… rows=… rowsize=… displaycols=… displayrows=…/>
    <inset author=… title=… date=… …>            <!-- TitleBlockProperties, tag is "inset" -->
        <properties><property …/></properties>
    </inset>
    <conductors …/>
    <report label="…"/>
    <xrefs><xref …/></xrefs>
    <conductors_autonums …/> <folio_autonums …/> <element_autonums …/> <guides …/>
  </newdiagrams>
  <diagram order="1" …>…</diagram>
  <diagram order="2" …>…</diagram>
  <terminal_strips>…</terminal_strips>           <!-- only if non-empty, :1057 -->
  <collection>…</collection>                     <!-- embedded elements, :1067 -->
</project>
```

**The default title block node is `<inset>`, not `<titleblock>`** — historical French
("cartouche"). Mapping is in `readDefaultPropertiesXml`
(`sources/qetproject.cpp:1726-1743`): `border`→`BorderProperties`,
`inset`→`TitleBlockProperties`, and the write side at `:1857-1864`.

Read order at load (`sources/qetproject.cpp:1527-1557`): project `<properties>` → usage →
`<newdiagrams>` → embedded title block templates → embedded elements collection → diagrams →
**terminal strips last** (`:1557`), because strips resolve element UUIDs that only exist once
the diagrams are built.

`readProjectPropertiesXml` (`:1680-1684`) merges **every** direct `<properties>` child of
`<project>`; `readDefaultPropertiesXml` uses `elementsByTagName("newdiagrams")` and takes the
first (`:1706-1709`) — that one *is* a document-wide search, so a stray `<newdiagrams>` nested
anywhere could be picked up.

---

## 6. Terminal strips

### 6.1 What the feature is

A terminal strip (French *bornier*, German *Klemmenleiste*) is a named physical rail of
terminals in a cabinet. In QET it is a **project-level object** that groups terminal *elements*
already drawn on folios, adds ordering, multi-level grouping, and bridging, and can be drawn
onto a folio as a table-like graphics item.

Object model (`sources/TerminalStrip/`):

```
QETProject
 └── TerminalStrip                 (terminalstrip.h:44)  — installation/location/name/comment/uuid
      ├── TerminalStripData        (terminalstripdata.h) — the descriptive fields + uuid
      ├── QVector<PhysicalTerminal>(physicalterminal.h)  — ordered; = one terminal block on the rail
      │    └── QVector<RealTerminal>(realterminal.h)     — one per *level* of that block
      │         └── Element* (a TerminalElement on a diagram)
      └── QVector<TerminalStripBridge> (terminalstripbridge.h) — colored jumpers across RealTerminals
```

- **RealTerminal** wraps one terminal `Element` on a folio (or, by design, a "reserved"
  terminal with no element — `realterminal.h:33-38`). It exposes `label()`, `Xref()`,
  `conductor()`, `level()`, `type()`, `function()` (`realterminal.cpp:122-180`).
- **PhysicalTerminal** is one multi-level terminal block. Index order **is** the level order,
  back (mounting plate) → front (door) — the ASCII diagram at `physicalterminal.h:39-58`.
- **TerminalStripBridge** carries a `QUuid` and a `QColor` and a set of bridged RealTerminals
  (`terminalstripbridge.cpp:80-121`).
- A terminal element is eligible to be added only if it is *free*:
  `ElementProvider::freeTerminal()` returns every element whose
  `elementData().m_type == ElementData::Terminal` and which has no parent strip
  (`sources/elementprovider.cpp:197-218`). An element is `terminal` when its `.elmt`
  definition says `type="terminal"` (`sources/properties/elementdata.cpp:676`, `:702`).
- Terminal kind info on the element: `kindInformation` entries named `type`
  (`generic|fuse|sectional|diode|ground`, `elementdata.cpp:830-865`) and `function`
  (`generic|phase|neutral`, `:884-911`).

UI lives in `sources/TerminalStrip/ui/` (editor window, creator dialog, layout editor,
free-terminal editor); undo commands in `sources/TerminalStrip/UndoCommand/`; the on-folio
graphics item and its drawer in `sources/TerminalStrip/GraphicsItem/`.

### 6.2 `<terminal_strips>` in the project root

Written by `QETProject::toXml` (`sources/qetproject.cpp:1057-1064`), read by
`readTerminalStripXml` (`:1811-1824`) using `firstChildElement("terminal_strips")` — so the
container must be a **direct child of `<project>`**, and only the first one is read.

Full shape (tag names from `TerminalStrip::xmlTagName()` `terminalstrip.h:120`,
`TerminalStripData::xmlTagName()` `terminalstripdata.h:40`,
`PhysicalTerminal::xmlTagName()` `physicalterminal.cpp:222-224`,
`RealTerminal::xmlTagName()` `realterminal.cpp:287`,
`TerminalStripBridge::xmlTagName()` `terminalstripbridge.h:46`):

```xml
<terminal_strips>
  <terminal_strip>
    <terminal_strip_data uuid="{…}">
      <informations>
        <information name="installation">=</information>
        <information name="location">+</information>
        <information name="name">X1</information>
        <information name="comment">…</information>
        <information name="description">…</information>
      </informations>
    </terminal_strip_data>
    <layout>
      <physical_terminal>
        <real_terminal element_uuid="{…}"/>   <!-- level 0, back -->
        <real_terminal element_uuid="{…}"/>   <!-- level 1 -->
      </physical_terminal>
      <physical_terminal>
        <real_terminal element_uuid="{…}"/>
      </physical_terminal>
    </layout>
    <terminal_strip_bridge uuid="{…}" color="#ff0000">
      <real_terminals>
        <real_terminal uuid="{…}"/>
        <real_terminal uuid="{…}"/>
      </real_terminals>
    </terminal_strip_bridge>
  </terminal_strip>
</terminal_strips>
```

Element-by-element rules:

**`<terminal_strip_data>`** (`terminalstripdata.cpp:31-85`)
- `uuid` attribute holds the strip identity, in Qt brace form `{xxxxxxxx-…}`
  (`QUuid::toString()`, `:35`).
- Children are `<information name="…">value</information>` inside a single `<informations>`
  wrapper; only the five names above are recognised, anything else is ignored (`:77-81`).
- An empty field is **omitted** on write (`:40-54`), so absence means empty.
- Defaults if the node is missing: `installation = "="`, `location = "+"`, everything else
  empty (`terminalstripdata.h:47-52`).
- On read, a wrong root tag aborts with a qDebug message and returns false (`:61-66`).

**`<layout>`** (`terminalstrip.cpp:1011-1046`)
- Contains the ordered `<physical_terminal>` list. **Document order is the strip order** —
  there is no index/position attribute.
- Each `<real_terminal element_uuid="…">` is resolved against the project's *free* terminal
  elements (`:1015-1016`, `:1026-1037`). Order inside a `<physical_terminal>` is the level
  order.
- A resolved element is removed from the candidate pool (`:1034`), so **the first
  `<physical_terminal>` that claims a uuid wins**; a duplicate reference elsewhere silently
  resolves to nothing.
- A `<physical_terminal>` whose real terminals all fail to resolve is **dropped entirely**
  (`:1040-1043`) — the strip silently shrinks.
- `<real_terminal>` here carries **`element_uuid`**; in the bridge node the very same tag name
  carries **`uuid`** instead. They are not interchangeable.

**`<terminal_strip_bridge>`** (`terminalstripbridge.cpp:80-121`)
- Direct child of `<terminal_strip>`, read with `QETXML::directChild` (`terminalstrip.cpp:1049`).
- `uuid` — bridge identity; `color` — parsed by `QColor(QString)`, so any Qt-accepted name or
  `#rrggbb` (`:109`). An invalid string yields an invalid QColor without error.
- `<real_terminals>/<real_terminal uuid="…">` where `uuid` is the **element** uuid of the
  bridged real terminal (`:93` writes `real_t->elementUuid()`), resolved via
  `TerminalStrip::realTerminalForUuid` (`:116`). Unresolvable entries are skipped silently.
- Because bridges are read after the layout (`terminalstrip.cpp:1048-1056`), a bridge can only
  reference terminals already placed in `<layout>` of the *same* strip.

**UNVERIFIED:** none of the `.qet` files in `examples/` or `tests/` contains a
`<terminal_strips>` element (`grep -rl "<terminal_strip" --include=*.qet .` returns nothing;
the `terminal_strips` hits in `examples/industrial.qet` etc. are element library paths such as
`embed://import/10_electric/10_allpole/130_terminals&amp;terminal_strips/borne_continuite.elmt`).
To settle the exact on-disk shape: open a project with terminal elements in the GUI, create a
strip in the Terminal Strip editor, save, and inspect. Everything above is read directly from
the serialisers and is believed exact.

### 6.3 Terminal strips drawn on a folio

A strip may additionally be *placed* on a diagram as a `TerminalStripItem`
(`sources/TerminalStrip/GraphicsItem/terminalstripitem.h:29`, `Type = UserType + 1011`).
This is a **reference**, not a copy.

Serialised by `sources/xml/terminalstripitemxml.cpp` (tag constants at `:28-29`):

```xml
<diagram …>
  …
  <terminal_strip_items>
    <terminal_strip_item>
      <terminal_strip uuid="{…}"/>
      <pos x="123" y="456" z="0"/>
    </terminal_strip_item>
  </terminal_strip_items>
</diagram>
```

- Written from `Diagram::toXml` at `sources/diagram.cpp:1073-1075`, only when at least one
  item exists.
- `toXml` returns a **null element** — i.e. the item is silently dropped — if the item has no
  associated strip (`terminalstripitemxml.cpp:87, 99-101`).
- `<terminal_strip uuid>` is matched against `QETProject::terminalStrip()` by uuid
  (`:122-131`); on failure the uuid is remembered in `m_pending_strip_uuid` and the item stays
  unbound (`:123`).
- `<pos>` uses attributes `x`, `y`, `z`, each defaulting to `0`
  (`sources/qetxml.cpp:934-955`).
- `fromXml` returns true only if **both** the strip resolved *and* the `<pos>` element was
  found (`:137`).
- Read from `Diagram::fromXml` at `sources/diagram.cpp:1497`.

Note the nesting confusion to avoid: `terminal_strip` appears as (a) a strip definition under
`<terminal_strips>`, and (b) a uuid-only reference under `<terminal_strip_item>`. Same tag name,
completely different content.

### 6.4 Layout patterns (present but unwired)

`sources/xml/terminalstriplayoutpatternxml.cpp` defines a `terminal_strip_layout_pattern` tag
(`:24`) with `TerminalStripLayoutPattern` objects. Grepping the tree, nothing outside that
`.cpp`/`.h` pair calls `TerminalStripLayoutPatternXml`. **[inference]** it is not part of the
project save format today; do not emit it.

---

## 7. Gotchas when writing these nodes by hand

Title block / folio:

1. **Custom field keys must match `^[a-z0-9-_]+$`** or `DiagramContext::addValue` drops them
   with no error (`sources/diagramcontext.cpp:94-101, 234-256`). This bites both hand-written
   `<property name="…">` and `--set-titleblock Key=value`.
2. **`<property>` without a `name` attribute is skipped** (`diagramcontext.cpp:176`).
   `show` defaults to `1`.
3. **The default-folio node is `<inset>`, not `<titleblock>`** (`qetproject.cpp:1728`, `:1862`).
4. **`date` in XML is `yyyyMMdd`, not ISO.** Anything unparseable becomes a null date and is
   rewritten as `date="null"` on the next save (`titleblockproperties.cpp:231-242`).
5. **`date="now"` does not survive a save.** See §4.6 #2.
6. **`version=` on a `<diagram>` is always overwritten** with the QET build string
   (`bordertitleblock.cpp:322`).
7. **`titleblocktemplate` without `titleblocktemplateCollection`** resolves the collection to
   `common` (`qet.cpp:739-751`), which makes QET look for `<name>.titleblock` on disk instead
   of in the project's `<titleblocktemplates>` — and, via
   `setDefaultTitleBlockProperties`, may copy that file into the project
   (`qetproject.cpp:558-582`). For an embedded template always write
   `titleblocktemplateCollection="embedded"`.
8. **`titleblocktemplate="default"` is wrong** — the built-in default is expressed by
   *omitting* both attributes (`bordertitleblock.cpp:403-407`).
9. **Duplicate `<titleblocktemplate name="X">` entries: only the first survives**
   (`templatescollection.cpp:347`).
10. **`displaycols`/`displayrows` truthiness is inconsistent**: `BorderTitleBlock::borderFromXml`
    treats "not the string `false`" as true (`bordertitleblock.cpp:277-278`), while
    `BorderProperties::fromXml` treats "not the string `true`" as false
    (`borderproperties.cpp:123-124`). Always write the exact literals `true` / `false`.
11. **`colsize` and `rowsize` are read with `toInt()` in `BorderProperties::fromXml`**
    (`borderproperties.cpp:120,122`) although the field is `qreal` and the writer uses
    `QString("%1").arg(qreal)`. A fractional `colsize="60.5"` in `<newdiagrams>/<border>`
    parses as `0`, which then clamps to the minimum. `BorderTitleBlock::borderFromXml` uses
    `toDouble()` (`bordertitleblock.cpp:257,268`), so `<diagram>` and `<border>` disagree.
12. **Counts and sizes are clamped**, not rejected: `cols>=3`, `rows>=3`, sizes `>=5.0`,
    header sizes bounded to `[5,50]` (`bordertitleblock.cpp:34-37, 751, 770, 785, 804, 823, 838`).
13. **`columns_header_height` / `rows_header_width` cannot be persisted** — no XML attribute
    exists for them (`borderproperties.cpp:99-107`).
14. **`%autonum` inside `folio` is consumed destructively**: after the first
    `setFolioData()` the literal is replaced in `btb_folio_` itself
    (`bordertitleblock.cpp:991-994`), so it will not be re-expanded after a save.
15. **`%name` variable substitution is a raw string replace.** A custom key that is a prefix
    of literal text in the cell will mangle it. Prefer `%{name}`; note also that only
    `%{…}` variables are discovered by `listOfVariables()`
    (`titleblocktemplate.cpp:1830-1854`), so `%name`-style custom variables never appear in
    the folio Custom-fields UI.
16. **`saveddate` / `savedtime` / … lag one save behind** (`qetproject.cpp:1107` vs `:1118`).
17. **Template out-of-range cells vanish silently.** `row`/`col` outside the grid, or a slot
    already taken/spanned, means the `<field>`/`<logo>` is simply not loaded
    (`titleblocktemplate.cpp:658-691`) — the rendered title block just has a hole.
18. **`<grid>` without both `rows` and `cols` yields a template with no cells at all**
    (`titleblocktemplate.cpp:371-374`), and malformed items inside those attributes are
    dropped one by one, silently shifting every subsequent `row`/`col` index.
19. **A `<titleblocktemplate>` without `name` fails to load entirely**
    (`titleblocktemplate.cpp:128-130`).
20. **`--set-titleblock` output uses `QIODevice::Text`** (`cli_export.cpp:745`) so it can emit
    CRLF, unlike the GUI save path which deliberately avoids it (`qet.cpp:658`). Byte-level
    diffs between a GUI save and a CLI save are expected.

Terminal strips:

21. **`<terminal_strips>` must be a direct child of `<project>`** — read via
    `firstChildElement` (`qetproject.cpp:1814`); a nested one is invisible.
22. **`element_uuid` must reference a terminal-type element that is not already claimed.**
    Non-terminal elements are never candidates (`elementprovider.cpp:207`), and the first
    claimant of a uuid wins (`terminalstrip.cpp:1034`).
23. **A `<physical_terminal>` with no resolvable `<real_terminal>` is deleted**, silently
    changing the strip's terminal numbering (`terminalstrip.cpp:1040-1043`).
24. **Two different attribute names for the same tag**: `<real_terminal element_uuid>` under
    `<layout>`, `<real_terminal uuid>` under `<real_terminals>` in a bridge
    (`realterminal.cpp:83` vs `terminalstripbridge.cpp:93`).
25. **Order is positional.** There is no `pos`/`index` attribute on `<physical_terminal>`;
    reordering the XML reorders the strip.
26. **Bridges are resolved after layout and only within the same strip**
    (`terminalstrip.cpp:1048-1056`, `terminalstripbridge.cpp:116`); a cross-strip bridge
    silently loses its terminals.
27. **A `<terminal_strip_item>` whose uuid matches no strip stays unbound and its
    `fromXml` returns false** (`terminalstripitemxml.cpp:113-138`); QET keeps the item on the
    diagram with a pending uuid rather than deleting it.
28. **`<terminal_strip_data>` omits empty fields**, so round-tripping a strip whose comment
    you cleared removes the node rather than writing an empty one
    (`terminalstripdata.cpp:49-54`).
29. **UUID format is Qt's braced form** (`{8-4-4-4-12}`). `QUuid::fromString` on an unbraced
    string works in Qt 5.10+, but write braced to match what QET produces
    (`terminalstripdata.cpp:35`).

---

## 8. Quick reference — tag/attribute inventory

Title block template (`.titleblock` file, or inside `<titleblocktemplates>`):

```
titleblocktemplate[@name]
  information                          (text)
  logos
    logo[@name @type @storage]         type: svg|png|jpeg…, storage: xml|base64
      svg                              (when storage="xml")
      #text                            (base64, when storage="base64")
  grid[@rows @cols]
    field[@row @col @rowspan @colspan @name @displaylabel @fontsize @align @valign @hadjust]
      value / translation[@lang]
      label / translation[@lang]
    logo[@row @col @rowspan @colspan @name @resource]
```

Project:

```
project[@title @version]
  titleblocktemplates / titleblocktemplate…
  properties / property[@name @show]
  newdiagrams
    border[@cols @colsize @rows @rowsize @displaycols @displayrows]
    inset[@author @title @filename @plant @locmach @indexrev @version @folio
          @auto_page_num @date @displayAt @titleblocktemplate
          @titleblocktemplateCollection]
      properties / property[@name @show]
    …
  diagram[@order + all inset attributes + @cols @colsize @rows @rowsize
          @displaycols @displayrows @height]
    properties / property[@name @show]
    terminal_strip_items / terminal_strip_item
      terminal_strip[@uuid]
      pos[@x @y @z]
  terminal_strips
    terminal_strip
      terminal_strip_data[@uuid]
        informations / information[@name]
      layout / physical_terminal / real_terminal[@element_uuid]
      terminal_strip_bridge[@uuid @color]
        real_terminals / real_terminal[@uuid]
  collection …
```
