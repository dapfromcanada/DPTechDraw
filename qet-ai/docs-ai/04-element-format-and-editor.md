# QElectroTech `.elmt` Element Format — Complete Reference

Scope: everything needed to **write a valid `.elmt` file from scratch**, derived from
the element editor (`sources/editor/`), the runtime loaders
(`sources/qetgraphicsitem/element.cpp`, `sources/factory/elementpicturefactory.cpp`),
the property classes (`sources/properties/`) and the CLI validator
(`sources/cli_export.cpp`).

Source root for all citations: `/root/qet/qelectrotech-source-mirror`.
Paths below are repo-relative. Line numbers are from the checked-out mirror.

Three code paths read a `.elmt`, independently:

| Path | Entry point | Purpose |
|---|---|---|
| **Editor** | `ElementScene::loadContent()` — `sources/editor/elementscene.cpp:1184` | Rebuild editable `Part*` objects |
| **Runtime (geometry/terminals/texts)** | `Element::buildFromXml()` — `sources/qetgraphicsitem/element.cpp:411` | Terminals + dynamic texts on a diagram |
| **Runtime (drawing)** | `ElementPictureFactory::build()` — `sources/factory/elementpicturefactory.cpp` (attr checks at :178–186) | Rasterise the artwork into a `QPicture` |

**These three do not agree in every detail.** Every divergence found is called out
below; a generator must satisfy all three.

The `elements/` submodule directory in this mirror is **empty** (`ls elements/` →
nothing; `find . -name '*.elmt'` → 0 hits). Cross-checking against real data was
therefore done against the **943 `<definition>` blocks embedded in the 23 projects
under `examples/*.qet`** — the element collection is embedded verbatim into `.qet`
projects, so those blocks are byte-identical to real `.elmt` file contents.

---

## 1. Document shell

`QETXML::writeXmlFile()` (`sources/qetxml.cpp:279–290`) writes:

* `QTextStream` with **UTF-8** encoding, `setGenerateByteOrderMark(false)` → **no BOM**.
* `xml_document.toString(4)` → 4-space indentation.
* `QDomDocument` emits **no XML declaration** unless a processing instruction was
  explicitly added. `EdzElementBuilder::build()`
  (`sources/import/edz/edzelementbuilder.cpp:127–130`) adds one:
  `<?xml version="1.0" encoding="utf-8"?>`. Both forms load. Prefer emitting it.
* Root element is **`<definition>`**. Nothing wraps it.

---

## 2. The `<definition>` root element

Written by `ElementScene::toXml()` — `sources/editor/elementscene.cpp:424`.

| Attribute | Written at | Type | Required? | Notes |
|---|---|---|---|---|
| `type` | `elementscene.cpp:455` | literal `"element"` | **YES** | Anything else → total rejection by all three loaders. |
| `width` | `elementscene.cpp:456` | **integer** | **YES** | Bounding box width in px. |
| `height` | `elementscene.cpp:457` | **integer** | **YES** | Bounding box height in px. |
| `hotspot_x` | `elementscene.cpp:458` | **integer** | **YES** | Distance from bbox left edge to the origin (0,0) of part coordinates. |
| `hotspot_y` | `elementscene.cpp:460` | **integer** | **YES** | Distance from bbox top edge to the origin. |
| `version` | `elementscene.cpp:463` via `QetVersion::toXmlAttribute()` (`sources/qetversion.cpp:59-62`) | `QVersionNumber` string | optional | Current QET writes `currentVersion().toString()` = **`0.200.1`** (`sources/qetversion.cpp:24-27`). |
| `link_type` | `elementscene.cpp:464` via `ElementData::typeToString()` (`sources/properties/elementdata.cpp:663`) | enum string | optional, defaults `simple` | See §2.2. |

### 2.1 `width` / `height` / `hotspot_*` must parse as **integers**

Both runtime paths use `QET::attributeIsAnInteger()` (`sources/qet.cpp:213`), which does `QString::toInt(&ok)` and **fails on any
decimal point**:

* `sources/qetgraphicsitem/element.cpp:437-446` → `*state = 5`, `buildFromXml` returns false → element does not load at all.
* `sources/factory/elementpicturefactory.cpp:180-186` → `build()` returns false → no picture.

`width="90.0"` is fatal. `width="90"` is fine.

`Element::setSize()` (`element.cpp:288-295`) then rounds **up** to the next
multiple of 10 (`while (wid % 10) ++wid;`). `Element::setHotspot()`
(`element.cpp:310-321`) clamps `hotspot_x ≤ width`, `hotspot_y ≤ height`
(no lower clamp — negatives are kept). `ElementPictureFactory::pixmap()`
(`elementpicturefactory.cpp:93-99`) repeats both.

### 2.2 `link_type` values

From `ElementData::typeToString()/typeFromString()` — `sources/properties/elementdata.cpp:663-714`:

`simple` · `next_report` · `previous_report` · `master` · `slave` · `terminal` ·
`thumbnail` · `conductor_definition`

Unknown / absent → falls back to `simple` (`elementdata.cpp:52`, `element.cpp:461`).

`link_type` gates which optional blocks the writer emits
(`elementscene.cpp:475-489`):

* `master`, `slave`, `terminal` → `<kindInformations>` block is written.
* `simple`, `master`, `terminal`, `thumbnail` → `<elementInformations>` block is written.
* `next_report` / `previous_report` / `slave` / `conductor_definition` get neither
  from the editor, but the readers do not enforce this — extra blocks are read
  regardless of type as long as `link_type` matches
  (`ElementData::kindInfoFromXml`, `elementdata.cpp:923-930`, only reads
  `kindInformations` when type is Master/Slave/Terminal).

Corpus distribution (`examples/*.qet`, 943 definitions): `simple` 365, `master` 107,
`slave` 50, `next_report` 16, `terminal` 16, `previous_report` 12, `thumbnail` 1,
**absent 376** — so omitting `link_type` is legal and common.

### 2.3 Legacy `<definition>` attributes that current code IGNORES

Present in the corpus, **read by nothing** in the current tree (grepped
`sources/` for `"ic"` and for `orientation` reads on a definition node — the only
`orientation` readers are diagram `<element>` instances, `element.cpp:812`, and
`terminal` parts):

* `orientation="dnny"` — 249 occurrences, values seen: `dyyy`, `dnny`, `dnnn`, `dnyn`, `dyny`. Pre-0.5 "which rotations are allowed" flags. **Silently ignored.** Do not emit.
* `ic="true"` — 177 occurrences. Legacy "internal connections". **Silently ignored.** Do not emit.

### 2.4 Child elements of `<definition>`, in write order

`ElementScene::toXml()` appends, in this exact order:

1. `<uuid uuid="{...}"/>` — `elementscene.cpp:467-469`
2. `<names>` — `elementscene.cpp:472`
3. `<kindInformations>` — `elementscene.cpp:480` (conditional, §5)
4. `<elementInformations>` — `elementscene.cpp:487-493` (conditional, §6)
5. `<informations>` — `elementscene.cpp:495-499` (conditional: only if the free-text drawing note is non-blank)
6. `<description>` — `elementscene.cpp:501-512`

**Order is not enforced on read.** Every reader uses
`firstChildElement(tag)` / a `nextSibling` scan, so any order works. Emit the
canonical order anyway.

`Element::buildFromXml()` requires `<definition>` to have **at least one child
node** (`element.cpp:449-455`, `*state = 6`) and requires at least one graphic
part or a non-null picture to be parsed (`element.cpp:544-550`, `*state = 8`).
An element consisting only of `<terminal>` parts satisfies this
(`parseTerminal` returning non-null counts).

---

## 3. `<uuid>`

```xml
<uuid uuid="{74eb70d9-1427-48f0-b140-1443bb340ff4}"/>
```

* Written: `elementscene.cpp:467-469`. **A brand-new v4 UUID is generated on every
  save** — it is not stable across saves of the same element.
* Read: `ElementsLocation::uuid()` — `sources/ElementsCollection/elementslocation.cpp:842-847`.
  Used as the cache key for the rendered `QPicture`/`QPixmap`
  (`elementpicturefactory.cpp`, `m_pictures_H.insert(uuid_, pic)`).
* Braced form `{xxxxxxxx-xxxx-...}` — `QUuid::toString()` output. `QUuid()`
  parses both braced and unbraced, but emit braces.
* **Absent uuid is legal** (returns a null QUuid) — 423 of 943 corpus definitions
  have no `<uuid>`. But the picture cache then keys everything on the null UUID.
  **Always emit one, and make it unique per element.**

---

## 4. `<names>` — localised element names

Written by `NamesList::toXml()` — `sources/NameList/nameslist.cpp:185-208`.
Read by `NamesList::fromXml()` — `nameslist.cpp` (QDom overload) and the pugixml
overload.

Tag names come from `getXmlOptions()` defaults (`nameslist.cpp:218-226`):
parent tag `names`, child tag `name`, language attribute `lang`.

```xml
<names>
    <name lang="fr">Bornier TBXVA(1)</name>
    <name lang="en">Terminal block TBXVA(1)</name>
    <name lang="de">Terminalblock TBXVA(1)</name>
</names>
```

* `lang` — a language code. QET keys on the **2-letter** code. `NamesList::name()`
  tries the full locale from settings (e.g. `de_DE`), then the base code (`de`),
  then `en`, then a caller fallback, then the first entry.
* The value is the element's **text node**, `.trimmed()` on write
  (`nameslist.cpp:201`).
* If the map is empty, the writer emits a single `<name lang="en"> </name>`
  (one space) and logs "NamesList of element is empty" (`nameslist.cpp:189-195`).
* **`addName()` overwrites on duplicate `lang`.** Last wins.
* Corpus: 943 `<names>`, 5774 `<name>`. Every definition has one.

