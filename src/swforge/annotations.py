"""工程图粗糙度与尺寸公差；只应用调用方给定的工艺要求。"""
from __future__ import annotations

import math
import os
import re

from .session import get_session, _value

__all__ = ['add_surface_finish', 'add_surface_finishes', 'list_surface_edges', 'list_dimensions', 'set_tolerance']

SURFACE_TYPES = {'basic': 0, 'machining': 1, 'no_machining': 2}
TOLERANCE_TYPES = {'none': 0, 'bilateral': 2, 'limit': 3, 'symmetric': 4, 'fit': 7}


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} 必须是有限数值')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'{name} 必须是有限数值')
    return number


def _drawing(path):
    from .drawing import _drawing_document
    from .resources import ensure_capacity
    sw = get_session().sw()
    if path:
        path = os.path.abspath(os.fspath(path))
        if not os.path.isfile(path):
            raise ValueError(f'工程图不存在：{path}')
        if sw.GetOpenDocumentByName(path) is None:
            ensure_capacity(1)
    return sw, _drawing_document(sw, path)


def _active(sw, md):
    doc = sw.ActiveDoc
    if doc is None:
        raise RuntimeError('活动工程图丢失')
    target = str(_value(md, 'GetPathName') or '')
    actual = str(_value(doc, 'GetPathName') or '')
    if target:
        same = os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(actual)) if actual else False
    else:
        same = _value(doc, 'GetTitle') == _value(md, 'GetTitle')
    if not same:
        raise RuntimeError('活动文档已被切换，停止标注；不自动重试以免重复插入')


def _sheet_size(md):
    # GetProperties2 的宽高是米，不依赖纸张枚举，兼容自定义幅面。
    sheet = _value(md, 'GetCurrentSheet')
    props = list(_value(sheet, 'GetProperties2'))
    width, height = float(props[5]), float(props[6])
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise RuntimeError('无法回读有效图纸幅面')
    return width, height


def _position(md, x, y, view_name, offset_x, offset_y):
    if (x is None) != (y is None):
        raise ValueError('x 与 y 必须同时提供，单位米')
    if x is None:
        from .views_extra import _pick_view
        view, _, error = _pick_view(md, view_name)
        if view is None:
            raise ValueError(error)
        outline = list(_value(view, 'GetOutline'))
        x = float(outline[2]) + _number(offset_x, 'offset_x')
        y = float(outline[3]) + _number(offset_y, 'offset_y')
    x, y = _number(x, 'x'), _number(y, 'y')
    width, height = _sheet_size(md)
    if not (0 < x < width and 0 < y < height):
        raise ValueError(f'位置 ({x}, {y}) 超出图纸内部 (0,{width}) × (0,{height})，单位米')
    return x, y


def _surface_request(md, *, x=None, y=None, ra='3.2', symbol_type='machining',
                     prod_method='', lay=0, view_name=None, offset_x=.008, offset_y=0.,
                     edge_index=None, edge_fraction=.5, leader=False):
    ra = str(ra).strip()
    if _number(ra, 'ra') <= 0:
        raise ValueError('ra 必须大于 0，单位 μm')
    if symbol_type is None:
        symbol_type = 'machining'
    sym = SURFACE_TYPES.get(symbol_type, symbol_type) if isinstance(symbol_type, str) else symbol_type
    if isinstance(sym, bool) or sym not in (0, 1, 2):
        raise ValueError('symbol_type 只支持 basic/0、machining/1、no_machining/2')
    if isinstance(lay, bool) or not isinstance(lay, int) or not 0 <= lay <= 7:
        raise ValueError('lay 必须为 0~7 的纹理方向枚举')
    attachment = {}
    if edge_index is not None:
        if not view_name:
            raise ValueError('附着轮廓边必须明确提供 view_name')
        if isinstance(edge_index, bool) or not isinstance(edge_index, int) or edge_index < 0:
            raise ValueError('edge_index 必须为非负整数，先调用 list_surface_edges')
        fraction = _number(edge_fraction, 'edge_fraction')
        if not 0 <= fraction <= 1:
            raise ValueError('edge_fraction 必须在 0~1 之间')
        _, edges = _surface_edges(md, view_name)
        edge = next((e for e in edges if e['edge_index'] == edge_index), None)
        if edge is None:
            raise ValueError('指定边不存在或不是可见直边，曲边附着未验证')
        start, end = edge['start_m'], edge['end_m']
        point = [a+(b-a)*fraction for a,b in zip(start,end)]
        if not leader:
            if x is not None or y is not None:
                raise ValueError('贴边模式不能提供 x/y；需要偏置文字时请用 leader=True')
            if abs(start[1]-end[1]) > 1e-7:
                raise ValueError('无引线模式目前仅支持水平直边；其他方向请用 leader=True')
            x, y = point[:2]
        elif x is None and y is None:
            x, y = point[0]+_number(offset_x,'offset_x'), point[1]+_number(offset_y,'offset_y')
        attachment = dict(view_name=view_name, edge_index=edge_index, edge_fraction=fraction,
                          leader=bool(leader), edge_start_m=start, edge_end_m=end)
    elif leader:
        raise ValueError('leader=True 必须指定附着的 edge_index 和 view_name')
    x, y = _position(md, x, y, view_name, offset_x, offset_y)
    return dict(x=x, y=y, ra=ra, symbol_type=int(sym), prod_method=str(prod_method), lay=lay, **attachment)


