"""Call the new MCP tools the way the AI will."""
import asyncio
import json

from qet_mcp import server as s

tools = asyncio.run(s.mcp.list_tools())
print(len(tools), "tools:", ", ".join(t.name for t in tools))

parts = s.qet_list_parts()
print("parts:", [(p["part"], len(p["pins"])) for p in parts["parts"]])

r = s.qet_create_drawing(
    title="DB9 to terminal strip", output="demo_db9", overwrite=True,
    parts=[{"id": "X1", "part": "terminal_block"}, {"id": "X2", "part": "terminal_block"},
           {"id": "X3", "part": "terminal_block"}, {"id": "PE1", "part": "ground"},
           {"id": "J1", "part": "dsub9_male"}],
    wires=[{"from": "J1:2", "to": "X1:1", "name": "W1", "colour": "red"},
           {"from": "J1:3", "to": "X2:1", "name": "W2", "colour": "white"},
           {"from": "J1:5", "to": "X3:1", "name": "W3", "colour": "black"},
           {"from": "X3:2", "to": "PE1", "name": "PE", "colour": "green-yellow"}])
print("create:", json.dumps({k: r.get(k) for k in ("ok", "file", "check", "message")}))

bad = s.qet_create_drawing(title="x", output="demo_db9", parts=[{"id": "A", "part": "ground"}], wires=[])
print("no-overwrite:", bad["ok"], bad.get("error"))

rel = s.qet_release(r["file"])
print("release:", json.dumps({k: rel.get(k) for k in ("ok", "previous_revision", "revision", "date", "backup")}))
rel2 = s.qet_release(r["file"])
print("release again:", rel2.get("previous_revision"), "->", rel2.get("revision"))
st = s.qet_stamp_date(r["file"])
print("stamp:", st.get("ok"), st.get("date"), st.get("revision"))