**Generator rule:** always emit `<names>` with at least `lang="en"`. It is what the
element browser tree shows.

---

## 5. `<kindInformations>` — master / slave / terminal semantics

Written by `ElementData::kindInfoToXml()` — `sources/properties/elementdata.cpp:67`.
Read by `ElementData::kindInfoFromXml()` — `elementdata.cpp:923`.

Each entry is `<kindInformation name="KEY">VALUE</kindInformation>` where VALUE is a
**text node**, not an attribute. Entries lacking a `name` attribute are skipped
(`elementdata.cpp:925-927`).

### link_type="master" (`elementdata.cpp:71-99`)
| `name` | Value domain | Source |
|---|---|---|
| `type` | `coil` · `protection` · `commutator` · `plc` | `masterTypeToString()` `elementdata.cpp:723-734` |
| `max_slaves` | integer; **omitted when `-1`** (unlimited) | `elementdata.cpp:83-90` |

Plus optional `<slaveContactGroups>` (`elementdata.cpp:92-115`):
`<group type="NO|NC|SW|Other" subtype="simple|power|delayOn|delayOff|delayOnOff|plc"
contactCount="N" terminalCount="N"><label>…</label>…</group>`

Plus `<plcMasterData>` when `type` is `plc` (`elementdata.cpp:118-208`) — a niche
sub-tree: attribute `rowHeight`, children `<breakPositions>`, `<columnWidths>`,
`<columnVisibility>`, `<headerFont>`, `<cellFont>`, `<columnNames>`,
`<columnOrder>`, `<showHeaders>`, `<plcIOs>` (each `<plcIO type address
functionText comment crossRef terminalCount>` holding `<terminal>` text children).
Read back at `elementdata.cpp:390-440`. Skip unless generating PLC masters.

### link_type="slave" (`elementdata.cpp:210-233`)
| `name` | Value domain |
|---|---|
| `type` | `simple` · `power` · `delayOn` · `delayOff` · `delayOnOff` · `plc` (`slaveTypeToString()` `elementdata.cpp:756-770`) |
| `state` | `NO` · `NC` · `SW` · `Other` (`slaveStateToString()` `elementdata.cpp:797-809`) |
| `number` | integer contact count |

### link_type="terminal" (`elementdata.cpp:235-251`)
| `name` | Value domain |
|---|---|
| `type` | `generic` · `fuse` · `sectional` · `diode` · `ground` (`terminalTypeToString()` `elementdata.cpp:830-844`) |
| `function` | `generic` · `phase` · `neutral` (`terminalFunctionToString()` `elementdata.cpp:884-895`) |

All `*FromString()` helpers log to `qDebug` and return a failsafe value for
unknown strings — **never fatal**.

Note: the corpus shows a stray `show` attribute on 264 of 290 `<kindInformation>`
elements. Nothing reads it — `kindInfoFromXml` only reads `name` and `.text()`.
It is residue from an older serialiser that shared `DiagramContext::toXml`.

---

## 6. `<elementInformations>` — the BOM / nomenclature payload

Written by `DiagramContext::toXml(element_info, "elementInformation")` —
`sources/diagramcontext.cpp:151-169`, called from `elementscene.cpp:487-493`.
Read by `DiagramContext::fromXml(…, "elementInformation")` — `diagramcontext.cpp:174-180`,
called from `ElementData::fromXml` (`elementdata.cpp:56-57`) and
`Element::buildFromXml` (`element.cpp:471-473`).

```xml
<elementInformations>
    <elementInformation name="manufacturer" show="1">Schneider</elementInformation>
    <elementInformation name="manufacturer_reference" show="1">LC1D09</elementInformation>
    <elementInformation name="label" show="1">KM%{numero}</elementInformation>
</elementInformations>
```

| Attribute | Written at | Meaning |
|---|---|---|
| `show` | `diagramcontext.cpp:162` | int, default `1` on read (`diagramcontext.cpp:178`). 0 = value exists but is hidden in the "add element" dialog. Written **before** `name` (the writer explicitly removes and re-adds both to force attribute order). |
| `name` | `diagramcontext.cpp:163` | The info key. |

Value is the **text node**, `.trimmed()` on write.

**Writer skips any key whose trimmed value is empty** (`diagramcontext.cpp:153-156`)
— specifically when `tag_name == "elementInformation"`. So an empty
`<elementInformations/>` is normal and appears 319 times in the corpus.

### 6.1 Info keys (`sources/qetinformation.h`)

The keys are plain strings; `DiagramContext` accepts **any** key. The canonical
element set is `QETInformation::elementInfoKeys()` (`sources/qetinformation.cpp:141`):

```
formula  label  plant  location  comment  function  description  designation
manufacturer  manufacturer_reference  machine_manufacturer_reference
supplier  quantity  unity
```

plus, for each of `auxiliary1..auxiliary4` (`qetinformation.h:50-85`), the group:

```
auxiliaryN  description_auxiliaryN  designation_auxiliaryN
manufacturer_auxiliaryN  manufacturer_reference_auxiliaryN
machine_manufacturer_reference_auxiliaryN  supplier_auxiliaryN
quantity_auxiliaryN  unity_auxiliaryN
```

PLC keys (`qetinformation.h:128-137`), used when `link_type="slave"` +
kind `type=plc`:
`plc_type  plc_address  plc_function  plc_comment  plc_crossref
plc_tc  plc_t1  plc_t2  plc_t3  plc_t4`

The element editor's properties dialog exposes
`QETInformation::elementEditorElementInfoKeys()` (`qetinformation.cpp:322`) — that is
`elementInfoKeys()` **minus `formula`**. `formula` is still readable and writable
in the file.

Keys are referenced from dynamic texts as `%{key}`
(`QETInformation::infoToVar()`, `qetinformation.cpp:222-225`). See §9.3.

The BOM CSV export queries exactly:
`label, designation, manufacturer, manufacturer_reference, quantity, location,
function` (plus diagram `title`, `folio`) — `sources/cli_export.cpp:306-310`.
Those seven are the keys worth populating for BOM usefulness.

---

## 7. `<informations>` — free-text note

`elementscene.cpp:495-499`. Written **only if** the trimmed string is non-empty.
No attributes; a single text node. Read back at `elementdata.cpp:59-62`.
Purely informational (author/licence blurb, by convention).

```xml
<informations>Author: The QElectroTech team
License: see http://qelectrotech.org/wiki/doc/elements_license</informations>
```

---

## 8. `<description>` — the drawing

`elementscene.cpp:501-512`. **All graphic parts must be direct children of
`<description>`.** Both `ElementScene::loadContent()` (`elementscene.cpp:1201`)
and `Element::buildFromXml()` (`element.cpp:485`) only descend into a child named
exactly `description`. Parts placed directly under `<definition>` are invisible to
every loader.

Recognised child tag names — `ElementScene::loadContent()`
(`elementscene.cpp:1212-1223`):

| Tag | Editor class | Rendered by factory? | Runtime object? |
|---|---|---|---|
| `line` | `PartLine` | yes (`parseLine`) | no |
| `rect` | `PartRectangle` | yes (`parseRect`) | no |
| `ellipse` | `PartEllipse` | yes (`parseEllipse`) | no |
| `circle` | `PartEllipse` | yes (`parseCircle`) | no |
| `arc` | `PartArc` | yes (`parseArc`) | no |
| `polygon` | `PartPolygon` | yes (`parsePolygon`) | no |
| `text` | `PartText` | yes (`parseText`) | no |
| `terminal` | `PartTerminal` | **no** | `Terminal` (`element.cpp:658`) |
| `dynamic_text` | `PartDynamicTextField` | **no** | `DynamicElementTextItem` (`element.cpp:638`) |
| `plc_table` | `PartPlcTable` | **no** (skipped at `elementpicturefactory.cpp:254-262`) | position recorded, drawn at runtime |
| `input` | *legacy* → converted to `PartDynamicTextField` (`elementscene.cpp:1223`) | no | `DynamicElementTextItem` (`element.cpp:583`) |

**Unknown tags inside `<description>` are silently skipped** — `else continue;`
(`elementscene.cpp:1224`); the factory's `parseElement` dispatcher
(`elementpicturefactory.cpp:286-295`) simply falls through; `Element::parseElement`
(`element.cpp:566-572`) returns `true` for anything it does not know.
There is no error, no warning. **A typo'd tag name means an invisible part.**

### 8.1 Z-order

The editor assigns `zValue` sequentially in document order starting at 1
(`elementscene.cpp:1226-1229`, `if (!qgi->zValue()) qgi->setZValue(z++)`), and
`ElementScene::toXml` writes parts sorted by `zItems()`. The picture factory
ignores z entirely and paints strictly in document order
(`elementpicturefactory.cpp:245-263`).
**For rendering, document order is the only thing that matters: later = on top.**
Only `dynamic_text` carries an explicit `z` attribute in the file.

---

## 9. Graphic part reference

### 9.0 Coordinates, common to every part

* One unit = **1 pixel at 100 % zoom**, same unit as the diagram sheet.
* All coordinates written to XML are **scene coordinates** of the element, i.e.
  relative to the element's own origin `(0,0)`. Every `toXml` maps local →
  scene first: `mapToScene(...)` in `partline.cpp:327` (`sceneP1`),
  `partrectangle.cpp:235` (`sceneTopLeft`), `abstractpartellipse.cpp:99`.
  **There is no per-part transform in the file** (except `rotation` on texts) —
  a generator emits absolute numbers and nothing else.
* **X grows right, Y grows DOWN** (Qt scene convention).
* The origin `(0,0)` is where the element's hotspot lands. On a diagram the
  element's `boundingRect()` is
  `QRectF(QPointF(-hotspot_x, -hotspot_y), QSize(width, height))`
  (`element.cpp:274-277`) — so a part at `(0,0)` sits `hotspot_x` px from the
  left edge and `hotspot_y` px from the top edge of the element's box.
  **Coordinates are routinely negative.**
