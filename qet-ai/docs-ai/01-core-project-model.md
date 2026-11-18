# QElectroTech — Core Document / Project Model

Source tree documented: `/root/qet/qelectrotech-source-mirror`
All `path:LINE` citations are relative to that root unless the path already starts with `sources/`.
Declared code version at time of writing: `QVersionNumber{0, 200, 1}` — `sources/qetversion.cpp:26`.

Legend:
- Unmarked statements were read directly in the source at the cited line.
- `[inference]` = deduced, not stated literally in the source.
- `UNVERIFIED:` = could not be settled from the source; the test that would settle it is named.

---

## 1. Purpose

This subsystem is the persistence and in-memory object model of a QElectroTech *project*: a single
`.qet` file that is one XML document containing (a) project-wide metadata and defaults, (b) zero or
more *folios* (`Diagram`, one drawing page each), (c) the graphical/logical content of each folio
(elements, conductors, texts, images, shapes, tables, terminal-strip items), and (d) a **complete
embedded copy of every element definition used by the project**, so the file is self-contained and
portable. `QETProject` owns the whole tree, `Diagram` owns one folio's `QGraphicsScene`,
`XmlElementCollection` owns the embedded element library, `ElementsLocation` is the URI-like handle
that binds a diagram's `<element type="...">` reference to a definition in one of the collections
(`common://`, `company://`, `custom://`, `macros://`, `embed://`), and `DiagramContext` is the generic
`key -> QVariant` bag used for every "information" set (project properties, title-block variables,
element information).

---

## 2. The `.qet` file structure

### 2.1 How the file is produced

```cpp
QDomDocument QETProject::toXml();                 // sources/qetproject.cpp:999
QETResult    QETProject::write();                 // sources/qetproject.cpp:1087
bool QET::writeXmlFile(QDomDocument &, const QString &filepath, QString *error);  // sources/qet.cpp:654
```

`write()` builds the document with `toXml()` (`sources/qetproject.cpp:1107`) and hands it to
`QET::writeXmlFile` (`sources/qetproject.cpp:1109`). Serialisation details, all verified in
`sources/qet.cpp:654-690`:

- `QSaveFile`, opened **without** `QIODevice::Text`, so line endings are LF even on Windows
  (`sources/qet.cpp:656-659`).
- UTF-8, **no BOM** (`sources/qet.cpp:673-680`).
- `xml_doc.toString(4)` — indent 4 spaces (`sources/qet.cpp:681`).
- No `<?xml ... ?>` declaration is created anywhere in `toXml()`; the document is built from a bare
  `QDomDocument` and only `createElement("project")` is appended (`sources/qetproject.cpp:1002-1012`).
  Example files confirm: `examples/741.qet` starts directly with `<project ...>`.
  `[inference]` A hand-written file *may* carry an XML declaration — `QDomDocument::setContent` accepts
  it — but QET itself never writes one.

There is a second, functionally identical writer used for element files and other XML:
`QETXML::writeXmlFile` (`sources/qetxml.cpp:257`), used by `ElementsLocation::setXml`
(`sources/ElementsCollection/elementslocation.cpp:753`).

### 2.2 Root element

```xml
<project version="0.200.1" title="My project">
```

- `version` — written by `QetVersion::toXmlAttribute(project_root)` (`sources/qetproject.cpp:1004`),
  which unconditionally writes the **current** running version, not the version the file was created
  with: `xml.setAttribute("version", currentVersion().toString())` (`sources/qetversion.cpp:59-62`).
- `title` — `project_root.setAttribute("title", project_title_)` (`sources/qetproject.cpp:1011`). If the
  title is empty at save time it is first replaced by the file's `completeBaseName()`
  (`sources/qetproject.cpp:1005-1010`).

On read, `readProjectXml` **requires** `documentElement().tagName() == "project"`; anything else sets
`m_state = ProjectParsingFailed` and aborts (`sources/qetproject.cpp:1462`, `1519-1524`).
Version handling on read (`sources/qetproject.cpp:1465-1515`):
- `version` missing → `QVersionNumber()` (null), all checks skipped (`sources/qetversion.cpp:72-79`).
- `version` newer than the running build → **modal warning dialog**, user may cancel
  (`sources/qetproject.cpp:1469-1496`).
- `version <= 0.60` → another modal warning dialog (`sources/qetproject.cpp:1500-1514`);
  `versionZeroDotSix()` is `QVersionNumber{0, 60}` (`sources/qetversion.cpp:82`).

### 2.3 Children of `<project>`, in the exact order `toXml()` appends them

| # | Tag | Condition | Written at |
|---|-----|-----------|-----------|
| 1 | `<titleblocktemplates>` | only if the project embeds ≥1 title-block template | `sources/qetproject.cpp:1015-1023` |
| 2 | `<properties>` | always | `sources/qetproject.cpp:1025-1027` |
| 3 | `<usage>` | always | `sources/qetproject.cpp:1030` → `sources/project/projectusagetracker.cpp:98-105` |
| 4 | `<newdiagrams>` | always | `sources/qetproject.cpp:1033-1035` |
| 5 | `<diagram>` × N | one per folio, in `m_diagrams_list` order | `sources/qetproject.cpp:1042-1054` |
| 6 | `<terminal_strips>` | only if `m_terminal_strip_vector` is non-empty | `sources/qetproject.cpp:1057-1064` |
| 7 | `<collection>` | always (the embedded element collection root) | `sources/qetproject.cpp:1067` |

**Reader order is NOT the same as writer order**, and most readers do not care about position — see
§6.2. Read order in `readProjectXml` is: properties, usage, newdiagrams, titleblocktemplates,
**elements collection**, diagrams, terminal strips, then `refresh()` and DB update
(`sources/qetproject.cpp:1528`, `1531`, `1534`, `1537`, `1549`, `1553`, `1557`). The collection is deliberately parsed *before* the diagrams,
because diagram elements resolve against it.

### 2.4 `<titleblocktemplates>`

```xml
<titleblocktemplates>
  <titleblocktemplate name="Page de garde">
    <information/>
    <logos>
      <logo name="logo.jpeg" type="jpeg" storage="base64">...</logo>
    </logos>
    ...
  </titleblocktemplate>
</titleblocktemplates>
```

Each `<titleblocktemplate>` is stored verbatim; `toXml()` imports the cached DOM node without
re-analysis (`sources/qetproject.cpp:1017-1021`, `sources/titleblock/templatescollection.cpp:231-236`).
On read, `TitleBlockTemplatesProjectCollection::fromXml` walks
`findInDomElement(project_root, "titleblocktemplates", "titleblocktemplate")`, i.e. **direct child of
`<project>` → direct child of that** (`sources/titleblock/templatescollection.cpp:340-353`).
Requirements: a `name` attribute is mandatory (templates without it are skipped,
`templatescollection.cpp:343`); on duplicate names the **first** wins (`templatescollection.cpp:347`).
Sample: `examples/Projet_vierge.qet` line 1 onward.

### 2.5 `<properties>` — project-wide variables

`writeProjectPropertiesXml` delegates to `DiagramContext::toXml(e)` with the default tag name
(`sources/qetproject.cpp:1829-1831`, `sources/diagramcontext.cpp:145-163`).

```xml
<properties>
  <property show="1" name="saveddate">21/08/2026</property>
  <property show="1" name="savedfilename">myproject</property>
</properties>
```

- Child tag is `property` (the `tag_name` default `"property"`, `sources/diagramcontext.h:114`; the default
  is used because `writeProjectPropertiesXml` passes no tag name).
- Attributes: `show` (int, from `m_content_show`) and `name` (the key)
  (`sources/diagramcontext.cpp:155-158`). The value is a **text node**, trimmed
  (`sources/diagramcontext.cpp:159-160`).
- Read: `readProjectPropertiesXml` uses `QET::findInDomElement(documentElement(), "properties")` —
  **direct children of `<project>` only** — and merges every match (`sources/qetproject.cpp:1682-1683`).
- `DiagramContext::fromXml` skips any `<property>` without a `name` attribute; `show` defaults to `"1"`
  (`sources/diagramcontext.cpp:169-175`).

The keys QET itself writes here on every save (`sources/qetproject.cpp:1117-1122`): `saveddate`,
`saveddate-us`, `saveddate-eu`, `savedtime`, `savedfilename`, `savedfilepath`. Note these are set
**after** the file is written, so they always describe the *previous* save in the file on disk.

### 2.6 `<usage>` — local, non-transmitted time tracking

```xml
<usage time_spent="3812" enabled="true"/>
```

`sources/project/projectusagetracker.cpp:98-105` (write) and `112-121` (read). `time_spent` is seconds
(`qint64`), `enabled` is `"true"`/`"false"` and any value other than the literal `"false"` reads as
true (`projectusagetracker.cpp:120`). Read via `firstChildElement("usage")` of the project root
(`projectusagetracker.cpp:114`), so it must be a **direct child of `<project>`**. Missing element is
fine — the reader returns early (`projectusagetracker.cpp:115-117`). None of the example `.qet` files
in `examples/` contain it (`grep -l "<usage" examples/*.qet` returns nothing), so it is a recent
addition and is optional for a hand-written file.

### 2.7 `<newdiagrams>` — defaults applied to newly created folios

Written by `writeDefaultPropertiesXml` (`sources/qetproject.cpp:1852-1935`), children appended in this
exact order:

