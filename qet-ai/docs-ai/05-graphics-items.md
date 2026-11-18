# QElectroTech — Graphics Items, Conductors, Terminals, Cross-references

Scope: `sources/qetgraphicsitem/`, `sources/QetGraphicsItemModeler/`, `sources/diagramevent/`,
`sources/dvevent/`, root-level `conductor*.{cpp,h}`, `sources/elementsmover.cpp`,
`sources/elementprovider.cpp`. Written for an agent that will build an MCP server that reads and
edits `.qet` project files and `.elmt` element definitions.

All paths are relative to the source root (`/root/qet/qelectrotech-source-mirror`).
XML attribute and tag names below are transcribed verbatim from the C++ — they are
case-sensitive and several are inconsistently spelled (`terminalname1`, `dash-size`,
`hold_to_bottom_page`, `numsize`). Do not "normalise" them.

---

## 1. Purpose — the item hierarchy and its XML mapping

### 1.1 Runtime class tree

```
QGraphicsObject
├── QetGraphicsItem                    qetgraphicsitem.h:27      (snap-to-grid base)
│   ├── Element                        element.h:43              Type = UserType+1000
│   │   ├── SimpleElement              simpleelement.h           Element::Simple
│   │   ├── MasterElement              masterelement.h           Element::Master
│   │   ├── SlaveElement               slaveelement.h            Element::Slave
│   │   ├── ReportElement              reportelement.h           Element::NextReport | PreviousReport
│   │   └── TerminalElement            terminalelement.h         Element::Terminale
│   └── DiagramImageItem               diagramimageitem.h:42     Type = UserType+1007
├── Conductor                          conductor.h:43            Type = UserType+1001
├── Terminal                           terminal.h:35             Type = UserType+1002
├── DiagramTextItem  (QGraphicsTextItem-derived)                 diagramtextitem.h:57  Type = UserType+1004
│   ├── IndependentTextItem            independenttextitem.h:39  Type = UserType+1005 (diagram-level free text)
│   ├── ConductorTextItem              conductortextitem.h:42    Type = UserType+1006 (the conductor's number label)
│   └── DynamicElementTextItem         dynamicelementtextitem.h  Type = UserType+1010
├── ElementTextItemGroup                                         elementtextitemgroup.h (QGraphicsItemGroup)
├── CrossRefItem                       crossrefitem.h            Type = UserType+1009
├── QetShapeItem                       qetshapeitem.h            Type = UserType+1008
└── QetGraphicsHandlerItem             QetGraphicsItemModeler/   Type = UserType+1200
```

`QetGraphicsItem::setPos()` (qetgraphicsitem.cpp) silently snaps every position through
`Diagram::snapToGrid()`; grid is 10×10 px (`Diagram::xGrid`/`yGrid`, diagram.cpp:46-47).
Loaders that must preserve an exact stored position bypass this by calling
`QGraphicsObject::setPos` directly — see element.cpp:801 and diagramimageitem.cpp:145.

### 1.2 XML shape of a folio

A `.qet` project file is `<project>` → `<diagram>`* (+ `<collection>` holding embedded `.elmt`
definitions). Each `<diagram>` contains, in the order `Diagram::fromXml` reads them
(diagram.cpp:1296-1553):

```xml
<diagram title="..." folio="..." cols="..." rows="..." ...>
  <defaultconductor .../>            <!-- ConductorProperties, same attrs as <conductor> -->
  <elements>   <element .../>   </elements>
  <inputs>     <input .../>     </inputs>        <!-- IndependentTextItem -->
  <images>     <image>...</image> </images>      <!-- DiagramImageItem, base64 PNG text node -->
  <shapes>     <shape .../>     </shapes>        <!-- QetShapeItem -->
  <tables>     <table .../>     </tables>        <!-- QetGraphicsTableItem, out of scope -->
  <conductors> <conductor .../> </conductors>
  ...terminal strips...
</diagram>
```

**Load order is load-bearing.** `<elements>` must be parsed before `<conductors>`, because
conductor endpoints resolve against the element list built in the same pass
(`added_elements`, diagram.cpp:1405-1447 then 1531-1553). An MCP server writing a project must
keep `<elements>` before `<conductors>` inside a `<diagram>`.

Element instance node (element.cpp:911 `Element::toXml`):

```xml
<element type="embed://import/10_electric/foo.elmt"
         uuid="{...}" prefix="" freezeLabel="false"
         x="960" y="130" z="10" orientation="0">
  <sequentialNumbers>…</sequentialNumbers>   <!-- only if it has children -->
  <terminals> <terminal x="-9" y="0" orientation="3" id="24"/> </terminals>
  <inputs/>                                   <!-- always empty today, kept for compat -->
  <links_uuids> <link_uuid uuid="{...}" group_index="0"/> </links_uuids>
  <elementInformations> <elementInformation name="label">Q1</elementInformation> </elementInformations>
  <properties> <element_type terminal_type="…" terminal_function="…" terminal_led="…"/> </properties>
  <plcMasterData .../>                        <!-- masters of MasterType PLC only -->
  <dynamic_texts> <dynamic_elmt_text .../> </dynamic_texts>
  <texts_groups>  <texts_group .../>        </texts_groups>
</element>
```

`Element::valideXml` (element.cpp:692) accepts a node only if tagName is `element` and it has
`type`, `x`, `y`, with `x`/`y` parsable as doubles. `uuid`, `orientation`, `z` are optional;
a missing `uuid` gets a fresh v4 minted at load (element.cpp:783) — meaning **an element without
a `uuid` attribute cannot be a conductor endpoint reference across a save cycle.**

`orientation` on the instance is an integer 0..3 = 0°/90°/180°/270°; out-of-range values are
clamped to 0 (element.cpp:824-829) and applied as `setRotation(90*read_ori)`.

---

## 2. Conductors

### 2.1 `<conductor>` — the complete attribute set

Written by `Conductor::toXml` (conductor.cpp:1053) plus `ConductorProperties::toXml`
(conductorproperties.cpp:269) plus `ConductorTextItem` position, in this order:

**Identity and geometry** (conductor.cpp:1059-1092)

