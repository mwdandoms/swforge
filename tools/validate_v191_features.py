"""Sequential SW2025 test. Builds only new files, closes each test's own document."""
import json
import math
import sys
import time
from pathlib import Path
import swforge
from swforge.resources import document_inventory
from swforge.feature_tree import inspect_feature_tree
from swforge.session import get_session, _value


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    sw = get_session().sw()
    before = document_inventory(sw)
    report = {"version": swforge.__version__, "module": swforge.__file__,
              "revision": str(_value(sw, "RevisionNumber")), "before": before, "cases": {}}
    def plate(path):
        return swforge.PartBuilder(str(path), merge=True).box("base", -50, 50, 0, 8, -40, 40)
    def hole(b, x, z):
        return b.hole("seed", "base", axis="y", x=x, z=z, diameter=8, through_all=True)
    a = 8 * math.pi * 4**2
    defs = {
        "linear_pattern": (lambda p: hole(plate(p), 0, 0).linear_pattern("tested", "seed", axis="x", count=3, spacing=16), -2*a),
        "circular_pattern": (lambda p: hole(plate(p), 20, 0).circular_pattern("tested", "seed", axis="y", count=4), -3*a),
        "mirror": (lambda p: hole(plate(p), 15, 0).mirror("tested", "seed", plane="yz"), -a),
        "shell": (lambda p: swforge.PartBuilder(str(p)).box("box", -20, 20, 0, 30, -15, 15).shell("tested", "box", thickness=2, open_side="+y"), -36*28*26),
        "rib": (lambda p: swforge.PartBuilder(str(p), merge=True).box("base", 0, 60, 0, 8, -15, 15).box(
            "wall", 0, 8, 8, 45, -15, 15).rib("tested", axis="z", start=(8,35,0), end=(40,8,0), thickness=4), 32*27*4/2),
        "loft": (lambda p: swforge.PartBuilder(str(p)).loft("tested", axis="y", sections=[(0,0,0,14),(0,30,0,8)]), math.pi*30*(14**2+14*8+8**2)/3),
        "cosmetic_thread": (lambda p: swforge.PartBuilder(str(p)).cylinder("seed", axis="y", r=5, h=20).cosmetic_thread(
            "tested", "seed", center=(0,20,0), edge_diameter=10, diameter=8.5, depth=8, note="M10"), 0),
    }
    expected_types = {"linear_pattern":"LPattern", "linear_reverse":"LPattern",
                      "circular_pattern":"CirPattern", "mirror":"MirrorPattern",
                      "shell":"Shell", "rib":"Rib", "loft":"Blend", "cosmetic_thread":"CosmeticThread"}
    defs["linear_reverse"] = (lambda p: hole(plate(p), 0, 0).linear_pattern(
        "tested", "seed", axis="x", count=3, spacing=16, reverse=True), -2*a)
    defs["linear_z"] = (lambda p: hole(plate(p), 0, 0).linear_pattern(
        "tested", "seed", axis="z", count=3, spacing=16), -2*a)
    defs["circular_partial"] = (lambda p: hole(plate(p), 20, 0).circular_pattern(
        "tested", "seed", axis="y", count=3, angle=90), -2*a)
    expected_types.update(linear_z="LPattern",circular_partial="CirPattern")
    expected_hole_centers = {
        "linear_z": [(0,0),(0,16),(0,32)],
        "circular_partial": [(0,-20),(14.1421,-14.1421),(20,0)],
        "linear_pattern": [(0,0),(16,0),(32,0)],
        "linear_reverse": [(-32,0),(-16,0),(0,0)],
        "circular_pattern": [(-20,0),(0,-20),(0,20),(20,0)],
        "mirror": [(-15,0),(15,0)],
    }

    def persisted_checks(name, tree, after_volume):
        if not tree.get("ok"):
            return {"ok":False, "error":tree.get("error")}
        feature = next((f for f in tree["features"] if f["name"]=="SWFORGE_tested"), None)
        expected = expected_types[name]
        kinds_ok = bool(feature and feature["type"] == expected and tree["feature_errors"] == 0)
        volume_ok = abs(tree["volume_mm3"]-after_volume)<.05
        body_ok = tree["body_count"] == 1
        centers = None
        geometry_ok = True
        if name in expected_hole_centers:
            centers = sorted({tuple(round(c["origin_mm"][i],4) for i in (0,2))
                              for body in tree["bodies"] for c in body["cylinders"]
                              if abs(c["diameter_mm"]-8) < .001})
            geometry_ok = centers == sorted(expected_hole_centers[name])
        bbox = [round(v*1000,4) for v in tree["bodies"][0]["bbox_m"]] if body_ok else None
        if name == "loft":
            geometry_ok = bbox is not None and abs(bbox[1])<.02 and abs(bbox[4]-30)<.02
        return {"ok":kinds_ok and volume_ok and body_ok and geometry_ok, "feature":feature,
                "feature_errors":tree["feature_errors"], "volume_mm3":tree["volume_mm3"],
                "body_count":tree["body_count"],"hole_centers_xz_mm":centers, "bbox_mm":bbox,
                "geometry_ok":geometry_ok}

    def save():
        (root/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    save()
    try:
        names = sys.argv[2:] or defs
        for name in names:
            if document_inventory(sw)["document_count"] != before["document_count"]:
                raise RuntimeError("Unexpected open documents; stopped without closing other documents")
            if before["document_count"] >= 8:
                raise RuntimeError("SolidWorks already at document limit")
            create, expected = defs[name]
            start = time.monotonic()
            path = root/(name+".SLDPRT")
            b = create(path)
            result = b.build(timeout_s=45, keep_open=False)
            rows = result.native_features
            row = rows[-1] if rows else {}
            delta = row.get("volume_after_mm3",0)-row.get("volume_before_mm3",0)
            match = abs(delta-expected) <= max(.05,abs(expected)*.002)
            tree = inspect_feature_tree(str(path)) if result.ok else {}
            reopened = persisted_checks(name, tree, row.get("volume_after_mm3",0))
            report["cases"][name] = {"passed": result.ok and match and reopened["ok"], "build_ok":result.ok,
                "reopened":reopened,"error":result.error,
                "readback":rows,"expected_volume_delta_mm3":expected,"actual_volume_delta_mm3":delta,
                "seconds":time.monotonic()-start, "path":str(path)}
            print(name, result.ok, delta, expected, reopened, flush=True)
            if not result.ok:
                print(result.error[-1300:], flush=True)
            save()
            if "可能仍在处理" in result.error:
                break
    finally:
        report["after"] = document_inventory(sw)
        report["passed"] = (len(report["cases"]) == len(names) and
                            all(row["passed"] for row in report["cases"].values()) and
                            report["after"]["documents"] == before["documents"])
        save()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
