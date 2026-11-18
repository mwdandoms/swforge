"""Sequential Community output acceptance. Uses only this run's new files."""
import argparse
import dataclasses
import json
import math
import os
from pathlib import Path
import sys
import traceback


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--year',required=True,choices=['2019','2025'])
    p.add_argument('--out',required=True)
    p.add_argument('--cases',nargs='*',default=['spring_right','spring_left','auger_right','auger_left','mixed','editable','drawing'])
    args=p.parse_args()
    os.environ['SWFORGE_SW_YEAR']=args.year
    import swforge
    from swforge.feature_tree import inspect_feature_tree
    from swforge.session import _value
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False)
    sw=swforge.get_session().sw()
    before=swforge.document_inventory(sw)
    if before['document_count']>=5:raise RuntimeError('Insufficient document capacity')
    report=dict(version=swforge.__version__,module=swforge.__file__,python=sys.executable,
        revision=str(_value(sw,'RevisionNumber')),before=before,cases={})
    def save():
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    save()
    try:
        for name in args.cases:
            if swforge.document_inventory(sw)['documents']!=before['documents']:
                raise RuntimeError('Unexpected document state; stopped without closing other files')
            row=report['cases'][name]={}
            path=out/(name+'.SLDPRT')
            try:
                b=swforge.PartBuilder(str(path),material='Q235')
                helical=name.startswith(('spring','auger')) or name=='mixed'
                if name.startswith('spring') or name=='mixed':
                    b.helix_spring('coil',wire_diameter=2,mean_diameter=20,height=45,turns=6,clockwise=name!='spring_left')
                    if name=='mixed':b.box('reference',100,110,0,10,0,10)
                elif name.startswith('auger'):
                    b.auger_flight('flight',inner_diameter=30,outer_diameter=80,pitch=55,turns=1.5,thickness=3,clockwise=name!='auger_left')
                else:
                    b.box('plate',0,120,0,10,0,80)
                    b.hole_grid('holes','plate',x=25,z=20,rows=2,columns=3,pitch_u=30,pitch_v=40,diameter=8,through_all=True)
                result=b.build(keep_open=False,max_documents=5,timeout_s=150)
                row['build']=dataclasses.asdict(result)
                if not result.ok:raise RuntimeError(result.error)
                tree=inspect_feature_tree(str(path));row['reopened']=tree
                if not tree.get('ok') or tree.get('feature_errors')!=0:raise RuntimeError('Saved model feature check failed')
                if abs(tree['volume_mm3']-result.volume_mm3)>max(.05,result.volume_mm3*1e-6):
                    raise RuntimeError('Saved and reopened volume differs')
                if helical:
                    types={f['type'] for f in tree['features']}
                    forbidden={'Helix','Sweep','SweepRefSurface','Thicken','ProfileFeature','3DProfileFeature'}
                    if forbidden & types:raise RuntimeError('Native history in geometry-only output')
                    pars=swforge.list_model_parameters(str(path));row['parameters']=pars
                    if not pars.get('ok') or pars.get('parameters'):raise RuntimeError('Unexpected geometry output dimensions')
                    expected_count=2 if name=='mixed' else 1
                    if tree['body_count']!=expected_count:raise RuntimeError('Unexpected body count')
                    checks=result.spring_checks if result.spring_checks else result.auger_checks
                    if not checks or not all(c.get('ok') for c in checks.values()):raise RuntimeError('Helical geometry verification failed')
                    if name.startswith('spring') and result.spring_checks['coil']['helix']['clockwise']!=(name=='spring_right'):
                        raise RuntimeError('Spring handedness mismatch')
                    row['geometry_only_verified']=True
                elif name=='editable':
                    pars=swforge.list_model_parameters(str(path));row['parameters_before']=pars
                    candidates=[x for x in pars.get('parameters',[]) if x.get('unit')=='mm' and not x.get('read_only') and abs(x.get('value',0)-120)<.001]
                    if len(candidates)!=1:raise RuntimeError('Cannot locate unique plate width driving dimension')
                    key=candidates[0]['key']
                    edited=swforge.set_parameters(str(path),{key:125},save=True)
                    row['edit']=edited
                    if not edited.get('ok'):raise RuntimeError('Dimension edit failed')
                    reopened=inspect_feature_tree(str(path));row['edited_reopened']=reopened
                    expected=tree['volume_mm3']+5*10*80
                    if not reopened.get('ok') or abs(reopened['volume_mm3']-expected)>.05:raise RuntimeError('Edited saved geometry incorrect')
                    final=swforge.list_model_parameters(str(path));row['parameters_after']=final
                    if not any(x.get('key')==key and abs(x.get('value',0)-125)<1e-6 for x in final.get('parameters',[])):
                        raise RuntimeError('Edited dimension was not persisted')
                elif name=='drawing':
                    drawing=out/'drawing.SLDDRW'
                    made=swforge.produce(str(path),str(drawing),paper='A3',keep_open=False,max_documents=5)
                    row['drawing']=made
                    if not made.get('ok'):raise RuntimeError('Frozen drawing path failed')
                    pdf=swforge.export_pdf(str(drawing),str(out/'drawing.pdf'))
                    row['pdf']=pdf
                    if not pdf.get('ok'):raise RuntimeError('PDF export failed')
                row['passed']=True
            except Exception as exc:
                row.update(passed=False,error=str(exc),traceback=traceback.format_exc())
            finally:
                # Parameter enumeration deliberately leaves its input open. Close only
                # exact paths generated inside this acceptance run, never baseline docs.
                for opened in swforge.document_inventory(sw)['documents']:
                    owned_path=Path(opened['path']) if opened.get('path') else None
                    if owned_path and owned_path.parent==out:
                        sw.CloseDoc(opened['title'])
            row['documents_after']=swforge.document_inventory(sw)
            print(name,row['passed'],row.get('error',''),flush=True)
            save()
    finally:
        report['after']=swforge.document_inventory(sw)
        report['passed']=(len(report['cases'])==len(args.cases) and all(r.get('passed') for r in report['cases'].values())
            and before['documents']==report['after']['documents'])
        save()
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
