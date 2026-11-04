"""v1.4 单位、唯一匹配与静默失败回归；COM 行为另走实机验证。"""
from types import SimpleNamespace
import pytest
from swforge import annotations as a


class Tolerance:
    def __init__(self):
        self.hole, self.shaft = '', ''

    def GetHoleFitValue(self):
        return self.hole

    def GetShaftFitValue(self):
        return self.shaft

    def SetFitValues(self, hole, shaft):
        self.hole, self.shaft = hole, shaft
        return True


class Dimension:
    def __init__(self, silent=False):
        self.SystemValue = .16
        self.kind, self.values, self.silent = 0, [0., 0.], silent
        self.Tolerance = Tolerance()

    def GetToleranceType(self):
        return self.kind

    def GetToleranceValues(self):
        return self.values

    def SetToleranceType(self, kind):
        self.kind = kind
        return True

    def SetToleranceValues(self, low, high):
        if not self.silent:
            self.values = [low, high]
        return True


def bind(monkeypatch, dim, duplicate=False, kind=2):
    md = SimpleNamespace(EditRebuild3=True)
    monkeypatch.setattr(a, '_drawing', lambda path: (None, md))
    monkeypatch.setattr(a, '_active', lambda *args: None)
    row = {'dim_obj': dim, 'name': 'RD1@主视图@测试.Drawing', 'view': '主视图',
           'value': 160., 'dimension_type': kind}
    monkeypatch.setattr(a, '_dimensions', lambda *args: [row, dict(row, name='other')] if duplicate else [row])
    return row


@pytest.mark.parametrize('kind,low,high', [('symmetric', None, .1), ('bilateral', -.02, .15), ('limit', -.3, -.1)])
def test_offsets_convert_mm_to_metres_and_nominal_unchanged(monkeypatch, kind, low, high):
    dim = Dimension()
    bind(monkeypatch, dim)
    result = a.set_tolerance(dim_value=160, tol_type=kind, upper=high, lower=low)
    assert result['ok'], result
    assert dim.values == [(-high if low is None else low)/1000, high/1000]
    assert result['nominal_before_mm'] == result['nominal_after_mm'] == 160


def test_fit_readback(monkeypatch):
    dim = Dimension()
    bind(monkeypatch, dim)
    result = a.set_tolerance(dim_value=160, tol_type='fit', fit='H7/g6')
    assert result['ok'] and result['fit_readback'] == {'hole': 'H7', 'shaft': 'g6'}


def test_initial_none_values_use_tolerance_object_readback(monkeypatch):
    dim = Dimension()
    bind(monkeypatch, dim)
    dim.GetToleranceValues = lambda: None if dim.kind == 0 else dim.values
    dim.Tolerance.GetMinValue = lambda: 0.
    dim.Tolerance.GetMaxValue = lambda: 0.
    assert a.set_tolerance(dim_value=160, upper=.1)['ok']


def test_none_clears_type_without_changing_nominal(monkeypatch):
    dim = Dimension()
    bind(monkeypatch, dim)
    dim.kind, dim.values = 4, [-.0001, .0001]
    result = a.set_tolerance(dim_value=160, tol_type='none')
    assert result['ok'] and result['type_readback'] == 0
    assert result['nominal_after_mm'] == 160


def test_ambiguous_value_never_changes_any_dimension(monkeypatch):
    dim = Dimension()
    bind(monkeypatch, dim, duplicate=True)
    result = a.set_tolerance(dim_value=160, upper=.1)
    assert not result['ok'] and not result['modified']
    assert dim.kind == 0


def test_silent_write_is_failure_and_original_tolerance_restored(monkeypatch):
    dim = Dimension(silent=True)
    bind(monkeypatch, dim)
    result = a.set_tolerance(dim_value=160, upper=.1)
    assert not result['ok'] and result['rollback_ok']
    assert dim.kind == 0 and dim.values == [0., 0.]


def test_angular_dimension_rejected(monkeypatch):
    dim = Dimension()
    bind(monkeypatch, dim, kind=3)
    result = a.set_tolerance(dim_value=160, upper=.1)
    assert not result['ok'] and not result['modified']


@pytest.mark.parametrize('kwargs', [dict(upper=None), dict(upper=float('nan')),
    dict(upper=True), dict(upper=-.1), dict(upper=.1, lower=0),
    dict(tol_type='bilateral', upper=.1), dict(tol_type='limit', upper=0, lower=.1),
    dict(tol_type='fit', fit=None), dict(tol_type='fit', fit='g6/H7'), dict(tol_type='bogus')])
def test_invalid_tolerance_rejected_before_com(monkeypatch, kwargs):
    monkeypatch.setattr(a, '_drawing', lambda path: pytest.fail('非法参数不应连接 COM'))
    assert not a.set_tolerance(dim_value=160, **kwargs)['ok']