```xml
<newdiagrams>
  <border cols="17" colsize="60" rows="8" rowsize="80" displaycols="true" displayrows="true"/>
  <inset author="" title="" filename="" plant="" locmach="" indexrev="" version=""
         folio="%id/%total" auto_page_num="" date="20100921" displayAt="bottom"
         titleblocktemplate="..." titleblocktemplateCollection="common">
     <properties><property show="1" name="foo">bar</property></properties>   <!-- only if context non-empty -->
  </inset>
  <conductors ... />
  <report label="%f-%l%c"/>
  <xrefs>
    <xref type="coil" showpowerctc="false" showterminalname="false" displayhas="contacts"
          snapto="bottom" xrefpos="AlignBaseline" offset="40"
          master_label="%f-%l%c" slave_label="(%f-%l%c)"
          powerprefix="" delayprefix="" switchprefix=""/>
  </xrefs>
  <conductors_autonums current_autonum="" freeze_new_conductors="false" auto_break_conductors="false">
    <conductor_autonum title="rule1" formula="%sequ_1">
      <part type="unit" value="1" increase="1"/>
    </conductor_autonum>
  </conductors_autonums>
  <folio_autonums>
    <folio_autonum title="rule1"><part .../></folio_autonum>
  </folio_autonums>
  <element_autonums current_autonum="" freeze_new_elements="false">
    <element_autonum title="rule1" formula="%sequ_1"><part .../></element_autonum>
  </element_autonums>
  <guides>
    <guide orientation="0" position="120" color="#ff0000"/>
  </guides>
</newdiagrams>
```

Element-by-element sources:
- `<border>` attributes: `BorderProperties::toXml` — `cols`, `colsize`, `rows`, `rowsize`,
  `displaycols`, `displayrows` (`sources/borderproperties.cpp:99-107`).
- `<inset>` attributes: `TitleBlockProperties::toXml` — `author`, `title`, `filename`, `plant`,
  `locmach`, `indexrev`, `version`, `folio`, `auto_page_num`, `date`, `displayAt`
  (`"bottom"` or `"right"`), plus `titleblocktemplate` + `titleblocktemplateCollection` **only when a
  template name is set** (`sources/titleblockproperties.cpp:77-100`). `titleblocktemplateCollection`
  takes one of `common` / `company` / `custom` / `embedded`; anything unrecognised falls back to
  `common` (`sources/qet.cpp:716-751`). Extra title-block variables are a nested `<properties>` child
  with `<property>` children (`sources/titleblockproperties.cpp:96-100`).
- `<conductors>`: `ConductorProperties::toXml`. Attribute set observed in
  `examples/741.qet`: `type`, `num`, `formula`, `text_color`, `numsize`, `condsize`, `displaytext`,
  `onetextperfolio`, `horizrotatetext`, `vertirotatetext`, `horizontal-alignment`,
  `vertical-alignment`, `bicolor`, `color2`, `dash-size`, `function`, `tension_protocol`,
  `conductor_color`, `conductor_section`, `cable`, `bus`.
- `<report label="...">` — `sources/qetproject.cpp:1874-1876`; read back with
  `setDefaultReportProperties(report_elmt.attribute("label"))` (`sources/qetproject.cpp:1750`).
- `<xrefs>` / `<xref>` — `XRefProperties::toXml` (`sources/properties/xrefproperties.cpp:106-135`).
  The `type` attribute is the XRef key (e.g. `coil`), and every entry in `m_prefix` becomes an
  attribute named `<key>prefix` (`xrefproperties.cpp:130-132`). Read by
  `findInDomElement(xref_elmt, "xref")` keyed on `type` (`sources/qetproject.cpp:1751-1760`).
- `<conductors_autonums>` — attributes `current_autonum`, `freeze_new_conductors`,
  `auto_break_conductors` (`sources/qetproject.cpp:1888-1891`). Only rules with a non-empty key **and**
  a non-empty formula are written (`sources/qetproject.cpp:1894-1899`). Read at
  `sources/qetproject.cpp:1761-1773`; the two booleans are compared literally against `"true"`.
- `<folio_autonums>` / `<folio_autonum title="...">` — no `formula` attribute, no filtering
  (`sources/qetproject.cpp:1902-1909`; read `sources/qetproject.cpp:1774-1783`).
- `<element_autonums>` — attributes `current_autonum`, `freeze_new_elements`
  (`sources/qetproject.cpp:1912-1914`), same non-empty filtering as conductors
  (`sources/qetproject.cpp:1916-1921`); read `sources/qetproject.cpp:1784-1794`.
- `<part>` children of every `*_autonum`: `NumerotationContext::toXml`
  (`sources/autoNum/numerotationcontext.cpp:173-195`) — attributes `type`, `value`, `increase`,
  plus `initialvalue` for `unitfolio`/`tenfolio`/`hundredfolio`, plus `modulus` for `wrap`, plus
  optional `format`.
- `<guides>` / `<guide orientation="0|1" position="<double>" color="#rrggbb">`
  (`sources/qetproject.cpp:1925-1933`; read `sources/qetproject.cpp:1796-1808`, defaults
  `orientation=0`, `position=0.0`, `color=#ff0000`).

Read entry point: `readDefaultPropertiesXml` (`sources/qetproject.cpp:1703`). If `<newdiagrams>` is
absent the function returns immediately and *all* defaults come from the global QET settings
(`sources/qetproject.cpp:1706-1707`). Otherwise it resets to global defaults first, then overlays what
the file provides (`sources/qetproject.cpp:1712-1717`). Unknown children are ignored — the dispatch is
an explicit `if/else if` chain on tag name (`sources/qetproject.cpp:1722-1743`).

### 2.8 `<diagram>` — one folio

Produced by `Diagram::toXml(whole_content = true)` (`sources/diagram.cpp:813`), imported into the
project document and given an `order` attribute (`sources/qetproject.cpp:1049-1053`).

Attributes on `<diagram>` (in the order the code sets them):
1. Title-block fields, set on the root by `border_and_titleblock.titleBlockToXml(dom_root)`
   (`sources/diagram.cpp:824` → `sources/bordertitleblock.cpp:212-214` →
   `sources/titleblockproperties.cpp:77-100`): `author`, `title`, `filename`, `plant`, `locmach`,
   `indexrev`, `version`, `folio`, `auto_page_num`, `date`, `displayAt`, and optionally
   `titleblocktemplate` + `titleblocktemplateCollection`.
2. Border fields, `border_and_titleblock.borderToXml(dom_root)` (`sources/diagram.cpp:825` →
   `sources/bordertitleblock.cpp:232-243`): `cols`, `colsize`, `displaycols`, `rows`, `rowsize`,
   `displayrows`, and the legacy-compat `height`.
3. `conductorAutonum` — only when non-empty (`sources/diagram.cpp:834-837`).
4. `freezeNewElement` — always, `"true"`/`"false"` (`sources/diagram.cpp:840-841`).
5. `freezeNewConductor` — always (`sources/diagram.cpp:844-846`).
6. `order` — 1-based, added by the project (`sources/qetproject.cpp:1053`).
7. `projectId` — **only** in the copy/paste path (`whole_content == false`), never in a saved file
   (`sources/diagram.cpp:934-938`).

Children of `<diagram>`, in write order:

```xml
<diagram title="..." author="..." cols="17" rows="8" order="1"
         freezeNewElement="false" freezeNewConductor="false">
  <properties>            <!-- only if the title block has extra variables -->
    <property show="1" name="custom-var">value</property>
  </properties>
  <defaultconductor ... />                       <!-- always -->
  <elementautonumfoliosequentials>...</elementautonumfoliosequentials>   <!-- optional -->
  <conductorautonumfoliosequentials>...</conductorautonumfoliosequentials> <!-- optional -->
  <elements>   <element .../> ... </elements>            <!-- omitted when empty -->
  <conductors> <conductor .../> ... </conductors>        <!-- omitted when empty -->
  <inputs>     <input .../> ... </inputs>                <!-- omitted when empty -->
  <images>     <image .../> ... </images>                <!-- omitted when empty -->
  <shapes>     <shape .../> ... </shapes>                <!-- omitted when empty -->
  <tables>     <graphics_table .../> ... </tables>       <!-- omitted when empty -->
  <terminal_strip_items> <terminal_strip_item .../> </terminal_strip_items> <!-- omitted when empty -->
</diagram>
```

Citations: `<properties>` comes from the title block context (`sources/titleblockproperties.cpp:96-100`);
`<defaultconductor>` `sources/diagram.cpp:828-832`; folio-sequential blocks `sources/diagram.cpp:849-931`;
`<elements>` `sources/diagram.cpp:1021-1031`; `<conductors>` `sources/diagram.cpp:1033-1040`;
`<inputs>` (independent texts, child tag `input`) `sources/diagram.cpp:1042-1048` and
`sources/qetgraphicsitem/independenttextitem.cpp:83`; `<images>` `sources/diagram.cpp:1050-1056`;
`<shapes>` `sources/diagram.cpp:1058-1064`; `<tables>` with child tag `graphics_table`
`sources/diagram.cpp:1066-1072` and `sources/.../qetgraphicstableitem.h:92`;
`<terminal_strip_items>` with child tag `terminal_strip_item`
`sources/diagram.cpp:1074-1075`, `sources/xml/terminalstripitemxml.cpp:28-29`.

