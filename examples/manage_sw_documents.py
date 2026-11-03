"""Inspect SW document count; close only this project's generated test artifacts."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import tempfile
import pythoncom
import win32com.client as wc


def value(obj, name):
    item = getattr(obj, name)
    return item() if callable(item) and not hasattr(item, "_oleobj_") else item


def snapshot(sw):
    result = []
    for raw in value(sw, "GetDocuments") or []:
        md = raw if hasattr(raw, "GetPathName") else wc.Dispatch(raw)
        result.append({"path":str(value(md,"GetPathName")),"title":str(value(md,"GetTitle")),
                       "modified":bool(value(md,"GetSaveFlag"))})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    pythoncom.CoInitialize()
    sw = wc.GetActiveObject("SldWorks.Application")
    before = snapshot(sw)
    roots = [args.evidence.resolve() / "models", args.evidence.resolve() / "final_models",
             Path(tempfile.gettempdir()).resolve() / "swforge_it"]
    closed = []
    for doc in before if args.cleanup else []:
        if not doc["path"]:
            continue
        path = Path(doc["path"]).resolve()
        if any(path.is_relative_to(root) for root in roots):
            sw.CloseDoc(str(path))
            closed.append(str(path))
    after = snapshot(sw)
    report = {"time":datetime.now().astimezone().isoformat(),"cleanup":args.cleanup,
              "before_count":len(before),"after_count":len(after),"before":before,
              "closed":closed,"after":after}
    args.evidence.mkdir(parents=True,exist_ok=True)
    with (args.evidence / "sw_window_management.jsonl").open("a",encoding="utf-8") as handle:
        handle.write(json.dumps(report,ensure_ascii=False)+"\n")
    print(json.dumps({"before":len(before),"closed":len(closed),"after":len(after),
                      "remaining":after},ensure_ascii=False,indent=2))