| attribute | written by | meaning |
|---|---|---|
| `uuid` | conductor.cpp:1059 | `QUuid` of the conductor, `{...}` braced form. **New field**: absent in every `examples/*.qet`; `Conductor::fromXml` mints a fresh v4 when absent/empty/malformed (conductor.cpp:1013-1020). |
| `x`, `y` | conductor.cpp:1060-1061 | `pos()` of the conductor item itself. In practice always `"0"`/`"0"` in the corpus — the path is stored in scene-ish local coords. |
| `element1` / `element2` | :1068 / :1090 | `{uuid}` of the **element** owning the endpoint terminal. Present ⇒ uuid addressing mode. |
| `terminal1` / `terminal2` | :1066 or :1076 | **Polymorphic.** If the terminal has a uuid ⇒ the terminal's `{uuid}`; otherwise the legacy integer id from `table_adr_id`. |
| `terminalname1` / `terminalname2` | :1077 / :1099 | `Terminal::name()` — denormalised copy, informational. |
| `element1_label` / `element2_label` | :1069 / :1091 | `Element::actualLabel()` of the owning element — denormalised. |
| `element1_name` / `element2_name` | :1075 / :1097 | `Element::name()` — denormalised. |
| `element1_linked` / `element2_linked` | :1073 / :1095 | `actualLabel()` of the **last** entry of `linkedElements()`; omitted when the element has no links. |
| `freezeLabel` | :1101 | `"true"`/`"false"`; freezes autonumbering of the label. |
| `userx`, `usery` | :1119-1120 | present only if the text item was dragged by the user. |
| `rotation` | :1123 | present only if the text item was rotated by the user. |

The `element*_label` / `element*_name` / `element*_linked` / `terminalname*` attributes are
**write-only denormalisations**: nothing in `Conductor::fromXml` or `findTerminal` reads them.
They exist for the wiring-list exporter, which reads them directly out of the DOM
(wiringlistexport.cpp:121-135). `wiringlistexport.cpp:121` also accepts `element1id` /
`element2id` as aliases for `element1` / `element2`; no writer in the tree emits those names
(grep confirms), so treat them as a tolerated foreign-file alias. [inference]

**Properties** (conductorproperties.cpp:269-303) — all written unconditionally except `color`:

| attribute | type | default on read | notes |
|---|---|---|---|
| `type` | `"multi"` \| `"single"` | `multi` | `ConductorProperties::typeToString`, conductorproperties.cpp:455. Anything ≠ `"single"` reads as `Multi` (:329-336). |
| `color` | `#rrggbb` | black | **Omitted when black** (:274-275). Absent/invalid ⇒ black. |
| `bicolor` | `"true"`/`"false"` | `false` | |
| `color2` | `#rrggbb` | black | second colour when `bicolor` |
| `dash-size` | int | `1` | note the hyphen |
| `num` | string | `""` | the conductor's displayed number/label text |
| `text_color` | `#rrggbb` | black | |
| `formula` | string | `""` | autonum formula, e.g. `%id%seqt_1`, evaluated in `Conductor::setProperties` (conductor.cpp:1602-1613) |
| `cable` | string | `""` | |
| `bus` | string | `""` | |
| `function` | string | `""` | |
| `tension_protocol` | string | `""` | |
| `conductor_color` | string | `""` | *wire* colour as free text (e.g. "BK"), distinct from `color` |
| `conductor_section` | string | `""` | wire cross-section as free text (e.g. "1.5") |
| `numsize` | int | `9` | point size of the number text |
| `condsize` | double | `1` | line width of the conductor |
| `displaytext` | `0`/`1` | `1` | written via `setAttribute(bool)` ⇒ emits `"0"`/`"1"` |
| `onetextperfolio` | `0`/`1` | `0` | |
| `vertirotatetext` | double | `0` | degrees, typical `270` |
| `horizrotatetext` | double | `0` | |
| `horizontal-alignment` | `Qt::Alignment` **key name** | `"AlignBottom"` | e.g. `AlignTop`, `AlignBottom`; via `QMetaEnum::valueToKey` |
| `vertical-alignment` | `Qt::Alignment` key name | `"AlignRight"` | e.g. `AlignLeft`, `AlignRight` |
| `style` | CSS-ish string | absent = solid | see below |

Note the two alignment attributes are **swapped relative to their names** in the defaults
(`horizontal-alignment` defaults to `AlignBottom`, `vertical-alignment` to `AlignRight`,
conductorproperties.cpp:352-366, matching the member defaults at conductorproperties.h:110-112).
Real files show `horizontal-alignment="AlignTop" vertical-alignment="AlignLeft"`. Do not
"fix" this; round-trip it verbatim.

`style` is written by `ConductorProperties::writeStyle` (conductorproperties.cpp:851) and is
**only ever** one of: absent/empty (SolidLine), `"line-style: dashed;"` (DashLine), or
`"line-style: dashdotted"` (DashDotLine — note: no trailing semicolon, an asymmetry in the
source). `readStyle` (:808) splits on `;` and matches `^(?<name>[a-z-]+): (?<value>[a-z-]+)$`
— **exactly one space after the colon**, lowercase and hyphens only. Recognised value names:
`dashed`, `dashdotted`, `normal`. Anything unparsable falls back to SolidLine with a qWarning.

**Single-line extras** — written only when `type == "single"` (`SingleLineProperties::toXml`,
conductorproperties.cpp:218):

| attribute | values | notes |
|---|---|---|
| `ground` | `"true"`/`"false"` | |
| `neutral` | `"true"`/`"false"` | |
| `phase` | int | phase count |
| `pen` | `"true"` only when set | PEN = merged protective-earth+neutral; on read, `is_pen` is true only if `ground && neutral && pen=="true"` (:234) |

### 2.2 Child nodes of `<conductor>`

```xml
<conductor ...>
  <segment orientation="horizontal" length="-9"/>
  <segment orientation="vertical"   length="-268"/>
  ...
  <sequentialNumbers>
    <unit>…;…</unit> <wrap>…</wrap> <unitFolio>…</unitFolio>
    <ten>…</ten> <tenFolio>…</tenFolio>
    <hundred>…</hundred> <hundredFolio>…</hundredFolio> <alpha>…</alpha>
  </sequentialNumbers>
</conductor>
```

`<sequentialNumbers>` (autoNum/assignvariables.cpp) — each child is a text node holding a
`;`-joined `QStringList`; empty lists are omitted on write. Element nodes carry the same
structure. Legacy files instead carry flat attributes `sequ_1`, `sequf_1`, `seqt_1`,
`seqtf_1`, `seqh_1` on the `<conductor>`/`<element>` node; the presence of any of those
switches the loader to a retro-compat path (conductor.cpp:1031-1034, element.cpp:790-800).

### 2.3 Segment / path encoding — exact rules

`Conductor::toXml` writes `<segment>` children **only when `modified_path == true`**
(conductor.cpp:1104-1116), i.e. only for conductors the user has hand-routed. A conductor with
no `<segment>` children is auto-routed at load.

Encoding (`Conductor::pathFromXml`, conductor.cpp:1135):
- Iterate direct children with tagName `segment`. A segment without a `length` attribute, or
  whose `length` is not a double, is **silently skipped** (:1147-1155).
- `orientation` is the literal string `"horizontal"`; **any other value, including a
  misspelling or missing attribute, is treated as vertical** (:1157-1163).
- Lengths are signed. The path is reconstructed by walking from
  `mapFromScene(terminal1->dockConductor())`, adding `(length,0)` for horizontal and
  `(0,length)` for vertical segments, in document order (:1184-1191).
