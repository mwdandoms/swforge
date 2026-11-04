"""显式选面的离线契约：引用作用域、输入前置校验与关键原生回读路径。"""
import base64
import copy
import subprocess
from pathlib import Path
import pytest
from swforge import mate_faces as f
from swforge.mates import MateBuilder, _CS_TEMPLATE


def reference(component='底座-1', kind='cylinder'):
    return dict(assembly_path=str(Path('fixture.SLDASM').absolute()),assembly_configuration='默认',
                component=component,part_path=str(Path(component+'.SLDPRT').absolute()),
                component_configuration='默认',face_ref=base64.b64encode(b'opaque-persist-reference').decode(),kind=kind)


def spec(kind='concentric'):
    face_kind='cylinder' if kind=='concentric' else 'plane'
    return dict(type=kind,face_a=reference('底座-1',face_kind),face_b=reference('销-1',face_kind))


@pytest.mark.parametrize('field', ['assembly_path','assembly_configuration','component','part_path',
                                 'component_configuration','face_ref','kind'])
def test_missing_reference_scope_rejected(field):
    face=reference();del face[field]
    with pytest.raises(ValueError):f._face_reference(face)


@pytest.mark.parametrize('value', ['???','',base64.b64encode(b'').decode(),42,None])
def test_invalid_persist_reference_is_not_a_face_index(value):
    face=reference();face['face_ref']=value
    with pytest.raises(ValueError):f._face_reference(face)


def test_roundtrip_reference_is_json_data_without_com_objects():
    face=reference();face.update(radius_mm=8.,face_index=123)
    accepted=f._face_reference(face)
    assert accepted['face_ref']==face['face_ref']
    assert 'face_index' not in accepted


@pytest.mark.parametrize('mutation', ['same_component','different_document','different_configuration','wrong_surface'])
def test_invalid_pair_never_connects_com(monkeypatch, mutation):
    item=spec()
    if mutation=='same_component':item['face_b']['component']=item['face_a']['component']
    if mutation=='different_document':item['face_b']['assembly_path']=str(Path('other.SLDASM').absolute())
    if mutation=='different_configuration':item['face_b']['assembly_configuration']='配置2'
    if mutation=='wrong_surface':item['face_b']['kind']='plane'
    monkeypatch.setattr(f,'_target',lambda *args:pytest.fail('非法请求不应连接COM'))
    assert not f.apply_face_mates(mates=[item])['ok']


@pytest.mark.parametrize('tolerance', [0,-1,float('inf'),float('nan'),True,.2])
def test_geometric_verification_cannot_be_disabled(tolerance):
    item=spec();item['verify_tolerance_mm']=tolerance
    with pytest.raises(ValueError):f._operation(item)


def test_unequal_cylinder_radii_are_not_used_to_pick_other_faces():
    item=spec();item['face_a']['radius_mm']=8.;item['face_b']['radius_mm']=7.8
    accepted=f._operation(item)
    assert accepted['face_a']['face_ref']==item['face_a']['face_ref']
    assert accepted['verify_tolerance_mm']==.001
    assert 'radius_tol' not in accepted


def test_batch_validates_later_requests_before_native_operation(monkeypatch):
    bad=spec();bad['face_b']['face_ref']='bad!'
    monkeypatch.setattr(f,'_target',lambda *args:pytest.fail('不能先执行第一项'))
    assert not f.apply_face_mates(mates=[spec(),bad])['ok']


def test_builder_does_not_mix_automatic_and_explicit_selection():
    item=spec()
    r=MateBuilder().concentric(0,1).concentric_faces(item['face_a'],item['face_b']).apply()
    assert not r['ok'] and not r['modified']


def test_builder_copies_reference_scope_and_passes_explicit_queue(monkeypatch):
    item=spec();builder=MateBuilder().concentric_faces(item['face_a'],item['face_b'])
    original=copy.deepcopy(builder._face_specs)
    item['face_a']['component']='后来被修改'
    monkeypatch.setattr(f,'apply_face_mates',lambda path,mates,timeout_s:dict(ok=True,mates=mates))
    assert builder.apply()['mates']==original


def test_native_bridge_verifies_identity_instead_of_only_addmate_status():
    src=f._ENGINE
    assert 'sw.IsSame(manager.GetSelectedObject6' in src
    assert 'EntityPair(mate,a,b)' in src
    assert 'GeometryOK' in src and 'parallel_error_deg' in src
    assert 'GetObjectByPersistReference3' in src
    assert 'foreach(object o in (IEnumerable)cmd["mates"])' in src
    assert 'MultiplyTransform(c.Transform2)' in src
    assert 'GetActiveObject' not in src
    assert 'radius_tol' not in src


def test_plane_parameter_order_regression():
    assert 'result.p=new[]{v[3],v[4],v[5]}' in f._ENGINE
    assert 'fi.pnt = new double[] { p[3], p[4], p[5] }' in _CS_TEMPLATE


def test_timeout_does_not_claim_no_mutation(monkeypatch,tmp_path):
    from swforge import modeling
    monkeypatch.setattr(modeling,'_find_sw_dir',lambda:str(tmp_path))
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('powershell',1)
    monkeypatch.setattr(subprocess,'run',timeout)
    result=f._run({'mode':'apply'},timeout_s=1)
    assert not result['ok'] and result['mutation_state']=='unknown'


def test_cli_invalid_pair_returns_nonzero_without_com(tmp_path,monkeypatch,capsys):
    import json
    from swforge.cli import main
    file=tmp_path/'bad.json';file.write_text(json.dumps({'mates':[{}]}),encoding='utf8')
    monkeypatch.setattr(f,'_target',lambda *args:pytest.fail('非法请求不应连接COM'))
    assert main(['mate','--spec',str(file)])==1