def _insert_surface(sw, md, request):
    from .drawing import _view_list
    x, y, ra, sym = (request[k] for k in ('x', 'y', 'ra', 'symbol_type'))
    _active(sw, md)
    before = len(_view_list(md))
    md.ClearSelection2(True)
    attached = 'edge_index' in request
    if attached:
        view, edges = _surface_edges(md, request['view_name'], include_objects=True)
        edge = next((e for e in edges if e['edge_index'] == request['edge_index']), None)
        if edge is None or any(abs(a-b)>1e-7 for field in ('start_m','end_m')
                               for a,b in zip(edge[field],request['edge_'+field])):
            raise RuntimeError('目标轮廓边已变化，请重新枚举后标注')
        md.ActivateView(request['view_name'])
        if not view.SelectEntity(edge['edge_obj'], False):
            raise RuntimeError('无法选中目标轮廓边，不退回悬空符号')
    else:
        md.ActivateView('')
    symbol = md.Extension.InsertSurfaceFinishSymbol3(
        sym, 1 if request.get('leader') else 0, x, y, 0., request['lay'], 0, '', '', request['prod_method'], '', ra, '', '')
    if symbol is None:
        return {'ok': False, 'error': 'InsertSurfaceFinishSymbol3 返回 None', 'created': False}
    result = {'ok': False, 'created': True, 'error': '', 'requested': request}
    try:
        annotation = _value(symbol, 'GetAnnotation')
        # SW2025 实测插入坐标被忽略、符号落在原点；必须再移动并回读。
        if not annotation.SetPosition2(x, y, 0.):
            raise RuntimeError('SetPosition2 返回 False')
        _value(md, 'EditRebuild3')
        result['type'] = int(_value(symbol, 'GetSymbolType'))
        result['lay_readback'] = int(_value(symbol, 'GetDirectionOfLay'))
        result['texts'] = [symbol.GetTextAtIndex(i) for i in range(int(_value(symbol, 'GetTextCount')))]
        result['position'] = [float(v) for v in _value(annotation, 'GetPosition')]
        result['placement'] = 'edge' if attached else 'sheet'
        if attached:
            result['attached_entity_count'] = int(_value(annotation, 'GetAttachedEntityCount3'))
            if result['attached_entity_count'] < 1:
                raise RuntimeError('粗糙度未关联目标边，不能作为贴边标注成功')
            if request.get('leader'):
                points = list(annotation.GetLeaderPointsAtIndex(0) or [])
                result['leader_points'] = points
                if len(points) < 6 or not bool(_value(symbol, 'IsAttached')):
                    raise RuntimeError('粗糙度引线未生成')
                tip = points[-3:]
                # 原生选边插入可能把箭头落在端点；只要确实在请求的直边上即可。
                if _distance_to_segment(tip, request['edge_start_m'], request['edge_end_m']) > 1e-6:
                    raise RuntimeError('引线端点不在目标轮廓边上')
        result['ra_readback'] = ra if ra in result['texts'] else None
        result['view_count_before'] = before
        result['view_count_after'] = len(_view_list(md))
        _active(sw, md)
        if result['type'] != sym or result['ra_readback'] is None:
            raise RuntimeError('符号类型或 Ra 回读不一致')
        if result['lay_readback'] != request['lay']:
            raise RuntimeError('纹理方向回读不一致')
        if request['prod_method'] and request['prod_method'] not in result['texts']:
            raise RuntimeError('加工方法回读不一致')
        if any(abs(a-b) > 1e-7 for a, b in zip(result['position'][:2], (x, y))) or len(result['position']) < 2:
            raise RuntimeError('符号位置回读不一致')
        if result['view_count_after'] != before:
            raise RuntimeError('标注后视图数发生变化')
        result['ok'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    return result


def add_surface_finish(drawing_path=None, x=None, y=None, ra='3.2',
                       symbol_type='machining', prod_method='', lay=0,
                       view_name=None, offset_x=.008, offset_y=0.,
                       edge_index=None, edge_fraction=.5, leader=False) -> dict:
    """添加并回读粗糙度。x/y 和视图偏移用米，Ra 用 μm；省略坐标从视图右上角推算。

    只修改当前内存文档；确认结果后由调用方保存或导出。不跳过回读验证。
    """
    try:
        sw, md = _drawing(drawing_path)
        request = _surface_request(md, x=x, y=y, ra=ra, symbol_type=symbol_type,
                                   prod_method=prod_method, lay=lay, view_name=view_name,
                                   offset_x=offset_x, offset_y=offset_y, edge_index=edge_index,
                                   edge_fraction=edge_fraction, leader=leader)
        return _insert_surface(sw, md, request)
    except Exception as exc:
        return {'ok': False, 'created': False, 'error': f'{type(exc).__name__}: {exc}'}


def add_surface_finishes(drawing_path=None, finishes=None) -> dict:
    """批量标注，先校验全部参数；执行中失败立即停止，返回已创建项供调用方处理。"""
    results = []
    try:
        items = list(finishes or [])
        if not items:
            raise ValueError('finishes 不能为空')
        sw, md = _drawing(drawing_path)
        requests = [_surface_request(md, **item) for item in items]
        for request in requests:
            results.append(_insert_surface(sw, md, request))
            if not results[-1]['ok']:
                break
        ok = len(results) == len(items) and all(r['ok'] for r in results)
        return {'ok': ok, 'results': results, 'created': sum(bool(r.get('created')) for r in results),
                'error': '' if ok else results[-1]['error']}
    except Exception as exc:
        return {'ok': False, 'results': results, 'created': sum(bool(r.get('created')) for r in results),
                'error': f'{type(exc).__name__}: {exc}'}


def _wrap(obj):
    if obj is not None and not hasattr(obj, '_oleobj_'):
        import win32com.client
        return win32com.client.Dispatch(obj)
    return obj


def _project_point(point, matrix):
    scale = matrix[12]
    return [sum(point[j]*matrix[j*3+i] for j in range(3))*scale+matrix[9+i] for i in range(3)]


def _distance_to_segment(point, start, end):
    # 只比较图纸平面；SW 可能保留模型的深度值，z 不代表图上偏移。
    delta = [end[i]-start[i] for i in (0,1)]
    length2 = sum(v*v for v in delta)
    fraction = max(0., min(1., sum((point[i]-start[i])*delta[i] for i in (0,1))/length2)) if length2 else 0.
    return math.hypot(*(point[i]-start[i]-fraction*delta[i] for i in (0,1)))


def _surface_edges(md, view_name, include_objects=False):
    import pythoncom
    from win32com.client import VARIANT
    from .views_extra import _pick_view
    view, name, error = _pick_view(md, view_name)
    if view is None:
        raise ValueError(error)
    transform = list(_value(_value(view,'ModelToViewTransform'),'ArrayData'))
    # Python None 是 VT_EMPTY，实测会报类型不匹配；这里需要带类型的空组件。
    raw = view.GetVisibleEntities2(VARIANT(pythoncom.VT_DISPATCH,None), 1) or []
    rows = []
    for index, obj in enumerate(raw):
        edge = _wrap(obj)
        if not bool(_value(_value(edge,'GetCurve'),'IsLine')):
            continue
        start, end = _wrap(_value(edge,'GetStartVertex')), _wrap(_value(edge,'GetEndVertex'))
        if start is None or end is None:
            continue
        p1 = _project_point(list(_value(start,'GetPoint')),transform)
        p2 = _project_point(list(_value(end,'GetPoint')),transform)
        if math.hypot(p2[0]-p1[0],p2[1]-p1[1]) < 1e-8:
            continue
        row = dict(view=name, edge_index=index, start_m=p1, end_m=p2)
        if include_objects:
            row['edge_obj'] = edge
        rows.append(row)
    return view, rows


def list_surface_edges(drawing_path=None, view_name=None) -> list[dict]:
    """只读枚举指定视图的可见直边，返回边索引及图纸端点（米），供显式指定粗糙度对象。"""
    sw, md = _drawing(drawing_path)
    _, rows = _surface_edges(md, view_name)
    _active(sw, md)
    return rows


def _dimensions(md, include_objects):
    from .drawing import _view_list
    rows = []
    for view, view_name in _view_list(md):
        disp = _wrap(_value(view, 'GetFirstDisplayDimension5'))
        count = 0
        while disp is not None:
            count += 1
            if count > 10000:
                raise RuntimeError('尺寸遍历超过上限，可能存在循环引用')
            dim = _wrap(disp.GetDimension2(0))
            if dim is None:
                raise RuntimeError(f'{view_name} 的显示尺寸无法取得 Dimension')
            # 工程图参考尺寸 IDimension.GetType 实测返回 0；显示尺寸 Type2 才有正确类型。
            kind = int(_value(disp, 'Type2'))
            raw = float(_value(dim, 'SystemValue'))
            # 角度不伪装成毫米；v1.4 公差仅支持线性尺寸。
            row = {'name': str(_value(dim, 'FullName')), 'view': view_name,
                   'dimension_type': kind, 'system_value': raw,
                   'value': math.degrees(raw) if kind in (3, 16) else raw * 1000,
                   'unit': 'deg' if kind in (3, 16) else 'mm'}
            if include_objects:
                row.update(dim_obj=dim, disp_obj=disp)
            rows.append(row)
            disp = _wrap(_value(disp, 'GetNext5'))
    return rows


def list_dimensions(drawing_path=None, include_objects=False) -> list[dict]:
    """枚举当前图纸尺寸。默认可 JSON 序列化；本线程可用 include_objects=True 取 COM 引用。

    读取失败抛异常，不能把断线误报成空工程图。
    """
    sw, md = _drawing(drawing_path)
    rows = _dimensions(md, include_objects)
    _active(sw, md)
    return rows


def _tolerance_request(tol_type, upper, lower, fit):
    if tol_type not in TOLERANCE_TYPES:
        raise ValueError('tol_type 必须为 symmetric/bilateral/limit/fit/none')
    if tol_type == 'fit':
        parts = str(fit).split('/') if fit is not None else []
        if len(parts) != 2 or not re.fullmatch(r'[A-Z]{1,2}\d{1,2}', parts[0]) or not re.fullmatch(r'[a-z]{1,2}\d{1,2}', parts[1]):
            raise ValueError('fit 必须是明确的孔/轴代号，例如 H7/g6')
        return {'type': 7, 'hole': parts[0], 'shaft': parts[1]}
    if tol_type == 'none':
        return {'type': 0}
    if upper is None:
        raise ValueError('必须明确指定 upper，单位毫米；不自动推荐公差')
    upper = _number(upper, 'upper')
    if tol_type == 'symmetric':
        if upper < 0:
            raise ValueError('对称公差 upper 不能为负')
        lower = -upper if lower is None else _number(lower, 'lower')
        if not math.isclose(lower, -upper, abs_tol=1e-12):
            raise ValueError('对称公差 lower 必须等于 -upper')
    else:
        if lower is None:
            raise ValueError('双向/极限公差必须明确指定 lower，单位毫米')
        lower = _number(lower, 'lower')
    if lower > upper:
        raise ValueError('lower 不能大于 upper；极限公差输入上下偏差，不是极限尺寸')
    return {'type': TOLERANCE_TYPES[tol_type], 'lower': lower, 'upper': upper}


def _tolerance_values(dim):
    values = _value(dim, 'GetToleranceValues')
    if values is None:
        # 无公差尺寸实测返回 None；不能在设置前误判成断线，也不能猜上下偏差。
        tolerance = _value(dim, 'Tolerance')
        return [float(_value(tolerance, 'GetMinValue')), float(_value(tolerance, 'GetMaxValue'))]
    values = [float(v) for v in values]
    if len(values) != 2 or not all(math.isfinite(v) for v in values):
        raise RuntimeError('公差偏差回读无效')
    return values


def set_tolerance(drawing_path=None, dim_name=None, dim_value=None,
                  tol_type='symmetric', upper=None, lower=None, fit=None,
                  view_name=None) -> dict:
    """仅给唯一匹配的线性尺寸加公差。偏差和值均为 mm；同值多尺寸时拒绝猜测。

    公差不修改名义值；失败会尝试恢复原公差并回读确认。只修改内存文档。
    """
    result = {'ok': False, 'error': '', 'modified': False}
    dim = None
    snapshot = None
    try:
        request = _tolerance_request(tol_type, upper, lower, fit)
        if not dim_name and dim_value is None:
            raise ValueError('必须指定 dim_name 或 dim_value')
        value = None if dim_value is None else _number(dim_value, 'dim_value')
        sw, md = _drawing(drawing_path)
        rows = _dimensions(md, True)
        matches = [r for r in rows if (not dim_name or r['name'] == dim_name)
                   and (view_name is None or r['view'] == view_name)
                   and (value is None or abs(r['value'] - value) < 1e-6)]
        if len(matches) != 1:
            raise ValueError(f'尺寸匹配 {len(matches)} 项，必须唯一；请用 list_dimensions 返回的完整 name 和 view')
        row = matches[0]
        if row['dimension_type'] not in (1, 2, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15):
            raise ValueError('v1.4 仅支持线性尺寸公差，角度公差未验证')
        dim = row['dim_obj']
        tolerance = _value(dim, 'Tolerance')
        snapshot = {'type': int(_value(dim, 'GetToleranceType')),
                    'values': _tolerance_values(dim),
                    'hole': str(_value(tolerance, 'GetHoleFitValue') or ''),
                    'shaft': str(_value(tolerance, 'GetShaftFitValue') or '')}
        before = float(_value(dim, 'SystemValue'))
        result.update(name=row['name'], view=row['view'], nominal_before_mm=before * 1000)
        _active(sw, md)
        result['modified'] = True
        if not dim.SetToleranceType(request['type']):
            raise RuntimeError('SetToleranceType 返回 False')
        if tol_type == 'fit':
            if not tolerance.SetFitValues(request['hole'], request['shaft']):
                raise RuntimeError('SetFitValues 返回 False')
        elif tol_type != 'none':
            # 与图纸坐标不同，调用方偏差用毫米；SW 公差 API 使用米。
            if not dim.SetToleranceValues(request['lower'] / 1000, request['upper'] / 1000):
                raise RuntimeError('SetToleranceValues 返回 False')
        _value(md, 'EditRebuild3')
        after = float(_value(dim, 'SystemValue'))
        result.update(type_readback=int(_value(dim, 'GetToleranceType')),
                      values_readback=[v*1000 for v in _tolerance_values(dim)],
                      fit_readback={'hole': str(_value(tolerance, 'GetHoleFitValue') or ''),
                                    'shaft': str(_value(tolerance, 'GetShaftFitValue') or '')},
                      nominal_after_mm=after * 1000)
        _active(sw, md)
        if result['type_readback'] != request['type'] or abs(after-before) > 1e-10:
            raise RuntimeError('公差类型或名义值回读不一致')
        if tol_type == 'fit':
            if result['fit_readback'] != {'hole': request['hole'], 'shaft': request['shaft']}:
                raise RuntimeError('配合代号回读不一致')
        elif tol_type != 'none':
            wanted = [request['lower'], request['upper']]
            if len(result['values_readback']) != 2 or any(abs(a-b)>1e-7 for a,b in zip(result['values_readback'], wanted)):
                raise RuntimeError('上下偏差回读不一致')
        result['ok'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        if snapshot is not None and result['modified']:
            try:
                dim.SetToleranceType(snapshot['type'])
                dim.SetToleranceValues(*snapshot['values'])
                _value(dim, 'Tolerance').SetFitValues(snapshot['hole'], snapshot['shaft'])
                restored = _tolerance_values(dim)
                result['rollback_ok'] = (int(_value(dim, 'GetToleranceType')) == snapshot['type']
                                         and restored == snapshot['values']
                                         and str(_value(tolerance, 'GetHoleFitValue') or '') == snapshot['hole']
                                         and str(_value(tolerance, 'GetShaftFitValue') or '') == snapshot['shaft'])
            except Exception as rollback_exc:
                result.update(rollback_ok=False, rollback_error=str(rollback_exc))
    return result