* Numeric formatting: the editor rounds positions/sizes to **2 decimals**
  (`qRound(v * 100.0)/100.0`, e.g. `partline.cpp:111-114`) and rotations to
  **1 decimal** (`parttext.cpp:165`). Readers use `toDouble()` — any decimal
  representation parses.
* Grid: `ElementScene` initialises `setGrid(1, 1)` (`elementscene.cpp:68`); the
  *view* adapts the snapping grid to the zoom, multiplying to 10/5/2
  (`sources/editor/elementview.cpp:509-531`). **There is no 10 px grid baked into
  the file format.** The 10 px convention is real but is imposed by (a) `width`/
  `height` being rounded up to multiples of 10 (`element.cpp:288-295`) and (b) the
  in-tree reference generator placing terminals on multiples of 10
  (`sources/import/edz/edzelementbuilder.cpp:92-99`). Follow it: terminals off the
  10 px grid will not line up with conductors drawn by users.

### 9.1 Common style attributes — `style` and `antialias`

Written by `CustomElementGraphicPart::stylesToXml()` —
`sources/editor/graphicspart/customelementgraphicpart.cpp:167`, attributes set at
`:509` (`style`) and `:510` (`antialias`).
Applies to: `line`, `rect`, `ellipse`, `circle`, `arc`, `polygon`, `plc_table`.
**NOT to `text` (`parttext.cpp:159-186` never calls `stylesToXml`) and NOT to
`terminal` or `dynamic_text`.**

The `style` value is a CSS-like `name:value;name:value` string. The writer always
emits **all four keys in this exact order**:

```
line-style:<v>;line-weight:<v>;filling:<v>;color:<v>
```

| Key | Values | Enum | Rendered width/effect |
|---|---|---|---|
| `line-style` | `normal` · `dashed` · `dotted` · `dashdotted` | `LineStyle`, `customelementgraphicpart.h:48-51` | `SolidLine` / `DashLine` / `DotLine` / `DashDotLine` |
| `line-weight` | `none` · `thin` · `normal` · `hight` · `eleve` | `LineWeight`, `customelementgraphicpart.h:55-59` | see below |
| `filling` | `none` + colour names + `hor` `ver` `bdiag` `fdiag` | `Filling` | `none` = no brush; patterns = hatch |
| `color` | `none` + colour names | `Color` | pen colour |

`line-weight` widths — **editor and runtime disagree**:

| Value | Editor `applyStylesToQPainter` (`customelementgraphicpart.cpp:915-921`) | Runtime `setPainterStyle` (`elementpicturefactory.cpp:645-650`) |
|---|---|---|
| `none` | pen colour alpha 0 (invisible) | pen colour alpha 0 |
| `thin` | `setWidth(0)` (cosmetic hairline) | `setWidthF(0.5)` |
| `normal` | `setWidthF(1.0)` | `setWidthF(1.0)` |
| `hight` | `setWidthF(2.0)` | `setWidthF(2.0)` |
| `eleve` | `setWidthF(5.0)` | `setWidthF(5.0)` |

Note the spellings: **`hight`** (not "high") and **`eleve`** (French). Transcribe exactly.

Colour names, both for `filling` and `color`
(maps at `customelementgraphicpart.cpp:183-340` for filling, `:352-509` for color;
runtime equivalents in `elementpicturefactory.cpp:652+`):

Basic: `white` `black` `green` `red` `blue` `gray` `brun` `yellow` `cyan`
`magenta` `lightgray` `orange` `purple` `none`
(`brun` = `QColor(97,44,0)`, `orange` = `(255,128,0)`, `purple` = `(136,28,168)`.)

Extended HTML palette: ~140 names of the form `HTML<Group><Name>`, groups
`Pink Red Orange Yellow Brown Green Cyan Blue Purple White Gray`, e.g.
`HTMLBlueDodgerBlue`, `HTMLGrayDarkSlateGray`, `HTMLRedCrimson`. Full list at
`customelementgraphicpart.cpp:183-340` (filling) and `:352-509` (color); the
runtime's identical list at `elementpicturefactory.cpp:652+`.

`filling` additionally accepts the four hatch patterns `hor` `ver` `bdiag` `fdiag`
(`customelementgraphicpart.cpp:337-340`; applied at `:925-928`).

**Parsing is strict and the two parsers differ:**

| | Editor `stylesFromXml` (`customelementgraphicpart.cpp:519`) | Runtime `setPainterStyle` (`elementpicturefactory.cpp:613`) |
|---|---|---|
| Regex | `^\s*([a-z-]+)\s*:\s*([a-zA-Z-]+)\s*$` (`:527`) | `^(?<name>[a-z-]+):(?<value>[a-zA-Z-]+)$` (`:623`) |
| Whitespace around `:` | tolerated | **rejected** |
| Digits in the value | rejected | rejected |
| Non-matching pair | skipped silently | logged `qDebug "no Match"`, skipped |

**Gotcha:** `style="line-style: normal; color: black"` loads correctly in the
editor and renders **unstyled** on a diagram. Emit no spaces.

Unknown keys and unknown values are ignored; the part keeps the reset default
(`resetStyles()`, `customelementgraphicpart.cpp:889-896`): `NormalStyle`,
`NormalWeight`, `NoneFilling`, `BlackColor`, antialias off.

**When `style` is absent entirely**, the runtime painter keeps Qt's default pen
(black, width 0 cosmetic, solid) and `NoBrush` — i.e. a hairline outline, thinner
than `line-weight:normal`. Always emit an explicit `style`.

`antialias` — `"true"` enables it; the reader is a literal equality test
`qde.attribute("antialias") == "true"` (`customelementgraphicpart.cpp:881`), so
`"True"` or `"1"` mean false. **The runtime picture factory does not read
`antialias` at all** — it sets `QPainter::Antialiasing` unconditionally for the
whole element (`elementpicturefactory.cpp:198-200`). So `antialias` only affects
the editor's own canvas.

Colour-after-weight ordering bug worth knowing: `setPainterStyle` handles
`line-weight:none` by zeroing the pen alpha, but a later `color:<name>` (other than
`black`/`white`, which preserve alpha) calls `pen.setColor()` and **restores full
opacity** (`elementpicturefactory.cpp:670-680` vs `:645-646`). Since the canonical
key order puts `color` last, `line-weight:none;…;color:red` draws a visible red
line at runtime while the editor shows it invisible. Use `color:none` or
`color:black`/`white` when you want `line-weight:none` to stick.

---

### 9.2 `<line>`

`PartLine::toXml()` — `sources/editor/graphicspart/partline.cpp:106`.

| Attribute | Written at | Type | Read default | Required at runtime |
|---|---|---|---|---|
| `x1` | `partline.cpp:119` | real | `0` (editor `partline.cpp:139`) | **YES** (`elementpicturefactory.cpp:301`) |
| `y1` | `partline.cpp:120` | real | `0` | **YES** (`:302`) |
| `x2` | `partline.cpp:121` | real | `0` | **YES** (`:303`) |
| `y2` | `partline.cpp:122` | real | `0` | **YES** (`:304`) |
| `end1` | `partline.cpp:123` | end-type enum | `none` | no |
| `length1` | `partline.cpp:124` | real | `1.5` (`partline.cpp:144`, `elementpicturefactory.cpp:309`) | no |
| `end2` | `partline.cpp:125` | end-type enum | `none` | no |
| `length2` | `partline.cpp:126` | real | `1.5` | no |
| `style`, `antialias` | `stylesToXml` | see §9.1 | | |

End types — `Qet::endTypeToString()` / `endTypeFromString()`, `sources/qet.cpp:555-580`,
enum at `sources/qet.h:198-205`:
**`none` · `simple` · `triangle` · `circle` · `diamond`**. Unknown string → `none`.

`length1`/`length2` scale the arrow/marker. Whether the decoration is drawn at all
depends on the line being long enough:
`line_length - length * requiredLengthForEndType(end)` must be ≥ 0
(`elementpicturefactory.cpp:326-336`). Too-short lines silently lose their arrowheads.

If a runtime `x1/y1/x2/y2` is missing or not a number, `parseLine` **returns
without drawing** (`elementpicturefactory.cpp:301-304`) — the line vanishes from
the diagram but still exists in the editor (which defaults them to 0).

`isUseless()` (`partline.cpp:450`): a line with p1 == p2 is dropped on save.

### 9.3 `<rect>`

`PartRectangle::toXml()` — `partrectangle.cpp:83`.

| Attribute | Written at | Type | Read default | Required at runtime |
|---|---|---|---|---|
| `x` | `partrectangle.cpp:94` | real, **top-left** | `0` | **YES** (`elementpicturefactory.cpp:400`) |
| `y` | `partrectangle.cpp:95` | real, top-left | `0` | **YES** (`:401`) |
| `width` | `partrectangle.cpp:96` | real | `0` | **YES** (`:402`) |
| `height` | `partrectangle.cpp:97` | real | `0` | **YES** (`:403`) |
| `rx` | `partrectangle.cpp:98` | real corner radius X | `0` (`:404`) | no |
| `ry` | `partrectangle.cpp:99` | real corner radius Y | `0` (`:405`) | no |
| `style`, `antialias` | | §9.1 | | |

The editor normalises negative width/height on read (`setRect(rect.normalized())`,
`partrectangle.cpp:119`); the runtime does **not** — `drawRoundedRect` with a
negative size draws an inverted rect (`elementpicturefactory.cpp:416`).
Emit positive `width`/`height` only.

Rendered with `Qt::MiterJoin` (`elementpicturefactory.cpp:411-413`).
`isUseless()` (`partrectangle.cpp:289`): null rect → dropped.

### 9.4 `<circle>` and `<ellipse>`

