"""Check the MCP 2.x stdio client path against our own server."""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "qet_mcp.server"],
                                   cwd=str(Path(__file__).resolve().parents[1]))
    async with stdio_client(params) as streams:
        print("streams:", type(streams), len(streams))
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("server:", init.server_info.name if hasattr(init, "server_info") else init)
            tools = await session.list_tools()
            t = tools.tools[0]
            print(len(tools.tools), "tools; first:", t.name, "| schema keys:", list(t.input_schema.keys())
                  if hasattr(t, "input_schema") else list(t.inputSchema.keys()))
            res = await session.call_tool("qet_list_parts", {})
            print("result type:", type(res).__name__, "| fields:", [f for f in dir(res) if not f.startswith("_")][:15])
            print("content[0]:", type(res.content[0]).__name__, str(res.content[0])[:300])
            sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
            print("structured:", str(sc)[:200])


asyncio.run(main())