- **Consistency check:** the summed horizontal lengths must equal `t2.x()-t1.x()` and the
  summed vertical lengths must equal `t2.y()-t1.y()`, each within **1.0 px** (:1170-1181).
  If not, `pathFromXml` logs *"les segments du conducteur ne semblent pas coherents"* and
  returns `false`, and the conductor keeps the auto-generated path from the constructor.
  This is the single most important invariant for an editor: **move an element and the stored
  segments become inconsistent, and QET silently reroutes the wire.**
- If there are zero usable segments, `generateConductorPath()` is called and `true` is returned
  (:1166-1169). Zero segments is therefore not an error.

Auto-routing (`Conductor::generateConductorPath`, conductor.cpp:362) is a fixed
Manhattan router: each terminal is first extended 10 px outward along its orientation and
rounded to a multiple of 10 (`extendTerminal`, :469), then one of four cases ("cas 1..4")
picks either an L, a Z with a mid-x line, or a Z with a mid-y line, depending on the pair of
terminal orientations and whether the route descends or ascends. Mid-lines are snapped down to
the grid (`while (ligne_inter_x % Diagram::xGrid) --ligne_inter_x`).

Beyond the flat `<segment>` list, the runtime keeps a `ConductorProfilesGroup` — a
`QHash<Qt::Corner, ConductorProfile>` with one profile per *quadrant of travel*
(TopLeft/TopRight/BottomLeft/BottomRight; `Conductor::currentPathType()` → `movementType()`,
conductor.cpp:1962-1976). `ConductorProfile` (conductorprofile.h) is a list of
`ConductorSegmentProfile{qreal length; bool isHorizontal;}` plus the two endpoint orientations.
When a terminal moves, `updateConductorPath` (:223) rescales the stored profile: it computes
the h/v deltas and distributes them proportionally across the horizontal and vertical segments
(`shareOffsetBetweenSegments`, :299). **Profiles are never serialised** — only the flat
`<segment>` list is, and it is re-derived on load via `saveProfile(false)` at :1197.
Consequence: a saved conductor only remembers its shape for the *one* quadrant it was in at
save time.

`ConductorSegment` (conductorsegment.h) is a doubly linked list; `Conductor::segments` points
at the head. `segmentsToPath()` (:182) turns it into the `QPainterPath`.

### 2.4 Conductor properties semantics worth knowing

- `Conductor::setProperties` (conductor.cpp:1595) short-circuits when
  `m_properties == property`. `ConductorProperties::operator==` (conductorproperties.cpp:766)
  compares every persisted field — `type, color, m_bicolor, m_color_2, m_dash_size, style,
  text, text_color, m_formula, m_cable, m_bus, m_function, m_tension_protocol, m_wire_color,
  m_wire_section, m_show_text, text_size, cond_size, verti_rotate_text, horiz_rotate_text,
  singleLineProperties, m_one_text_per_folio, m_horizontal_alignment, m_vertical_alignment` —
  with `singleLineProperties` delegating to `SingleLineProperties::operator==`
  (conductorproperties.cpp:866). Nothing that reaches XML is excluded.
- If `m_formula` is non-empty, `text` is *recomputed* from the formula whenever the conductor
  is attached to a diagram (:1602-1607). **Editing `num` without clearing `formula` is
  pointless — the formula wins on next load.**
- `setPropertyToPotential(props, only_text)` (:1564) pushes properties across the whole
  electrical potential. With `only_text = true` it copies only
  `m_formula, text, m_function, m_tension_protocol, m_wire_color, m_wire_section`.