`PartEllipse::toXml()` — `partellipse.cpp:80`. The editor writes **`circle` when
width == height** (`qFuzzyCompare`, `partellipse.cpp:83`), otherwise `ellipse`.
Both map back to `PartEllipse` (`elementscene.cpp:1214-1215`).

`<circle>`:
| Attribute | Written at | Type | Required at runtime |
|---|---|---|---|
| `x` | `partellipse.cpp:101` | real, **top-left of the bounding box — NOT the centre** | **YES** (`elementpicturefactory.cpp:448`) |
| `y` | `partellipse.cpp:102` | real, top-left | **YES** (`:449`) |
| `diameter` | `partellipse.cpp:87` | real | **YES** (`:450`) |
| `style`, `antialias` | | §9.1 | |

`<ellipse>`:
| Attribute | Written at | Type | Required at runtime |
|---|---|---|---|
| `x` | `partellipse.cpp:101` | real, top-left | **YES** (`:424`) |
| `y` | `partellipse.cpp:102` | real, top-left | **YES** (`:425`) |
| `width` | `partellipse.cpp:94` | real | **YES** (`:426`) |
| `height` | `partellipse.cpp:95` | real | **YES** (`:427`) |
| `style`, `antialias` | | §9.1 | |

`parseCircle` builds `QRectF(x, y, diameter, diameter)`
(`elementpicturefactory.cpp:452`). To centre a circle of diameter `d` at
`(cx, cy)`, write `x = cx - d/2`, `y = cy - d/2`.

An `<ellipse>` with a `diameter` and no `width`/`height` **loads in the editor**
(`partellipse.cpp:117-123` falls through to the `diameter` branch only for a
non-`ellipse` tag → width/height default `0`) but **is skipped by the runtime**.
Never mix the two attribute sets.

`isUseless()` (`abstractpartellipse.cpp:137`): null rect → dropped.

### 9.5 `<arc>`

`PartArc::toXml()` — `partarc.cpp:98`.

| Attribute | Written at | Type | Read default | Required at runtime |
|---|---|---|---|---|
| `x` | `partarc.cpp:110` | real, top-left of the **full ellipse** bbox | `0` | **YES** (`elementpicturefactory.cpp:465`) |
| `y` | `partarc.cpp:111` | real | `0` | **YES** (`:466`) |
| `width` | `partarc.cpp:112` | real, full ellipse width | `0` | **YES** (`:467`) |
| `height` | `partarc.cpp:113` | real, full ellipse height | `0` | **YES** (`:468`) |
| `start` | `partarc.cpp:115` | real, **degrees** | `0` (`partarc.cpp:132`) | **YES** (`:469`) |
| `angle` | `partarc.cpp:116` | real span, **degrees** | `-1440` (`partarc.cpp:133`) | **YES** (`:470`) |
| `style`, `antialias` | | §9.1 | | |

Internally QET stores sixteenths of a degree; `toXml` divides by 16 and `fromXml`
multiplies by 16 — the file value is **plain degrees**, positive or negative.
Runtime: `painter.drawArc(QRectF(x,y,w,h), start*16, angle*16)`
(`elementpicturefactory.cpp:484`) — plain `QPainter` semantics: **0° is at the
3 o'clock position; positive angles sweep counter-clockwise, negative clockwise**
(Qt handles the y-down flip internally, so this is what the viewer sees).
`start` is where the arc begins, `angle` is the signed span from there.
Corpus example, a half-circle opening downward:
`<arc x="-7.4982" y="2.5849" width="4" height="4" start="-90" angle="-180"/>`.

Arcs are **never filled**: the editor removes the brush explicitly
(`partarc.cpp:62`) and `drawArc` does not fill. `filling:` in an arc's style is a
no-op. There is no `arc` variant that closes to a chord or pie in this format.

### 9.6 `<polygon>`

`PartPolygon::toXml()` — `partpolygon.cpp:116`.

| Attribute | Written at | Type | Notes |
|---|---|---|---|
| `x1`, `y1`, `x2`, `y2`, … `xN`, `yN` | `partpolygon.cpp:124-125` | real | Vertices, **1-based, contiguous** |
| `closed` | `partpolygon.cpp:128` | `"false"` only | **Written only when the polygon is open.** |
| `style`, `antialias` | | §9.1 | |

Vertex discovery walks `i = 1, 2, 3 …` and **stops at the first index where either
`xi` or `yi` is missing or unparsable** — editor `partpolygon.cpp:88-95`, runtime
`elementpicturefactory.cpp:490-493`. A gap (`x1 y1 x3 y3`) silently truncates the
polygon to one point. Numbering must be dense from 1.

Closure: the editor reads `m_closed = qde.attribute("closed") != "false"`
(`partpolygon.cpp:107`) — **absent means closed**. The runtime checks
`dom.attribute("closed") == "false"` → `drawPolyline`, else `drawPolygon`
(`elementpicturefactory.cpp:512-517`). Same result, opposite phrasing; both agree
that only the exact string `false` opens the polygon.

Runtime requires **at least 2 vertices** (`if (i < 3) return;`,
`elementpicturefactory.cpp:496-498`) — a 1-point polygon renders nothing.
`isUseless()` (`partpolygon.cpp:138`): all points equal → dropped.

Corpus max observed: 15 vertices.

### 9.7 `<text>` — static text

`PartText::toXml()` — `parttext.cpp:159`. **No `style`/`antialias`.**

| Attribute | Written at | Type | Read behaviour |
|---|---|---|---|
| `x` | `parttext.cpp:166` | real | `toDouble()`, no default guard (`parttext.cpp:147`) |
| `y` | `parttext.cpp:167` | real | idem |
| `text` | `parttext.cpp:168` | string | The literal text, in an **attribute**, not a text node (`parttext.cpp:132`) |
| `font` | `parttext.cpp:169` | Qt font description, §9.7.1 | Used only if `size` is absent |
| `rotation` | `parttext.cpp:170` | real degrees, 1 decimal | default `0`, normalised via `QET::correctAngle` (`sources/qet.cpp:614`, called at `parttext.cpp:149`) |
| `color` | `parttext.cpp:171` | `#rrggbb` (`QColor::name()`) | default `#000000` (`parttext.cpp:131`) |
| `Halignment` | `parttext.cpp:177/179` | `AlignRight` \| `AlignHCenter` | **Only written when non-default.** |
| `Valignment` | `parttext.cpp:181/183` | `AlignBottom` \| `AlignVCenter` | **Only written when non-default.** |
| `size` | *never written* | int | **If present, wins over `font`.** |

`size` (legacy, 1904 of 2541 corpus `<text>` elements have it) is read first by
both the editor (`parttext.cpp:117-125`) and the factory
(`elementpicturefactory.cpp:538-543`); values `< 1` or unparsable fall back to
`20` in the editor. **Never emit both `size` and `font`** — emit `font` only, and
never emit `size` in new elements.

Alignment values are `Qt::Alignment` enum key names resolved via `QMetaEnum`
(`parttext.cpp:135-144`). Valid strings: `AlignLeft` `AlignRight` `AlignHCenter`
`AlignJustify` `AlignTop` `AlignBottom` `AlignVCenter`. An unrecognised string
yields `keyToValue() == -1` → garbage alignment. The runtime only honours
`Halignment` and only when it is `AlignHCenter`/`AlignRight`
(`elementpicturefactory.cpp:576-587`); `Valignment` is an editor-only anchor.

**Anchor point:** `x,y` is the **baseline-left of the first line**, not the top-left.
- Runtime: `painter.translate(x, y)` then `translate(0, -fontMetrics.ascent())`
  with `documentMargin = 0` (`elementpicturefactory.cpp:566-571, 585`).
- Editor: `setPos(x, y)` with an item transform of `-margin()` where
  `margin() = (documentMargin, documentMargin + ascent)` and `documentMargin = 1.0`
  (`parttext.cpp:192-206, 496-503`, set at `parttext.cpp:38`).

The two agree on the glyph origin. **A generator that treats `y` as the text top
will place text one ascent too low.** Empirically, for a 5 pt font, subtract ≈4 px
from a desired top-edge Y.

`isUseless()` (`parttext.cpp:287`): empty text → dropped on save.

#### 9.7.1 The `font` attribute format

`QETUtils::fontToString()` — `sources/utils/qetutils.cpp`. QET deliberately does
**not** use `QFont::toString()` (Qt 6.11 changed it to 19 fields, unreadable by
Qt 5). It always writes the **Qt 5 "10/11 field" form**, comma-separated:

```
family,pointSizeF,pixelSize,styleHint,legacyWeight,style,underline,strikeOut,fixedPitch,0[,styleName]
```

* `legacyWeight`: `0 12 25 50 57 63 75 81 87` mapping to OpenType 100…900
  (`qetutils.cpp`, `legacyFontWeight()`). **50 = Normal, 75 = Bold.**
* `styleHint` is typically `5` (`QFont::AnyStyle` → in practice `SansSerif`).
* `style`: 0 = normal, 1 = italic, 2 = oblique.
* The trailing `0` is the (unused) tenth field; an eleventh optional field is the
  style name.

Known-good values in the tree
(`sources/import/edz/edzelementbuilder.cpp:33-37`):

```
Liberation Sans,5,-1,5,50,0,0,0,0,0,Regular
Liberation Sans,5,-1,5,75,0,0,0,0,0,Bold
Liberation Sans,9,-1,5,50,0,0,0,0,0,Regular
```

Most common in the corpus: `Sans Serif,4,-1,5,50,0,0,0,0,0`,
`Sans Serif,9,-1,5,50,0,0,0,0,0`, `DejaVu Sans,5,-1,5,50,0,0,0,0,0`,
`MS Shell Dlg 2,4,-1,5,75,0,0,0,0,0,Gras`.

