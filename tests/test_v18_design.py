import copy,json
from pathlib import Path
import pytest
from swforge import resolve_design,builder_from_spec,PartBuilder

def example():
    return json.loads((Path(__file__).parents[1]/'examples/v18_mounting_plate.json').read_text(encoding='utf8'))

def test_centered_holes_follow_design_changes(tmp_path):
    spec=example();before=copy.deepcopy(spec)
    resolved=resolve_design(spec,{'length':160,'pitch_u':30})
    assert resolved['parameters']['start_x']==35
    assert resolved['spec']['hole_grids'][0]['x']==35
    assert resolved['spec']['boxes'][0]['x1']==160
    assert spec==before
    b=builder_from_spec(str(tmp_path/'p.SLDPRT'),spec)
    assert b.feature_count==2
    assert b.design_spec==spec

@pytest.mark.parametrize('params',[
    {'x':'=y','y':'=x'}, {'x':'=unknown+1'}, {'x':'=1/0'},
    {'x':'=__import__("os").getcwd()'}, {'x':True}, {'x':float('inf')},
    {'x':'=2**200'}, {'x':'=x.real'}, {'x':'=[1][0]'}, {'x':1e10}])
def test_bad_designs_rejected(params):
    with pytest.raises(ValueError):resolve_design({'parameters':params})

def test_requirements_and_unknown_override():
    with pytest.raises(ValueError,match='requirement'):resolve_design(example(),{'length':60})
    with pytest.raises(ValueError,match='Unknown'):resolve_design(example(),{'typo':4})

def test_legacy_tags_are_opt_in(tmp_path):
    b=PartBuilder(str(tmp_path/'p.SLDPRT'),feature_strategy='legacy')
    b.tube_y('tube',0,100,0,0,40,40,wall=4)
    assert b.feature_count==4 and 'tube_前' in b._tags
    b=PartBuilder(str(tmp_path/'q.SLDPRT')).tube_y('tube',0,100,0,0,40,40,wall=4)
    assert b.feature_count==1 and 'tube' in b._tags

def test_failed_grid_leaves_no_partial_features(tmp_path):
    b=PartBuilder(str(tmp_path/'p.SLDPRT')).box('plate',0,100,0,10,0,100)
    with pytest.raises(ValueError):b.hole_grid('grid','plate',rows=2,pitch_v=5,diameter=8,through_all=True)
    assert b.feature_count==1 and b._tags=={'plate'}

def test_counterbore_group_keeps_two_depths(tmp_path):
    b=PartBuilder(str(tmp_path/'p.SLDPRT')).box('plate',0,100,0,10,0,100)
    b.hole_grid('grid','plate',rows=2,columns=2,diameter=6,through_all=True,counterbore_diameter=10,counterbore_depth=3)
    assert b.feature_count==3

def test_stepped_shaft_requires_explicit_steps(tmp_path):
    b=PartBuilder(str(tmp_path/'p.SLDPRT'))
    with pytest.raises(ValueError):b.stepped_shaft('shaft',[{'length':0,'diameter':10}])
    assert b.feature_count==0
    b.stepped_shaft('shaft',[{'length':10,'diameter':20},{'length':30,'diameter':10}])
    assert b.feature_count==1

def test_stale_design_manifest_never_connects_sw(tmp_path,monkeypatch):
    from swforge import create_design_variant
    import swforge.session as session
    monkeypatch.setattr(session,'get_session',lambda:pytest.fail('must reject stale source before COM'))
    source=tmp_path/'source.SLDPRT';source.write_bytes(b'manual revision')
    Path(str(source)+'.design.json').write_text(json.dumps({'schema':1,'model_sha256':'stale','design':example()}),encoding='utf8')
    result=create_design_variant(str(source),str(tmp_path/'new.SLDPRT'),{'length':160})
    assert not result['ok'] and 'differs' in result['error']
    assert not (tmp_path/'new.SLDPRT').exists()

def test_design_cli_and_mcp_share_resolver(tmp_path,capsys):
    from swforge import cli
    path=tmp_path/'design.json';path.write_text(json.dumps(example()),encoding='utf8')
    assert cli.main(['design-resolve',str(path),'--parameters','{"length":160}'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['parameters']['start_x']==42.5
    from swforge.server import mcp
    assert mcp._gateway.registry['sw_resolve_design']['group']=='review'
    result=mcp._gateway.invoke('sw_resolve_design',{'spec':example(),'parameters':{'length':160}})
    assert result['ok'] and result['parameters']['start_x']==42.5
