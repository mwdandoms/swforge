# -*- coding: utf-8 -*-
"""MCP 服务器契约测试 —— 保证「别的智能体也能用」。

为什么要单独测这个
------------------
swforge 自己用得顺手，不代表 Claude Desktop / Cursor / Codex 接上也能用。
外部 Agent 只通过 MCP 协议看这个服务器，它能看到的只有三样东西：

    1. serverInfo（名字 + 版本）
    2. instructions（一段自然语言，教它怎么用）
    3. tools 列表（名字 + 描述 + JSON Schema）

这三样任何一样缺了或错了，Agent 就会用不对 —— 而作者在本机自测发现不了。

这些用例走**真实 stdio 协议**（和外部客户端完全同一条路），
不需要 SolidWorks，所以能进 CI。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

mcp_sdk = pytest.importorskip("mcp", reason="需要 mcp 包（pip install swforge[mcp]）")


# ---------------------------------------------------------------- 静态契约
def test_server_reports_own_version_not_sdk_version():
    """serverInfo.version 必须是 swforge 的版本。

    实测发现 FastMCP 的底层 Server.version 默认是 None，MCP 客户端于是拿到
    MCP SDK 的版本（1.30.0）。排查问题时这会把人带偏，所以锁死。
    """
    from swforge import __version__
    from swforge.server import mcp

    if mcp is None:
        pytest.skip("mcp 未安装")
    opt = mcp._mcp_server.create_initialization_options()
    assert opt.server_version == __version__, (
        f"serverInfo.version 报的是 {opt.server_version!r}，"
        f"应该是 swforge 的 {__version__!r}")


def test_server_has_instructions():
    """instructions 必须非空 —— 它是 Agent 读到的第一段话。

    空着等于让 Agent 自己猜这个服务器怎么用，而 Agent 猜不出来。
    """
    from swforge.server import mcp

    if mcp is None:
        pytest.skip("mcp 未安装")
    opt = mcp._mcp_server.create_initialization_options()
    ins = opt.instructions or ""
    assert len(ins.strip()) > 100, "instructions 太短，没起到指导作用"

    # 这几件事必须说清楚，否则 Agent 必然踩坑
    for keyword in ("SolidWorks", "mm", "8", "ok"):
        assert keyword in ins, f"instructions 没提到 {keyword!r}"


def test_all_tools_have_descriptions():
    """每个工具都要有中文描述 —— 决定 Agent 选不选得对工具。"""
    import asyncio

    from swforge.server import mcp

    if mcp is None:
        pytest.skip("mcp 未安装")
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) >= 20, f"工具太少：{len(tools)}"

    for t in tools:
        assert t.description and len(t.description.strip()) >= 8, \
            f"{t.name} 没有描述"
        schema = t.inputSchema or {}
        assert schema.get("type") == "object", f"{t.name} 的 inputSchema 不是 object"
        assert "properties" in schema, f"{t.name} 的 inputSchema 缺 properties"


def test_write_tools_document_destructive_defaults():
    """破坏性工具必须说明默认是 dry-run。

    Agent 会照着描述做决策：如果它以为 purge 一调用就删，
    就不敢用；如果以为 purge 默认真删，就会误删用户的东西。
    """
    import asyncio

    from swforge.server import mcp

    if mcp is None:
        pytest.skip("mcp 未安装")
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}

    for name in ("sw_purge_giant", "sw_purge_small", "sw_sweep_documents"):
        t = tools.get(name)
        assert t is not None, f"缺少 {name}"
        desc = (t.description or "").lower()
        assert ("默认只列" in t.description) or ("默认" in desc and "只" in desc), \
            f"{name} 没说明「默认只列不删」，Agent 会误判"


# ---------------------------------------------------------------- 真实协议
def _server_env():
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_stdio_handshake_and_list_tools():
    """走真实 stdio 协议握手并拉工具列表 —— 外部 Agent 用的就是这条路。

    不需要 SolidWorks：握手和 list_tools 都不碰它。
    """
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-X", "utf8", "-m", "swforge.server"],
            env=_server_env(),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                return init, tools

    init, tools = asyncio.run(run())

    assert init.serverInfo.name == "swforge"
    assert init.capabilities.tools is not None, "服务器没声明 tools 能力"
    assert len(tools.tools) >= 20
    names = {t.name for t in tools.tools}
    assert "sw_validate_part" in names
    assert "sw_build_part" in names


def test_stdio_validate_part_returns_actionable_error():
    """参数非法时返回的错误必须能让 Agent 自己改对。

    这是 Agent 可用性的核心：错了不可怕，怕的是错得看不懂。
    """
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-X", "utf8", "-m", "swforge.server"],
            env=_server_env(),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool("sw_validate_part", {
                    "out_path": "x.SLDPRT",
                    "spec": {"cylinders": [{"tag": "轴", "axis": "q", "r": 10, "h": 50}]},
                })

    r = asyncio.run(run())
    import json as _json
    payload = _json.loads(r.content[0].text)
    assert payload["ok"] is False
    err = payload["error"]
    # 必须指出是哪个字段错了、合法值是什么
    assert "axis" in err, f"错误信息没指出字段：{err}"
    assert "x/y/z" in err, f"错误信息没给出合法值：{err}"