QET's default UI font family is `Liberation Sans` at 9.0 pt
(`QETApp::diagramTextsFont()`, `sources/qetapp.cpp:1358-1370`, overridable by the
`diagramitemfont` / `diagramitemsize` settings). **Use `Liberation Sans` for
portability.** `fontFromString()` (`qetutils.cpp`) can salvage a 19-field Qt 6.11
string, but only the plain `…,0,0` case — do not emit that form.

### 9.8 `<dynamic_text>` — per-instance text

`PartDynamicTextField::toXml()` — `sources/editor/graphicspart/partdynamictextfield.cpp:134`
(tag from `xmlName()`, `:60`). **No `style`/`antialias`.**

| Attribute | Written at | Type | Read default |
|---|---|---|---|
| `x` | `partdynamictextfield.cpp:142` | real | `0` (`:212`) |
| `y` | `partdynamictextfield.cpp:143` | real | `0` |
| `z` | `partdynamictextfield.cpp:144` | real | current zValue (`:215`). **Editor only** — `DynamicElementTextItem::fromXml` never reads it. |
| `rotation` | `partdynamictextfield.cpp:145` | real degrees | `0`, via `QET::correctAngle` (`:216`) |
| `font` | `partdynamictextfield.cpp:146` | §9.7.1 | falls back to `font_size` then to 9 pt (`:221-236`) |
| `uuid` | `partdynamictextfield.cpp:147` | `{uuid}` | random if absent (`:238`) |
| `frame` | `partdynamictextfield.cpp:148` | `"true"`/`"false"` | `"false"` (`:239`) |
| `text_width` | `partdynamictextfield.cpp:149` | real; **`-1` = no wrapping** | `-1` (`:240`) |
| `keep_visual_rotation` | `partdynamictextfield.cpp:150` | `"true"`/`"false"` | **`"true"`** (`:217`) — note the default differs from what a fresh part writes |
| `rotation_point_center` | `partdynamictextfield.cpp:151` | `"true"`/`"false"` | `"false"` (`:218`) |
| `text_from` | `partdynamictextfield.cpp:154` | `UserText` \| `ElementInfo` \| `CompositeText` | **no default — an invalid string gives `keyToValue() == -1`** |
| `Halignment` | `partdynamictextfield.cpp:158-162` | `AlignRight` \| `AlignLeft` \| `AlignHCenter` | absent = untouched |
| `Valignment` | `partdynamictextfield.cpp:165-169` | `AlignBottom` \| `AlignTop` \| `AlignVCenter` | absent = untouched |
| `font_size` | *legacy, never written* | int | used when `font` absent (`:230-233`) |
| `font_family` | *legacy, never written* | string | runtime only (`dynamicelementtextitem.cpp`) |

Child elements (**text nodes, not attributes**):

| Child | Written at | Purpose |
|---|---|---|
| `<text>` | `partdynamictextfield.cpp:171-173` | The literal text. **Always written, even when empty** (`<text/>`). |
| `<info_name>` | `partdynamictextfield.cpp:176-180` | Only when non-empty. The info key (§6.1), e.g. `label`. Required when `text_from="ElementInfo"`. |
| `<composite_text>` | `partdynamictextfield.cpp:183-187` | Only when non-empty. A template mixing literals and `%{key}` variables. Required when `text_from="CompositeText"`. |
| `<color>` | `partdynamictextfield.cpp:190-194` | Only when **not** black. `#rrggbb`. |

`text_from` semantics (`DynamicElementTextItem::TextFrom`,
`sources/qetgraphicsitem/dynamicelementtextitem.h:57-62`):
* `UserText` — display `<text>` verbatim.
* `ElementInfo` — display the value of the info key in `<info_name>` for the
  placed instance.
* `CompositeText` — display `<composite_text>` with `%{key}` substituted.

Canonical label field (as generated by `EdzElementBuilder`,
`sources/import/edz/edzelementbuilder.cpp:240-260`):

```xml
<dynamic_text x="-9" y="-29" z="5" text_width="-1"
              Halignment="AlignLeft" Valignment="AlignTop"
              frame="false" rotation="0" keep_visual_rotation="false"
              text_from="ElementInfo"
              uuid="{a0a0a0a0-0000-4000-8000-000000000001}"
              font="Liberation Sans,9,-1,5,50,0,0,0,0,0,Regular">
    <text/>
    <info_name>label</info_name>
</dynamic_text>
```

`isUseless()` is hardcoded `false` (`partdynamictextfield.h:77`) — an empty
dynamic text is always kept.

At runtime, `Element::parseDynamicText()` (`element.cpp:638-651`) **clones the node,
renames the tag to `dynamic_elmt_text`, and assigns a fresh UUID** — the `uuid` in
the `.elmt` identifies the *definition* of the text field, not the placed instance.

### 9.9 `<input>` — legacy text field (do not generate)

1627 occurrences in the corpus. Attributes: `x`, `y`, `size` (all required —
`element.cpp:584-589`), `text`, `tagg`, `rotation`, plus a legacy `rotate`.
`tagg` absent or `"none"` → `UserText` from `text`; otherwise `ElementInfo` with
info key = `tagg` (`partdynamictextfield.cpp:287-296`).

Both loaders convert it into a dynamic text field on the fly
(`elementscene.cpp:1223`, `element.cpp:570`), including a Y-offset fix-up because
`<input>`'s anchor was the mid-left of the text
(`PartDynamicTextField::fromTextFieldXml`, `partdynamictextfield.cpp:280-315`).
`Element::buildFromXml` also force-tags the **first** `<input>` as `tagg="label"`
if none carries it (`element.cpp:487-504`).

**Read-only compatibility. Emit `<dynamic_text>` instead.**

### 9.10 `<plc_table>`

`PartPlcTable::toXml()` — `sources/editor/graphicspart/partplctable.cpp:370`.
Attributes: `x`, `y` (real, default `0`), plus `style`/`antialias`.
Size is not stored — it is recomputed from the `<plcMasterData>` in
`<kindInformations>` (`partplctable.cpp:396-400`).
**Not rendered into the cached picture** (`elementpicturefactory.cpp:254-262`,
skipped deliberately to avoid a crash); drawn live by `Element::drawPlcTable()`.
Only meaningful with `link_type="master"` + kind `type=plc`. Niche — skip it.

---

## 10. `<terminal>` — the connection points

This is the most consequential part type. Written by `TerminalData::toXml()` —
`sources/properties/terminaldata.cpp:100` (delegated from `PartTerminal::toXml()`,
`sources/editor/graphicspart/partterminal.cpp:62`). Read by
`TerminalData::fromXml()` — `terminaldata.cpp:150`.

| Attribute | Written at | Type | Required? | Read default |
|---|---|---|---|---|
| `x` | `terminaldata.cpp:107` | real | **YES** — `attributeIsAReal` failure → `fromXml` returns false → the whole terminal is dropped (`terminaldata.cpp:157-158`, `element.cpp:660-664`) | — |
| `y` | `terminaldata.cpp:108` | real | **YES** (`terminaldata.cpp:160-161`) | — |
| `orientation` | `terminaldata.cpp:113` | `n` \| `e` \| `s` \| `w` | effectively yes | anything not starting with `e`/`s`/`w` → **North** (`sources/qet.cpp:44-50`) |
| `uuid` | `terminaldata.cpp:110` | `{uuid}` | no | null UUID; see §10.2 |
| `name` | `terminaldata.cpp:111` | string | no | empty |
| `type` | `terminaldata.cpp:116` | `Generic` \| `Inner` \| `Outer` \| `No` \| `Nc` \| `Common` | no | `Generic` (`terminaldata.cpp:230-234`) |
| `show_name` | `terminaldata.cpp:119` | `"true"` only | no | false |
| `label_x` | `terminaldata.cpp:120` | real | only if `show_name="true"` | `0` |
| `label_y` | `terminaldata.cpp:121` | real | idem | `0` |
| `label_font` | `terminaldata.cpp:122` | §9.7.1 | idem | app default |
| `label_rotation` | `terminaldata.cpp:123` | real degrees | idem | `0` |
| `label_halign` | `terminaldata.cpp:124` | **integer** `Qt::Alignment` bitmask | idem | `0` |
| `label_valign` | `terminaldata.cpp:125` | **integer** bitmask | idem | `0` |
| `label_frame` | `terminaldata.cpp:127` | `"true"`; written only when true | no | false |
| `label_color` | `terminaldata.cpp:129` | `#rrggbb`; written only when ≠ black | no | black |
| `use_master_label` | `terminaldata.cpp:134` | `"true"`; written only when true | no | false |
| `master_label_index` | `terminaldata.cpp:135` | int, `T1=0 … T20=19` | with `use_master_label` | `0` |

**No `style` / `antialias`** — `PartTerminal::toXml` delegates entirely to
`TerminalData` and never calls `stylesToXml`. A terminal's stub is always drawn by
`Terminal::paint()` in QET's own colours.

The `label_*` block is written **only when `show_name` is true**
(`terminaldata.cpp:118-130`) and read only then (`terminaldata.cpp:181-200`).
Note the alignment attributes here are **raw integers**, unlike the `Qt::Alignment`
*key names* used by `<text>` and `<dynamic_text>`. Useful values:
`AlignLeft=1 AlignRight=2 AlignHCenter=4 AlignTop=32 AlignBottom=64 AlignVCenter=128`.

### 10.1 Geometry and orientation

`x,y` is the **outer end** — the point where a conductor docks. The stub runs
`terminalSize = 4.0` px **inward**, and that inner point is where the element's
artwork should meet it:

`Terminal::init()` — `sources/qetgraphicsitem/terminal.cpp:45-55`
(mirrored by `PartTerminal::updateSecondPoint()`, `partterminal.cpp`):