`if (items().isEmpty()) return document;` at `sources/diagram.cpp:942-943` — an empty folio has only
its attributes and (if present) `<properties>` / `<defaultconductor>` / sequential blocks.

Reader: `Diagram::fromXml(QDomElement&, ...)` (`sources/diagram.cpp:1296`). It rejects anything whose
tag name is not `diagram` (`sources/diagram.cpp:1303-1305`); no attribute is mandatory. Child lookups
all use `QET::findInDomElement(root, "<container>", "<item>")`, i.e. **exactly two levels: a direct
child container, then its direct children** (`sources/qet.cpp:370-393`).

### 2.9 `<element>` inside `<diagram><elements>`

Written by `Element::toXml(QDomDocument&, QHash<Terminal*,int>&)`
(`sources/qetgraphicsitem/element.cpp:911`).

```xml
<element type="embed://import/oznaczenia/tekst_08.elmt"
         uuid="{52d4b9e8-05c3-49a2-8455-a42ff651200a}"
         prefix=""
         freezeLabel="false"
         x="390" y="570" z="10" orientation="0">
  <sequentialNumbers><unit>1</unit></sequentialNumbers>   <!-- only if it has children -->
  <terminals>
    <terminal x="0" y="3" orientation="s" id="0"/>
  </terminals>
  <inputs/>                                <!-- always present, always EMPTY -->
  <links_uuids>                            <!-- only when the element is linked -->
    <link_uuid uuid="{...}" group_index="0"/>
  </links_uuids>
  <elementInformations>                    <!-- only when non-empty -->
    <elementInformation show="1" name="label">Q1</elementInformation>
  </elementInformations>
  <properties>                             <!-- terminal-type elements only -->
    <element_type terminal_type="generic" terminal_function="phase" terminal_led="false"/>
  </properties>
  <plcMasterData rowHeight="...">...</plcMasterData>   <!-- PLC master elements only -->
  <dynamic_texts>
    <dynamic_elmt_text x="0" y="0" rotation="0" uuid="{...}" frame="false"
                       text_width="-1" font="..." text_from="ElementInfo"
                       Halignment="AlignLeft" Valignment="AlignTop">
      <text>Q1</text>
      <info_name>label</info_name>
      <composite_text>%{label}</composite_text>
      <color>#ff0000</color>
    </dynamic_elmt_text>
  </dynamic_texts>
  <texts_groups>
    <texts_group .../>
  </texts_groups>
</element>
```

Field-by-field:
- `type` = `m_location.path()` = `ElementsLocation::m_collection_path`
  (`sources/qetgraphicsitem/element.cpp:919`, `sources/ElementsCollection/elementslocation.cpp:223-226`).
  For an embedded element this is `embed://import/...`; for a filesystem element
  `common://...` / `company://...` / `custom://...` / `macros://...`.
- `uuid` = `QUuid::toString()`, i.e. **braced** form `{xxxxxxxx-....}`
  (`sources/qetgraphicsitem/element.cpp:922`).
- `prefix` (`element.cpp:925`), `freezeLabel` `"true"`/`"false"` (`element.cpp:928`).
- `<sequentialNumbers>` is appended only if `seq.hasChildNodes()` (`element.cpp:931-933`); its
  children are `<unit>`, `<wrap>`, `<unitFolio>`, `<ten>`, `<tenFolio>`, `<hundred>`, … each a
  `;`-joined list (`sources/autoNum/assignvariables.cpp:103-140`).
- `x`, `y` (`QString::number(pos().x/y())`), `z` (`zValue()`), `orientation` (int 0..3, meaning
  *quarter turns*: `setRotation(90 * read_ori)`) — `element.cpp:936-939`, read at
  `element.cpp:804-816`. An `orientation` outside `[0,3]` or non-numeric silently becomes `0`
  (`element.cpp:812-815`).
- `<terminals>`: `Terminal::toXml` writes only `x`, `y`, `orientation`
  (`sources/qetgraphicsitem/terminal.cpp:714-725`); the `id` attribute is added by `Element::toXml`
  (`element.cpp:961`) and is a document-wide sequence shared by all elements of the folio, allocated
  as `max(existing ids) + 1` per element (`element.cpp:943-951`).
- `<inputs>` is created and appended but **never filled** (`element.cpp:968-969`) — a legacy husk.
- `<links_uuids>`/`<link_uuid uuid="..." group_index="N">` — only when `!isFree()`
  (`element.cpp:973-989`); `group_index` is written only when ≥ 0 (`element.cpp:981-984`), and defaults
  to `-1` on read (`element.cpp:778`).
- `<elementInformations>` with child tag `elementInformation` — only when the info map is non-empty
  (`element.cpp:992-997`). **`DiagramContext::toXml` skips keys whose trimmed value is empty when the
  tag name is `elementInformation`** (`sources/diagramcontext.cpp:147-150`) — this is specific to this
  tag name and does not apply to `<property>`.
- `<properties><element_type terminal_type= terminal_function= terminal_led=>` — written only when
  `m_data.m_type == ElementData::Terminal` (`element.cpp:1000-1013`), read via
  `QETXML::subChild(e, "properties", "element_type")` (`element.cpp:856`).
- `<plcMasterData>` — Master elements whose master type is PLC only (`element.cpp:1016-1023`,
  tag created at `sources/properties/elementdata.cpp:276`).
- `<dynamic_texts>` and `<texts_groups>` are **always appended**, even when empty
  (`element.cpp:1025-1068`). Child tags: `dynamic_elmt_text`
  (`sources/qetgraphicsitem/dynamicelementtextitem.h:104`) and `texts_group`
  (`sources/qetgraphicsitem/elementtextitemgroup.h:84`).
  Attributes of `dynamic_elmt_text`: `x`, `y`, `rotation`, `uuid`, `frame`, `text_width`, `font`,
  `keep_visual_rotation`, `rotation_point_center`, `text_from`, `Halignment`, `Valignment`; children
  `<text>`, optional `<info_name>`, optional `<composite_text>`, optional `<color>`
  (`sources/qetgraphicsitem/dynamicelementtextitem.cpp:90-149`).

Validation gate — `Element::valideXml` (`sources/qetgraphicsitem/element.cpp:692-709`). An `<element>`
node is **silently skipped** by `Diagram::fromXml` (`sources/diagram.cpp:1411`) unless *all* of:
- `tagName() == "element"`,
- it has a `type` attribute,
- it has `x` and `y` attributes,
- `x` and `y` both parse as `double`.
`uuid`, `orientation`, `z`, `prefix` are all optional. A missing `uuid` causes a fresh random one at
load time (`element.cpp:783`).

### 2.10 `<conductor>` inside `<diagram><conductors>`

Two mutually exclusive encodings — `Conductor::toXml`
(`sources/qetgraphicsitem/conductor.cpp:1053-1100`):

- **Modern (element/terminal UUIDs)**, used when the terminal has a non-null uuid:
  `element1`, `element1_label`, `element1_linked` (optional), `element1_name`,
  `terminal1` = *terminal uuid string*, `terminalname1`; same for `…2`
  (`conductor.cpp:1064-1078`, `1080-1093`).
- **Legacy (integer ids)**, used when the terminal uuid is null: `terminal1` / `terminal2` hold the
  integer id from the `table_adr_id` map (`conductor.cpp:1066`, `1082`).

Always: `uuid`, `x`, `y` (`conductor.cpp:1059-1061`).

`Conductor::valideXml` (`sources/qetgraphicsitem/conductor.cpp:604-624`) requires tag `conductor` plus
`terminal1` and `terminal2`; if `element1` is present, `element1` and `terminal1` must parse as
non-null `QUuid`s, otherwise `terminal1` must parse as `int`.

Resolution is done by the free function `findTerminal`
(`sources/diagram.cpp:1208-1265`): presence of the `element1`/`element2` attribute is the switch that
selects UUID matching over legacy-id matching (`sources/diagram.cpp:1219-1221`). UUID matching scans
`added_elements` for the element uuid, then that element's terminals for the terminal uuid
(`sources/diagram.cpp:1224-1234`). Terminal UUIDs come from the **element definition**
(`<terminal uuid="...">` inside `<definition><description>`,
`sources/properties/terminaldata.cpp:110`, read `terminaldata.cpp:167-174`), not from the diagram.

A conductor whose two terminals cannot both be resolved, or which resolve to the same terminal, is
silently dropped (`sources/diagram.cpp:1541-1552`).

### 2.11 `<terminal_strips>` (project level)

```xml
<terminal_strips>
  <terminal_strip .../>
</terminal_strips>
```

Written at `sources/qetproject.cpp:1057-1064`. The child tag is `TerminalStrip::xmlTagName()` =
`"terminal_strip"` (`sources/TerminalStrip/terminalstrip.h:120`). Read via
`documentElement().firstChildElement("terminal_strips")` — hence it **must be a direct child of
`<project>`** — then `QETXML::findInDomElement(xml_strips, "terminal_strip")`
(`sources/qetproject.cpp:1813-1822`).

Distinct from the per-folio `<terminal_strip_items>` (§2.8), which references a strip by uuid:
`<terminal_strip_item><terminal_strip uuid="{...}"/><position .../></terminal_strip_item>`
(`sources/xml/terminalstripitemxml.cpp:85-102`).

### 2.12 `<collection>` — the embedded element collection

