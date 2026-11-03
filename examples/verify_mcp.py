"""Real stdio MCP round trip; creates demo CAD + machine-readable evidence.

Requires running SolidWorks and installed mcp/pywin32/Pillow.
python -X utf8 examples/verify_mcp.py --out F:/out/demo.SLDPRT
"""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def verify(out):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    spec = json.loads((ROOT / "examples" / "v04_demo.json").read_text(encoding="utf-8"))
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    params = StdioServerParameters(command=sys.executable,
        args=["-X", "utf8", "-m", "swforge.server"], cwd=str(ROOT), env=env)
    report = {}
    async with stdio_client(params) as streams:
        async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=180)) as session:
            info = await session.initialize()
            report["server"] = info.serverInfo.model_dump()
            listed = await session.list_tools()
            report["tools"] = [t.name for t in listed.tools]

            async def call(name, args, label=None):
                response = await session.call_tool(name, args)
                data = response.structuredContent
                if data is None:
                    data = json.loads(next(c.text for c in response.content if c.type == "text"))
                report[label or name] = data
                assert not response.isError and data.get("ok"), (name, data)
                return data

            await call("sw_ping", {})
            capabilities=await call("sw_capabilities", {})
            await call("sw_validate_part", {"out_path": str(out), "spec": spec})
            invalid = await session.call_tool("sw_validate_part", {
                "out_path": str(out.with_name("invalid.SLDPRT")),
                "spec": {"cylinders":[{"tag":"bad","axis":"q","r":5,"h":10}]}})
            data = invalid.structuredContent or json.loads(invalid.content[0].text)
            report["invalid_spec"] = data
            assert data["ok"] is False and not out.with_name("invalid.SLDPRT").exists()
            initial=await call("sw_resources", {},'resources_before')
            result = await call("sw_build_part", {"out_path": str(out), "spec": spec,"keep_open":True})
            assert result["bodies"] == 10 and result["features_ok"] == 13
            assert result["color_coverage"] >= 0.99
            await call("sw_survey", {})
            await call("sw_read_colors", {"sample": 16})
            await call("sw_preview_edges",{"part_path":str(out),"tag":"倒角块","edges_rule":{"axis":"y"}})
            drawing=out.with_suffix('.SLDDRW')
            await call('sw_produce_drawing',{'model_path':str(out),'out_path':str(drawing)})
            await call('sw_layout_views',{'drawing_path':str(drawing)})
            await call('sw_export_pdf',{'drawing_path':str(drawing)})
            if capabilities['mechdog']:
                audit=await call('sw_delivery_check',{'drawing_path':str(drawing)})
                assert not audit['ready_for_manufacture']
            before_batch=await call('sw_resources',{},'resources_before_batch')
            await call('sw_build_part',{'out_path':str(out.with_name('batch_closed.SLDPRT')),
                'spec':{'boxes':[{'tag':'closed','x0':0,'x1':20,'y0':0,'y1':20,'z0':0,'z1':20}]}},'batch_closed')
            final=await call('sw_resources',{},'resources_after')
            assert final['document_count']==before_batch['document_count']
            assert final['document_count']<=initial['document_count']+2
            assert len(report['tools'])==18
    out.with_suffix(".mcp-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def preview(out):
    import pythoncom
    import win32com.client
    from PIL import Image
    pythoncom.CoInitialize()
    sw = win32com.client.GetActiveObject("SldWorks.Application")
    sw.Visible = True
    md = sw.GetOpenDocumentByName(str(out))
    assert md is not None
    sw.ActivateDoc(str(out))
    md.ShowNamedView2("", 7)
    for name in ("ViewZoomtofit2", "GraphicsRedraw2"):
        method = getattr(md, name)
        if callable(method):
            method()
    bmp = out.with_suffix(".bmp")
    assert md.SaveBMP(str(bmp), 1600, 1000), "SW 模型视口导出失败"
    Image.open(bmp).save(out.with_suffix(".png"))
    return str(out.with_suffix(".png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(verify(args.out))
    print(json.dumps({"ok": True, "tool_count": len(result["tools"]),
        "build": result["sw_build_part"], "preview": preview(args.out)}, ensure_ascii=False, indent=2))