| `orientation` | Meaning | Inner (body) point |
|---|---|---|
| `n` | terminal faces **north/up**; conductor arrives from above | `(x, y + 4)` |
| `e` | faces east/right | `(x - 4, y)` |
| `s` | faces south/down | `(x, y - 4)` |
| `w` | faces west/left | `(x + 4, y)` |

`Qet::orientationFromString()` (`sources/qet.cpp:44-50`) inspects only `s[0]` —
`"north"` also yields North, and an **empty string indexes `s[0]` on an empty
QString**. Always write exactly one of `n` / `e` / `s` / `w`.

Corpus: `n` 1698, `s` 1377, `e` 419, `w` 411 — all four letters, never integers.

**Critical format split:** inside a diagram's `<element>` instance (a `.qet`
project, not an `.elmt`), `Terminal::toXml()` writes
`orientation` as the **integer** enum value and adds an `id`
(`sources/qetgraphicsitem/terminal.cpp:714-725`, `element.cpp:955-965`), validated
by `Terminal::valideXml()` (`terminal.cpp:733-767`) which requires an integer
`orientation` in 0..3 (`North=0 East=1 South=2 West=3`, `sources/qet.h:211-215`)
and an integer `id`. **Never copy a project-file `<terminal>` into an `.elmt`, or
vice versa.** In `.elmt` files: letters, no `id`.

Terminals are sorted top-to-bottom then left-to-right on load
(`element.cpp:671-682`), so the implicit index a user sees is positional, not
document order.

### 10.2 Terminal identity — why `uuid` is not a per-instance id

`Terminal::stableUuid()` — `sources/qetgraphicsitem/terminal.cpp:853-875`.

The project database keys terminals on the **pair** `(uuid, element_uuid)`, not on
`uuid` alone, with an explicit comment
(`sources/dataBase/projectdatabase.cpp:455-472`):

> *`Terminal::uuid()` is the terminal-position id baked into the catalog `.elmt`
> definition (e.g. "the top terminal") — identical across every placed instance of
> that catalog element, not a per-instance id.*

Consequences for a generator:

1. The `uuid` you write into a `<terminal>` is a **position identity within the
   element definition**. Every placed copy of the element shares it. That is
   correct and intended — do not try to make it unique per placement.
2. **Each terminal in one element must have a distinct `uuid`.** Two terminals with
   the same uuid in one definition collapse to one row in the `terminal` table
   (primary key `(uuid, element_uuid)`), and conductor endpoints become ambiguous.
3. **Omitting `uuid` is safe and back-compatible.** When absent, `stableUuid()`
   derives a UUID v5 in the fixed namespace
   `{6b1f6d1e-6a1a-5f7e-9a3d-9c0a5b2d7e11}` from the key
   `"%1|%2|%3"` = `x` (4 decimals) `|` `y` (4 decimals) `|` `int(orientation)`
   (`terminal.cpp:859-874`). Position + orientation only — the **name is
   deliberately excluded**, because QET rewrites a terminal named `_` as unnamed
   and that would change identity on the first resave.
4. Therefore **two terminals at the same `(x, y, orientation)` in one element are
   indistinguishable** if neither carries an explicit `uuid`. The code notes this
   happens three times in the whole example corpus and is harmless, but a generator
   should never do it deliberately.
5. Derived ids are v5, explicit editor-written ids are v4 — they cannot collide.
6. `conductor` rows carry `terminal1_uuid + terminal1_element_uuid` (and 2)
   as a compound foreign key (`projectdatabase.cpp:476-486`). A conductor whose
   terminal has no parent element is skipped entirely
   (`projectdatabase.cpp:262-274`).

**Recommended:** emit an explicit unique `{uuid}` per terminal. It survives moving
the terminal (the derived id would not), which matters if the element is ever
edited after placement.

### 10.3 Dead terminal attributes in the corpus

`number` (269) and `nameHidden` (265, with junk values like `192`, `33`, `176`)
appear in old files. Grepping `sources/` finds no reader for either on a
`<terminal>` node. **Silently ignored. Do not emit.**

---

## 11. Coordinate system, hotspot and bounding box — the exact algorithm

`ElementScene::toXml()` — `sources/editor/elementscene.cpp:424-455`:

```
size = elementSceneGeometricRect()                       // union of part geometric rects
if !size.contains(0,0):  centerElementToOrigin(); recompute size

upwidth  = (round(size.width())/10)*10 + 10
if (round(size.width())  % 10) > 6:  upwidth  += 10
upheight = (round(size.height())/10)*10 + 10
if (round(size.height()) % 10) > 6:  upheight += 10

xmargin = round(upwidth  - size.width())
ymargin = round(upheight - size.height())

width     = upwidth
height    = upheight
hotspot_x = -(round(size.x() - xmargin/2))               // NOTE: integer division
hotspot_y = -(round(size.y() - ymargin/2))
```

Key facts a generator must absorb:

* **`hotspot_x` = distance in px from the element box's left edge to `x = 0`.**
  Equivalently `hotspot_x = -min_x + left_padding`. If the leftmost drawn point is
  at `x = -35` and you want 5 px of padding, `hotspot_x = 40`.
* Both are **integers** and both are typically **positive** even though part
  coordinates are negative.
* The box always gets **at least 10 px of total slack** and is a multiple of 10.
* `elementSceneGeometricRect()` (`elementscene.cpp:607-620`) **excludes
  `PartText` and `PartDynamicTextField`**. Text can and does stick out of the
  declared box. That is normal — it is why the corpus has texts at `y = -23.45` in
  a `height="20"` element.
* Per-part contributions are `sceneGeometricRect()`, which is **not** always the
  drawn shape: `PartTerminal::sceneGeometricRect()` returns `sceneBoundingRect()`
  (`partterminal.cpp`), i.e. the 4 px stub **plus ~3 px of handle padding on each
  side**; `PartArc::sceneGeometricRect()` (`partarc.cpp:237`) returns the true arc
  extent, not the full ellipse box. Reproducing QET's byte-exact numbers therefore
  requires reimplementing those; **you do not need to.**
* **Nothing validates that `width`/`height`/`hotspot_*` actually enclose the
  artwork.** They only set the placed element's `boundingRect()`
  (`element.cpp:274-277`) — used for the selection highlight, the drag preview and
  the catalogue pixmap crop. A box a few px larger than QET would have computed is
  harmless; a box smaller than the artwork clips the catalogue pixmap but still
  draws correctly on the diagram.
* `centerElementToOrigin()` (`elementscene.cpp:1369`) moves everything by
  `-round(center)` when the origin is outside the drawing. A generator that already
  places the origin inside its artwork never triggers this.

A simpler, sufficient generator algorithm (this is exactly what
`EdzElementBuilder::build()` does, `sources/import/edz/edzelementbuilder.cpp:105-140`):

```
collect every drawn coordinate, plus (0,0)
pad = 10
min_x = min(xs) - pad ;  max_x = max(xs) + pad
min_y = min(ys) - pad ;  max_y = max(ys) + pad
width     = max(10, ceilTo10(max_x - min_x))
height    = max(10, ceilTo10(max_y - min_y))
hotspot_x = -min_x
hotspot_y = -min_y
```

with `ceilTo10(v) = ((v + 9) / 10) * 10`.

This yields a slightly larger box than `ElementScene::toXml()` would (it pads a
full 10 px on every side rather than distributing one 10-px slack allowance), which
is fine per the "nothing validates the box" point above. Use whichever is more
convenient and be consistent.

**Grid:** there is no grid attribute in the format. `ElementScene` starts at
`setGrid(1,1)` (`elementscene.cpp:68`); `ElementView::drawBackground`
(`sources/editor/elementview.cpp:509-531`) picks 1/2/5/10 px snapping depending on
zoom. The **10 px convention is a placement convention only**: `width`/`height` are
forced to multiples of 10, and the reference generator puts terminals on multiples
of 10 so they align with the diagram grid. Put terminals on multiples of 10.

---

## 12. Validation — what `--check-elements` actually verifies

`checkOneElement()` — `sources/cli_export.cpp:426-493`;
`checkElements()` — `cli_export.cpp:480-522`. CLI registration at
`cli_export.cpp:76` (`--check-elements`), dispatch at `cli_export.cpp:783-790`.

```
qelectrotech --check-elements <element.elmt | directory>
```

Directory mode recurses (`QDirIterator::Subdirectories`) over `*.elmt`, sorted.

Exit codes: `0` per-file OK, `1` warning, `2` failure; the run exits `1` if any
file failed, `2` if the path does not exist or contains no `.elmt`.

| Check | Result |
|---|---|
| File cannot be opened | `FAIL … (cannot open)` |
| `QDomDocument::setContent` fails | `FAIL … (XML error line N: msg)` |
| Root tag ≠ `definition` **or** `type` ≠ `element` | `FAIL … (root is not <definition type="element">)` |
| `width` or `height` missing / non-numeric / **zero** | `FAIL … (missing/zero bounding box WxH)` |
| `width < 0` or `height < 0` | `WARN … (negative bounding box …)` — deliberately a warning, "so this agrees with QET's own loader" |
| `elementsByTagName("terminal").count() == 0` | `WARN … (loads, but 0 terminals)` |
| otherwise | `OK … (N terminals)` |

**What `--check-elements` does NOT check** — and QET therefore accepts or silently
mangles:

* `hotspot_x` / `hotspot_y` presence — but **`Element::buildFromXml` requires them**
  (`element.cpp:439-446`). A file passing `--check-elements` can still fail to load.
* Non-integer `width`/`height`/`hotspot_*` — `toDouble` accepts `"90.5"` here,
  `toInt` rejects it at load. **The validator passes files QET cannot open.**
* Terminals counted anywhere in the document, including outside `<description>`
  where no loader will find them.
* Any part attribute, any `style` string, any tag name.
* `<names>`, `<uuid>`, `<elementInformations>`.

### 12.1 What QET rejects outright

