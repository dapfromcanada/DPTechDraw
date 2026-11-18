"""Build a sample DB9 drawing, load it with QET, render a PNG."""
import json
from pathlib import Path

from qet_mcp import drawing as d
from qet_mcp.cli import QetCli

out = d.resolve_output("test_db9")
parts = [
    {"id": "X1", "part": "terminal_block"},
    {"id": "X2", "part": "terminal_block"},
    {"id": "X3", "part": "terminal_block"},
    {"id": "PE1", "part": "ground"},
    {"id": "J1", "part": "dsub9_male"},
]
wires = [
    {"from": "J1:2", "to": "X1:1", "name": "W1", "colour": "red"},
    {"from": "J1:3", "to": "X2:1", "name": "W2", "colour": "white"},
    {"from": "J1:5", "to": "X3:1", "name": "W3", "colour": "black"},
    {"from": "X3:2", "to": "PE1", "name": "PE", "colour": "green-yellow"},
]
tree, summary = d.build_drawing("DB9 test harness", parts, wires, filename=out.name)
d.write_tree(tree, out)
cli = QetCli()
print(json.dumps(summary, indent=1))
print(json.dumps(d.verify(cli, out, len(parts), len(wires)), indent=1))
png = out.parent / "test_db9_png"
print(cli.export_render(out, png, "png"))
print(sorted(p.name for p in png.glob("*")))
