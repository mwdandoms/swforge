"""Regression contracts for the independent-review gaps."""
import copy
import pytest
from swforge.gb_check import GBSpec,evaluate_gb_completeness
from swforge.gb_notes import build_tech_requirements
from swforge.section_check import evaluate_central_bore


def snap():
    return {'ok':True,'views':[{'dimensions':[{'name':'D1','view':'front','type':2,'value_mm':20,'attached_entity_count':2}]}],
            'properties':{'图样名称':'支架','图样代号':'A-1','材料':'Q235','比例':'1:2','技术要求':'去除毛刺。'},
            'annotations':[{'type':6,'text':'支架 A-1 Q235 1:2\n去除毛刺。'}]}


def spec(**kwargs):
    return GBSpec(min_views=1,min_dimensions=1,require_projection_symbol=False,require_surface_finish=False,
                  require_tolerance=False,**kwargs)


def test_properties_cannot_fake_visible_title_or_requirements():
    s=snap();s['annotations']=[]
    r=evaluate_gb_completeness(s,spec())
    assert r['status']=='FAILED' and len(r['critical'])==5


def test_matching_dimension_count_cannot_hide_missing_diameter():
    r=evaluate_gb_completeness(snap(),spec(required_dimensions=[{'kind':'diameter','value_mm':20}]))
    assert not r['ok'] and '关键尺寸' in r['critical'][0]


def test_equal_thickness_does_not_prove_axial_location():
    assert not evaluate_gb_completeness(snap(),spec(required_dimensions=[{'kind':'position','value_mm':20}]))['ok']
    assert evaluate_gb_completeness(snap(),spec(required_dimensions=[{'kind':'position','value_mm':20,'name':'D1'}]))['ok']


def test_dangling_or_unattached_nominal_is_not_evidence():
    for flag in ({'dangling':True},{'attached_entity_count':0}):
        s=snap();s['views'][0]['dimensions'][0].update(flag)
        assert not evaluate_gb_completeness(s,spec(required_dimensions=[{'value_mm':20}]))['ok']


def test_manufacturing_requirements_are_never_invented():
    assert build_tech_requirements()==[]
    with pytest.raises(ValueError):build_tech_requirements(general=True)
    assert build_tech_requirements(['去除毛刺。'])==['去除毛刺。']


def cut_faces(x=0,gap=.02):
    return {'ok':True,'hatch_count':2,'faces':[{'planar':True,'vertices_m':[
        [x,sign*gap/2,0],[x,sign*.06,0],[x,sign*gap/2,.035],[x,sign*.025,.035]]} for sign in [-1,1]]}


def test_hatches_alone_cannot_prove_central_bore():
    assert not evaluate_central_bore({'ok':True,'hatch_count':2},20,35)['ok']
    assert not evaluate_central_bore(cut_faces(x=.03),20,35)['ok']
    assert not evaluate_central_bore(cut_faces(gap=.018),20,35)['ok']
    assert evaluate_central_bore(cut_faces(),20,35)['ok']


def test_one_side_or_wrong_width_does_not_prove_through_bore():
    s=cut_faces();s['faces'].pop()
    assert not evaluate_central_bore(s,20,35)['ok']
    assert not evaluate_central_bore(cut_faces(),20,25)['ok']