Last child of `<project>`, a deep clone of `XmlElementCollection::root()`
(`sources/qetproject.cpp:1067`). Full structure documented in §3.

---

## 3. The embedded element collection

### 3.1 Shape of the tree

A fresh, empty collection is (verbatim from the constructor's own doc comment,
`sources/ElementsCollection/xmlelementcollection.cpp:28-34`, code at `:61-66`):

```xml
<collection>
  <category name="import">
    <names>
      <name lang="en">Imported elements</name>
      <name lang="fr">Éléments importés</name>
      ...
    </names>
  </category>
</collection>
```

Rules verified in `sources/ElementsCollection/xmlelementcollection.cpp`:
- Root tag is `collection` (`:61-63`). The alternate constructor **rejects** any other tag name and
  leaves the document empty (`:127-133`).
- Directories are `<category name="...">` (`:237-249`, `:632-641`).
- Elements are `<element name="foo.elmt">` containing exactly one `<definition>` child
  (`:459-464`, `:509-535`).
- Translated directory names are a `<names><name lang="xx">…</name></names>` child of `<category>`
  (`sources/NameList/nameslist.cpp:185-206`; read `:126-139` / `:151-172`).
- **All imported elements live under `<category name="import">`** — `addElement` always starts from
  `importCategory()` (`:381-386`) which is `root().firstChildElement("category")` (`:153-156`).
  Note: `importCategory()` returns the *first* `<category>` child regardless of its `name`.
  `[inference]` If a hand-written collection puts a different category first, every subsequent import
  lands under it instead.

Real sample (`examples/741.qet`):

```xml
<collection>
  <category name="import">
    <names><name lang="fr">Éléments importés</name>...</names>
    <category name="oznaczenia">
      <names><name lang="pl">Oznaczenia</name></names>
      <element name="tekst_08.elmt">
        <definition type="element" version="0.22" width="20" height="30" hotspot_x="10" hotspot_y="10">
          <names><name lang="pl">Tekst</name></names>
          <informations>Author: ...</informations>
          <description>
            <input x="3" y="0.333333" tagg="label" size="7" text="_"/>
            <terminal x="0" y="3" orientation="s"/>
          </description>
        </definition>
      </element>
    </category>
  </category>
</collection>
```

### 3.2 Path resolution

`XmlElementCollection::child(const QString &path)` splits on `"/"` and walks from `root()`
(`:213-235`). Each hop uses the two-argument `child()` which selects the tag to search by the
**suffix of the name**: names ending in `.elmt` are looked up as `<element>`, everything else as
`<category>`, matching on the `name` attribute (`:183-211`, decision at `:194-195`).

Therefore a path is collection-relative and **includes the leading `import` segment**:
`import/oznaczenia/tekst_08.elmt`.

- `element(path)` additionally requires the path to end in `.elmt` and the found node's tag to be
  `element` (`:325-341`).
- `directory(path)` requires the found node's tag to be `category` (`:343-352`).
- `exist(path)` is `!child(path).isNull()` (`:603-609`).
- The inverse, `domToLocation`, walks up the parents prepending every `<category name>` — the
  `<collection>` root contributes nothing because its tag is not `category` (`:721-743`). So the
  reconstructed path is again `import/…/foo.elmt`.

### 3.3 The URI schemes

`ElementsLocation` holds two strings: `m_collection_path` (the URI) and `m_file_system_path`
(`sources/ElementsCollection/elementslocation.h:99-101`).

`ElementsLocation::setPath` (`sources/ElementsCollection/elementslocation.cpp:236-350`):

1. **If `m_project` is already set** (constructor `ElementsLocation(path, project)`), the path is taken
   as-is and `embed://` is prepended when missing (`:245-250`). This is why
   `ElementsLocation("import/foo.elmt", project)` and
   `ElementsLocation("embed://import/foo.elmt", project)` are equivalent.
2. **If the string starts with `project`**, it is matched against
   `^project(?<project_id>[0-9])\+(?<collection_path>embed://*.*)$` (`:253-254`). The project is
   looked up in the global registry via `QETApp::project(project_id)` and, only if found, the
   collection path and project are set (`:262-268`).
   Note the regex captures a **single digit** here, unlike `QETApp::projectIdFromString` which uses
   `[0-9]+` (`sources/qetapp.cpp:2454-2455`).
   `[inference]` project ids ≥ 10 will fail to parse through `ElementsLocation::setPath` but succeed
   through `QETApp::projectIdFromString`.
   UNVERIFIED: whether any real workflow reaches 10 simultaneously open projects. Test: open 11
   projects and drag an element from the 11th project's embedded collection.
3. `common://`, `company://`, `custom://`, `macros://` are translated to absolute filesystem paths
   under `QETApp::commonElementsDirN()` etc. (`:270-297`).
4. A bare absolute filesystem path is stored and, if it lives under one of the known roots, the
   corresponding `xxx://` collection path is derived (`:299-347`).

Accessors:
- `path()` / `collectionPath(true)` → `"embed://import/foo.elmt"`
  (`:223-226`, `:177-186`).
- `collectionPath(false)` strips the scheme with the regex
  `common://|company://|custom://|macros://|embed://` → `"import/foo.elmt"` (`:181-185`).
- `projectCollectionPath()` → `"project" + QETApp::projectId(m_project) + "+" + collectionPath()`,
  i.e. **`project0+embed://import/foo.elmt`**; returns a null string for filesystem locations
  (`:193-202`).
- `toString()` is the same composition but omits the `projectN+` prefix when the project is not
  registered (`projectId() == -1`) (`:457-468`).

**Where each form appears:**
- `project0+embed://…` is a **runtime / UI / drag-and-drop** identifier. It is produced by
  `projectCollectionPath()` and consumed by `ElementsLocation::setPath` and
  `QETApp::projectIdFromString`. Call sites: the collection tree item
  (`sources/ElementsCollection/xmlprojectelementcollectionitem.cpp:90`), the collection handler
  (`sources/ElementsCollection/elementcollectionhandler.cpp:242,250,289`), copy operations
  (`sources/ElementsCollection/xmlelementcollection.cpp:820,869,926`), the add-element diagram event
  (`sources/diagramevent/diagrameventaddelement.cpp:208`), and rename in
  `sources/qetproject.cpp:1250`.
- `embed://…` (no project prefix) is the **on-disk** form: `Element::toXml` writes
  `m_location.path()` (`sources/qetgraphicsitem/element.cpp:919`), which is `m_collection_path`.
  Confirmed in `examples/741.qet`: `type="embed://import/oznaczenia/tekst_08.elmt"`.
  A `project0+embed://` value must **never** appear in a saved `<element type>` — it would not match
  `type_id.startsWith("embed://")` at `sources/diagram.cpp:1416` and would be passed to the
  project-less `ElementsLocation(type_id)` constructor, whose `setPath` would then try to resolve
  project id 0 against the live registry.

### 3.4 What must exist for a diagram `<element>` node to resolve

Trace, in order, for `<element type="embed://import/dir/foo.elmt" x="…" y="…">`:

1. `Element::valideXml` passes (§2.9) — `sources/diagram.cpp:1410`.
2. `type_id.startsWith("embed://")` → `ElementsLocation location(type_id, m_project)`
   (`sources/diagram.cpp:1414-1421`). Otherwise a project-less location is built and the definition is
   read from the user's filesystem collections.
3. `ElementFactory::createElement(location, nullptr, &state)`
   (`sources/diagram.cpp:1423-1426`) immediately fails with `state = 1` unless
   `location.isElement() && location.exist()` (`sources/factory/elementfactory.cpp:38-43`).
   - `isElement()` ⇔ the collection path ends in `.elmt` or `.qetmak`
     (`sources/ElementsCollection/elementslocation.cpp:474-477`).
   - `exist()` for a project location ⇔
     `project->embeddedElementCollection()->exist(collectionPath(false))`
     (`elementslocation.cpp:548-553`) ⇔ `XmlElementCollection::child("import/dir/foo.elmt")` is
     non-null (`xmlelementcollection.cpp:603-609`).
4. The factory reads `location.xml().attribute("link_type")` to pick the subclass
   (`sources/factory/elementfactory.cpp:49-64`): `next_report`/`previous_report` → `ReportElement`,
   `master` → `MasterElement`, `slave` → `SlaveElement`, `terminal` → `TerminalElement`, anything
   else (including a missing attribute) → `SimpleElement`.
   `ElementsLocation::xml()` for a project location returns
   `collection->element(path).firstChildElement("definition")`
   (`sources/ElementsCollection/elementslocation.cpp:651-684`, project branch `:665-678`).
5. The subclass constructor runs `Element::buildFromXml` on that `<definition>`
   (`sources/qetgraphicsitem/element.cpp:410`). It fails with:
   - `state = 4` if the tag is not `definition` **or** `type != "element"` (`element.cpp:414-421`);
   - `state = 5` if any of `width`, `height`, `hotspot_x`, `hotspot_y` is missing or not an integer
     (`element.cpp:434-446`);
   - `state = 6` if `<definition>` has no children (`element.cpp:451-457`);
   - `state = 8` if no drawing part could be loaded (documented at `element.cpp:406`).
6. Any non-zero state → the element is logged and dropped from the folio
   (`sources/diagram.cpp:1427-1437`).
