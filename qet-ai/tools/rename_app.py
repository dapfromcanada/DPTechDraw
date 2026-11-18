"""One-off: rename QElectroTech -> DPTechDraw in qet-ai's Python code."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [p for d in ("qet_mcp", "qet_chat", "tests") for p in (ROOT / d).rglob("*.py")]

RULES = [
    (r"qelectrotech\.exe", "DPTechDraw.exe"),
    (r'shutil\.which\("qelectrotech"\)', 'shutil.which("DPTechDraw")'),
    (r'f"qelectrotech \{', 'f"DPTechDraw {'),
    (r'MCPServer\("qelectrotech"\)', 'MCPServer("dptechdraw")'),
    (r"QET Chat", "DPTechDraw Chat"),
    (r"QElectroTech", "DPTechDraw"),
]

for f in FILES:
    text = f.read_text(encoding="utf-8")
    new = text
    for pat, rep in RULES:
        new = re.sub(pat, rep, new)
    if new != text:
        f.write_text(new, encoding="utf-8", newline="")
        print(f"{f.relative_to(ROOT)}: {sum(1 for a, b in zip(text.splitlines(), new.splitlines()) if a != b)} lines")