@pytest.mark.parametrize('x,y', [(0,.1), (.42,.1), (.1,-1), (float('nan'),.1), (.1,None)])
def test_surface_positions_rejected(monkeypatch, x, y):
    monkeypatch.setattr(a, '_sheet_size', lambda md: (.42,.297))
    with pytest.raises(ValueError):
        a._position(None, x, y, None, .008, 0.)


def test_batch_prevalidates_all_before_inserting(monkeypatch):
    monkeypatch.setattr(a, '_drawing', lambda path: (None,None))
    monkeypatch.setattr(a, '_sheet_size', lambda md: (.42,.297))
    monkeypatch.setattr(a, '_insert_surface', lambda *args: pytest.fail('不应部分插入'))
    r = a.add_surface_finishes(finishes=[{'x': .1, 'y': .1}, {'x': 1., 'y': .2}])
    assert not r['ok'] and r['created'] == 0


def test_surface_ignored_coordinates_corrected_and_readback_checked(monkeypatch):
    from swforge import drawing
    monkeypatch.setattr(drawing, '_view_list', lambda md: [])
    monkeypatch.setattr(a, '_active', lambda *args: None)
    class Annotation:
        position = (0.,0.,0.)
        def SetPosition2(self, x, y, z):
            self.position = (x,y,z)
            return True
        def GetPosition(self):
            return self.position
    ann = Annotation()
    symbol = SimpleNamespace(GetSymbolType=1, GetTextCount=1,
                             GetTextAtIndex=lambda i: '3.2', GetAnnotation=ann, GetDirectionOfLay=0)
    md = SimpleNamespace(ActivateView=lambda *args: True, ClearSelection2=lambda *args: None,
                         EditRebuild3=True,
                         Extension=SimpleNamespace(InsertSurfaceFinishSymbol3=lambda *args: symbol))
    req = dict(x=.1, y=.2, ra='3.2', symbol_type=1, prod_method='', lay=0)
    assert a._insert_surface(None, md, req)['ok']
    ann.SetPosition2 = lambda *args: True
    ann.position = (0.,0.,0.)
    r = a._insert_surface(None, md, req)
    assert not r['ok'] and r['created']


def test_cli_failure_returns_nonzero(monkeypatch, capsys):
    from swforge.cli import _main
    monkeypatch.setattr(a, 'add_surface_finish', lambda *args, **kwargs: {'ok': False, 'error': '位置回读失败'})
    assert _main(['surface-finish', '--x', '.1', '--y', '.2']) == 1


def test_mcp_annotation_tools_have_explicit_units():
    import asyncio
    from swforge.server import mcp
    if mcp is None:
        pytest.skip('mcp 未安装')
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert 'sw_add_surface_finishes' in tools and 'sw_list_dimensions' in tools
    assert '米' in tools['sw_add_surface_finish'].description
    assert 'mm' in tools['sw_set_tolerance'].description


def test_projection_includes_view_rotation_scale_and_sheet_translation():
    matrix = [0,1,0,-1,0,0,0,0,1,.1,.2,.3,.5,0,0,0]
    assert a._project_point([.04,.06,.08],matrix) == pytest.approx([.07,.22,.34])


def test_leader_tip_distance_ignores_model_depth():
    assert a._distance_to_segment([.15,.2,99],[.1,.2,0],[.3,.2,0]) == pytest.approx(0)
    assert a._distance_to_segment([.15,.21,0],[.1,.2,0],[.3,.2,0]) == pytest.approx(.01)


def test_edge_placement_uses_projected_geometry_not_view_outline(monkeypatch):
    edge = dict(edge_index=2,start_m=[.1,.2,0],end_m=[.3,.2,0])
    monkeypatch.setattr(a,'_surface_edges',lambda *args: (None,[edge]))
    monkeypatch.setattr(a,'_sheet_size',lambda md:(.42,.297))
    r = a._surface_request(None,view_name='主视图',edge_index=2,edge_fraction=.25)
    assert (r['x'],r['y']) == pytest.approx((.15,.2))
    assert r['edge_index'] == 2


@pytest.mark.parametrize('kwargs',[dict(edge_index=0),dict(view_name='主视图',edge_index=-1),
    dict(view_name='主视图',edge_index=0,edge_fraction=1.1),dict(leader=True)])
def test_invalid_edge_request_never_selects_com(monkeypatch, kwargs):
    monkeypatch.setattr(a,'_surface_edges',lambda *args: pytest.fail('非法参数不应选边'))
    with pytest.raises(ValueError):
        a._surface_request(None,**kwargs)