7. `Element::fromXml` then applies the per-instance data (`sources/diagram.cpp:1441`). It returns
   `false` — and the element is removed again — if a terminal `id` in this element collides with an id
   already registered by an earlier element of the same folio
   (`sources/qetgraphicsitem/element.cpp:755-764`, removal at `sources/diagram.cpp:1441-1446`).

**Minimum viable embedded definition** (all attributes verified as required at
`sources/qetgraphicsitem/element.cpp:414-457`):

```xml
<collection>
  <category name="import">
    <category name="mydir">
      <element name="myelement.elmt">
        <definition type="element" width="20" height="20" hotspot_x="10" hotspot_y="10"
                    version="0.200.1" link_type="simple">
          <uuid uuid="{9b2fd0e0-....}"/>
          <names><name lang="en">My element</name></names>
          <description>
            <terminal x="0" y="10" orientation="s" uuid="{...}" name="" type="Generic"/>
          </description>
        </definition>
      </element>
    </category>
  </category>
</collection>
```

Referenced from a folio as `type="embed://import/mydir/myelement.elmt"`.

Other `<definition>` children QET reads (all optional):
- `<uuid uuid="{...}"/>` — read by `ElementsLocation::uuid()` via pugixml
  (`sources/ElementsCollection/elementslocation.cpp:835-850`); returns a null `QUuid` when absent.
  Written by the element editor at `sources/editor/elementscene.cpp:467-469`.
- `<names>` — `NamesList`, used for the displayed name (`elementslocation.cpp:874-879`).
- `<informations>` — free text, author/license (`sources/properties/elementdata.cpp:59-62`).
- `<kindInformations>` with `<kindInformation name="type">…</kindInformation>` children — master/slave/
  terminal metadata (`sources/qetgraphicsitem/element.cpp:466-468`,
  `sources/properties/elementdata.cpp:67-110`).
- `<elementInformations>` with `<elementInformation name="…">` children — the definition's default
  element information (`sources/qetgraphicsitem/element.cpp:470-473`).
- `<description>` — the graphic parts plus `<input>`, `<terminal>`, `<dynamic_text>`, `<plc_table>`
  (`sources/qetgraphicsitem/element.cpp:481-520`).

`link_type` accepted values (`sources/properties/elementdata.cpp:663-714`): `simple`, `next_report`,
`previous_report`, `master`, `slave`, `terminal`, `thumbnail`, `conductor_definition`. Unknown values
fall back to `simple` with a debug message (`elementdata.cpp:710-713`).

### 3.5 Import / copy paths

- `QETProject::importElement(ElementsLocation&)` (`sources/qetproject.cpp:1189-1285`) is the entry
  point. For a filesystem source the target path is `"import/" + collectionPath(false)`
  (`:1197-1199`); for a source in *another* project's collection, the source path is reused verbatim
  (`:1200-1206`). If the target already exists **and both have the same `<uuid>`**, the existing one
  is reused with no dialog (`:1213-1216`); otherwise the user is prompted Ignore / Erase / Rename
  (`:1218-1266`).
- `XmlElementCollection::addElement(ElementsLocation&)` (`:367-492`) creates the missing intermediate
  `<category>` nodes as it walks, pulling `qet_directory` translations from disk for the filesystem
  case (`:400-441`, helper `sources/qetxml.cpp:178-207`) or `NamesList` from the source project for
  the project case (`:445-484`). It returns the integrated path (`import/...`) or a null string.
  It refuses when the element already exists at `import/<path>` (`:378-379`).
- `XmlElementCollection::addElementDefinition(dir_path, elmt_name, xml_definition)` (`:511-537`)
  requires `dir_path` to be an existing `<category>` and `xml_definition.tagName() == "definition"`;
  it appends `.elmt` to the name if missing (`:544-547`).
- `ElementsLocation::setXml(QDomDocument&)` (`:739-826`) is the write path for a single element:
  requires `isWritable()` (a project location is writable iff the project is not read-only, `:575-593`)
  and a `definition` document element (`:744-751`); for an existing project element it removes and
  re-appends the node (`:765-775`), otherwise it splits the path with `^(.*)/(.*\.elmt)$` and calls
  `addElementDefinition` (`:778-820`).
- `ElementCollectionHandler` (`sources/ElementsCollection/elementcollectionhandler.h:63-121`) picks a
  strategy: `ECHSFileToFile`, `ECHSXmlToFile`, `ECHSToXml`.
- Cleanup: `cleanUnusedElement()` removes every embedded element not referenced by any folio
  (`:745-751`, using `QETProject::unusedElements()` at `sources/qetproject.cpp:1350-1359`);
  `cleanUnusedDirectory()` removes `<category>` nodes with no `<element>` and no `<category>`
  descendants (`:755-773`).

---

## 4. Key classes

### 4.1 `QETProject` — `sources/qetproject.h`, `sources/qetproject.cpp`

Owns: the diagram list `m_diagrams_list`, the embedded element collection `m_elements_collection`
(`XmlElementCollection*`), the embedded title-block collection `m_titleblocks_collection`, the
project-wide `DiagramContext m_project_properties`, all defaults for new folios, the auto-numbering
rule hashes, the `QUndoStack`, the SQLite-backed `projectDataBase m_data_base`, and the terminal-strip
vector (`sources/qetproject.h:277-335`).

```cpp
QETProject(QObject *parent = nullptr);                    // empty project
QETProject(const QString &path, QObject * = nullptr);     // sources/qetproject.cpp:99  — opens a file
QETProject(KAutoSaveFile *backup, QObject *parent);       // sources/qetproject.cpp:119 — crash recovery

ProjectState state() const;                               // sources/qetproject.h:110
QList<Diagram *> diagrams() const;                        // sources/qetproject.cpp:318
XmlElementCollection *embeddedElementCollection() const;  // sources/qetproject.h:113
QDomDocument toXml();                                     // sources/qetproject.cpp:999
QETResult    write();                                     // sources/qetproject.cpp:1087
ElementsLocation importElement(ElementsLocation &);       // sources/qetproject.cpp:1189
bool usesElement(const ElementsLocation &) const;         // sources/qetproject.cpp:1333
QList<ElementsLocation> unusedElements() const;           // sources/qetproject.cpp:1350
Diagram *addNewDiagram(int pos = -1);                     // sources/qetproject.h:217
QUuid uuid() const;                                       // sources/qetproject.cpp:192
```

`ProjectState` (`sources/qetproject.h:83-90`): `Ok=0`, `FileOpenFailed=1`, `XmlParsingFailed=2`,
`ProjectParsingRunning=3`, `ProjectParsingFailed=4`, `FileOpenDiscard=5`.

Lifecycle:
- `openFile(QFile*)` → `QDomDocument::setContent` → `readProjectXml` (`sources/qetproject.cpp:234-277`).
  On parse failure the state is `XmlParsingFailed` and `init()` is never called
  (`sources/qetproject.cpp:105-111`).
- `init()` wires the title-block collection signals, creates the undo stack, starts the crash-recovery
  backup timer (fires immediately once) and the optional autosave timer
  (`sources/qetproject.cpp:200-227`).
- `readProjectXml` sets `m_state = ProjectParsingRunning`, then, in order: properties, usage,
  newdiagrams, title-block templates, **elements collection**, diagrams, terminal strips, `refresh()`,
  DB update, `m_state = Ok` (`sources/qetproject.cpp:1528`, `1531`, `1534`, `1537`, `1549`, `1553`, `1557`, `1561`, `1578`).
- `refresh()` calls `Diagram::refreshContents()` on every folio (`sources/qetproject.cpp:284-303`).
- Destructor waits for the in-flight async backup, blocks DB signals, then deletes every diagram one
  at a time, removing each from the list as it goes (`sources/qetproject.cpp:153-175`).
- `m_uuid` is `QUuid::createUuid()` at construction and is **never serialised** — `grep m_uuid
  qetproject.cpp` yields only the getter at `:194`. It is a per-session identity, not a document id.

### 4.2 `Diagram` — `sources/diagram.h`, `sources/diagram.cpp`

A `QGraphicsScene` subclass representing one folio. Constructor and destructor are **private**, with
`QETProject` and `DiagramFolioList` as friends (`sources/diagram.h:55-63`), so folios can only be
created through the project.

Public data members that carry persisted state: `defaultConductorProperties` and
`border_and_titleblock` (a `BorderTitleBlock`) (`sources/diagram.h:85-87`), plus the six
folio-sequential hashes (`sources/diagram.h:106-112`).

```cpp
QDomDocument toXml(bool wholeContent = true, bool is_copy_command = false); // sources/diagram.cpp:813
bool initFromXml(QDomElement &, QPointF = {}, bool = true, DiagramContent * = nullptr); // :1182
bool fromXml(QDomElement &, QPointF = {}, bool = true, DiagramContent * = nullptr);     // :1296
QString title() const;              // sources/diagram.cpp:2135 — delegates to border_and_titleblock.title()
QETProject *project() const;
int folioIndex() const;
bool usesElement(const ElementsLocation &);   // sources/diagram.cpp:2197
QList<Element *> elements() const;            // sources/diagram.cpp:2144
QUuid uuid();                                 // runtime only, see below
```

`initFromXml` is a thin wrapper that just forwards to `fromXml` (`sources/diagram.cpp:1182-1197`),
despite the doc comment claiming it also initialises an internal XML document.

`m_uuid = QUuid::createUuid()` (`sources/diagram.h:134`) is **not serialised**; the persisted
folio identity for title-block variables is the position-derived `folio-id` (see §5).

