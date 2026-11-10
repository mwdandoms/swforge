import math
import pytest
from swforge.mechanical import frame_plan,spur_gear_plan,create_spur_gear,create_weldment_frame


def test_frame_analytic_stock_and_joints():
    p=frame_plan(600,400,500,40,3)
    assert sorted(p['lengths_mm'])==[320]*4+[420]*4+[600]*4
    assert p['expected_volume_mm3']==2379840
    # Axis-aligned swept member boxes must have zero overlapping volume.
    boxes=[]
    for a,b in p['lines_mm']:
        boxes.append([(min(x,y)-(20 if x==y else 0),max(x,y)+(20 if x==y else 0)) for x,y in zip(a,b)])
    for i,box in enumerate(boxes):
        for other in boxes[i+1:]:
            assert math.prod(max(0,min(c[1],d[1])-max(c[0],d[0])) for c,d in zip(box,other))==0


@pytest.mark.parametrize('parameters',[(2,24),(1,18),(3,40)])
def test_gear_reference_dimensions_and_pitch_thickness(parameters):
    m,z=parameters;p=spur_gear_plan(m,z,bore=4)
    assert p['pitch_diameter_mm']==m*z
    assert p['outside_diameter_mm']==m*(z+2)
    assert p['root_diameter_mm']==m*(z-2.5)
    assert p['base_diameter_mm']==pytest.approx(m*z*math.cos(math.radians(20)))
    pitch=[xy for xy in p['seed_polygon_mm'] if abs(math.hypot(*xy)-m*z/2)<1e-8]
    assert len(pitch)==2
    assert abs(math.atan2(pitch[0][1],pitch[0][0])-math.atan2(pitch[1][1],pitch[1][0]))*m*z/2==pytest.approx(math.pi*m/2)
    assert p['sampled_flank_error_mm']<=.005/4


@pytest.mark.parametrize('kwargs',[{'teeth':True},{'teeth':17},{'teeth':121},{'module':float('nan')},{'bore':100},{'hub_diameter':30},{'pressure_angle':15},{'chord_error':0}])
def test_gear_invalid_never_connects(kwargs,tmp_path):
    with pytest.raises(ValueError):create_spur_gear(tmp_path/'invalid.SLDPRT',**kwargs)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('kwargs',[{'length':70},{'wall':20},{'section':0},{'height':float('inf')}])
def test_frame_invalid_never_connects(kwargs,tmp_path):
    with pytest.raises(ValueError):create_weldment_frame(tmp_path/'invalid.SLDPRT',**kwargs)
    assert not list(tmp_path.iterdir())


def test_existing_file_is_preserved(tmp_path):
    p=tmp_path/'source.SLDPRT';p.write_bytes(b'original')
    with pytest.raises(ValueError):create_spur_gear(p)
    assert p.read_bytes()==b'original'


@pytest.mark.parametrize('bounds',[[-.02,.1,.05,.2],[.39,.1,.46,.2],[.1,-.03,.2,.05],[.1,.27,.2,.31]])
def test_sheet_level_table_extent_outside_is_failure_even_with_anchor_inside(bounds):
    from swforge.drawing_review import review_snapshot
    snap=dict(ok=True,width_m=.42,height_m=.297,sheet='S1',views=[],properties={},
              annotations=[dict(view='S1',type=12,position_m=[.2,.2,0],dangling=False,
                                bounds_m=bounds,bounds_source='native table row/column sizes')])
    result=review_snapshot(snap)
    assert not result['passed']
    assert any(f['code']=='annotation_extent_outside_sheet' for f in result['findings'])
