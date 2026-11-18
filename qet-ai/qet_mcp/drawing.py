"""Write simple DPTechDraw wiring drawings from a parts + wires description.

This is the "scaffold" layer: it builds a .qet project directly as XML.
Rules it follows (all from docs-ai/01-core-project-model.md and
05-graphics-items.md):

- Parts are embedded under <collection><category name="import">..., and the
  diagram references them as embed://import/<cat>/<file>.elmt. The "import"
  segment is mandatory or the part silently vanishes.
- Wires use modern uuid addressing: element uuid + terminal uuid taken from
  the part's own definition. No <segment> children are written, so QET
  auto-routes every wire at load time.
- Title-block and wire defaults come from DPTechDraw's own settings
  (HKCU\\Software\\DPTechDraw\\DPTechDraw\\diagrameditor), the same
  values "File > Configure > New project" edits.
- Every QET silent-drop condition is checked afterwards by loading the file
  with the real binary (see verify()).
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import uuid as _uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QET_FORMAT_VERSION = "0.200.1"

APPDATA_QET = Path(os.environ.get("APPDATA", "")) / "DPTechDraw" / "DPTechDraw"
DEFAULT_PART_DIRS = [
    APPDATA_QET / "elements-company",
    APPDATA_QET / "elements",          # the "custom" collection
]
DEFAULT_DRAWINGS_DIR = Path(os.environ.get("QET_DRAWINGS_DIR", r"F:\QelectricoTech\drawings"))

ORIENT_INT = {"n": 0, "e": 1, "s": 2, "w": 3}

# name -> (line colour, free-text wire colour code, bicolor second colour)
WIRE_COLOURS: dict[str, tuple[str, str, str | None]] = {
    "black":        ("#000000", "BK", None),
    "red":          ("#e00000", "RD", None),
    "blue":         ("#0050e0", "BU", None),
    "white":        ("#a0a0a0", "WH", None),   # true white is invisible on paper
    "green":        ("#008000", "GN", None),
    "yellow":       ("#d0b000", "YE", None),
    "orange":       ("#ff8000", "OG", None),
    "brown":        ("#8b4513", "BN", None),
    "violet":       ("#8000c0", "VT", None),
    "purple":       ("#8000c0", "VT", None),
    "grey":         ("#808080", "GY", None),
    "gray":         ("#808080", "GY", None),
    "pink":         ("#ff69b4", "PK", None),
    "green-yellow": ("#00a000", "GNYE", "#e0d000"),
    "green/yellow": ("#00a000", "GNYE", "#e0d000"),
}


class DrawingError(ValueError):
    """The drawing request is invalid (unknown part, pin, duplicate id...)."""


# ------------------------------------------------------------------ settings

_FALLBACK_SETTINGS = {
    "defaultcols": "17", "defaultcolsize": "60", "defaultdisplaycols": "true",
    "defaultrows": "8", "defaultrowsize": "80", "defaultdisplayrows": "true",
    "defaultauthor": "", "defaultplant": "", "defaultlocmach": "",
    "defaultversion": "", "defaultfolio": "%id/%total", "defaultdisplayAt": "bottom",
    "defaulttitleblocktemplate": "", "defaulttitleblocktemplateCollection": "common",
    "defaultconductorcolor": "#000000", "defaultconductortextsize": "7",
    "defaultconductorsize": "1", "defaultconductordash-size": "2",
    "defaultconductorvertirotatetext": "270", "defaultconductorhorizrotatetext": "0",
    "defaultconductorhorizontal-alignment": "AlignBottom",
    "defaultconductorvertical-alignment": "AlignRight",
    "defaultconductortext_color": "#000000",
}


def read_qet_settings() -> dict[str, str]:
    """QET's 'new project' defaults from the registry, with safe fallbacks."""
    values = dict(_FALLBACK_SETTINGS)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\DPTechDraw\DPTechDraw\diagrameditor") as key:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                if name.startswith("default") and isinstance(val, (str, int)):
                    values[name] = str(val)
                i += 1
    except (ImportError, OSError):
        pass
    return values


# ------------------------------------------------------------------ parts

@dataclass
class Pin:
    name: str
    uuid: str
    x: float
    y: float
    orientation: str          # n / e / s / w


