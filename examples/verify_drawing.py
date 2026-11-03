"""Verify drawing creation, non-mutating preview, measured layout and PDF export."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def value(obj, name):
    member = getattr(obj, name)
    return member() if callable(member) and not hasattr(member, "_oleobj_") else member


def views(md):
    sheet = value(md, "GetFirstView")
    current = value(sheet, "GetNextView")
    result = []
    while current is not None:
        result.append(current)
        current = value(current, "GetNextView")
    return result


def main(model, builtin, existing=False):
    from dsh_sw_toolkit import drawing, get_session
    if builtin:
        drawing.have_mechdog = lambda: False
    out = model.with_name(model.stem + ("_builtin" if builtin else "") + "_三视图.SLDDRW")
    report = (json.loads(out.with_suffix(".verification.json").read_text(encoding="utf-8"))
              if existing else {"produce": drawing.produce(str(model), str(out), paper="A3")})
    try:
        assert report["produce"].get("ok"), report["produce"]
        sw = get_session().sw()
        md = drawing._drawing_document(sw, str(out))
        def state():
            return [(tuple(value(v, "Position")), v.ScaleDecimal) for v in views(md)]
        before = state()
        report["preview"] = drawing.normalize_layout(str(out), dry_run=True)
        assert before == state(), "dry-run changed the drawing"
        assert report["preview"]["ok"], report["preview"]
        report["layout"] = drawing.normalize_layout(str(out))
        assert report["layout"]["ok"], report["layout"]
        report["measured_views"] = [{"name":str(v.Name), "position":list(value(v,"Position")),
            "outline":list(value(v,"GetOutline")), "scale":v.ScaleDecimal} for v in views(md)]
        report["pdf"] = drawing.export_pdf(str(out), str(out.with_suffix(".pdf")))
        assert report["pdf"]["ok"], report["pdf"]
        assert out.with_suffix(".pdf").read_bytes().startswith(b"%PDF-")
        return report
    finally:
        out.with_suffix(".verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--builtin", action="store_true")
    parser.add_argument("--existing", action="store_true", help="reuse previously created drawing")
    args = parser.parse_args()
    main(args.model.resolve(), args.builtin, args.existing)