Lifecycle: created by `QETProject::readDiagramsXml` (one per `<diagram>` node,
`sources/qetproject.cpp:1618-1633`) or by `addNewDiagram`. `QETProject::addDiagram` connects
`BorderTitleBlock::needFolioData` → `updateDiagramsFolioData` and
`Diagram::usedTitleBlockTemplateChanged` → the project slot (`sources/qetproject.cpp:1949-1954`,
same connections at `:1622-1626` on load). Deleted only by `QETProject::~QETProject` or
`removeDiagram`.

### 4.3 `XmlElementCollection` — `sources/ElementsCollection/xmlelementcollection.{h,cpp}`

Owns a standalone `QDomDocument m_dom_document` whose document element is `<collection>`
(`xmlelementcollection.h:123`). It is a `QObject` parented to the project
(`xmlelementcollection.cpp:38-41`). It never touches the filesystem for its own storage — the project
clones its root into the project document at save time (`sources/qetproject.cpp:1067`).

```cpp
XmlElementCollection(QETProject *project);                          // :38  builds the empty skeleton
XmlElementCollection(const QDomElement &dom, QETProject *project);  // :126 imports an existing <collection>
QDomElement root() const;                                           // :143
QDomElement importCategory() const;                                 // :153
QDomElement child(const QString &path) const;                       // :213
QDomElement element(const QString &path) const;                     // :325
QDomElement directory(const QString &path) const;                   // :343
bool        exist(const QString &path) const;                       // :603
QString     addElement(ElementsLocation &location);                 // :367
bool        addElementDefinition(dir_path, elmt_name, xml_definition); // :511
bool        removeElement(const QString &path);                     // :550
ElementsLocation copy(source, destination, rename = {}, deep = true); // :579
bool createDir(path, name, name_list);                              // :621
bool removeDir(const QString &path);                                // :655
QList<ElementsLocation> elementsLocation(QDomElement = {}, bool childs = true) const; // :676
ElementsLocation domToLocation(QDomElement) const;                  // :721
void cleanUnusedElement();  void cleanUnusedDirectory();            // :745, :755
```

Signals: `elementAdded`, `elementChanged`, `elementRemoved`, `directorieAdded`, `directoryRemoved`,
all carrying the collection path as a `QString` (`xmlelementcollection.h:90-120`). These drive the
collection tree view.

Guard rail worth knowing: `childs()`, `child(parent, name)` and `elementsLocation()` all return empty
when the passed `QDomElement` belongs to a different `QDomDocument`
(`:167-169`, `:189-190`, `:685-686`).

### 4.4 `ElementsLocation` — `sources/ElementsCollection/elementslocation.{h,cpp}`

Value type (copyable, `Q_DECLARE_METATYPE`, registered meta-type id at `elementslocation.cpp:31`).
Holds `m_collection_path`, `m_file_system_path`, `m_project` (`elementslocation.h:99-101`).

Predicates (all in `elementslocation.cpp`): `isElement()` `:474`, `isDirectory()` `:483`,
`isFileSystem()` `:492`, `isCommonCollection()` `:504`, `isCompanyCollection()` `:514`,
`isCustomCollection()` `:524`, `isMacrosCollection()` `:949`, `isProject()` `:535`, `isNull()` `:447`,
`exist()` `:548`, `isWritable()` `:575`.

Accessors: `baseName()` `:146` (name without `.elmt`), `fileName()` `:891` (last path segment with
extension), `name()` `:874` (localised name from `<names>`), `collectionPath(bool)` `:177`,
`projectCollectionPath()` `:193`, `fileSystemPath()` `:210`, `path()` `:223`, `toString()` `:457`,
`parent()` `:394`, `uuid()` `:835`, `icon()` `:854`, `nameList()` `:608`,
`elementInformations()` `:909`, `xml()` `:651`, `pugiXml()` `:686`, `setXml()` `:739`.

Equality is `(m_collection_path, m_project)` — the XML content is not compared
(`elementslocation.cpp:115-121`).

Note `pugiXml()` caches the serialised document in a `std::stringstream` member on non-Linux builds
and does *not* cache on Linux, deliberately (`elementslocation.cpp:686-712`). `[inference]` On
non-Linux, a location object held across an edit of the same element returns stale XML from
`pugiXml()` while `xml()` stays live.

### 4.5 `XmlProjectElementCollectionItem` — `sources/ElementsCollection/xmlprojectelementcollectionitem.{h,cpp}`

`QStandardItem` adapter that exposes one node of an `XmlElementCollection` to the collection tree
model. `type()` is `UserType+3` (`xmlprojectelementcollectionitem.h:36-37`).

- `isDir()` ⇔ the wrapped DOM tag is `category`; `isElement()` ⇔ it is `element` (`.cpp:31-49`).
- `name()` is the DOM `name` attribute (`.cpp:76-79`).
- `embeddedPath()` rebuilds `embed://dir/sub/foo.elmt` by walking up the *item* tree; the collection
  root maps to the bare string `"embed://"` (`.cpp:87-107`).
- `collectionPath()` returns `projectCollectionPath()` (`project0+embed://…`), falling back to the
  translated literal `"Collection"` when empty (`.cpp:85-95`).
- `isCollectionRoot()` ⇔ no parent, or the parent is not an `XmlProjectElementCollectionItem`
  (`.cpp:112-120`).
- `setProject()` binds the item to `project->embeddedElementCollection()->root()` and populates
  (`.cpp:173-183`); it is a no-op if a project is already set (`.cpp:177-178`).

### 4.6 Other files in `sources/ElementsCollection/`

| File | Role |
|------|------|
| `elementcollectionitem.{h,cpp}` | Abstract `QStandardItem` base for collection tree items (`elementcollectionitem.h:24-29`) |
| `fileelementcollectionitem.{h,cpp}` | Filesystem-collection specialisation (`fileelementcollectionitem.h:25-29`) |
| `xmlprojectelementcollectionitem.{h,cpp}` | Embedded-collection specialisation (§4.5) |
| `elementscollectionmodel.{h,cpp}` | `QStandardItemModel` aggregating common/company/custom/macros collections + N projects; owns MIME drag/drop (`elementscollectionmodel.h:33-83`) |
| `elementscollectionwidget.{h,cpp}` | The dockable panel in the diagram editor (`elementscollectionwidget.h:41-46`) |
| `elementstreeview.{h,cpp}` | `QTreeView` subclass, only overrides `startDrag` for a custom pixmap (`elementstreeview.h:26-30`) |
| `elementcollectionhandler.{h,cpp}` | Strategy-based copy between collections: `ECHSFileToFile`, `ECHSXmlToFile`, `ECHSToXml`; also `createDir`, `importFromProject`, `setNames` (`elementcollectionhandler.h:25-121`) |
| `elementslocation.{h,cpp}` | §4.4 |
| `xmlelementcollection.{h,cpp}` | §4.3 |
| `ui/renamedialog.{h,cpp,ui}` | Rename prompt used during import conflicts |

### 4.7 `DiagramContext` — `sources/diagramcontext.{h,cpp}`

A `QHash<QString,QVariant> m_content` plus a parallel `QHash<QString,bool> m_content_show`.

```cpp
bool addValue(const QString &key, const QVariant &value, bool show = true); // :91
QVariant value(const QString &key) const;                                   // :101
bool contains(const QString &key) const;                                    // :70
QList<QString> keys(KeyOrder order = None) const;                           // :49
void toXml(QDomElement &e, const QString &tag_name = "property") const;     // :145
void fromXml(const QDomElement &e, const QString &tag_name = "property");   // :168
void fromXml(const pugi::xml_node &, const QString &tag_name);              // :183
void toSettings/fromSettings(QSettings &, const QString &array_name);       // :195, :211
static QString validKeyRegExp();                                            // :227
static bool isKeyAcceptable(const QString &key);                            // :239
```

**Key validation is the single most important behaviour here**: `addValue` silently returns `false`
and stores nothing unless the key matches `^[a-z0-9-_]+$` (`sources/diagramcontext.cpp:227-230`,
`:239-246`, enforced at `:92`). Lowercase letters, digits, hyphen and underscore only. No dots, no
uppercase, no spaces, and an empty key is rejected too (`+` requires ≥1 char).

`fromXml` still inserts into `m_content_show` even when `addValue` rejected the key
(`sources/diagramcontext.cpp:171-173`) — the show flag is orphaned. `[inference]` harmless, but it
means `m_content_show.count()` can exceed `m_content.count()`.

`KeyOrder` (`sources/diagramcontext.h`): `None`, `Alphabetical`, `DecreasingLength` — the last is used
where longer keys must be substituted first during `%{var}` expansion (`sources/diagramcontext.cpp:56-62`).

---

## 5. The info-key system — `sources/qetinformation.h`, `sources/qetinformation.cpp`

Every key is defined as a `static QString` in `namespace QETInformation`
(`sources/qetinformation.h:33-138`). A key is turned into a template variable by
`infoToVar()` → `"%{" + info + "}"` (`sources/qetinformation.cpp:222-225`).

### 5.1 Element info keys (literal strings)

Base set — `sources/qetinformation.h:36-49`:

```
label                            formula                          comment
function                         description                      designation
manufacturer                     manufacturer_reference           machine_manufacturer_reference
supplier                         quantity                         unity
plant                            location
```