| Condition | Where | Effect |
|---|---|---|
| root tag ≠ `definition` or `type` ≠ `element` | `element.cpp:415-422` (state 4), `elementscene.cpp:1191`, `elementdata.cpp:46-49` | Element does not load; editor loads zero parts |
| `width`/`height`/`hotspot_x`/`hotspot_y` missing or non-integer | `element.cpp:437-446` (state 5), `elementpicturefactory.cpp:180-186` | Element does not load; no picture |
| `<definition>` has no child nodes | `element.cpp:449-455` (state 6) | Element does not load |
| No graphic part parsed and picture is null | `element.cpp:544-550` (state 8) | Element does not load |
| `<terminal>` missing or unparsable `x` or `y` | `terminaldata.cpp:154-161` → `element.cpp:660-664` | That terminal is dropped; `Element::parseElement` returns false → **state 7, the whole element fails to load** |

That last one is the harshest: **one malformed terminal kills the entire element.**

### 12.2 What QET silently ignores

* Unknown tags inside `<description>` (`elementscene.cpp:1224`, `element.cpp:571`).
* Unknown or misspelled `style` keys and values (`customelementgraphicpart.cpp:530-533`).
* `style` pairs containing whitespace — **editor OK, runtime rendering lost**
  (§9.1).
* `antialias` at runtime (always on).
* `<definition orientation=…>`, `<definition ic=…>`.
* `<terminal number=…>`, `<terminal nameHidden=…>`.
* `<kindInformation show=…>`.
* `z` on `dynamic_text` at runtime.
* A `<part>` whose required real attributes are missing: the runtime `parse*`
  functions `return` early with no message; the editor substitutes `0`.
  **Result: the shape exists in the editor at the origin, and is invisible on a
  diagram.** This is the single most common way a hand-written element "half works".
* A `.elmt` whose `version` is newer than `0.200.1` — a warning is printed to
  **stderr only** (`element.cpp:423-434`, `elementpicturefactory.cpp:165-175`);
  loading proceeds.

---

## 13. Minimal valid `.elmt`

Smallest file that loads, renders, and connects. A 20×20 box with one terminal on
top and one on the bottom.

```xml
<?xml version="1.0" encoding="utf-8"?>
<definition type="element" link_type="simple" version="0.200.1"
            width="30" height="40" hotspot_x="15" hotspot_y="20">
    <uuid uuid="{11111111-2222-4333-8444-555555555555}"/>
    <names>
        <name lang="en">Minimal box</name>
    </names>
    <elementInformations/>
    <description>
        <rect x="-10" y="-10" width="20" height="20"
              style="line-style:normal;line-weight:normal;filling:none;color:black"
              antialias="false"/>
        <terminal x="0" y="-14" orientation="n"
                  uuid="{aaaaaaaa-0000-4000-8000-000000000001}"/>
        <terminal x="0" y="14" orientation="s"
                  uuid="{aaaaaaaa-0000-4000-8000-000000000002}"/>
    </description>
</definition>
```

Why the numbers work (`ElementScene::toXml()` formula, §11, ignoring the few px of
handle padding `PartTerminal::sceneGeometricRect()` adds):
* Drawn extent `x ∈ [-10, 10]` (w = 20), `y ∈ [-14, 14]` (h = 28).
* `upwidth  = (20/10)*10 + 10 = 30`; `20 % 10 = 0`, not > 6, so no extra 10.
* `upheight = (28/10)*10 + 10 = 30`; `28 % 10 = 8`, > 6, so `+10` → `40`.
* `xmargin = 30-20 = 10`, `ymargin = 40-28 = 12`.
* `hotspot_x = -(-10 - 10/2) = 15`; `hotspot_y = -(-14 - 12/2) = 20`.

QET's own save would land within a few px of these because of the terminal handle
padding; that difference does not matter (§11).
* Terminal `n` at `y=-14` has its body point at `y=-10` — exactly the rect's top edge.
* Terminal `s` at `y=14` has its body point at `y=10` — the rect's bottom edge.

`--check-elements` on this file prints `OK … (2 terminals)`.

---

## 14. Richer annotated `.elmt`

A 2-pole contactor coil: master link type, BOM info, a bound label, a static
caption, and a dashed guide line.

```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- type: MANDATORY, exactly this literal.
     link_type="master": enables the <kindInformations> block.
     version: must be <= QetVersion::currentVersion() (0.200.1) or QET warns.
     width/height/hotspot_x/hotspot_y: INTEGERS. Sizes are multiples of 10;
     hotspots are the origin's offset from the box's top-left corner.
     NOTE: XML comments may never appear inside a start tag - they are only
     placed between elements here. -->
<definition type="element" link_type="master" version="0.200.1"
            width="60" height="70" hotspot_x="30" hotspot_y="35">

    <!-- Cache key for the rendered picture. Regenerate per element, not per save. -->
    <uuid uuid="{9e2f0d3a-71c4-4a9b-8e35-2f6c11ab77d0}"/>

    <!-- Browser tree label. 2-letter lang codes; "en" is the fallback. -->
    <names>
        <name lang="en">Contactor coil, 2 pole</name>
        <name lang="fr">Bobine de contacteur, 2 pôles</name>
        <name lang="de">Schützspule, 2-polig</name>
    </names>

    <!-- Only read when link_type is master|slave|terminal. Values are TEXT NODES. -->
    <kindInformations>
        <kindInformation name="type">coil</kindInformation>
        <!-- max_slaves omitted == unlimited (-1) -->
    </kindInformations>

    <!-- BOM payload. name+show are attributes; the value is a text node.
         Keys with an empty value are dropped by QET on the next save. -->
    <elementInformations>
        <elementInformation name="label" show="1">KM</elementInformation>
        <elementInformation name="manufacturer" show="1">Schneider</elementInformation>
        <elementInformation name="manufacturer_reference" show="1">LC1D09</elementInformation>
        <elementInformation name="designation" show="1">3P contactor, 9 A</elementInformation>
        <elementInformation name="quantity" show="1">1</elementInformation>
    </elementInformations>

    <!-- Free text, no attributes. Author/licence note by convention. -->
    <informations>Generated by mcp-qet. License: see ELEMENTS.LICENSE</informations>

    <!-- Every drawable part MUST live here. Document order == paint order. -->
    <description>

        <!-- Coil body. x,y is the TOP-LEFT corner. rx/ry round the corners. -->
        <rect x="-15" y="-10" width="30" height="20" rx="0" ry="0"
              style="line-style:normal;line-weight:normal;filling:none;color:black"
              antialias="false"/>

        <!-- Upper lead. No arrowheads. length1/2 only matter if end1/2 != none. -->
        <line x1="0" y1="-25" x2="0" y2="-10"
              end1="none" length1="1.5" end2="none" length2="1.5"
              style="line-style:normal;line-weight:normal;filling:none;color:black"
              antialias="false"/>

        <!-- Lower lead. -->
        <line x1="0" y1="10" x2="0" y2="25"
              end1="none" length1="1.5" end2="none" length2="1.5"
              style="line-style:normal;line-weight:normal;filling:none;color:black"
              antialias="false"/>

        <!-- Mechanical-link guide. Note "hight" (sic) and "dashed". -->
        <line x1="15" y1="0" x2="26" y2="0"
              end1="none" length1="1.5" end2="none" length2="1.5"
              style="line-style:dashed;line-weight:thin;filling:none;color:gray"
              antialias="true"/>

        <!-- Filled marker dot. x,y is the TOP-LEFT of the bbox, NOT the centre:
             centred on (0,0) with diameter 3 => x = y = -1.5 -->
        <circle x="-1.5" y="-1.5" diameter="3"
                style="line-style:normal;line-weight:normal;filling:black;color:black"
                antialias="true"/>

        <!-- Static caption. x,y is the BASELINE-LEFT of the first line.
             No style/antialias on <text>. Emit "font", never "size". -->
        <text x="-11" y="3" text="A1"
              font="Liberation Sans,5,-1,5,50,0,0,0,0,0,Regular"
              rotation="0" color="#000000"/>

        <!-- Per-instance device tag, bound to the "label" info key.
             <text/> stays empty because text_from is ElementInfo. -->
        <dynamic_text x="18" y="-30" z="5" rotation="0"
                      text_width="-1"
                      Halignment="AlignLeft" Valignment="AlignTop"
                      frame="false"
                      keep_visual_rotation="false"
                      rotation_point_center="false"
                      text_from="ElementInfo"
                      uuid="{6d4a1f88-0c1e-4b2a-9d77-3ec5c9a1f201}"
                      font="Liberation Sans,9,-1,5,50,0,0,0,0,0,Regular">
            <text/>
            <info_name>label</info_name>
        </dynamic_text>

        <!-- Terminals. x,y is the CONDUCTOR end; the 4 px stub runs inward.
             "n" => body point at (0, -25+4) = (0, -21). Distinct uuids. -->
        <terminal x="0" y="-25" orientation="n" name="A1" type="Generic"
                  uuid="{2c9a4e10-5b31-4d02-b7a8-9f0e4d2c1a01}"/>
        <terminal x="0" y="25" orientation="s" name="A2" type="Generic"
                  uuid="{2c9a4e10-5b31-4d02-b7a8-9f0e4d2c1a02}"/>

    </description>
</definition>
```

Bounding-box check: drawn extent, terminals included and texts excluded, is
`x ∈ [-15, 26]`, `y ∈ [-25, 25]` → 41 × 50. Padded and rounded up to tens that is
`width = 60`, `height = 70`, with `hotspot_x = 30` and `hotspot_y = 35` placing the
origin at the box centre. Any box of at least that size with a matching hotspot is
accepted (§11).
Round to the integers shown.

---

## 15. Cross-check against real files: format vs. corpus