- `Conductor::relatedPotentialConductors()` (conductor.cpp) walks the potential recursively:
  it follows both terminals, and through `relatedPotentialTerminal()` (terminal.cpp:963) it
  also crosses **folio reports** (jumps to the linked report's terminals) and **terminal
  elements** (all other terminals of that element) — unless the terminal element's
  `elementInformations()["potential_isolating"] == "true"`, which stops propagation.
- Default properties for a new conductor come from `Diagram::defaultConductorProperties`,
  serialised as `<defaultconductor>` with the identical attribute set.

---

## 3. Terminals at runtime

### 3.1 Two XML representations of one concept

| | in the `.elmt` `<definition>` | in the `.qet` `<element>` instance |
|---|---|---|
| written by | `TerminalData::toXml` (properties/terminaldata.cpp:100) | `Terminal::toXml` (terminal.cpp:714) + `Element::toXml` |
| `x`,`y` | `q->scenePos()` in element coords, rounded to 2 dp — the **conductor dock point** | `dock_elmt_` — the dock point shifted **4 px toward the element body** |
| `orientation` | string `"n"/"e"/"s"/"w"` (`Qet::orientationToString`) | **integer** `0..3` (North/East/South/West, qet.h:211) |
| `uuid` | `{...}` v4, authored by the element editor | *not written* |
| `name` | free text | *not written* |
| `type` | `Generic`/`Inner`/`Outer`/`No`/`Nc`/`Common` | *not written* |
| `id` | — | int, assigned at save time |
| label fields | `show_name`, `label_x`, `label_y`, `label_font`, `label_rotation`, `label_halign`, `label_valign`, `label_frame`, `label_color` (written only when `show_name`) | *not written* |
| master-label override | `use_master_label`, `master_label_index` (written only when set) | *not written* |

The 4 px offset is `Terminal::terminalSize` (terminal.cpp:34, value `4.0`) applied in
`Terminal::init` (:45-52): North ⇒ `+(0,4)`, East ⇒ `+(-4,0)`, West ⇒ `+(4,0)`,
South ⇒ `+(0,-4)`. So an `.elmt` terminal at `x="9" y="-10" orientation="e"` becomes
`<terminal x="5" y="-10" orientation="1" id="…"/>` in the diagram.

Old files also carry `name`, `number`, `nameHidden` on the *instance* `<terminal>` node
(seen in `examples/weneedpolonez-…qet`). Nothing in the current tree writes them
(grep: only `elementdata.cpp` uses `"number"`, for a kindInformation). **They are dropped on
resave** — expect them in inputs, never emit them.

### 3.2 Terminal identity and how it is resolved

`Terminal` holds a `TerminalData* d` (terminal.h:126) carrying `m_uuid`, `m_name`, `m_pos`,
`m_orientation`, `m_type`. Three identity notions exist:

1. **`Terminal::uuid()`** (terminal.cpp:818) — `d->m_uuid`, straight from the `.elmt`
   definition. Null for every element authored before the field existed (most of the installed
   base: 364 of 1041 `<terminal>` tags in `examples/weneedpolonez-…qet` carry one).
2. **`Terminal::stableUuid()`** (terminal.cpp:853) — returns `uuid()` when non-null, otherwise
   a **UUID v5** in the fixed namespace `{6b1f6d1e-6a1a-5f7e-9a3d-9c0a5b2d7e11}` over the key
   `"%1|%2|%3"` = `m_pos.x` (4 dp) `|` `m_pos.y` (4 dp) `|` `int(m_orientation)`. The terminal
   **name is deliberately excluded** because QET rewrites a terminal named `"_"` as unnamed on
   save, which would change the identity of most terminals in `industrial.qet` on first resave.
   This is derived, never written to file. An MCP server that needs a stable per-terminal key
   for elements without uuids should reimplement exactly this v5 derivation.
3. **Legacy integer `id`** — assigned at save time in `Element::toXml` (element.cpp:942-963)
   by walking `terminals()` and handing out `max(existing ids)+1` upward. It is **not stable**:
   it depends on element save order within the folio, and on `m_terminals` ordering.

`m_terminals` order is fixed by `Element::parseTerminal` (element.cpp) which re-sorts after
every insertion: **ascending `dockConductor().y()`, ties broken by ascending `x()`** — i.e.
top-to-bottom, then left-to-right, in *scene* coordinates. So the id sequence in a resaved file
reflects geometry, not definition order.

### 3.3 Endpoint resolution at load

`findTerminal(index, conductorNode, table_adr_id, added_elements)` — diagram.cpp:1208:

```
if node has attribute "element<N>":                       # uuid mode
    element_uuid  = QUuid(node.attribute("element<N>"))
    for element in added_elements:                        # linear scan, this folio only
        if element->uuid() != element_uuid: continue
        terminal_uuid = QUuid(node.attribute("terminal<N>"))
        for terminal in element->terminals():
            if terminal->uuid() == terminal_uuid: return terminal
        qDebug "terminalN: {…} not found in elementN: {…}" ; break
    qDebug "elementN: {…} not found"
else:                                                     # legacy int-id mode
    id = node.attribute("terminal<N>").toInt()
    return table_adr_id.value(id)   # or qDebug "terminal id N not found"
return nullptr
```

`table_adr_id` is built in `Element::fromXml` (element.cpp:723-770): for every child `Terminal`
object of the element, it walks every `<terminal>` node in the element's `<terminals>` list and
calls `Terminal::fromXml` (terminal.cpp:780), which returns true iff

```
qFuzzyCompare(node.x, dock_elmt_.x()) && qFuzzyCompare(node.y, dock_elmt_.y())
&& node.orientation.toInt() == d->m_orientation
```

— i.e. **exact geometric match on the offset dock point and the raw (unrotated) orientation.**
On a match, `priv_id_adr[node.id] = terminal`. If any id in `priv_id_adr` already exists in the
folio-wide `table_adr_id`, the whole element load **fails** and the element is removed from the
scene (element.cpp:753-762, diagram.cpp:1439-1445).

`Terminal::valideXml` (terminal.cpp:733) additionally rejects a node lacking `x`, `y` or
`orientation`, or whose `id` is not an int, or whose orientation is not in `{0,1,2,3}`.

**If either endpoint resolves to `nullptr`, or both resolve to the same `Terminal`, the whole
`<conductor>` node is skipped without any error surfaced to the user** (diagram.cpp:1541).
That is the silent-wire-loss failure mode.

`Conductor::valideXml` (conductor.cpp:604) runs first and requires: tagName `conductor`, both
`terminal1` and `terminal2` present, and per index — if `element<N>` is present, both
`element<N>` and `terminal<N>` must parse as non-null `QUuid`; otherwise `terminal<N>` must
parse as an int. **The two indices are validated independently**, so a mixed conductor
(`terminal1="127"` int + `terminal2="{uuid}"` with `element2`) is legal, and such conductors
exist in `examples/weneedpolonez-Polonez_MR89_wiring_diagram.qet`.

### 3.4 What breaks routing

- `Terminal::addConductor` (terminal.cpp:129) **refuses** a second conductor between the same
  pair of terminals (:142-144) and asserts that the conductor references `this` exactly once.
  A refusal sets `Conductor::m_valid = false` (conductor.cpp:96-100); `Diagram::fromXml`
  deletes such a conductor (diagram.cpp:1543-1551). So duplicate `<conductor>` nodes with the
  same endpoint pair silently lose all but the first.
- `~Terminal` does `qDeleteAll(m_conductors_list)` (terminal.cpp:87-90): deleting a terminal
  deletes its wires.
- `Terminal::orientation()` (terminal.cpp:104) composes the element's rotation with the
  terminal's own: `(elementOrientation + d->m_orientation) mod 4`. Rotating an element
  therefore changes conductor routing but not terminal identity.
- `Terminal::dockConductor()` = `mapToScene(d->m_pos)` (terminal.cpp:794). `m_pos` is *only* set during
  `TerminalData::fromXml` and never by mouse movement (documented at terminaldata.h:100-110).
- `Element::AlignedFreeTerminals()` (element.cpp:1296) and `Terminal::alignedWithTerminal()`
  (terminal.cpp:425) drive auto-connection: a terminal with **zero** conductors that is
  colinear with an oppositely-oriented terminal of another element (`Qet::isOpposed`,
  `QET::lineContainsPoint` on the help line) gets auto-wired.

---

## 4. Cross-references / master–slave links

### 4.1 Storage

Links are stored **only** as `<links_uuids><link_uuid uuid="{…}" group_index="N"/></links_uuids>`
inside the *source* element node (element.cpp:972-988). They are written only when
`!isFree()`. `group_index` is written only when ≥ 0.

```xml
<element type="…" uuid="{8cc7841b-…}">
  …
  <links_uuids>
    <link_uuid uuid="{40419259-316b-489f-972f-9d51b6558144}"/>
  </links_uuids>
</element>
```

The relation is **stored on both sides**: `MasterElement::linkToElement` appends the slave and
calls `elmt->linkToElement(this)` (masterelement.cpp:57-73), and vice versa, so both elements
serialise a `link_uuid` pointing at each other. A one-sided `<links_uuids>` still resolves
(each side loads independently), but resaving will make it two-sided.

### 4.2 Resolution

1. `Element::fromXml` collects the uuids into `tmp_uuids_link` as `LinkInfo{uuid, group_index}`
   (element.cpp:772-781); `group_index` defaults to `-1`.
2. `Diagram::refreshContents()` (diagram.cpp:1621), called from `QETProject` after all folios
   are loaded (qetproject.cpp:301), calls `Element::initLink(project)` on every element.
3. `Element::initLink` (element.cpp:1324) builds an `ElementProvider(prj)` — which searches
   **all** diagrams of the project (elementprovider.cpp:33-37, the excluded-diagram arg is
   null) — resolves via `ElementProvider::fromUuids` (elementprovider.cpp:83-98, a linear scan
   over every element of every diagram), then calls `elmt->linkToElement(this)` and records
   `m_group_index_map[elmt] = group_index` when ≥ 0. `tmp_uuids_link` is then cleared, so
   **`initLink` is single-shot**; links added after that point are runtime-only until saved.

Link legality is enforced per subclass, not by the file:

| class | accepts a link to | file |
|---|---|---|
| `MasterElement` | `linkType() == Slave` only; also refuses duplicates; `isFull()` caps at `kindInformations()["max_slaves"]` (−1 = unlimited) | masterelement.cpp:57, :226 |
| `SlaveElement` | `linkType() == Master` only; **unlinks everything else first** — a slave has at most one master | slaveelement.cpp:51 |
| `ReportElement` | only the *inverse* report kind (`next_report` ↔ `previous_report`); at most one | reportelement.cpp:44-70 |
| `SimpleElement`, `TerminalElement` | `linkToElement` is the no-op base (`Element::linkToElement` is `{}`, element.h:190) — **link_uuids on a simple element are read and then silently dropped** | simpleelement.cpp / terminalelement.cpp |

`link_type` in the **definition** (`.elmt` `<definition link_type="…">`) selects the class via
`ElementFactory::createElement` (factory/elementfactory.cpp:36-63):
`next_report`/`previous_report` → `ReportElement`, `master` → `MasterElement`,
`slave` → `SlaveElement`, `terminal` → `TerminalElement`, anything else → `SimpleElement`.
Canonical strings from `ElementData::typeToString` (properties/elementdata.cpp:663): `simple`,
`next_report`, `previous_report`, `master`, `slave`, `terminal`, `thumbnail`,
`conductor_definition`. Note `Element::kind` (element.h:54-63) is a **bit flag** enum with
`AllReport = 6 = NextReport|PreviousReport`, so `linkType() & Element::AllReport` is the
"is a folio reference" test.

`Element::linkedElements()` (element.h, inline) sorts `connected_elements` through `comparPos`
(element.cpp:1561) before returning: by folio index, then by the folio row *letter*, then by
`pos().x()`, then `y()`. Order is therefore reading order across the whole project.

### 4.3 Contact groups (`group_index`)

A master `.elmt` may declare `<kindInformations>` → `<slaveContactGroups><group …>` with
attributes `type` (`NO`/`NC`/`SW`/`Other`), `subtype` (`SSimple`/`Power`/`DelayOn`/…),
`contactCount`, `terminalCount`, and `<label>` text children (max 20, T1..T20)
— properties/elementdata.cpp:92-115. A slave's `link_uuid/@group_index` selects which group of
its master it occupies. `Terminal::name()` (terminal.cpp:877) then *overrides* the terminal's
own name with `master.slaveContactGroups[group_index].labels[master_label_index]` when the
terminal has `use_master_label="true"` in the definition. `Terminal::baseName()` (:916) returns
the un-overridden name; it is what sorting uses.

For `MasterType::PLC` masters the same machinery reads `plcMasterData().ios[group_index]
.effectiveTerminals()` instead.

### 4.4 `CrossRefItem`

`CrossRefItem` (crossrefitem.h, Type = UserType+1009) is a **pure runtime overlay** — it has no
`toXml`/`fromXml` and nothing about it is persisted. A master creates one lazily when the
project's `XRefProperties` for its `kindInformations()["type"]` has `snapTo() == Bottom`, or
unconditionally for PLC masters (masterelement.cpp:63-68, :160-176). Its rendering reads
`m_element->linkedElements()` and each slave's `kindInformations()["type"]` (`power`, `delay…`)
and `["state"]` (`NO`, `NC`, `SW`) to bucket contacts (`CrossRefItem::CONTACTS`,
crossrefitem.h:66-77). The displayed reference string comes from
`CrossRefItem::elementPositionText` (crossrefitem.cpp:172): the project's
`XRefProperties::masterLabel()` formula (default `%f-%l%c`) run through
`autonum::AssignVariables::formulaToLabel`, optionally prefixed with the power/delay/switch
prefix. XRef configuration itself lives in the project XML as `<xrefs><xref type="coil"
master_label="…" slave_label="…" snapto="…" displayhas="…" xrefpos="…" offset="…"
showpowerctc="…" powerprefix="…" delayprefix="…" switchprefix="…"/></xrefs>`.

### 4.5 `--export-links`

`CLIExport::exportLinks` (cli_export.cpp:604) — invoked as
`qelectrotech --export-links <project.qet> <output.csv>`.

Output CSV, `;`-separated, one header line:

```
element;link_type;linked_to;folio;status
```

- rows: **every element whose `linkType() != Element::Simple`** — masters, slaves, both report
  kinds, terminal elements, thumbnails, conductor definitions; iterated folio by folio in
  `project.diagrams()` order (:613-617).
- `element` = `elementLabel(e)` (cli_export.cpp:84): `elementInformations()["label"]`, falling
  back to `Element::name()`. Passed through `csvField()` (:288) for quoting.
- `link_type` = `Element::linkTypeToString()` (element.cpp:1355) — the deprecated stringifier,
  values `Simple`/`NextReport`/`PreviousReport`/`Master`/`Slave`/`Terminale`/…
- `linked_to` = `", "`-joined `label(f<folioIndex>)` for each entry of `linkedElements()`,
  e.g. `KM1(f3), KM1(f7)`. Empty string when unlinked.
- `folio` = 1-based folio index of the element (`folioIndex()`, cli_export.cpp:~70).
- `status` = `linked`, or **`UNRESOLVED`** — set only when `linkType()` is exactly `Master` or
  `Slave` **and** `linkedElements()` is empty (:626-632). An unlinked report or terminal
  element is reported as `linked`, which is misleading; do not treat `status` as a general
  health signal.
- stdout gets `Exported <N> linkable element(s), <M> unresolved -> <file>`.

Because the report is produced from the loaded object graph, a `link_uuid` pointing at a
missing/renamed element simply shows up as `UNRESOLVED` with an empty `linked_to`; the dangling
uuid itself is **not** reported. To audit dangling uuids you must read the DOM.

---

## 5. Other item types

### 5.1 `<input>` — `IndependentTextItem` (diagram-level free text)

`independenttextitem.cpp:81` / `:65`.

| attribute | notes |
|---|---|
| `x`, `y` | doubles |
| `text` | **Qt rich text HTML**, `toHtml()`; a full `<!DOCTYPE HTML …><html>…` document, XML-escaped into the attribute. Verified in `examples/Habitat-Unifilaire.qet`. |
| `rotation` | `QET::correctAngle(rotation())` |
| `font` | `QETUtils::fontToString(font())`, e.g. `Arial,9,-1,5,50,0,0,0,0,0,Normal` — a `QFont::toString()` string, comma-separated, **not** the same arity across Qt versions |

No tag validation on read; a missing `font` leaves the constructed default.
Beware: `<input>` is also a **legacy element-definition part** inside `.elmt`
`<description>` (attributes `tagg`, `size`, `text`, `x`, `y`) — a different thing entirely,
parsed by `Element::parseInput` (element.cpp:583). Disambiguate by parent tag.

### 5.2 `<image>` — `DiagramImageItem`

`diagramimageitem.cpp:170` / `:136`.

| attribute | notes |
|---|---|
| `x`, `y`, `z` | doubles |
| `rotation` | `QET::correctAngle` |
| `size` | the item's `scale()` (a double, not pixels) |
| `is_movable` | written from a `bool` ⇒ `"0"`/`"1"`; read with `.toInt()` |

The pixmap is the element's **text node**: base64 of a PNG (`pixmap_.save(&buffer,"PNG")`).
`fromXml` requires `e.firstChild().isText()` — an `<image>` with only whitespace-free-comment
children fails and returns false. Note `fromXml` reads `e.text()`, so a base64 blob split by
the XML writer's indentation still decodes (whitespace is not valid base64 for
`QByteArray::fromBase64` in strict mode, but Qt's default is lenient). UNVERIFIED: whether a
pretty-printed re-indent of the base64 text node survives a load — test by
`--resave` on `examples/perceuse.qet` with `doc.toString(4)` and reloading the result.

### 5.3 `<shape>` — `QetShapeItem`

`qetshapeitem.cpp:888` / `:846`. `ShapeType` (qetshapeitem.h:56-59) values are
`Line`=1, `Rectangle`=2, `Ellipse`=4, `Polygon`=8, serialised by **enum key name**
(`QMetaEnum::valueToKey`): `type="Rectangle"`.

| attribute | applies to | notes |
|---|---|---|
| `type` | all | `Line` \| `Rectangle` \| `Ellipse` \| `Polygon` |
| `is_movable` | all | `"0"`/`"1"` |
| `closed` | all (meaningful for Polygon) | `"0"`/`"1"`, default `"0"` |
| `z` | all | double |
| `x1`,`y1`,`x2`,`y2` | non-Polygon | **scene** coords (`mapToScene(m_P1/m_P2)`) |
| `rx`,`ry` | Rectangle only | corner radii, default `0` |

Children: exactly one `<pen>` and one `<brush>`, plus `<points><point x= y=/>…</points>` for
Polygon (again scene coords).

`<pen>` (qetxml.cpp:36): `style` ∈ `SolidLine`, `DashLine`, `DotLine`, `DashDotLine`,
`DashDotDotLine`, `CustomDashLine`, or `Unknown`; `color` `#rrggbb`; `widthF` double.
**Default when `<pen>` is missing or mis-tagged is `DashLine`, not `SolidLine`**
(qetxml.cpp:65-76). `CustomDashLine` reads back with a hardcoded `[10,10]` dash pattern (qetxml.cpp:79-82) — the
pattern itself is not persisted.

`<brush>` (qetxml.cpp:92-129 write / 138 read): `style` ∈ `NoBrush`, `SolidPattern`, `Dense1Pattern`…`Dense7Pattern`,
`HorPattern`, `VerPattern`, `CrossPattern`, `BDiagPattern`, `FDiagPattern`, `DiagCrossPattern`,
`Unknown`; `color` `#rrggbb`.

### 5.4 `<dynamic_elmt_text>` — `DynamicElementTextItem`

Tag name is `DynamicElementTextItem::xmlTagName()` = `"dynamic_elmt_text"`
(dynamicelementtextitem.h:104). Written at dynamicelementtextitem.cpp:90, read at :159
(which hard-rejects a wrong tagName).

| attribute | notes |
|---|---|
| `x`, `y` | doubles; **applied last** in `fromXml` (after rotation/alignment) so alignment logic cannot clobber them |
| `rotation` | `QET::correctAngle` |
| `uuid` | `{…}`; identity used by `<texts_group>` membership. Missing ⇒ fresh v4. |
| `frame` | `"true"`/`"false"` |
| `text_width` | double, `-1` = unlimited |
| `font` | `QETUtils::fontToString`. Legacy fallback when absent: `font_family`, `font_size`, `dynamicitemstyle` |
| `keep_visual_rotation` | `"true"`/`"false"`, **default on read is `"true"`** |
| `rotation_point_center` | `"true"`/`"false"`, default `false` |
| `text_from` | enum key: `UserText` \| `ElementInfo` \| `CompositeText` (dynamicelementtextitem.h:57-61) |
| `Halignment` | `Qt::Alignment` key: `AlignRight` \| `AlignLeft` \| `AlignHCenter` — note capital H |
| `Valignment` | `AlignBottom` \| `AlignTop` \| `AlignVCenter` |

Children (all optional, all text nodes):
`<text>` the literal displayed text; `<info_name>` the `elementInformation` key when
`text_from="ElementInfo"` (e.g. `label`, `description`); `<composite_text>` the template when
`text_from="CompositeText"` (e.g. `%{description}`); `<color>` `#rrggbb`, **written only when
not black**.

Element::toXml writes *all* dynamic texts — including those owned by groups — into the single
`<dynamic_texts>` container, temporarily pulling them out of their group so their `x`/`y` are
element-relative rather than group-relative (element.cpp:1030-1055). On load, texts are created
first, then groups re-adopt them by uuid.

`Element::fromXml` **deletes the dynamic texts that came from the element definition** before
loading the instance's ones (element.cpp:820-823), so a definition's default texts are not
merged with the saved ones.

### 5.5 `<texts_group>` — `ElementTextItemGroup`

Tag = `ElementTextItemGroup::xmlTaggName()` = `"texts_group"` (note the double-g,
elementtextitemgroup.h:84). Written at elementtextitemgroup.cpp:411, read at :446.

| attribute | notes |
|---|---|
| `name` | free text, default on read `"no name"` |
| `x`, `y` | doubles |
| `alignment` | `Qt::Alignment` key name, e.g. `AlignVCenter` |
| `rotation` | double |
| `vertical_adjustment` | int |
| `frame` | `"true"`/`"false"` |
| `hold_to_bottom_page` | `"true"`/`"false"` |

Child `<texts>` holds `<text uuid="{…}"/>` references into the sibling `<dynamic_texts>`.
Membership resolution is by uuid only; a uuid that matches nothing is silently ignored.

### 5.6 Folio references

There is no dedicated node type. A folio reference is an ordinary `<element>` whose
`.elmt` definition carries `link_type="next_report"` / `"previous_report"`; the pairing to its
counterpart is an ordinary `<links_uuids>` entry. The *label formula* for reports is a project-
level `<report label="%f-%l%c"/>` node. `DynamicElementTextItem` on a report element gets extra
runtime behaviour: it watches the potential's conductor and turns blue on hover to advertise
that a double-click jumps to the other report (dynamicelementtextitem.cpp:654-671, 1108-1140).

`relatedPotentialTerminal` (terminal.cpp:963) is what makes a potential continue across a
folio boundary: for a report element it returns **all terminals of the first linked element**.

---

## 6. The form-factor constraint for a headless part swap

Goal: rewrite an `<element type="…">` to point at a different `.elmt` and keep every
`<conductor>` attached. Derived from `findTerminal` (diagram.cpp:1208), `Terminal::fromXml`
(terminal.cpp:780), `Element::fromXml` (element.cpp:723) and `Conductor::pathFromXml`
(conductor.cpp:1135).

There are **two independent addressing regimes**, and a project can contain both in the same
folio. Which one applies is decided per conductor endpoint by the presence of `element<N>`.

### 6.1 UUID regime (`element1`/`element2` present)

For each affected conductor endpoint, the load must find, **inside the element whose
`uuid` equals `element<N>`**, a terminal whose `Terminal::uuid()` equals `terminal<N>`.

Therefore, to swap parts without touching the `<conductor>` nodes:

1. The `<element uuid="…">` attribute **must not change**. (It is only regenerated by
   `Element::newUuid()`, element.h:216, or by the absent-attribute path at element.cpp:783.)
2. The **new `.elmt` must declare terminals carrying exactly the same `uuid` values** as the
   old one for every terminal that has a wire on it. Terminal uuids are v4 randoms authored by
   the element editor; two independently authored `.elmt` files will never collide. So a naive
   swap between catalogue parts **always drops every wire**, silently.
3. Geometry does **not** matter for identity in this regime. A terminal may move anywhere in
   the new definition and the wire still resolves — but see §6.3 for what happens to the path.
4. Terminal `name`, `type`, `orientation` and count do not participate in resolution.
   Extra terminals in the new part are harmless; a *missing* uuid loses exactly that wire.

Practical consequence for an MCP server: **the safe swap is not "match form factor", it is
"rewrite the references".** For each conductor whose `element<N>` names the swapped element,
map `terminal<N>` from the old definition's terminal uuid to the new definition's terminal uuid
and rewrite the attribute (and, for tidiness, `terminalname<N>`). The mapping has to come from
somewhere — a name match (`<terminal name="1">` ↔ `<terminal name="1">`), a positional match,
or an explicit user-supplied map. Only if you copy the uuids across into the new `.elmt` can
you leave the conductors untouched.

### 6.2 Legacy integer regime (no `element<N>`)

Resolution goes through `table_adr_id`, keyed by the `id` attribute on the *instance*
`<terminal>` nodes. Those nodes are matched to runtime `Terminal` objects purely by geometry
(terminal.cpp:780):

```
qFuzzyCompare(node@x, dock_elmt_.x)  &&  qFuzzyCompare(node@y, dock_elmt_.y)
&&  node@orientation.toInt() == d->m_orientation
```

So in this regime the form-factor constraint is literal and strict. For every wired terminal,
the new `.elmt` must provide a terminal with:

- the **same local position after the 4 px dock offset** — i.e. the same `.elmt` `x`/`y`
  *and* the same orientation, since the offset direction depends on orientation
  (`init()`, terminal.cpp:45-52). `qFuzzyCompare` on doubles is ~1e-12 relative: this is exact
  equality in practice, not a tolerance.
- the **same raw orientation** (the definition's `n`/`e`/`s`/`w` maps to `0`/`1`/`2`/`3`).
  This is the *unrotated* value; the element's own `orientation` attribute is applied on top
  and is irrelevant here.

Beyond that: the element load **fails wholesale** if two elements in the folio claim the same
terminal `id` (element.cpp:753-762). Since ids are handed out at save time from
`max+1` in `Element::toXml`, an MCP server that inserts a new `<element>` with hand-written
terminal ids must guarantee project-folio-wide uniqueness.

Also: if two terminals of the same element sit at the same position and orientation, the
geometric match is ambiguous and the *last* `<terminal>` node processed wins for that id
(element.cpp:738-748). `Terminal::stableUuid`'s doc comment (terminal.cpp:838-846) reports
three such cases across the whole example corpus and argues they are harmless.

### 6.3 Path preservation is a separate, additional constraint

Even when both endpoints resolve, the *drawn route* survives only if the stored `<segment>`
lengths still sum to the terminal separation within **1.0 px** in each axis
(conductor.cpp:1170-1181). So:

- Moving a terminal by ≥ 1 px in the new definition ⇒ the wire reconnects but is **rerouted**
  by `generateConductorPath`, discarding the user's hand-routing.
- Deleting/adding intermediate segments, or rescaling the element, has the same effect.
- Because `<segment>` is written only when `modified_path` is true, most conductors have no
  segments and are auto-routed anyway; those are indifferent to terminal movement.

### 6.4 Checklist: minimal conditions for a wiring-preserving swap

| condition | uuid regime | legacy regime |
|---|---|---|
| `<element uuid>` unchanged | **required** | not used |
| terminal `uuid` preserved per wired terminal | **required** | not used |
| terminal local `x`,`y` preserved | not required (see path) | **required, exact** |
| terminal `orientation` preserved (n/e/s/w) | not required (see path) | **required** |
| terminal `id` uniqueness in folio | n/a | **required** |
| terminal count / names / `type` | irrelevant | irrelevant |
| element `x`,`y`,`orientation`,`z` | free | free |
| hand-routed path preserved | needs terminal positions within 1 px | needs terminal positions within 1 px (implied by the exactness above) |

Note the two regimes have **opposite** notions of "form factor": uuid mode ignores geometry
entirely; legacy mode is nothing but geometry.

### 6.5 Auto-break and auto-connect will edit wiring behind your back

If the project has `autoBreakConductor()` enabled, dropping or moving an element runs
`autoBreakConductors` (autobreakconductor.cpp:71): for each of the element's terminals it
looks for an existing conductor whose painted path passes within **5.0 px** of the terminal's
dock point (`distanceToSegment`, :47 — clamped to the segment, so a point past a wire's end is
correctly "far"), then **deletes** that conductor and creates two new ones through the
element. Sibling conductors sharing the same far endpoint are broken together
(:157-172). `elementsmover.cpp:182-193` runs it on every moved element; the same happens on
element placement (diagrameventaddelement.cpp:265-271). If `autoConductor()` is enabled,
`Element::AlignedFreeTerminals()` additionally auto-wires colinear free terminals
(elementsmover.cpp:196-238, diagrameventaddelement.cpp:274-290), and copies the potential's
properties onto the new wire when every conductor in the potential agrees
(elementsmover.cpp:216-232), else numbers it via `ConductorAutoNumerotation`.

**These paths are GUI-only** (they build `QUndoCommand`s and push to the diagram's undo stack);
a headless XML editor never triggers them — which also means a headless edit will *not*
reproduce what the GUI would have done.

---

## 7. Gotchas

1. **Silent conductor loss.** An unresolvable endpoint drops the whole `<conductor>` with only
   a `qDebug()` line, no user-visible error, no exit code (diagram.cpp:1235-1260, :1541).
   After a scripted edit, diff conductor counts before/after, or use `--export-nets` /
   `--export-links` to detect the loss.

2. **`terminal1`/`terminal2` are polymorphic.** Never assume they are ids or uuids project-wide;
   decide per attribute pair by testing for `element1`/`element2`. Mixed-mode conductors are
   real (`examples/weneedpolonez-Polonez_MR89_wiring_diagram.qet`).

3. **Orientation is encoded two ways.** `"n"/"e"/"s"/"w"` in `.elmt` definitions
   (terminaldata.cpp:112, qet.cpp `orientationToString`), integers `0..3` in `.qet` element
   instances (terminal.cpp:721). Converting the wrong way silently yields North.

4. **The 4 px dock offset.** `.elmt` terminal `(x,y)` ≠ `.qet` instance terminal `(x,y)`; they
   differ by 4 px along the orientation axis (terminal.cpp:45-52).

5. **Resave is lossy for terminals.** `Terminal::toXml` emits only `x`, `y`, `orientation`
   (+`id` from `Element::toXml`). Legacy `name`, `number`, `nameHidden` attributes present in
   old files are dropped. `--resave` is the intended way to see this normalisation
   (`resaveProject`, cli_export.cpp:652).

6. **`formula` beats `num`.** If `formula` is non-empty, `num` is recomputed on load from the
   formula (conductor.cpp:1602-1607). To set a literal wire number you must clear `formula`.

7. **`color` is omitted when black.** Absence means black, not "inherit"
   (conductorproperties.cpp:274-275).

8. **`style` parsing is brittle.** The regex demands exactly `name: value` with one space and
   `[a-z-]+` on both sides; `line-style:dashed` (no space) or `Line-Style: Dashed` silently
   falls back to SolidLine (conductorproperties.cpp:812-846).

9. **Alignment attribute names are semantically swapped** relative to their defaults
   (`horizontal-alignment` defaults `AlignBottom`). Round-trip, don't reason about them.

10. **`<pen>` defaults to `DashLine`** when the node is missing or wrongly tagged
    (qetxml.cpp:65-76) — a shape written without a pen will not come back solid.

11. **Element load can fail wholesale on a terminal-id collision**, taking the element and all
    its wires with it (element.cpp:753-762 → diagram.cpp:1439-1445).

12. **`<segment>` present but inconsistent ⇒ silent reroute** (1.0 px tolerance,
    conductor.cpp:1170-1181). Never edit terminal positions and leave segments alone.

13. **A `<segment>` without `orientation="horizontal"` is vertical**, including a typo'd or
    absent attribute (conductor.cpp:1157).

14. **`links_uuids` on a `SimpleElement`/`TerminalElement` is inert** — read into
    `tmp_uuids_link`, then `linkToElement` does nothing (element.h:190). The uuids are lost on
    resave because `isFree()` stays true.

15. **`Element::initLink` is single-shot per load.** It clears `tmp_uuids_link`
    (element.cpp:1346). Adding a `<link_uuid>` to an already-loaded project in memory has no
    effect; it must be re-loaded.

16. **A slave has at most one master** — `SlaveElement::linkToElement` calls
    `unlinkAllElements()` first (slaveelement.cpp:~57). Writing two `<link_uuid>` entries under
    a slave means only one survives, and which one depends on `ElementProvider::fromUuids`
    iteration order (project diagram order, then scene item order).

17. **`CrossRefItem` is not persisted.** Nothing in the file describes a cross-reference block;
    it is recomputed from `linkedElements()` + project `<xrefs>` settings.

18. **`--export-links` marks only Master/Slave as `UNRESOLVED`.** An orphaned folio report or
    terminal element is reported as `linked` with an empty `linked_to` (cli_export.cpp:626-632).

19. **Duplicate conductors between the same terminal pair are dropped**, not merged
    (terminal.cpp:142-144 → conductor.cpp:96-100 → diagram.cpp:1543-1551).

20. **Terminal ordering is geometric, not authored.** `m_terminals` is re-sorted top-to-bottom
    then left-to-right on every insertion (`Element::parseTerminal`), which is what determines
    the `id` sequence on save — so ids shuffle when terminal geometry changes.

21. **`QetGraphicsItem::setPos` snaps to a 10 px grid** and the snap is read from `QSettings`
    at call time (diagram.cpp:2364-2380), i.e. it depends on the *user's* preferences.
    Loaders deliberately bypass it (element.cpp:801, diagramimageitem.cpp:145); anything you
    write should assume grid-aligned coordinates.

22. **Element `<inputs/>` is always written empty** (element.cpp:966-968) but the tag is still
    emitted; don't infer that an element has no texts from it. Texts live in `<dynamic_texts>`.

23. `Conductor` `x`/`y` are the item's own `pos()`, essentially always `0`. Segment lengths are
    absolute in that frame; do not try to offset a path by editing `x`/`y`.

24. **`uuid` on `<conductor>` is new to this fork.** Existing projects have none, and one is
    minted at load. Any table keyed on it must tolerate a project where every conductor gains a
    fresh uuid on first load. UNVERIFIED: whether two loads of the same untouched legacy file
    produce the same conductor uuids — they do not (`QUuid::createUuid()` is random); confirm
    by `--resave`-ing a legacy project twice and diffing the `uuid` attributes.

25. `Diagram::refreshContents()` is what makes links, conductor texts and table links live
    (diagram.cpp:1621); it is called once per folio from `QETProject` (qetproject.cpp:301).
    Anything constructing a `Diagram` programmatically must call it or cross-references will
    be absent from exports.

---

## 8. Event interfaces (brief)

`sources/diagramevent/` implements the scene-level modal tools. `DiagramEventInterface`
(diagrameventinterface.h:30) is an abstract QObject installed on a `Diagram` via
`Diagram::setEventInterface()` (diagram.cpp:617); the diagram forwards mouse/wheel/key events
to it with `accepted == false`, and deletes it on the `finish()` signal. Concrete tools:
`DiagramEventAddElement`, `DiagramEventAddImage`, `DiagramEventAddShape`,
`DiagramEventAddText`, `DiagramEventAddMacro` (the last calls `Diagram::refreshContents()`
after paste, diagrameventaddmacro.cpp:245).

`sources/dvevent/DVEventInterface` (dveventinterface.h:41) is the same pattern one level up,
on the `DiagramView` (QWidget) rather than the scene; every method returns bool
("did I consume this?").

`sources/QetGraphicsItemModeler/` is the geometry-handle toolkit:
`QetGraphicsHandlerItem` (Type = UserType+1200) is a draggable square that the edited item
adopts via `installSceneEventFilter` + a `sceneEventFilter` override — `Conductor` uses it for
segment dragging (conductor.cpp:739-897), `QetShapeItem` for shape editing.
`QetGraphicsHandlerUtility` (qetgraphicshandlerutility.h) provides the pure geometry:
`pointsForRect/Line/Arc`, `rectForPosAtIndex`, `lineForPosAtIndex`,
`polygonForInsertPoint`, `radiusForPosAtIndex`.

None of this touches XML; it exists only in the GUI. An MCP server should ignore it except to
know that hand-dragging a conductor segment sets `modified_path = true`
(conductor.cpp:838) and hence causes `<segment>` children to be written on the next save.