Auxiliary blocks 1–4 — `sources/qetinformation.h:50-85`. For `N` ∈ {1,2,3,4}:

```
auxiliaryN
description_auxiliaryN
designation_auxiliaryN
manufacturer_auxiliaryN
manufacturer_reference_auxiliaryN
machine_manufacturer_reference_auxiliaryN
supplier_auxiliaryN
quantity_auxiliaryN
unity_auxiliaryN
```

PLC keys — `sources/qetinformation.h:128-137`:

```
plc_type    plc_address    plc_function    plc_comment    plc_crossref
plc_tc      plc_t1         plc_t2          plc_t3         plc_t4
```

`QETInformation::elementInfoKeys()` (`sources/qetinformation.cpp:141-200`) returns, in this order:
`formula`, `label`, `plant`, `location`, `comment`, `function`, `description`, `designation`,
`manufacturer`, `manufacturer_reference`, `machine_manufacturer_reference`, `supplier`, `quantity`,
`unity`, then the four auxiliary blocks in full, then `plc_type`, `plc_address`, `plc_function`,
`plc_comment`, `plc_crossref`, then the literal `"exclude_from_bom"`
(`sources/qetinformation.cpp:198` — note this last one is **not** a named constant and is not in the
header).
`plc_tc`, `plc_t1`..`plc_t4` are defined in the header but are **absent** from `elementInfoKeys()`.

`QETInformation::elementEditorElementInfoKeys()` (`:322-374`) is the subset offered in the element
editor: `label`, `plant`, `location`, `comment`, `function`, `description`, `designation`,
`manufacturer`, `manufacturer_reference`, `machine_manufacturer_reference`, `supplier`, `quantity`,
`unity` + the four auxiliary blocks. No `formula`, no PLC keys, no `exclude_from_bom`.

`QETInformation::terminalElementInfoKeys()` (`:376-387`): `formula`, `label`, `comment`,
`designation`, `manufacturer`, `manufacturer_reference`, `machine_manufacturer_reference`, `supplier`.

`QETInformation::folioReportInfoKeys()` (`:86-95`): `label`, `function`, `tension_protocol`,
`conductor_color`, `conductor_section`.

### 5.2 Diagram info keys

Constants — `sources/qetinformation.h:97-109`:

```
author    date    display_folio    filename    folio    indexrev
locmach   plant   pos              title       folio-id
previous-folio-num                 next-folio-num
```

`QETInformation::diagramInfoKeys()` (`sources/qetinformation.cpp:127-139`) returns exactly:
`title`, `author`, `filename`, `folio`, `plant`, `locmach`, `indexrev`, `date`, `display_folio`.
(`pos`, `folio-id`, `previous-folio-num`, `next-folio-num` are defined but not in this list; the last
three appear in `titleblockInfoKeys()` instead.)

### 5.3 Conductor info keys

`sources/qetinformation.h:89-94`: `function`, `tension_protocol`, `conductor_color`,
`conductor_section`, `formula`, `text`.
`QETInformation::conductorInfoKeys()` (`:116-125`) returns them in the order
`formula`, `text`, `function`, `tension_protocol`, `conductor_color`, `conductor_section`.

Note `COND_FUNCTION` and `ELMT_FUNCTION` are both the literal `"function"`; `COND_FORMULA` and
`ELMT_FORMULA` are both `"formula"` (`sources/qetinformation.h:37,39,89,93`).

### 5.4 Project info keys

`sources/qetinformation.h:112-121`:

```
folio-total    projecttitle    projectpath     projectfilename
saveddate      saveddate-eu    saveddate-us    savedtime
savedfilename  savedfilepath
```

Plus `version` (`QET_VERSION`, `sources/qetinformation.h:125`).

### 5.5 Title-block keys

`QETInformation::titleblockInfoKeys()` (`sources/qetinformation.cpp:27-52`), in order:
`author`, `date`, `title`, `filename`, `plant`, `locmach`, `indexrev`, `version`, `folio`,
`folio-id`, `folio-total`, `previous-folio-num`, `next-folio-num`, `projecttitle`, `projectpath`,
`projectfilename`, `saveddate`, `saveddate-eu`, `saveddate-us`, `savedtime`, `savedfilename`,
`savedfilepath`.

`titleblockInfoKeysToVar(info)` returns `%{info}` if the key is in that list, else the literal
`"%{void}"` (`:60-66`). `elementInfoToVar` and `folioReportInfoToVar` behave the same for their own
lists (`:208-214`, `:108-114`).

### 5.6 Where these keys land in the XML

- Element info → `<element><elementInformations><elementInformation name="<key>" show="1">value`
  (`sources/qetgraphicsitem/element.cpp:992-997`).
- Definition-level defaults → `<definition><elementInformations>` same shape
  (`sources/editor/elementscene.cpp:487-490`).
- Diagram/title-block keys → attributes on `<diagram>` / `<inset>` for the historical ones
  (`sources/titleblockproperties.cpp:79-89`), and `<properties><property name="…">` for anything else.
- Project keys → `<project><properties><property name="…">`
  (`sources/qetproject.cpp:1025-1027`).

**All of these pass through `DiagramContext::addValue`, so every key must satisfy `^[a-z0-9-_]+$`
(§4.7).** Every key listed above complies (`folio-id`, `saveddate-eu` etc. use hyphens, which are
allowed).

---

## 6. Gotchas for an automated writer

### 6.1 UUIDs

1. **Braced form.** Every uuid QET writes comes from `QUuid::toString()`, which produces
   `{8-4-4-4-12}` **with braces** (`sources/qetgraphicsitem/element.cpp:922`,
   `sources/properties/terminaldata.cpp:110`, `sources/qetgraphicsitem/conductor.cpp:1059`,
   `sources/editor/elementscene.cpp:468`). `QUuid(QString)` accepts both braced and unbraced input,
   so reading is tolerant, but write braced to match.
2. **Element uuid is optional but load-bearing.** `Element::fromXml` falls back to a fresh random uuid
   when the attribute is missing (`sources/qetgraphicsitem/element.cpp:783`). A **malformed** uuid
   string yields a null `QUuid`, not a fresh one. Consequences: `<link_uuid>` master/slave links and
   uuid-based conductor endpoints will not resolve.
3. **Terminal uuids live in the element definition, not in the folio.** The folio's
   `<terminals><terminal>` nodes carry only `x`/`y`/`orientation`/`id`
   (`sources/qetgraphicsitem/terminal.cpp:714-725`). Modern conductors reference
   `terminal1="{uuid}"` where the uuid must match a `<terminal uuid="…">` inside the referenced
   `<definition><description>` (`sources/diagram.cpp:1228-1234`,
   `sources/properties/terminaldata.cpp:167-174`). If the definition's terminals have no `uuid`
   attribute, you **must** use the legacy integer form.
4. **The element definition's `<uuid>` is regenerated on every editor save.**
   `ElementScene::toXml` writes `QUuid::createUuid().toString()` unconditionally
   (`sources/editor/elementscene.cpp:468`), so a definition uuid is not stable across edits. It is
   only used to decide "same element?" during import (`sources/qetproject.cpp:1213-1216`).
5. **Project and Diagram uuids are runtime-only.** `QETProject::m_uuid` and `Diagram::m_uuid` are
   never serialised (`sources/qetproject.h:331`, `sources/diagram.h:134`; no write site exists).
   Do not invent `<project uuid="…">` — it will be ignored.

### 6.2 Ordering and placement constraints

1. **`<project>` must be the document element.** Anything else → `ProjectParsingFailed`
   (`sources/qetproject.cpp:1462`, `:1519-1524`).
2. **`readDiagramsXml` uses `xml_project.elementsByTagName("diagram")` — a whole-document search**
   (`sources/qetproject.cpp:1607`). Any element named `diagram` *anywhere* in the file — nested inside
   a title-block template, inside an element `<definition>`, inside the collection — becomes a folio.
   Never emit that tag name outside its intended place.
3. **`readElementsCollectionXml` takes `elementsByTagName("collection").at(0)`** — the **first**
   `<collection>` in document order anywhere in the file (`sources/qetproject.cpp:1657-1665`). Because
   `<collection>` is written last, a stray earlier `<collection>` (e.g. inside a title-block template)
   would shadow the real one.
4. **`readDefaultPropertiesXml` takes `elementsByTagName("newdiagrams").at(0)`** — same whole-document
   caveat (`sources/qetproject.cpp:1706-1709`).
5. **`<properties>` at project level must be a direct child of `<project>`** — the reader uses
   `QET::findInDomElement(documentElement, "properties")`, which walks only direct children
   (`sources/qetproject.cpp:1682`, `sources/qet.cpp:346-360`). The `<properties>` blocks nested inside
   `<inset>` and inside `<diagram>` are therefore not picked up as project properties.
6. **`<usage>` and `<terminal_strips>` must be direct children of `<project>`** — both use
   `firstChildElement(...)` (`sources/project/projectusagetracker.cpp:114`,
   `sources/qetproject.cpp:1814`).
7. **The `order` attribute on `<diagram>` is written but never read.** `grep 'attribute("order")'`
   over `sources/` returns nothing; folio order is purely document order in
   `elementsByTagName("diagram")` (`sources/qetproject.cpp:1607-1632`). Emitting a correct-looking
   `order` while listing folios in a different document order will silently produce the document
   order.
