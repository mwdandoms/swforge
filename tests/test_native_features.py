import pytest

from swforge import PartBuilder
from swforge.spec import builder_from_spec


def plate(tmp_path):
    return PartBuilder(str(tmp_path/"plate.SLDPRT")).box("base", -50, 50, 0, 8, -40, 40)


@pytest.mark.parametrize("method,params,message", [
    ("linear_pattern", {"seed":"base","axis":"x","count":True,"spacing":10}, "count"),
    ("linear_pattern", {"seed":"missing","axis":"x","count":3,"spacing":10}, "existing"),
    ("circular_pattern", {"seed":"base","axis":"z","count":4,"angle":361}, "angle"),
    ("mirror", {"seed":"base","plane":"x"}, "plane"),
    ("shell", {"target":"base","thickness":2,"open_side":"top"}, "open_side"),
    ("rib", {"axis":"z","start":[0,0,0],"end":[4,4,1],"thickness":2}, "same"),
    ("loft", {"axis":"y","sections":[[0,0,0,2],[0,0,2,1]]}, "strictly increasing"),
    ("loft", {"axis":"z","sections":[[0,0,0,2],[0,0,2,float("nan")]]}, "finite"),
    ("cosmetic_thread", {"seed":"base","center":[0,0,0],"edge_diameter":10,"diameter":10,"depth":3}, "differ"),
])
def test_invalid_feature_does_not_change_plan(tmp_path, method, params, message):
    b = plate(tmp_path)
    with pytest.raises(ValueError, match=message):
        getattr(b,method)("feat", **params)
    assert b.feature_count == 1
    assert "feat" not in b._tags


def test_shared_json_accepts_all_seven_feature_types(tmp_path):
    b = builder_from_spec(str(tmp_path/"native.SLDPRT"), {
        "lofts":[{"tag":"body","axis":"y","sections":[[0,-10,0,20],[0,10,0,18]]}],
        "holes":[{"tag":"hole","target":"body","axis":"y","through_all":True,"diameter":6}],
        "linear_patterns":[{"tag":"linear","seed":"hole","axis":"x","count":3,"spacing":5}],
        "circular_patterns":[{"tag":"circ","seed":"hole","axis":"y","count":4}],
        "mirrors":[{"tag":"mirror","seed":"hole","plane":"yz"}],
        "shells":[{"tag":"shell","target":"body","thickness":2,"open_side":"+y"}],
        "ribs":[{"tag":"rib","axis":"z","start":[0,2,0],"end":[6,0,0],"thickness":2}],
        "cosmetic_threads":[{"tag":"thread","seed":"hole","center":[0,0,0],"edge_diameter":6,"diameter":8,"depth":4}],
    })
    assert b.shape_count == 1
    assert b.feature_count == 8
    assert not (tmp_path/"native.SLDPRT").exists()


def test_duplicate_tag_rejected_between_feature_phases(tmp_path):
    b = plate(tmp_path).mirror("copy","base",plane="yz")
    with pytest.raises(ValueError, match="唯一"):
        b.loft("copy",axis="y",sections=[[0,0,0,2],[0,10,0,1]])