Read from the 943 `<definition>` blocks embedded in `examples/*.qet`.
All discrepancies are **historical attributes the current writer no longer emits**;
none contradicts the format described above.

| Observation | Count | Verdict |
|---|---|---|
| `<definition orientation="dnny">` etc. | 249 | Legacy, no reader. Ignore. |
| `<definition ic="true">` | 177 | Legacy, no reader. Ignore. |
| `<definition>` with no `link_type` | 376 | Legal; defaults to `simple`. |
| `<definition version>` values `0.1`…`0.90` | all 943 | All `< 0.200.1`; no warning. |
| `<text size="9">` instead of `font` | 1904 of 2541 | Legacy but **actively read, and it wins over `font`**. Do not emit. |
| `<input …>` legacy text field | 1627 | Converted on load. Do not emit. |
| `<dynamic_text font_size="9">` without `font` | 52 | Legacy fallback path. Do not emit. |
| `<dynamic_text font_family=…>` | 1 | Runtime-only legacy. Do not emit. |
| `<terminal number=…>` | 269 | Dead. Ignore. |
| `<terminal nameHidden=…>` (values `0`,`1`,`192`,`33`…) | 265 | Dead. Ignore. |
| `<terminal type>` values seen: only `Generic`, `Outer` | 362 | Subset of the 6 documented. |
| `<terminal orientation>` values: only `n e s w` | 3905 | Confirms the letter form in `.elmt`. |
| `<kindInformation show=…>` | 264 | Dead. Ignore. |
| `<polygon>` max vertex index | 15 | No hard limit in code. |
| `<circle>` never has `width`/`height`; `<ellipse>` never has `diameter` | all | Confirms §9.4. |
| `<line>` without `end1/end2/length1/length2` | 69 of 10187 | Legal; defaults `none` / `1.5`. |
| `<polygon closed="false">` | 797 of 1002 | Confirms "absent == closed". |
| `<elementInformations/>` empty | 319 | Normal; empty values are stripped. |

**No contradiction found between the code-derived format and the corpus.**

---

## 16. Gotchas checklist for a generator

Ordered by how badly each one breaks things.

1. **`width` / `height` / `hotspot_x` / `hotspot_y` must be integer literals.**
   `"90.0"` → element does not load at all, while `--check-elements` says OK.
2. **One `<terminal>` with a bad `x` or `y` kills the whole element** (state 7).
3. **All parts must be inside `<description>`.** Anything else is invisible to every
   loader, with no warning.
4. **Tag names are exact and unknown ones are silently dropped.** `<rectangle>`,
   `<Line>`, `<Circle>` all vanish without a message.
5. **Missing a required real attribute makes a shape render nowhere but still exist
   in the editor.** `parseLine/parseRect/parseEllipse/parseCircle/parseArc` return
   early with no diagnostic. Always emit every geometry attribute explicitly.
6. **`<circle x y diameter>` — x,y is the top-left of the bounding box, not the
   centre.** Same for `<ellipse>` and `<arc>`.
7. **`<text x y>` is the baseline-left, not the top-left.** Text sits roughly one
   font-ascent higher than a naive top-left assumption.
8. **Never emit `size` on `<text>`.** If both `size` and `font` are present, `size`
   wins in both readers and your font is discarded.
9. **No spaces in a `style` value.** The runtime regex has no `\s*`; a spaced style
   loads fine in the editor and renders completely unstyled on a diagram.
10. **`line-weight` values are `none thin normal hight eleve`.** `hight` is
    misspelled in the format and `eleve` is French; both must be transcribed
    verbatim. `high`/`bold`/`2` are silently ignored → falls back to `normal`.
11. **`line-weight:none` is defeated by a later `color:<name>`** other than
    `black`/`white` at runtime. Pair it with `color:none`.
12. **Terminal `orientation` is a letter (`n e s w`) in `.elmt`, an integer (0–3) in
    `.qet`.** Copying between the two silently reorients or drops terminals.
13. **Give every terminal in one element a distinct `uuid`**, or omit `uuid` on all
    of them and guarantee no two share `(x, y, orientation)` — those collapse to one
    row in the project database and confuse conductor resolution.
14. **`text_from` must be exactly `UserText`, `ElementInfo` or `CompositeText`.**
    Anything else gives `keyToValue() == -1`, an out-of-range enum, and undefined
    text behaviour. `ElementInfo` also requires a non-empty `<info_name>` child.
15. **`<dynamic_text>` children are text nodes, not attributes.** `<text>Foo</text>`,
    not `text="Foo"` — the opposite of `<text text="Foo"/>`.
16. **`keep_visual_rotation` defaults to `true` on read** but a fresh field writes
    `false`. Always state it explicitly.
17. **Polygon vertices must be numbered `1..N` with no gaps.** Parsing stops dead at
    the first missing index.
18. **A polygon with fewer than 2 vertices renders nothing** at runtime
    (`if (i < 3) return;`).
19. **`antialias` must be the literal `"true"`** — `"True"`, `"1"`, `"yes"` are false.
    (Runtime ignores it entirely.)
20. **Put terminals on multiples of 10** so they meet user-drawn conductors on the
    diagram grid. Nothing enforces it; everything downstream assumes it.
21. **The element bounding box excludes `<text>` and `<dynamic_text>`.** Do not
    inflate `width`/`height` to cover labels — QET does not, and your element will
    space oddly among stock parts.
22. **`version` above `0.200.1`** prints a stderr warning on every load. Write
    `0.200.1` or lower.
23. **Emit UTF-8 without a BOM.** `QETXML::writeXmlFile` sets
    `setGenerateByteOrderMark(false)`; a BOM would land before `<?xml`.
24. **The element `<uuid>` is regenerated by QET on every save.** Do not treat it as
    a stable external identifier for round-tripping.
25. **`<name>` values are trimmed on write**; leading/trailing whitespace is lost.

---

## 17. `sources/qet_elementscaler/` — scaling elements

`sources/qet_elementscaler/qet_elementscaler.cpp` (159 lines) is **not** a scaler.
It is a thin wrapper that shells out to a **separate third-party binary**,
`QET_ElementScaler`, expected at `QETApp::dataDir()/binary/QET_ElementScaler[.exe]`
(`qet_elementscaler.cpp:113-124`), downloadable from
`https://github.com/plc-user/QET_ElementScaler/releases`
(`qet_elementscaler.cpp:147-152`).

`ElementScaler(file_path, parent)` (`qet_elementscaler.cpp:36-110`):
prompts for an X factor and a Y factor (`QInputDialog::getDouble`, range 0.1–100,
5 decimals), and a mirror choice, then runs:

```
QET_ElementScaler -x <fx> -y <fy> [--FlipHorizontal] [--FlipVertical] -o -f <file_path>
```

`-o` makes the tool write the scaled `.elmt` to **stdout**, which the wrapper
captures as a `QByteArray` and returns (`:91-107`). stderr is surfaced verbatim in
a `QMessageBox` detail pane. If the binary is absent, the function returns an empty
`QByteArray` immediately (`:38-40`).

`ElementScalerIsPresent()` (`:135-158`) only checks `QFile::exists`.

**Implication for an MCP server:** scaling is not implemented inside QET and is not
available unless the user has installed the external binary. A server that wants to
scale an element should transform the coordinates itself — every geometric
attribute in §9 is an absolute scene coordinate with no per-part transform, so
scaling is a straightforward multiply of `x y x1 y1 x2 y2 xN yN width height
diameter length1 length2 label_x label_y` plus recomputation of
`width`/`height`/`hotspot_*` per §11. Angles (`start`, `angle`, `rotation`) are
invariant under uniform scaling but not under a non-uniform one.

UNVERIFIED: whether `QET_ElementScaler` rewrites `<terminal uuid>` values. If it
does not, scaling preserves terminal identity; if it strips them, identity falls
back to the derived position hash and **changes**, because the derived key is
`x|y|orientation` (§10.2). Test: scale an element with explicit terminal uuids by
2.0 and diff the `<terminal>` nodes.

---

## 18. Open questions

* **UNVERIFIED:** whether `hotspot_x`/`hotspot_y` may legitimately be negative.
  `Element::setHotspot` clamps only the upper bound (`element.cpp:310-321`), so a
  negative value survives and shifts the origin outside the box. No corpus example
  exists. Test: load an element with `hotspot_x="-5"` and check the placement
  offset and the drag preview.
* **UNVERIFIED:** [inference] the arc sweep direction above is taken from
  `QPainter::drawArc`'s documented contract, not from an observed render. Test:
  draw `<arc x="0" y="0" width="20" height="20" start="0" angle="90"/>` and confirm
  the swept quadrant is the upper-right one.
* **UNVERIFIED:** whether `<plc_table>` is usable outside a `link_type="master"`
  PLC element. `PartPlcTable::fromXml` recomputes its size from live
  `ElementData` (`partplctable.cpp:396-400`); with no `<plcMasterData>` the size is
  presumably zero. Test: place a `plc_table` in a `simple` element and check
  whether it renders or crashes.
* **UNVERIFIED:** whether a `<text>` `Valignment` value has any effect at runtime.
  `parseText` reads only `Halignment` (`elementpicturefactory.cpp:576-587`).
  [inference] `Valignment` on a static `<text>` is editor-only. Test: set
  `Valignment="AlignBottom"` and compare the editor canvas to the diagram render.
* **UNVERIFIED:** whether `elementsByTagName("terminal")` in `checkOneElement`
  (`cli_export.cpp:441`) can be fooled by a `<terminal>` inside `<plcIOs>`
  (`<plcIO><terminal>…</terminal></plcIO>`, `elementdata.cpp:212-216`).
  [inference] yes — `elementsByTagName` is document-wide, so a PLC master element
  would report an inflated terminal count. Test: run `--check-elements` on a PLC
  master `.elmt` and compare the reported count to the real `<description>` count.
