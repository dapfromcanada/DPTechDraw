"""One-off: give every terminal in My Parts a usable name.

DB9 pins are matched to the nearest printed pin-number text in the symbol.
Two-terminal blocks get 1 (top) / 2 (bottom). Single terminals keep their
existing name or get "1". A fresh definition <uuid> is minted for any file
changed, because QET caches elements by that uuid with no invalidation.

Usage: python tools/name_pins.py <my-parts-folder> [--dry]
"""
import re
import sys
import uuid
from pathlib import Path

FOLDER = Path(sys.argv[1])
DRY = "--dry" in sys.argv

TERM_RE = re.compile(r'<terminal\b[^>]*/>')


def attr(tag, a):
    m = re.search(rf'\b{a}="([^"]*)"', tag)
    return m.group(1) if m else None


def nearest_label(tx, ty, labels):
    best = min(labels, key=lambda l: (l[1] - tx) ** 2 + (l[2] - ty) ** 2)
    return best[0]


for f in sorted(FOLDER.glob("*.elmt")):
    text = f.read_text(encoding="utf-8")
    terms = TERM_RE.findall(text)
    if not terms:
        continue
    pos = [(float(attr(t, "x")), float(attr(t, "y"))) for t in terms]
    labels = [(m.group(1), float(m.group(2)), float(m.group(3)))
              for m in re.finditer(r'<text text="(\d+)" x="([-\d.]+)" y="([-\d.]+)"', text)]

    if "dsub" in f.name and len(labels) == len(terms):
        names = [nearest_label(x, y, labels) for x, y in pos]
    elif len(terms) == 1:
        names = [attr(terms[0], "name") or "1"]
    else:
        order = sorted(range(len(terms)), key=lambda i: (pos[i][1], pos[i][0]))
        names = [""] * len(terms)
        for n, i in enumerate(order, 1):
            names[i] = str(n)

    if len(set(names)) != len(names):
        print(f"SKIP {f.name}: duplicate names {names}")
        continue

    new = text
    for t, n in zip(terms, names):
        new = new.replace(t, re.sub(r'\bname="[^"]*"', f'name="{n}"', t), 1)
    changed = new != text
    if changed:
        new = re.sub(r'<uuid uuid="\{[^}]*\}"/>', f'<uuid uuid="{{{uuid.uuid4()}}}"/>', new, count=1)
    print(f"{f.name}: " + ", ".join(f"{n}@({x:g},{y:g})" for n, (x, y) in zip(names, pos))
          + ("" if changed else "  (unchanged)"))
    if changed and not DRY:
        f.write_text(new, encoding="utf-8", newline="")