@dataclass
class Part:
    key: str                  # short name the AI uses, e.g. "dsub9_male"
    path: Path
    rel_dir: str              # folder path inside its collection, "/"-joined
    title: str                # English display name
    width: int
    height: int
    hotspot_x: int
    hotspot_y: int
    link_type: str
    pins: list[Pin] = field(default_factory=list)

    def pin(self, name: str | None) -> Pin:
        if name is None or name == "":
            if len(self.pins) == 1:
                return self.pins[0]
            raise DrawingError(
                f"Part '{self.key}' has {len(self.pins)} pins; say which one "
                f"(pins: {', '.join(p.name for p in self.pins)})")
        for p in self.pins:
            if p.name.lower() == str(name).lower():
                return p
        raise DrawingError(
            f"Part '{self.key}' has no pin '{name}' "
            f"(pins: {', '.join(p.name or '?' for p in self.pins)})")


def _short_key(stem: str) -> str:
    return re.sub(r"^\d+[_-]", "", stem).lower()


def _load_part(path: Path, root: Path) -> Part:
    root_el = ET.parse(path).getroot()
    names = {n.get("lang"): (n.text or "") for n in root_el.iter("name")}
    pins: list[Pin] = []
    unnamed = []
    for t in root_el.iter("terminal"):
        pins.append(Pin(name=t.get("name", "") or "", uuid=t.get("uuid", ""),
                        x=float(t.get("x", 0)), y=float(t.get("y", 0)),
                        orientation=t.get("orientation", "n")))
    # Unnamed pins get numbers top-to-bottom, then left-to-right.
    if any(not p.name for p in pins):
        order = sorted(pins, key=lambda p: (p.y, p.x))
        taken = {p.name for p in pins if p.name}
        n = 1
        for p in order:
            if not p.name:
                while str(n) in taken:
                    n += 1
                p.name = str(n)
                taken.add(p.name)
    rel = path.parent.relative_to(root).as_posix()
    return Part(key=_short_key(path.stem), path=path,
                rel_dir="" if rel == "." else rel,
                title=names.get("en") or next(iter(names.values()), path.stem),
                width=int(root_el.get("width", 0)), height=int(root_el.get("height", 0)),
                hotspot_x=int(root_el.get("hotspot_x", 0)),
                hotspot_y=int(root_el.get("hotspot_y", 0)),
                link_type=root_el.get("link_type", "simple"), pins=pins)


def load_library(dirs: list[Path] | None = None) -> dict[str, Part]:
    """All parts in the company and custom collections, keyed by short name."""
    library: dict[str, Part] = {}
    for root in dirs or DEFAULT_PART_DIRS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.elmt")):
            try:
                part = _load_part(path, root)
            except (ET.ParseError, ValueError):
                continue
            library.setdefault(part.key, part)
            library.setdefault(path.stem.lower(), part)
    return library


