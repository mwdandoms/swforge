"""v1.4 可复现实机验收：粗糙度、四类公差、保存重开、压力与公差回退。

python examples/verify_annotations.py --work-dir <新的证据目录> [--keep]
只清理本轮创建的文档；--keep 最后保留演示零件和工程图。
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import traceback


def verify(work_dir, keep=False):
    from swforge import (PartBuilder, produce, add_dimensions, add_surface_finish,
                         add_surface_finishes, list_dimensions, set_tolerance,
                         document_inventory, get_session, export_pdf, list_surface_edges)
    from swforge.session import _value
    from swforge.drawing import _drawing_document, _save_as, _default_template, _view_list
    from swforge.annotations import _wrap, _tolerance_values
    import pypdfium2 as pdfium

    root = Path(work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'checks': [], 'before': document_inventory()}
    sw = get_session().sw()
    owned = []
    part, drawing = root / '公差与粗糙度演示.SLDPRT', root / '公差与粗糙度演示.SLDDRW'
    if part.exists() or drawing.exists():
        raise ValueError('请使用新的证据目录，避免覆盖已有成果')
    for item in report['before']['documents']:
        if item['path'] and Path(item['path']).name.casefold() in (part.name.casefold(), drawing.name.casefold()):
            raise ValueError('已有同名演示文档打开；请先保存并关闭它，避免 SolidWorks 按名称激活到其他路径')

    def check(name, ok, detail):
        report['checks'].append(dict(name=name, ok=bool(ok), detail=detail))
        print(json.dumps(report['checks'][-1], ensure_ascii=False), flush=True)
        if not ok:
            raise AssertionError(f'{name}: {detail}')

    try:
        owned.extend([str(part), str(drawing)])
        builder = PartBuilder(str(part), material='Q235')
        builder.box('底板', 0, 160, 0, 20, 0, 100)
        built = builder.build(paint=False, keep_open=True)
        check('模型回读', built.ok and abs(built.volume_mm3-320000)<1, built.__dict__)
        made = produce(str(part), str(drawing), paper='A3', keep_open=True)
        check('生成三视图', made['ok'], made)
        dimensions = add_dimensions(str(drawing), internal=0)
        check('创建尺寸', dimensions['ok'], dimensions)
        rows = list_dimensions(str(drawing))
        report['dimensions'] = rows
        check('尺寸枚举', len(rows)>=4, rows)
        ambiguous = set_tolerance(str(drawing), dim_value=160, upper=.1)
        check('同值尺寸拒绝猜选', not ambiguous['ok'] and not ambiguous['modified'], ambiguous)
        operations = [dict(tol_type='symmetric', upper=.1), dict(tol_type='fit', fit='H7/g6'),
                      dict(tol_type='limit', upper=.1, lower=-.1),
                      dict(tol_type='bilateral', upper=.2, lower=-.05)]
        tolerance_results = []
        for row, operation in zip(rows, operations):
            result = set_tolerance(str(drawing), dim_name=row['name'], **operation)
            tolerance_results.append(result)
            check(operation['tol_type'], result['ok'] and result['nominal_before_mm']==result['nominal_after_mm'], result)
        report['tolerances'] = tolerance_results
        cleared = set_tolerance(str(drawing), dim_name=rows[0]['name'], tol_type='none')
        check('公差回退为无', cleared['ok'] and cleared['type_readback']==0 and cleared['nominal_after_mm']==160, cleared)
        restored = set_tolerance(str(drawing), dim_name=rows[0]['name'], upper=.1)
        check('公差回退后恢复', restored['ok'] and restored['values_readback']==[-.1,.1], restored)
        md = _drawing_document(sw, str(drawing))
        view_count = len(_view_list(md))
        views = [name for _,name in _view_list(md)]
        def edge_for(view_name, side):
            edges = list_surface_edges(str(drawing), view_name)
            if side == 'top':
                return max((e for e in edges if abs(e['start_m'][1]-e['end_m'][1])<1e-7), key=lambda e:e['start_m'][1])['edge_index']
            return max((e for e in edges if abs(e['start_m'][0]-e['end_m'][0])<1e-7), key=lambda e:e['start_m'][0])['edge_index']
        finishes = [dict(view_name=views[0],edge_index=edge_for(views[0],'top'),ra='3.2'),
                    dict(view_name=views[1],edge_index=edge_for(views[1],'top'),ra='1.6',symbol_type='basic'),
                    dict(view_name=views[2],edge_index=edge_for(views[2],'top'),ra='6.3',symbol_type='no_machining'),
                    dict(view_name=views[0],edge_index=edge_for(views[0],'right'),leader=True,
                         offset_x=.015,offset_y=.023,ra='0.8',prod_method='铣'),
                    dict(view_name=views[1],edge_index=edge_for(views[1],'right'),leader=True,
                         offset_x=.015,offset_y=.012,ra='12.5')]
        surfaces = add_surface_finishes(str(drawing), finishes)
        check('五个粗糙度附着轮廓边', surfaces['ok'] and surfaces['created']==5 and len(_view_list(md))==view_count, surfaces)
        report['surfaces'] = surfaces
        invalid = add_surface_finish(str(drawing), x=10., y=.1)
        check('图纸外位置拒绝插入', not invalid['ok'] and not invalid['created'], invalid)
        # 压力标注放在独立文档，避免演示图因测试堆叠而不可读。
        stress = sw.NewDocument(_default_template('drawing','A3'), 0, 0., 0.)
        stress_title = str(_value(stress, 'GetTitle'))
        owned.append(stress_title)
        try:
            stress_results = [add_surface_finish(x=.04+(i%5)*.065, y=.24-(i//5)*.045, ra='3.2', lay=i%8) for i in range(20)]
            check('连续20次插入', all(r['ok'] for r in stress_results), stress_results)
        finally:
            sw.CloseDoc(stress_title)
            owned.remove(stress_title)
        md = _drawing_document(sw, str(drawing))
        saved, error, warning = _save_as(md, str(drawing))
        check('保存工程图', saved and error==0, dict(saved=saved,error=error,warning=warning))
        sw.CloseDoc(str(drawing))
        md = _drawing_document(sw, str(drawing))
        reread = list_dimensions(str(drawing), include_objects=True)
        for row, operation, expected in zip(reread, operations, tolerance_results):
            dim = row['dim_obj']
            offsets = [v*1000 for v in _tolerance_values(dim)]
            tolerance = _value(dim, 'Tolerance')
            fits = dict(hole=str(_value(tolerance,'GetHoleFitValue') or ''),
                        shaft=str(_value(tolerance,'GetShaftFitValue') or ''))
            check('重开公差_'+operation['tol_type'],
                  int(_value(dim,'GetToleranceType'))==expected['type_readback'] and row['value']==expected['nominal_before_mm']
                  and fits==expected['fit_readback'] and all(abs(a-b)<1e-7 for a,b in zip(offsets,expected['values_readback'])),
                  dict(name=row['name'],type=int(_value(dim,'GetToleranceType')),value=row['value'],offsets=offsets,fit=fits))
        symbols = []
        attached_annotations = []
        for view,name in _view_list(md):
            ann = _wrap(_value(view, 'GetFirstAnnotation3'))
            while ann is not None:
                if int(_value(ann,'GetType')) == 7:
                    symbol = _wrap(_value(ann,'GetSpecificAnnotation'))
                    symbols.append(dict(type=int(_value(symbol,'GetSymbolType')),
                                        texts=[symbol.GetTextAtIndex(i) for i in range(int(_value(symbol,'GetTextCount')))],
                                        position=list(_value(ann,'GetPosition')),
                                        attached_entity_count=int(_value(ann,'GetAttachedEntityCount3'))))
                    attached_annotations.append((view,ann))
                ann = _wrap(_value(ann,'GetNext3'))
        report['reopened_symbols'] = symbols
        check('重开粗糙度', len(symbols)==5 and all(s['attached_entity_count']>0 for s in symbols) and all(any(r['requested']['ra'] in s['texts'] and s['type']==r['type']
             and all(abs(a-b)<1e-7 for a,b in zip(s['position'],r['position'])) for s in symbols) for r in surfaces['results']), symbols)
        import pythoncom
        from win32com.client import VARIANT
        movement = []
        for view,ann in attached_annotations:
            old = list(_value(view,'Position'))
            before = list(_value(ann,'GetPosition'))
            try:
                view.Position = VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,[old[0]+.01,old[1]+.01])
                after = list(_value(ann,'GetPosition'))
                movement.append(dict(before=before,after=after,
                                     ok=all(abs(after[i]-before[i]-.01)<1e-7 for i in (0,1))))
            finally:
                view.Position = VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,old)
        check('五个符号随视图移动10毫米', all(r['ok'] for r in movement), movement)
        _save_as(md,str(drawing))
        pdf = export_pdf(str(drawing))
        check('PDF导出并独立渲染', pdf['ok'], pdf)
        with pdfium.PdfDocument(pdf['path']) as doc:
            page = doc[0]
            text = page.get_textpage().get_text_range()
            report['pdf_text'] = text
            check('PDF标注文字', all(token in text for token in ('±0.10','160.10','159.90','H7/g6','3.2','1.6','6.3','12.5')), text)
            image = page.render(scale=3).to_pil()
            image.save(root/'公差与粗糙度演示.png')
            image.thumbnail((1500,1100))
            image.save(root/'演示总览.png')
        report['pdf'] = pdf
        report['ok'] = True
    except Exception:
        report['exception'] = traceback.format_exc()
        raise
    finally:
        if not keep or not report['ok']:
            for path in reversed(owned):
                sw.CloseDoc(path)
        else:
            sw.ActivateDoc(str(drawing))
            _value(sw.ActiveDoc, 'ViewZoomtofit2')
            sw.Visible = True
        report['after'] = document_inventory(sw)
        (root/'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', required=True)
    parser.add_argument('--keep', action='store_true')
    args = parser.parse_args()
    verify(args.work_dir, args.keep)
