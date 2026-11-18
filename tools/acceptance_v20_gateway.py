"""Live gateway entry-point verification using exclusively new owned outputs."""
import argparse,json,os,traceback
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();os.environ['SWFORGE_SW_YEAR']=a.year
    import swforge
    from swforge.server import mcp
    from swforge.session import _value
    root=Path(a.out).resolve();root.mkdir(parents=True,exist_ok=False)
    sw=swforge.get_session().sw();before=swforge.document_inventory(sw)
    assert before['document_count']<5
    report=dict(version=swforge.__version__,module=swforge.__file__,revision=str(_value(sw,'RevisionNumber')),before=before,cases={})
    cases=[('sw_create_spring',dict(wire_diameter=2,mean_diameter=20,height=45,turns=6,clockwise=False)),
           ('sw_create_auger_flight',dict(inner_diameter=30,outer_diameter=80,pitch=55,turns=1.5,thickness=3)),
           ('sw_build_part',dict(spec={'boxes':[dict(tag='plate',x0=0,x1=40,y0=0,y1=10,z0=0,z1=30)]},keep_open=False))]
    try:
        for name,kwargs in cases:
            row=report['cases'][name]={};path=root/(name+'.SLDPRT')
            try:
                result=mcp._gateway.invoke(name,dict(kwargs,out_path=str(path)))
                row['result']=result;assert result['ok'],result
                tree=swforge.inspect_feature_tree(str(path));row['reopened']=tree
                assert tree['ok'] and tree['feature_errors']==0 and tree['body_count']==1,tree
                if name!='sw_build_part':
                    assert result['native_history'] is False,result
                    pars=swforge.list_model_parameters(str(path));row['parameters']=pars
                    assert pars['ok'] and not pars['parameters'],pars
                    assert not {'Helix','Sweep','SweepRefSurface','Thicken','ProfileFeature','3DProfileFeature'} & {f['type'] for f in tree['features']},tree
                row['passed']=True
            except Exception as exc:row.update(passed=False,error=str(exc),traceback=traceback.format_exc())
            finally:
                for doc in swforge.document_inventory(sw)['documents']:
                    if doc.get('path') and Path(doc['path']).parent==root:sw.CloseDoc(doc['title'])
            print(name,row['passed'],flush=True)
    finally:
        report['after']=swforge.document_inventory(sw)
        report['passed']=len(report['cases'])==3 and all(r.get('passed') for r in report['cases'].values()) and before['documents']==report['after']['documents']
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