def list_parts(dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    seen: set[Path] = set()
    out = []
    for part in load_library(dirs).values():
        if part.path in seen:
            continue
        seen.add(part.path)
        out.append({"part": part.key, "name": part.title, "folder": part.rel_dir,
                    "pins": [p.name for p in part.pins]})
    return sorted(out, key=lambda d: (d["folder"], d["part"]))


# ------------------------------------------------------------------ helpers

def _braced(u: _uuid.UUID | None = None) -> str:
    return "{" + str(u or _uuid.uuid4()) + "}"


def _snap(v: float, grid: int = 10) -> int:
    return int(round(v / grid) * grid)


def resolve_colour(colour: str | None) -> tuple[str, str, str | None]:
    """Colour name or #rrggbb -> (line colour, wire code, bicolor 2nd colour)."""
    if not colour:
        return ("", "", None)
    c = colour.strip().lower()
    if c in WIRE_COLOURS:
        return WIRE_COLOURS[c]
    if re.fullmatch(r"#[0-9a-f]{6}", c):
        return (c, "", None)
    raise DrawingError(
        f"Unknown wire colour '{colour}'. Use one of: "
        f"{', '.join(sorted(WIRE_COLOURS))}, or #rrggbb")


def _parse_end(end: str) -> tuple[str, str | None]:
    """'J1:3' -> ('J1', '3');  'G1' -> ('G1', None)."""
    if ":" in end:
        ref, pin = end.split(":", 1)
        return ref.strip(), pin.strip()
    return end.strip(), None


ROTATE_CW = {"n": "e", "e": "s", "s": "w", "w": "n"}


def _is_strip_block(part: Part) -> bool:
    """A feed-through terminal block: two pins, one top, one bottom."""
    return (len(part.pins) == 2
            and sorted(p.orientation for p in part.pins) == ["n", "s"])


def pin_scene(item: dict[str, Any], pin: Pin) -> tuple[float, float, str]:
    """Where a pin ends up on the page, and which way it faces."""
    x, y, facing = pin.x, pin.y, pin.orientation
    for _ in range(item["rotation"]):
        x, y, facing = -y, x, ROTATE_CW[facing]      # 90 deg clockwise, y down
    return item["x"] + x, item["y"] + y, facing


def _layout(placed: list[dict[str, Any]], cols: int, colsize: int) -> None:
    """Give parts without x/y a position.

    Wiring-diagram layout: terminal blocks become a vertical strip turned
    sideways (pin 1 facing right, pin 2 facing left), ground/single-pin
    parts sit below-left of the strip, and everything else (connectors,
    devices) stacks in a column to the right. Positions are the part's
    hotspot, snapped to QET's 10 px grid. Parts with explicit x/y are left
    where the caller put them.
    """
    free = [i for i in placed if i.get("x") is None or i.get("y") is None]
    for item in placed:
        if item not in free:
            item["x"], item["y"] = _snap(item["x"]), _snap(item["y"])

    strip = [i for i in free if _is_strip_block(i["part"]) and i["rotation_given"] is None]
    singles = [i for i in free if len(i["part"].pins) == 1]
    others = [i for i in free if i not in strip and i not in singles]

    top = 160
    strip_x = 300
    for n, item in enumerate(strip):
        item["rotation"] = 1                  # pins now face east / west
        item["x"], item["y"] = strip_x, top + n * 30

    other_x = 620 if strip else 160
    y = top
    for item in others:
        part = item["part"]
        item["x"] = _snap(other_x + part.hotspot_x)
        item["y"] = _snap(y + part.hotspot_y)
        y += part.height + 60

    strip_bottom = top + max(len(strip) - 1, 0) * 30
    for n, item in enumerate(singles):
        part = item["part"]
        item["x"] = _snap(strip_x - 120 + n * 60)
        item["y"] = _snap(strip_bottom + 80 + part.hotspot_y)


def _route(wires: list[dict[str, Any]]) -> None:
    """Give left-to-right wires their own vertical lane so none overlap.

    Only wires whose ends face each other (one facing east, the other west,
    east end on the left) get explicit segments; everything else is left to
    QET's auto-router. If QET finds the segments inconsistent it silently
    falls back to auto-routing, so a mistake here is cosmetic, not fatal.
    """
    candidates = []
    for w in wires:
        (i1, p1), (i2, p2) = w["ends"]
        x1, y1, f1 = pin_scene(i1, p1)
        x2, y2, f2 = pin_scene(i2, p2)
        if {f1, f2} != {"e", "w"}:
            continue
        east_x = x1 if f1 == "e" else x2
        west_x = x2 if f1 == "e" else x1
        if east_x >= west_x - 30:
            continue
        candidates.append((y1 if f1 == "e" else y2, w,
                           (x1, y1), (x2, y2), east_x, west_x))
    if not candidates:
        return
    left_edge = max(c[4] for c in candidates)
    right_edge = min(c[5] for c in candidates)
    lanes = int((right_edge - left_edge - 20) // 10)
    if lanes < len(candidates):
        return                                  # not enough room; auto-route all
    candidates.sort(key=lambda c: c[0])
    for n, (_, w, (x1, y1), (x2, y2), _, _) in enumerate(candidates):
        lane = left_edge + 10 + n * 10
        segs = [("horizontal", lane - x1), ("vertical", y2 - y1), ("horizontal", x2 - lane)]
        w["segments"] = [(o, length) for o, length in segs if abs(length) > 0.01]


# ------------------------------------------------------------------ build

def build_drawing(title: str, parts: list[dict[str, Any]], wires: list[dict[str, Any]],
                  *, revision: str = "1.0", filename: str = "",
                  library: dict[str, Part] | None = None,
                  settings: dict[str, str] | None = None,
                  date: _dt.date | None = None) -> tuple[ET.ElementTree, dict[str, Any]]:
    """Build a one-page .qet project. Returns (tree, summary).

    parts: [{"id": "J1", "part": "dsub9_male", "x": opt, "y": opt}]
    wires: [{"from": "J1:2", "to": "X1:1", "name": "W1", "colour": "red"}]
    """
    library = library if library is not None else load_library()
    s = settings if settings is not None else read_qet_settings()
    date = date or _dt.date.today()
    if not parts:
        raise DrawingError("A drawing needs at least one part")

    # ---- resolve parts
    placed: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for spec in parts:
        ref = str(spec.get("id", "")).strip()
        key = str(spec.get("part", "")).strip().lower()
        if not ref:
            raise DrawingError(f"Every part needs an id (label), got {spec!r}")
        if ref.upper() in (r.upper() for r in by_id):
            raise DrawingError(f"Duplicate part id '{ref}'")
        part = library.get(key) or library.get(_short_key(key))
        if part is None:
            raise DrawingError(f"Unknown part '{spec.get('part')}'. Call qet_list_parts.")
        rot = spec.get("rotation")
        if rot is not None and int(rot) not in (0, 90, 180, 270):
            raise DrawingError(f"Part '{ref}': rotation must be 0, 90, 180 or 270")
        item = {"id": ref, "part": part, "x": spec.get("x"), "y": spec.get("y"),
                "rotation_given": rot, "rotation": int(rot or 0) // 90,
                "uuid": _braced()}
        placed.append(item)
        by_id[ref] = item

    cols, colsize = int(s["defaultcols"]), int(s["defaultcolsize"])
    _layout(placed, cols, colsize)

    # ---- resolve wires
    lookup = {k.upper(): v for k, v in by_id.items()}
    resolved_wires = []
    for w in wires:
        ends = []
        for side in ("from", "to"):
            ref, pin = _parse_end(str(w.get(side, "")))
            item = lookup.get(ref.upper())
            if item is None:
                raise DrawingError(f"Wire {side} '{w.get(side)}': no part with id '{ref}'")
            ends.append((item, item["part"].pin(pin)))
        if ends[0][0] is ends[1][0] and ends[0][1] is ends[1][1]:
            raise DrawingError(f"Wire {w!r} starts and ends on the same pin")
        line, code, second = resolve_colour(w.get("colour") or w.get("color"))
        resolved_wires.append({"ends": ends, "name": str(w.get("name", "") or ""),
                               "line": line, "code": w.get("wire_code") or code,
                               "second": second, "segments": []})
    _route(resolved_wires)

    # ---- project + title block
    project = ET.Element("project", {"version": QET_FORMAT_VERSION, "title": title})
    ET.SubElement(project, "properties")
    diagram_attrs = {
        "title": title, "author": s["defaultauthor"], "date": date.strftime("%Y%m%d"),
        "indexrev": revision, "version": s["defaultversion"], "plant": s["defaultplant"],
        "locmach": s["defaultlocmach"], "filename": filename, "folio": s["defaultfolio"],
        "auto_page_num": "", "displayAt": s["defaultdisplayAt"],
        "cols": str(cols), "colsize": str(colsize), "displaycols": s["defaultdisplaycols"],
        "rows": s["defaultrows"], "rowsize": s["defaultrowsize"],
        "displayrows": s["defaultdisplayrows"],
        "freezeNewElement": "false", "freezeNewConductor": "false", "order": "1",
    }
    if s.get("defaulttitleblocktemplate"):
        diagram_attrs["titleblocktemplate"] = s["defaulttitleblocktemplate"]
        diagram_attrs["titleblocktemplateCollection"] = s["defaulttitleblocktemplateCollection"]
    diagram = ET.SubElement(project, "diagram", diagram_attrs)

    # ---- embedded parts: import/<folder...>/<file>.elmt
    collection = ET.Element("collection")
    import_cat = ET.SubElement(collection, "category", {"name": "import"})
    names = ET.SubElement(import_cat, "names")
    ET.SubElement(names, "name", {"lang": "en"}).text = "Imported elements"
    embedded: dict[Path, str] = {}
    for item in placed:
        part: Part = item["part"]
        if part.path in embedded:
            item["type"] = embedded[part.path]
            continue
        segments = [seg for seg in (part.rel_dir or "parts").split("/") if seg]
        cat = import_cat
        for seg in segments:
            nxt = next((c for c in cat.findall("category") if c.get("name") == seg), None)
            if nxt is None:
                nxt = ET.SubElement(cat, "category", {"name": seg})
                ET.SubElement(ET.SubElement(nxt, "names"), "name", {"lang": "en"}).text = seg
            cat = nxt
        el = ET.SubElement(cat, "element", {"name": part.path.name})
        el.append(ET.parse(part.path).getroot())
        type_path = "embed://import/" + "/".join(segments) + "/" + part.path.name
        embedded[part.path] = item["type"] = type_path

    # ---- elements on the page
    elements = ET.SubElement(diagram, "elements")
    term_id = 0
    for item in placed:
        part = item["part"]
        el = ET.SubElement(elements, "element", {
            "type": item["type"], "uuid": item["uuid"], "prefix": "",
            "freezeLabel": "false", "x": str(item["x"]), "y": str(item["y"]),
            "z": "10", "orientation": str(item["rotation"])})
        terms = ET.SubElement(el, "terminals")
        for pin in part.pins:
            ET.SubElement(terms, "terminal", {
                "x": f"{pin.x:g}", "y": f"{pin.y:g}",
                "orientation": str(ORIENT_INT.get(pin.orientation, 0)),
                "id": str(term_id)})
            term_id += 1        # ids must be unique across the whole page
        ET.SubElement(el, "inputs")
        infos = ET.SubElement(el, "elementInformations")
        ET.SubElement(infos, "elementInformation", {"show": "1", "name": "label"}).text = item["id"]

    # ---- wires (no <segment> children -> QET auto-routes them)
    if resolved_wires:
        conductors = ET.SubElement(diagram, "conductors")
    for w in resolved_wires:
        (i1, p1), (i2, p2) = w["ends"]
        attrs = {
            "uuid": _braced(), "x": "0", "y": "0", "freezeLabel": "false",
            "element1": i1["uuid"], "terminal1": p1.uuid, "terminalname1": p1.name,
            "element1_label": i1["id"], "element1_name": i1["part"].title,
            "element2": i2["uuid"], "terminal2": p2.uuid, "terminalname2": p2.name,
            "element2_label": i2["id"], "element2_name": i2["part"].title,
            "type": "multi", "num": w["name"], "formula": "",
            "displaytext": "1" if w["name"] else "0",
            "text_color": s["defaultconductortext_color"],
            "numsize": s["defaultconductortextsize"], "condsize": s["defaultconductorsize"],
            "onetextperfolio": "0",
            "vertirotatetext": s["defaultconductorvertirotatetext"],
            "horizrotatetext": s["defaultconductorhorizrotatetext"],
            "horizontal-alignment": s["defaultconductorhorizontal-alignment"],
            "vertical-alignment": s["defaultconductorvertical-alignment"],
            "bicolor": "true" if w["second"] else "false",
            "color2": w["second"] or "#000000",
            "dash-size": s["defaultconductordash-size"],
            "cable": "", "bus": "", "function": "", "tension_protocol": "",
            "conductor_color": w["code"], "conductor_section": "",
        }
        line = w["line"] or s["defaultconductorcolor"]
        if line.lower() != "#000000":
            attrs["color"] = line          # QET omits colour when black
        cond = ET.SubElement(conductors, "conductor", attrs)
        for orient, length in w["segments"]:
            ET.SubElement(cond, "segment", {"orientation": orient, "length": f"{length:g}"})

    project.append(collection)
    ET.indent(project, space="    ")
    summary = {
        "parts": [{"id": i["id"], "part": i["part"].key, "x": i["x"], "y": i["y"],
                   "rotation": i["rotation"] * 90} for i in placed],
        "wires": len(resolved_wires),
        "wires_with_lanes": sum(1 for w in resolved_wires if w["segments"]),
        "title_block": {k: diagram_attrs[k] for k in
                        ("title", "author", "locmach", "date", "indexrev")},
    }
    return ET.ElementTree(project), summary


# ------------------------------------------------------------------ files

def resolve_output(output: str | Path) -> Path:
    """Bare file names go to the drawings folder; '.qet' is added if missing."""
    p = Path(output)
    if not p.is_absolute() and p.parent == Path("."):
        p = DEFAULT_DRAWINGS_DIR / p
    if p.suffix.lower() != ".qet":
        p = p.with_suffix(".qet")
    return p


def next_free_copy(path: Path) -> Path:
    """null_modem.qet -> null_modem_2.qet (or _3, _4... whichever is free).

    A name that already ends in _N counts up from N, so null_modem_2 -> _3.
    """
    m = re.fullmatch(r"(.*)_(\d+)", path.stem)
    base, n = (m.group(1), int(m.group(2)) + 1) if m else (path.stem, 2)
    while True:
        candidate = path.with_name(f"{base}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def backup(path: Path) -> Path | None:
    """Copy an existing drawing to <folder>\\_backups\\<name>_<timestamp>.qet."""
    if not path.is_file():
        return None
    folder = path.parent / "_backups"
    folder.mkdir(exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = folder / f"{path.stem}_{stamp}{path.suffix}"
    n = 2
    while dest.exists():                     # two saves in the same second
        dest = folder / f"{path.stem}_{stamp}_{n}{path.suffix}"
        n += 1
    shutil.copy2(path, dest)
    return dest


def write_tree(tree: ET.ElementTree, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".qet.tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, path)


def verify(cli: Any, path: Path, expected_parts: int, expected_wires: int) -> dict[str, Any]:
    """Load the file with the real QET binary and compare counts.

    QET drops bad parts and wires silently, so this is the only way to know
    the drawing really loads as written.
    """
    info = cli.info(path)
    problems = []
    if info.get("elements") != expected_parts:
        problems.append(f"QET loaded {info.get('elements')} of {expected_parts} parts")
    if info.get("conductors") != expected_wires:
        problems.append(f"QET loaded {info.get('conductors')} of {expected_wires} wires")
    return {"loaded_ok": not problems, "problems": problems,
            "parts_loaded": info.get("elements"), "wires_loaded": info.get("conductors"),
            "unconnected_pins": info.get("free_terminals")}


# ------------------------------------------------------------------ revisions
#
# Rules agreed with Derek:
#   - Every save/change updates the date only.
#   - "Release" bumps the revision 1.2 -> 1.3 and also updates the date.
# Only the date/indexrev attributes on each <diagram> tag are touched, by
# text substitution, so the rest of the file stays byte-identical (QET's own
# --resave renumbers ~150 lines on every pass).

_DIAGRAM_TAG = re.compile(r"<diagram\b[^>]*>")


def next_revision(current: str) -> str:
    cur = (current or "").strip()
    if not cur:
        return "1.0"
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?", cur)
    if not m:
        raise DrawingError(f"Revision '{current}' is not in the 1.2 style; set it by hand")
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    return f"{major}.{minor + 1}"


def _set_attr(tag: str, name: str, value: str) -> str:
    if re.search(rf'\s{name}="[^"]*"', tag):
        return re.sub(rf'(\s{name}=)"[^"]*"', rf'\g<1>"{value}"', tag)
    return tag[:-1].rstrip("/") + f' {name}="{value}"' + ("/>" if tag.endswith("/>") else ">")


def read_title_block(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = _DIAGRAM_TAG.search(text)
    if not m:
        raise DrawingError(f"No page found in {path}")
    tag = m.group(0)
    get = lambda a: (re.search(rf'\s{a}="([^"]*)"', tag) or [None, ""])[1]
    return {"title": get("title"), "revision": get("indexrev"), "date": get("date"),
            "author": get("author")}


def stamp(path: Path, *, revision: str | None = None,
          date: _dt.date | None = None) -> dict[str, Any]:
    """Set today's date (and optionally a revision) on every page of a drawing."""
    text = path.read_bytes().decode("utf-8")   # keep line endings exactly
    datestr = (date or _dt.date.today()).strftime("%Y%m%d")
    pages = 0

    def fix(m: re.Match) -> str:
        nonlocal pages
        pages += 1
        tag = _set_attr(m.group(0), "date", datestr)
        if revision is not None:
            tag = _set_attr(tag, "indexrev", revision)
        return tag

    new = _DIAGRAM_TAG.sub(fix, text)
    if pages == 0:
        raise DrawingError(f"No page found in {path}")
    tmp = path.with_suffix(".qet.tmp")
    tmp.write_text(new, encoding="utf-8", newline="")
    os.replace(tmp, path)
    return {"pages": pages, "date": datestr, "revision": revision}
