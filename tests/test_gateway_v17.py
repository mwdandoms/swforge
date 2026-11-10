import pytest
from swforge.gateway import Gateway


def test_registry_forwards_defaults_and_rejects_extra():
    g=Gateway()
    def sw_list_example(value:int=7)->dict:
        """Read example fixture."""
        return dict(ok=True,value=value)
    g.register(sw_list_example)
    assert g.invoke('sw_list_example',{})['value']==7
    assert not g.invoke('sw_list_example',{'extra':True})['ok']
    assert g.describe(['sw_list_example'])['operations'][0]['inputSchema']['properties']['value']['default']==7


def test_unregistered_and_disabled_admin():
    g=Gateway()
    def sw_close_all(discard_unsaved:bool=False)->dict:return dict(ok=True)
    g.register(sw_close_all)
    assert g.invoke('unknown',{})['error']=='unregistered'
    assert g.invoke('sw_close_all',{})['error']=='group_disabled'


def test_admin_requires_token_when_explicitly_enabled():
    g=Gateway(enabled_groups=['admin'])
    def sw_close_all()->dict:return dict(ok=True)
    g.register(sw_close_all)
    assert g.invoke('sw_close_all',{})['error']=='approval_required'


def test_existing_output_requires_token(tmp_path):
    g=Gateway();p=tmp_path/'saved';p.write_text('saved')
    def sw_build_example(out_path:str)->dict:raise AssertionError('must not run')
    g.register(sw_build_example)
    assert g.invoke('sw_build_example',{'out_path':str(p)})['error']=='approval_required'


def test_matrix_load_and_no_cross_version_claim():
    from swforge.capability_matrix import load_matrix,capability
    matrix=load_matrix()
    assert matrix['cross_version']=='excluded_by_user'
    for version in ('2024','2026'):
        assert capability(matrix['capabilities'][0]['id'],version)['status']=='unverified'
