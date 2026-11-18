"""SolidWorks 2019 acceptance for the default PartBuilder driving dimensions."""
from pathlib import Path
import json
import math
import shutil
import sys
from datetime import datetime

import swforge
from swforge.assembly import _value

base = Path(sys.argv[1])
out = base / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
out.mkdir(parents=True)
data = {"version": swforge.__version__, "source": swforge.__file__, "cases": {}}
sw = swforge.get_session().sw()
data["revision"] = _value(sw, "RevisionNumber")
data["before"] = swforge.document_inventory(sw)
assert data["before"]["document_count"] < 8, data["before"]


def build(model, configure):
    builder = swforge.PartBuilder(str(model))
    configure(builder)
    result = builder.build(keep_open=False, timeout_s=120)
    print(model.name, result.ok, result.error, flush=True)
    assert result.ok, result.error
    return result


def sizes(part):
    existing = sw.GetOpenDocumentByName(str(part))
    try:
        result = swforge.list_model_parameters(part)
        assert result["ok"], result
        return result["parameters"]
    finally:
        opened = sw.GetOpenDocumentByName(str(part))
        if not existing and opened:
            assert Path(_value(opened,"GetPathName")).resolve() == part.resolve()
            assert not _value(opened,"GetSaveFlag")
            sw.CloseDoc(_value(opened,"GetTitle"))


def key_for(parameters, key):
    matches = [row for row in parameters if row["name"].split("@", 1)[0] == key]
    assert len(matches) == 1, matches
    return matches[0]["name"]


def exercise(part, name, value, expected_volume):
    other = out / "移机重开"
    other.mkdir(exist_ok=True)
    moved = other / part.name
    shutil.copy2(part, moved)
    before = sizes(moved)
    key = key_for(before, name)
    result = swforge.set_parameters(moved, {key:value}, save=True, backup=False,
                                    expect_volume_mm3=expected_volume, tolerance_pct=.01)
    assert result["ok"] and result["saved"], result
    after = sizes(moved)
    row = next(item for item in after if item["name"] == key)
    assert math.isclose(row["value"], value, abs_tol=1e-7), row
    return {"before": before, "result": result, "after": after}


def plate_geometry(builder):
    builder.box("Plate", 0, 120, 0, 12, 0, 70)
    builder.hole("Mount", "Plate", axis="y", x=25, y=0, z=24, diameter=10, through_all=True)


def tube_geometry(builder):
    builder.tube_z("Tube", 0, 90, 25, -42, 40, 30, 3)


def cylinder_geometry(builder):
    builder.cylinder("Journal", axis="x", x=-20, y=0, z=0, r=10, h=40)


try:
    plate = out / "Editable_Plate.SLDPRT"
    build(plate,plate_geometry)
    for p in sizes(plate): print(p["name"], p["value"], flush=True)
    data["cases"]["plate"] = exercise(plate,"ProfileWidth",125,((125*70)-math.pi*25)*12)
    moved_plate=out/"移机重开"/plate.name
    hole_key=key_for(sizes(moved_plate),"Diameter")
    hole_edit=swforge.set_parameters(moved_plate,{hole_key:12},save=True,backup=False,
        expect_volume_mm3=(125*70-math.pi*36)*12,tolerance_pct=.01)
    assert hole_edit["ok"] and hole_edit["saved"],hole_edit
    assert math.isclose(next(p["value"] for p in sizes(moved_plate) if p["name"]==hole_key),12,abs_tol=1e-7)
    data["cases"]["hole"] = hole_edit
    tube=out/"Editable_Tube.SLDPRT"
    build(tube,tube_geometry)
    data["cases"]["tube"]=sizes(tube)
    assert len(data["cases"]["tube"])>=5
    cylinder=out/"Editable_Journal.SLDPRT"
    build(cylinder,cylinder_geometry)
    data["cases"]["cylinder"]=exercise(cylinder,"Diameter",21,math.pi*10.5**2*40)
    slot=out/"Editable_Slot.SLDPRT"
    build(slot,lambda b:b.box("Blank",0,80,0,40,0,15)
          .cut_box("Pocket","Blank",15,45,8,22,9,16,axis="z"))
    data["cases"]["pocket"]=sizes(slot)
    assert sum(row["name"].startswith("ProfileWidth@") for row in data["cases"]["pocket"])==2
finally:
    data["after"]=swforge.document_inventory(sw)
    (out / "acceptance.json").write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