8. **The elements collection is parsed before the folios** (`sources/qetproject.cpp:1549` vs `:1553`), so the
   `<collection>` element may physically appear anywhere as long as it is the first one; but keeping
   it last matches what QET writes.
9. **Two-level containers only.** Every folio child list is read with
   `QET::findInDomElement(root, container, item)` which is strictly *direct child → direct child*
   (`sources/qet.cpp:370-393`). `<elements><group><element/></group></elements>` finds nothing.

### 6.3 Silent-drop conditions (no error, no dialog)

| Condition | Effect | Source |
|---|---|---|
| `<element>` missing `type`, `x` or `y`, or non-numeric `x`/`y` | element skipped | `sources/qetgraphicsitem/element.cpp:692-709` + `sources/diagram.cpp:1411` |
| `type` points at a path not present in the collection | element skipped, `qDebug` only | `sources/factory/elementfactory.cpp:38-43` + `sources/diagram.cpp:1427-1437` |
| `<definition>` missing/invalid `width`/`height`/`hotspot_x`/`hotspot_y` | element skipped (state 5) | `sources/qetgraphicsitem/element.cpp:434-446` |
| `<definition type>` ≠ `"element"` | element skipped (state 4) | `sources/qetgraphicsitem/element.cpp:414-421` |
| `<definition>` with no children | element skipped (state 6) | `sources/qetgraphicsitem/element.cpp:451-457` |
| Duplicate terminal `id` across two elements of the same folio | the **second** element is removed | `sources/qetgraphicsitem/element.cpp:755-764`, `sources/diagram.cpp:1441-1446` |
| `<terminal>` without a parsable integer `id` | terminal not registered (`Terminal::valideXml` fails) | `sources/qetgraphicsitem/terminal.cpp:752-754` |
| `<conductor>` whose endpoints don't both resolve, or resolve to the same terminal | conductor dropped | `sources/diagram.cpp:1541-1552` |
| `<conductor>` missing `terminal1`/`terminal2`, or uuid form with null uuids | conductor skipped | `sources/qetgraphicsitem/conductor.cpp:604-624` |
| `<property>`/`<elementInformation>` without a `name` attribute | entry skipped | `sources/diagramcontext.cpp:170` |
| Info key not matching `^[a-z0-9-_]+$` | value silently discarded | `sources/diagramcontext.cpp:92`, `:227-246` |
| `elementInformation` whose trimmed value is empty | **not written** on save | `sources/diagramcontext.cpp:147-150` |
| `<titleblocktemplate>` without `name` | template skipped | `sources/titleblock/templatescollection.cpp:343` |
| Duplicate `<titleblocktemplate name>` | first wins, rest ignored | `sources/titleblock/templatescollection.cpp:347` |
| Second and later `<collection>` elements | ignored | `sources/qetproject.cpp:1660-1665` |
| Unknown child of `<newdiagrams>` | ignored | `sources/qetproject.cpp:1722-1743` |
| `link_type` value not in the known list | falls back to `simple` | `sources/properties/elementdata.cpp:710-713` |
| `orientation` outside 0..3 or non-numeric | falls back to `0` | `sources/qetgraphicsitem/element.cpp:812-815` |
| `titleblocktemplateCollection` unrecognised | falls back to `common` | `sources/qet.cpp:739-751` |

### 6.4 Conditions that block the load entirely

- Root tag ≠ `project` → `ProjectParsingFailed`, nothing is built (`sources/qetproject.cpp:1519-1524`).
- Malformed XML → `QDomDocument::setContent` fails → `XmlParsingFailed`
  (`sources/qetproject.cpp:249-256`).
- `version` newer than the running build, or `<= 0.60`, opens a **modal `QMessageBox`**; choosing
  Cancel sets `FileOpenDiscard` (`sources/qetproject.cpp:1469-1496`, `:1500-1514`). A headless writer
  should emit a `version` that is neither.

### 6.5 Embedded-collection specific traps

1. **The `import` segment is part of the path.** `type="embed://foo.elmt"` will not resolve to
   `<category name="import"><element name="foo.elmt">`; the type must be
   `embed://import/foo.elmt`. Path walking starts at `<collection>`
   (`sources/ElementsCollection/xmlelementcollection.cpp:217-232`).
2. **Name-based lookup keys off the `.elmt` suffix.** A `<category name="something.elmt">` is
   unreachable as a directory, and an `<element name="foo">` (no extension) is unreachable as an
   element (`xmlelementcollection.cpp:194-206`, `:325-329`).
3. **`<element>` must wrap exactly one `<definition>`.** `ElementsLocation::xml()` returns
   `element.firstChildElement("definition")` (`elementslocation.cpp:670`); anything else yields a null
   element and the factory refuses.
4. **`importCategory()` is the first `<category>` child of `<collection>`, whatever its name**
   (`xmlelementcollection.cpp:153-156`). Keep `name="import"` first.
5. **A definition's `<terminal>` entries define the element's terminals; the folio's
   `<terminals>` entries only *match* them.** `Terminal::fromXml` compares `x`, `y` and `orientation`
   with `qFuzzyCompare` against the terminal built from the definition
   (`sources/qetgraphicsitem/terminal.cpp:780-787`). If the folio's terminal coordinates do not match
   the definition's, the id→terminal mapping is never established and every conductor using the legacy
   integer form on that element is dropped.
   Note the folio writes terminal `x`/`y` from `dock_elmt_` (`terminal.cpp:719-720`) while the
   definition writes `scenePos()` rounded to 2 decimals (`sources/properties/terminaldata.cpp:104-108`).
   UNVERIFIED: whether these two coordinate spaces are identical in all orientations. Test: save a
   project containing a rotated element, then compare the `<terminal x y>` values in the folio against
   the same terminal in the embedded `<definition>`.
6. **`orientation` is spelled differently in the two places.** In the folio it is the integer
   `d->m_orientation` (`terminal.cpp:723`); in the definition it is the string form from
   `Qet::orientationToString` (`sources/properties/terminaldata.cpp:115-116`) — e.g. `"n"`, `"s"`,
   `"e"`, `"w"` as seen in `examples/741.qet`.

### 6.6 Value-format notes

- Booleans are always the literal lowercase strings `"true"` / `"false"` on write. On read the
  comparison is usually `== "true"` or `!= "false"`, so any other string is treated as the opposite
  of the tested literal — e.g. `freeze_new_conductors="1"` reads as **false**
  (`sources/qetproject.cpp:1764`), while `enabled="1"` reads as **true**
  (`sources/project/projectusagetracker.cpp:120`). Use the literals.
  `Diagram::fromXml` is the exception: it reads `freezeNewElement` / `freezeNewConductor` with
  `.toInt()`, so `"true"` becomes `0` (`sources/diagram.cpp:1326,1329`) — a **known asymmetry** with
  the writer at `sources/diagram.cpp:840-846`.
  UNVERIFIED: whether this is intentional. Test: set "freeze new element" on a folio, save, reopen,
  and check whether the setting survived.
- Coordinates are written with `QString::number(double)` — locale-independent, `.` decimal separator
  (`sources/qetgraphicsitem/element.cpp:936-937`).
- `date` in `<inset>`/`<diagram>` is `TitleBlockProperties::exportDate()`; the sample files use
  `yyyyMMdd` (`examples/741.qet`: `date="20100921"`).
- The `<property>` value is a **text node**, not an attribute, and is `trimmed()` on write
  (`sources/diagramcontext.cpp:159-160`).

### 6.7 Things QET writes that a generator may safely omit

- `<usage>` (absent from all shipped examples).
- `<titleblocktemplates>` (only written when templates are embedded, `sources/qetproject.cpp:1015`).
- `<terminal_strips>` (only when strips exist, `sources/qetproject.cpp:1057`).
- `<element><inputs/>` — always written, always empty, never read as element content
  (`sources/qetgraphicsitem/element.cpp:968-969`).
- `<dynamic_texts>` / `<texts_groups>` — written even when empty
  (`sources/qetgraphicsitem/element.cpp:1064-1067`); omitting them is fine because the reader uses
  `findInDomElement` which tolerates a missing container.
- `height` on `<diagram>` — explicitly marked "attribut datant de la version 0.1 - laisse pour
  retrocompatibilite" (`sources/bordertitleblock.cpp:241-242`); it is only consulted when `rows` and
  `rowsize` are both absent (`sources/bordertitleblock.cpp:262-270`).
- `<guides>` — absent in old projects, list stays empty (`sources/qetproject.cpp:1796-1808`).

### 6.8 Minimal valid `.qet`

Verified against every requirement cited above; the collection skeleton matches the constructor's own
documented output (`sources/ElementsCollection/xmlelementcollection.cpp:28-34`).

```xml
<project version="0.200.1" title="Minimal">
    <properties/>
    <newdiagrams/>
    <diagram title="Folio 1" cols="17" colsize="60" rows="8" rowsize="80"
             displaycols="true" displayrows="true"
             freezeNewElement="false" freezeNewConductor="false" order="1"/>
    <collection>
        <category name="import">
            <names><name lang="en">Imported elements</name></names>
        </category>
    </collection>
</project>
```

`[inference]` `<properties/>` and `<newdiagrams/>` may also be omitted entirely — both readers return
early when the tag is absent (`sources/qetproject.cpp:1682`, `:1706-1707`) — but QET always writes
them, so keeping them empty is the closest match to a round-trip.
